# Example Playbooks + Parallel Validation Workflow

Date: 2026-06-17
Status: Approved

## Goal

Provide runnable, copy-pasteable example playbooks for the `trozz.pocketid`
collection that exercise **every module, every lookup, and every option**, and a
GitHub Actions workflow that runs them in parallel as a functional smoke test
against a real Pocket-ID instance.

These are documentation-grade examples first and a validation harness second.
They are **not** part of the PR-gating CI and do not replace the existing
`tests/integration` targets.

## Constraints and decisions

- **Standalone examples**, living in a top-level `examples/` directory. They
  intentionally overlap with the integration tests; their value is being
  readable and self-contained.
- **Excluded from the published tarball** via `galaxy.yml` `build_ignore`
  (consistent with `docs/` and `tests/`).
- **Triggers**: `workflow_dispatch` (manual) and a weekly `schedule` (Monday).
  Not run on PRs or pushes.
- No Molecule, no custom inventory, no live SMTP/LDAP servers. LDAP/SMTP options
  are written and asserted as configuration values, not functionally tested.
- Reuse the existing `scripts/integration-bootstrap.sh` to stand up Pocket-ID.

## Why per-job isolated instances (not shared)

The collection manages global, interdependent state, so many playbooks cannot
safely run concurrently against one Pocket-ID:

- `application_config` is a **singleton**; concurrent writers clobber each other.
- `group_membership` needs users+groups; `client_secret`/`scim` need a client;
  `one_time_access_token` needs a user. Concurrent create/delete across
  playbooks races (e.g. one playbook's `*_info` listing while another deletes).

Parallelism is therefore achieved at the **CI-job** level: a GitHub Actions
matrix where each job stands up its **own** `pocket-id:v2` container (via the
bootstrap script, on `localhost:1411`) and runs exactly one playbook. Separate
runners mean no port conflict and full isolation.

## Architecture

```
examples/
  README.md                  # how to run locally + what each playbook covers
  users.yml
  groups.yml
  group_membership.yml
  clients.yml
  client_secret.yml
  scim.yml
  one_time_access_token.yml
  app_config.yml
.github/workflows/examples.yml   # parallel matrix over the 8 playbooks
galaxy.yml                        # add `examples` to build_ignore
```

### Workflow (`.github/workflows/examples.yml`)

- `on: { workflow_dispatch: {}, schedule: [{cron: "0 5 * * 1"}] }`
- One job, `strategy.matrix.playbook` over the 8 playbook basenames,
  `fail-fast: false` so one failure does not cancel the others.
- Per job:
  1. checkout into `ansible_collections/trozz/pocketid` (same layout as `ci.yml`).
  2. setup Python 3.11, install `ansible-core` (stable-2.18, matching the
     integration job).
  3. `bash scripts/integration-bootstrap.sh` (its own container).
  4. Export `POCKETID_BASE_URL=http://localhost:1411` and
     `POCKETID_API_TOKEN=<static key>` (mirrors what the bootstrap proves works).
  5. `ansible-playbook examples/${{ matrix.playbook }}`.
  6. `bash scripts/integration-bootstrap.sh --down` in an `always` step.
- Action versions match the rest of the repo (`checkout@v5`, `setup-python@v6`).

### Playbook contract

Every playbook is uniform so it reads as an example and behaves as a test:

1. `hosts: localhost`, `connection: local`, `gather_facts: false`.
2. `module_defaults` for the `group/trozz.pocketid.pocketid` action group, set
   from env plus explicit `validate_certs: false` and `timeout: 30` (this is how
   the four connection options get exercised):
   ```yaml
   module_defaults:
     group/trozz.pocketid.pocketid:
       base_url: "{{ lookup('env', 'POCKETID_BASE_URL') }}"
       api_token: "{{ lookup('env', 'POCKETID_API_TOKEN') }}"
       validate_certs: false
       timeout: 30
   ```
   Lookups read the `POCKETID_*` env vars directly (they do not support
   `module_defaults`).
3. Create any prerequisites the playbook needs.
4. Exercise the primary module across **every option**. For stateful modules,
   run the converging task twice and `assert changed == false` on the second run
   (idempotence). For the two non-idempotent action modules
   (`client_secret`, `one_time_access_token`): assert check mode is a no-op and a
   real run returns the secret/token exactly once.
5. Exercise the matching `*_info` module and lookup plugin; `assert` the results.
6. Exercise `state: absent` / empty-list clearing.
7. Tear down prerequisites in an `always` block (resource cleanup), so the
   playbook is self-contained even though the CI instance is ephemeral.

Failures surface through `assert` and `failed_when`; the playbook exits non-zero
and the matrix job fails.

## Coverage map

Every module (12), lookup (4), and option appears in exactly one playbook.

| Playbook | Modules | Lookups | Notable options exercised |
|---|---|---|---|
| `users.yml` | `user`, `user_info` | `user` | id-anchored rename, username, email, first/last/display name, email_verified, is_admin, locale, disabled, groups, custom_claims, manage_ldap_synced, state present/absent; `user_info` id/username/email/list-all |
| `groups.yml` | `group`, `group_info` | `group` | id, name, friendly_name, custom_claims (set + clear with `{}`), manage_ldap_synced, state; `group_info` id/name/list-all |
| `group_membership.yml` | `group_membership` | — | user form (`user`+`groups`), group form (`group`+`users`), empty-list clearing, manage_ldap_synced |
| `clients.yml` | `client`, `client_info` | `client` | name, callback_urls, logout_callback_urls, is_public, pkce_enabled, requires_reauthentication, requires_pushed_authorization_requests, launch_url, is_group_restricted, allowed_user_groups, credentials (issuer/subject/audience/jwks), state; `client_info` id/name/list-all |
| `client_secret.yml` | `client_secret` (+ `client` setup) | — | rotate by `client_id` and by `name`; check-mode no-op |
| `scim.yml` | `scim_service_provider` (+ `client` setup) | — | oidc_client_id, endpoint, token, id, state present/absent |
| `one_time_access_token.yml` | `one_time_access_token` (+ `user` setup) | — | by `user_id` and by `username`, `ttl` as seconds and Go-style duration; check-mode no-op |
| `app_config.yml` | `application_config`, `application_config_info` | `application_config` | ~45 fields: app_name, session_duration, home_page_url, emails_verified, disable_animations, allow_own_account_edit, allow_user_signups, signup defaults, accent_color, require_user_email, full SMTP block, full LDAP block, email_* toggles; `application_config_info` + lookup (full + key-filtered) |

Connection options `base_url`, `api_token`, `validate_certs`, `timeout` are
exercised via `module_defaults` in all eight playbooks.

## Out of scope

- Functional verification of SMTP/LDAP/SCIM endpoints (no live external servers).
- Running on PRs or as a release gate.
- Shipping examples inside the installable collection artifact.

## Risks

- Pocket-ID `:v2` API drift could break a playbook; the weekly schedule surfaces
  this. A `:next` matrix entry is intentionally omitted for now (can be added
  later, mirroring `ci.yml`'s experimental lane).
- `app_config.yml` is the largest single playbook (~45 options); it stays one
  playbook because the config is a single singleton resource.
