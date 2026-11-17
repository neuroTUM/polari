import os

import pytest


@pytest.mark.parametrize(
    "var", ["NEXTCLOUD_USERNAME", "NEXTCLOUD_PASSWORD", "NEXTCLOUD_ROOT_PATH"]
)
def test_config_present(var: str) -> None:
    # Reduce to a bool first: pytest's assertion rewriting would otherwise
    # dump the whole os.environ (including the secrets) into the CI log.
    is_set = bool(os.environ.get(var))
    assert is_set, f"{var} is not set"
