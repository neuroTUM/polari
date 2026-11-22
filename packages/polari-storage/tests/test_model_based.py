from functools import partial
from unittest import mock

import httpx
from hypothesis import HealthCheck, settings

from dav_helpers import ROOT_URL, FakeNextcloud, Faulty
from object_store_model import Fault, Model, ObjectStoreMachine
from polari_storage import NextcloudStorage, Version


class FakeNextcloudMachine(ObjectStoreMachine):
    """Model-based test against the in-memory fake, with injected network faults.

    Deterministic: the fake has no clock, threads or real I/O, so a failure
    replays exactly from the Hypothesis seed it prints.
    """

    def make_storage(self) -> NextcloudStorage:
        self.fake = FakeNextcloud()
        self.faulty = Faulty(self.fake)
        client = partial(httpx.AsyncClient, transport=httpx.MockTransport(self.faulty))
        with mock.patch.object(httpx, "AsyncClient", client):
            return NextcloudStorage(ROOT_URL, "alice", "not-a-real-password")

    def fault_for(self, dice: int) -> Fault:
        if dice == 0:
            return "before"
        if dice == 1:
            return "after"
        return None

    def inject(self, fault: Fault, methods: frozenset[str]) -> None:
        self.faulty.next_fault = fault
        self.faulty.methods = methods

    def resync(self) -> Model:
        versions = {
            key: [Version(str(number)) for number in numbers]
            for key, numbers in self.fake.versions().items()
        }
        folders = {f for f in self.fake.folders - {""} if "@" not in f}
        return Model(self.fake.objects(), versions, frozenset(folders))


TestFakeNextcloud = FakeNextcloudMachine.TestCase
TestFakeNextcloud.settings = settings(
    max_examples=200,
    stateful_step_count=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
