from pathlib import Path

import pytest

INTEGRATION_DIR = Path(__file__).parent / "integration"


@pytest.hookimpl(tryfirst=True)  # tag before `-m` deselection runs
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tag every test under tests/integration/ with the `integration` marker."""
    for item in items:
        if item.path.is_relative_to(INTEGRATION_DIR):
            item.add_marker(pytest.mark.integration)
