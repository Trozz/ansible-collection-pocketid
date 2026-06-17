# trozz.pocketid example playbooks

Runnable, self-contained example playbooks that exercise **every module, lookup,
and option** in the collection. They double as a functional smoke test: each one
creates its own prerequisites, asserts behaviour (including idempotence), and
cleans up after itself.

These examples are **not** shipped in the published collection
(`examples/` is excluded via `build_ignore`) and are **not** part of the
PR-gating CI. They run on demand and weekly via
[`.github/workflows/examples.yml`](../.github/workflows/examples.yml).

## Playbooks

| Playbook | Covers |
|----------|--------|
| `users.yml` | `user`, `user_info`, `user` lookup |
| `groups.yml` | `group`, `group_info`, `group` lookup |
| `group_membership.yml` | `group_membership` (user form and group form) |
| `clients.yml` | `client`, `client_info`, `client` lookup |
| `client_secret.yml` | `client_secret` (rotate by id and by name) |
| `scim.yml` | `scim_service_provider` |
| `one_time_access_token.yml` | `one_time_access_token` (by id and by username) |
| `app_config.yml` | `application_config`, `application_config_info`, `application_config` lookup |

## Running locally

The playbooks read their connection details from the environment, the same
variables the modules and lookups fall back to:

```bash
export POCKETID_BASE_URL=http://localhost:1411
export POCKETID_API_TOKEN=<an admin API key>

ansible-playbook examples/users.yml
```

To run them all against a throwaway Pocket-ID, the collection ships a bootstrap
that starts a container and prints/needs the static admin key:

```bash
# starts pocket-id on http://localhost:1411 with a known static API key
bash scripts/integration-bootstrap.sh

export POCKETID_BASE_URL=http://localhost:1411
export POCKETID_API_TOKEN=test-ansible-pocketid-static-key-0123456789

for pb in examples/*.yml; do ansible-playbook "$pb"; done

bash scripts/integration-bootstrap.sh --down
```

> **macOS:** the lookup plugins run in forked workers that crash under macOS's
> fork-safety check. Export `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` before
> running the playbooks locally (Linux and CI are unaffected).
>
> Each playbook is independent and idempotent (the two action modules,
> `client_secret` and `one_time_access_token`, are intentionally not idempotent
> and assert that instead). Because they share a single Pocket-ID, run them
> sequentially when pointing at one instance. CI runs them in parallel by giving
> each job its **own** Pocket-ID container.
