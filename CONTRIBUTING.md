# Contributing

## Local setup

```sh
uv sync --locked --all-packages
uv run just          # list recipes
uv run just ci       # everything CI runs on a pull request
```

## Running integration tests

Integration tests (`pytest -m integration`) talk to a real Nextcloud instance
and need configuration from the `secrets` GitHub environment: the
`NEXTCLOUD_USERNAME` / `NEXTCLOUD_PASSWORD` secrets and the non-secret
`NEXTCLOUD_ROOT_PATH` variable.
They are **not** run on pull requests, and contributors cannot run them in CI:
code from a fork never gets access to those secrets.

To run them for a pull request, a maintainer:

1. Reviews the full diff, including changes to tests, `Justfile`,
   `pyproject.toml`, and `uv.lock`. This code will run with the secrets.
2. Pushes it to a `ci/` branch in this repository:

   ```sh
   gh pr checkout <n> && git push origin HEAD:ci/pr-<n>
   ```

3. Approves the `secrets` deployment when the
   **Integration / test:integration** run asks for it.

Re-review and re-push after every new commit to the PR. Delete the `ci/`
branch when you're done.

Tests under `tests/integration/` are tagged `integration` automatically.
If you have your own Nextcloud credentials you can run them locally:

```sh
cp .env.example .env      # fill in the NEXTCLOUD_* values
uv run just test-integration   # integration only
uv run just test-all           # unit + integration
```
