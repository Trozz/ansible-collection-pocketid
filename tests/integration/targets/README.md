# Integration targets (`trozz.pocketid`)

These targets exercise each module/lookup against a live Pocket-ID instance.

## Running

From the collection root (a path ending in
`ansible_collections/trozz/pocketid`):

```bash
# 1. Bring up Pocket-ID, seed an admin + API key, run the auth smoke check,
#    and render tests/integration/integration_config.yml.
bash scripts/integration-bootstrap.sh

# 2. Run the integration suite locally (host venv, connection: local).
ansible-test integration --local -v

# 3. Tear the test instance down when finished.
bash scripts/integration-bootstrap.sh --down
```

`ansible-test` auto-loads `tests/integration/integration_config.yml`, exposing
`pocketid_base_url`, `pocketid_api_token`, and `pocketid_validate_certs` to every
target. Each target sets `module_defaults` for the
`group/trozz.pocketid.pocketid` action group from those variables, so the
connection options are configured once per play.

The lookup target instead relies on the `POCKETID_*` environment variables
(lookups are not covered by `module_defaults`); the bootstrap exports them and
the target also sets them via the play `environment`.

## Conventions

- Every target plays `hosts: localhost` with `connection: local`; Pocket-ID is
  reached over HTTP on `localhost:1411`.
- Targets carry `aliases` marking them `unsupported` so they do not run during
  default `ansible-test sanity`; run them explicitly with `ansible-test
  integration`.
- Idempotency is asserted by converging twice and requiring `changed == false`
  on the second run. The non-idempotent action modules
  (`one_time_access_token`, `client_secret`) are **exempt**: their targets
  instead assert that check mode performs no mint/rotation and that a real run
  returns the secret/token exactly once.

## Running locally on macOS

Lookup plugins run inside a forked Ansible worker. On macOS, making an HTTPS
call after `fork()` aborts the worker ("A worker was found in a dead state")
due to Objective-C fork-safety. Export the documented workaround before running
the lookup target (or the full suite) locally:

```bash
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
```

This is a macOS-only test-runner artifact; CI runs on Linux and is unaffected.
