import pytest


@pytest.hookimpl(tryfirst=True)  # tag before `-m` deselection runs
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tag every test below a ``tests/integration/`` folder as `integration`."""
    for item in items:
        if any(
            folder.name == "integration" and folder.parent.name == "tests"
            for folder in item.path.parents
        ):
            item.add_marker(pytest.mark.integration)
