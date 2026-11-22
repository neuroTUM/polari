# polari

TODO: add project documentation once we have an MVP.

## Tests

`just test` runs the unit tests.
`just test-integration` runs the integration tests against a real Nextcloud.
They need every value in `.env`.
Copy `.env.example` to `.env` and fill it in:

- `NEXTCLOUD_BASE_URL`: the server, e.g. `https://cloud.example.org`.
- `NEXTCLOUD_USERNAME`: the test account.
- `NEXTCLOUD_PASSWORD`: an app password of that account.
- `NEXTCLOUD_ROOT_PATH`: the test folder, as that account sees it.

<br>

#### License

<sup>
Licensed under either of <a href="LICENSE-APACHE">Apache License, Version
2.0</a> or <a href="LICENSE-MIT">MIT license</a> at your option.
</sup>

<br>

<sub>
Unless you explicitly state otherwise, any contribution intentionally submitted
for inclusion in polari by you, as defined in the Apache-2.0 license, shall be
dual licensed as above, without any additional terms or conditions.
</sub>