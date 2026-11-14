# Run `just` (or `uv run just` if it isn't on your PATH) to list recipes.

set shell := ["bash", "-euo", "pipefail", "-c"]
set positional-arguments
# Load NEXTCLOUD_* config from a local, gitignored .env (copy .env.example)
set dotenv-load

[private]
default:
    @just --list

# Install the workspace and dev tools from the lockfile
sync:
    uv sync --locked --all-packages

# Lint and check formatting
lint:
    uv run ruff check
    uv run ruff format --check

# Auto-fix lint issues and reformat
fmt:
    uv run ruff check --fix
    uv run ruff format

# Type check with ty and pyrefly
typecheck:
    uv run ty check
    uv run pyrefly check

# Audit GitHub workflows (zizmor) and dependencies (uv audit)
audit:
    uv run zizmor --pedantic .github
    uv audit --locked --preview-features audit-command

# Unit tests only (integration tests are deselected by default)
test *args:
    uv run pytest "$@"

# Integration tests only; needs NEXTCLOUD_* vars (env or .env)
test-integration *args:
    uv run pytest -m integration "$@"

# Unit and integration tests together
test-all *args:
    uv run pytest -m "" "$@"

# Everything CI runs on a pull request
ci: lint typecheck audit test
