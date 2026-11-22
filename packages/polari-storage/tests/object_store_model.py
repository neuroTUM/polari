"""Model-based testing of ``NextcloudStorage``, shared by unit and integration tests.

``ObjectStoreMachine`` lets Hypothesis run random sequences of operations
against a real ``NextcloudStorage`` and against :class:`Model`, a plain dict,
and asserts after every step that both agree. Subclasses decide which server
the storage talks to (the in-memory fake or a real Nextcloud).
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule

from polari_storage import (
    Committed,
    Conflict,
    NextcloudStorage,
    NotFoundError,
    RangeNotSatisfiableError,
    StorageError,
    StorageTransportError,
    Version,
)

type Fault = Literal["before", "after"] | None


class Faulted:
    """What ``call`` returns when an injected fault ended the operation."""


FAULTED = Faulted()

FOLDERS = st.lists(st.sampled_from(["a", "b", "ü x"]), max_size=2)
KEYS = st.builds(
    lambda folders, name: "/".join([*folders, name]),
    FOLDERS,
    st.sampled_from(["1.bin", "2.bin", "100% #.bin"]),
)
PREFIXES = FOLDERS.map(lambda folders: "".join(f"{level}/" for level in folders))
DATA = st.binary(max_size=24)
# Mapped to a fault by ``fault_for``; machines without fault injection ignore it.
FAULT_DICE = st.integers(min_value=0, max_value=9)


def ancestors(key: str) -> set[str]:
    levels = key.split("/")[:-1]
    return {"/".join(levels[: depth + 1]) for depth in range(len(levels))}


@dataclass(frozen=True)
class Model:
    """What the store should contain, and every version seen per key."""

    objects: dict[str, bytes] = field(default_factory=dict)
    versions: dict[str, list[Version]] = field(default_factory=dict)
    folders: frozenset[str] = frozenset()

    def latest(self, key: str) -> Version | None:
        seen = self.versions.get(key)
        return seen[-1] if seen and key in self.objects else None

    def put(self, key: str, data: bytes, version: Version) -> Model:
        return Model(
            {**self.objects, key: data},
            {**self.versions, key: [*self.versions.get(key, []), version]},
            self.folders | ancestors(key),
        )

    def delete(self, key: str) -> Model:
        objects = {k: v for k, v in self.objects.items() if k != key}
        return replace(self, objects=objects)

    def listing(
        self, prefix: str, delimiter: Literal["/"] | None
    ) -> tuple[dict[str, int], list[str]]:
        below = {k: len(v) for k, v in self.objects.items() if k.startswith(prefix)}
        if delimiter is None:
            return below, []
        objects = {k: n for k, n in below.items() if "/" not in k[len(prefix) :]}
        prefixes = sorted(
            f"{folder}/"
            for folder in self.folders
            if folder.startswith(prefix) and "/" not in folder[len(prefix) :]
        )
        return objects, prefixes


class ObjectStoreMachine(RuleBasedStateMachine):
    # Keys that were written before. Drawing from them half of the time makes
    # reads and updates hit existing objects.
    written = Bundle("written")

    def __init__(self) -> None:
        super().__init__()
        self.runner = asyncio.Runner()
        self.model = Model()
        self.storage = self.make_storage()

    def make_storage(self) -> NextcloudStorage:
        raise NotImplementedError

    def fault_for(self, dice: int) -> Fault:
        return None

    def inject(self, fault: Fault, methods: frozenset[str]) -> None:
        assert fault is None, "this machine cannot inject faults"

    def resync(self) -> Model:
        """Read the true state after a fault left the outcome open."""
        raise NotImplementedError

    def before_write(self, size: int) -> None:
        """Called with the number of bytes an operation is about to create."""

    def teardown(self) -> None:
        self.runner.run(self.storage.aclose())
        self.runner.close()

    def call[T](
        self,
        operation: Callable[[], Awaitable[T]],
        dice: int,
        *,
        methods: frozenset[str] = frozenset(),
        changed: Model | None = None,
    ) -> T | StorageError | Faulted:
        """Run one operation, possibly with an injected fault.

        Returns the result, or the error it raised. A transport error is
        checked here and gives ``FAULTED``: the operation must have happened
        completely (``changed``) or not at all, and must say so honestly.
        """
        fault = self.fault_for(dice)
        self.inject(fault, methods)
        try:
            return self.runner.run(operation())
        except StorageTransportError as exc:
            transport_error = exc
        except StorageError as exc:
            return exc
        finally:
            self.inject(None, frozenset())
        assert fault is not None, (
            f"transport error without a fault: {transport_error!r}"
        )
        self.check_fault_outcome(fault, transport_error, changed)
        return FAULTED

    def check_fault_outcome(
        self, fault: Fault, exc: StorageTransportError, changed: Model | None
    ) -> None:
        actual = self.resync()
        if fault == "before":
            # Nothing reached the server, so nothing may have changed.
            assert actual.objects == self.model.objects
        else:
            outcomes = [self.model.objects]
            if changed is not None:
                outcomes.append(changed.objects)
            assert actual.objects in outcomes, f"partial outcome after {exc!r}"
        self.model = actual

    def current_version(self, key: str) -> Version:
        version = self.model.latest(key)
        if version is None:
            version = self.runner.run(self.storage.head_object(key)).version
            self.model = self.model.put(key, self.model.objects[key], version)
        return version

    @rule(target=written, key=KEYS, data=DATA, dice=FAULT_DICE)
    def create(self, key: str, data: bytes, dice: int) -> str:
        exists = key in self.model.objects
        self.before_write(len(data))
        result = self.call(
            lambda: self.storage.put_object(key, data, if_none_match=True),
            dice,
            methods=frozenset({"MOVE"}),
            changed=None if exists else self.model.put(key, data, Version("?")),
        )
        if isinstance(result, Faulted):
            return key
        if exists:
            assert isinstance(result, Conflict), f"create over {key!r}: {result!r}"
        else:
            assert isinstance(result, Committed), f"create {key!r}: {result!r}"
            self.model = self.model.put(key, data, result.version)
        return key

    @rule(key=written | KEYS, data=DATA, stale=st.booleans(), dice=FAULT_DICE)
    def update(self, key: str, data: bytes, stale: bool, dice: int) -> None:
        exists = key in self.model.objects
        if exists and not stale:
            version = self.current_version(key)
        else:
            # Versions restart after a delete, so an "older" one can equal the
            # current one; only a different version is stale.
            current = self.model.latest(key)
            older = [v for v in self.model.versions.get(key, []) if v != current]
            version = older[-1] if older else Version("999999")
        self.before_write(len(data))
        result = self.call(
            lambda: self.storage.put_object(key, data, if_match=version),
            dice,
            methods=frozenset({"MOVE"}),
            changed=self.model.put(key, data, Version("?")),
        )
        if isinstance(result, Faulted):
            return
        if exists and not stale:
            assert isinstance(result, Committed), f"update {key!r}: {result!r}"
            assert result.version != version, "a write must give a new version"
            self.model = self.model.put(key, data, result.version)
        else:
            assert isinstance(result, Conflict), f"stale update won: {result!r}"

    @rule(
        key=written | KEYS,
        offset=st.integers(0, 12),
        length=st.none() | st.integers(1, 12),
        dice=FAULT_DICE,
    )
    def get_object(self, key: str, offset: int, length: int | None, dice: int) -> None:
        data = self.model.objects.get(key)
        result = self.call(
            lambda: self.storage.get_object(key, offset=offset, length=length), dice
        )
        if isinstance(result, Faulted):
            return
        ranged = offset > 0 or length is not None
        if data is None:
            assert isinstance(result, NotFoundError), result
        elif ranged and offset >= len(data):
            assert isinstance(result, RangeNotSatisfiableError), result
        else:
            assert not isinstance(result, StorageError), result
            end = None if length is None else offset + length
            assert result.data == data[offset:end]
            known = self.model.latest(key)
            assert known is None or result.version == known, "version changed"

    @rule(key=written | KEYS, dice=FAULT_DICE)
    def head_object(self, key: str, dice: int) -> None:
        result = self.call(lambda: self.storage.head_object(key), dice)
        if isinstance(result, Faulted):
            return
        if key not in self.model.objects:
            assert isinstance(result, NotFoundError), result
            return
        assert not isinstance(result, StorageError), result
        assert result.size == len(self.model.objects[key])
        known = self.model.latest(key)
        assert known is None or result.version == known, "version changed"

    @rule(key=written | KEYS, dice=FAULT_DICE)
    def delete_object(self, key: str, dice: int) -> None:
        expected = self.model.delete(key)
        result = self.call(
            lambda: self.storage.delete_object(key),
            dice,
            methods=frozenset({"DELETE"}),
            changed=expected,
        )
        if isinstance(result, Faulted):
            return
        assert not isinstance(result, StorageError), result
        self.model = expected

    @rule(prefix=PREFIXES, delimiter=st.sampled_from([None, "/"]), dice=FAULT_DICE)
    def list_objects(
        self, prefix: str, delimiter: Literal["/"] | None, dice: int
    ) -> None:
        result = self.call(
            lambda: self.storage.list_objects(prefix, delimiter=delimiter), dice
        )
        if isinstance(result, Faulted):
            return
        assert not isinstance(result, StorageError), result
        objects, prefixes = self.model.listing(prefix, delimiter)
        assert len({o.key for o in result.objects}) == len(result.objects)
        assert {o.key: o.size for o in result.objects} == objects
        assert sorted(result.common_prefixes) == prefixes
        for info in result.objects:
            known = self.model.latest(info.key)
            assert known is None or info.version == known, "version changed"
