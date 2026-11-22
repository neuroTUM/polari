from typing import Protocol


class ObjectStore(Protocol):
    def put(self, key: str, object: bytes) -> None: ...
