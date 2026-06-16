# Design: Ansible Collection `trozz.pocketid`

Date: 2026-06-16
Status: Approved (pending spec review)

## Goal

Provide an Ansible collection that manages a [Pocket-ID](https://github.com/pocket-id/pocket-id)
instance through its REST API, reaching full feature parity with the existing
[`terraform-provider-pocketid`](../../../../terraform-provider-pocketid). Users
should be able to declaratively manage users, groups, OIDC clients, application
configuration, SCIM service providers, and one-time access tokens from
playbooks, and query the same objects from tasks and inline lookups.

## Background

The Terraform provider talks to Pocket-ID over HTTP using an `X-API-KEY` header
against `/api/...` endpoints. Its internal client (`internal/client/client.go`,
`models.go`) defines the full API surface we need to mirror:

- Resources: OIDC clients, users, user-groups, application configuration,
  one-time access tokens, SCIM service providers, custom claims (user + group),
  client secret generation, client allowed-user-groups, user group membership.
- Data sources: user(s), group(s), client(s), application configuration.

Authentication env vars used by the provider, which we keep for consistency:
`POCKETID_BASE_URL`, `POCKETID_API_TOKEN`.

Integration tests in the provider seed a SQLite database with a fixed token whose
sha256 hash is inserted directly (`scripts/prepare-test-db.sh`, token
`test-terraform-provider-token-123456789`). We mirror this approach.

Pocket-ID v1 is end-of-life. Integration tests target the `v2` and `next`
Pocket-ID images only.

## Non-Goals

- Auto-generating modules from an OpenAPI spec (hand-written, idiomatic modules
  instead).
- A single mega-module dispatching on a `resource:` parameter.
- Managing Pocket-ID passkeys/credentials or end-user authentication flows.
- Publishing to Ansible Galaxy in this iteration (structure is Galaxy-ready, but
  release automation is out of scope here).

## Architecture

Approach: thin per-resource modules over a shared `module_utils` HTTP client.

- One Python HTTP client in `plugins/module_utils/pocketid.py` ports the Go
  client: `X-API-KEY` auth, retry with exponential backoff, `429` `Retry-After`
  handling, and structured error parsing (`{error, message}`).
- The client uses Ansible's vendored `ansible.module_utils.urls.open_url`, so the
  collection has **zero runtime Python dependencies** (no `requests`).
- Each resource is its own small, independently testable module that calls the
  shared client. This matches idiomatic Ansible structure and the TF internals
  1:1.

### Collection layout

```
ansible_collections/trozz/pocketid/   (dev layout; repo root maps here)
├── galaxy.yml                # collection metadata, version, deps
├── meta/runtime.yml          # requires_ansible (>=2.15), action_groups
├── README.md, LICENSE, CHANGELOG.rst
├── plugins/
│   ├── module_utils/pocketid.py     # HTTP client + shared argspec + env fallback
│   ├── doc_fragments/pocketid.py    # shared connection docs
│   ├── modules/                     # resource + _info modules
│   └── lookup/                      # lookup plugins
├── tests/
│   ├── sanity/                      # ignore files if needed
│   ├── unit/                        # pytest, mocked open_url
│   └── integration/targets/         # live-instance tests per module
├── changelogs/                      # antsibull-changelog config + fragments
└── .github/workflows/ci.yml         # sanity + units + integration matrix
```

The repository root maps to `ansible_collections/trozz/pocketid` for
`ansible-test` (via a symlink or checkout layout documented in the README).

## Components

### Shared infrastructure

- `plugins/doc_fragments/pocketid.py` — documents the common connection options
  so every module's docs stay consistent.
- `plugins/module_utils/pocketid.py`:
  - `pocketid_argument_spec()` — returns the shared connection argspec.
  - `PocketIDClient` — methods mirroring the TF client (CRUD per resource).
  - Env fallback resolution and a helper to build the client from an
    `AnsibleModule`.

### Connection options (all modules + lookups)

| Option           | Type   | Default | Env fallback              | Notes              |
|------------------|--------|---------|---------------------------|--------------------|
| `base_url`       | str    | —       | `POCKETID_BASE_URL`       | required           |
| `api_token`      | str    | —       | `POCKETID_API_TOKEN`      | required, `no_log` |
| `validate_certs` | bool   | `true`  | `POCKETID_VALIDATE_CERTS` |                    |
| `timeout`        | int    | `30`    | `POCKETID_TIMEOUT`        | seconds            |

`meta/runtime.yml` declares an action group so a playbook can set these once via
`module_defaults`.

### Resource modules (FQCN `trozz.pocketid.*`)

All support `state: present|absent` (except where noted), `check_mode`, and
`--diff`. Idempotency model: GET current state, compare to desired, then
POST/PUT/DELETE only when they differ. Fields the API never returns (secrets) are
excluded from diffing.

- **`user`** — `username`, `email`, `first_name`, `last_name`, `display_name`,
  `email_verified`, `is_admin`, `locale`, `disabled`. Folds in:
  - `groups` — declarative group membership (list of group names or IDs) with an
    `append` option (default `false` = authoritative/purge).
  - `custom_claims` — dict of key/value claims (authoritative).
  Managed via `/users/{id}/user-groups` and `/custom-claims/user/{id}`.
- **`group`** — `name`, `friendly_name`, plus folded `custom_claims`. Group
  membership is intentionally owned by the `user` module to avoid
  double-ownership conflicts.
- **`client`** — OIDC client: `name`, `callback_urls`, `logout_callback_urls`,
  `is_public`, `pkce_enabled`, `requires_reauthentication`,
  `requires_pushed_authorization_requests`, `launch_url`, `is_group_restricted`,
  `allowed_user_groups`, and federated identity `credentials`. The client
  `secret` is returned on create for confidential clients; `regenerate_secret:
  true` is an opt-in, non-idempotent action (documented, `no_log`).
- **`application_config`** — singleton. The Pocket-ID
  `PUT /api/application-configuration` is **all-or-nothing**: its
  `AppConfigUpdateDto` marks many keys `required` (several with `oneof`
  constraints), so a partial body is rejected. The module therefore uses a
  **read-modify-write overlay**: it GETs the current config, overlays the keys
  the user specified, and PUTs the complete DTO. Users declare only what they
  want to change; unspecified keys retain their current value. Secret fields
  (`smtp_password`, `ldap_bind_password`) are `no_log`. The full writable key set
  from `ApplicationConfig` / `AppConfigUpdateDto` is supported.
- **`scim_service_provider`** — `endpoint`, `token` (`no_log`),
  `oidc_client_id`; full CRUD.
- **`one_time_access_token`** — generates a one-time access token for a user.
  Inherently non-idempotent (action-style); returns the token (`no_log`) and is
  documented as always-changed.

### Info modules (read-only; mirror the TF data sources)

- `user_info`, `group_info`, `client_info`, `application_config_info` — get by
  id/name or list all with simple filters. Return structured facts; never report
  `changed`.

### Lookup plugins

- `user`, `group`, `client`, `application_config` — the same reads, usable inline
  (e.g. `lookup('trozz.pocketid.user', 'alice')`). Connection options resolved
  from plugin options and the same env vars.

## Data flow

1. Module resolves connection options (args → env fallback) and builds a
   `PocketIDClient`.
2. Module GETs the current object (by id or by natural key such as username /
   group name / client name).
3. Module computes the desired state from parameters and diffs against current.
4. In check mode, it reports `changed` and the diff without writing.
5. Otherwise it issues the minimal POST/PUT/DELETE calls, then returns the final
   object and `changed`.

## Error handling

- Network/5xx/429 errors retried with exponential backoff; `429` respects
  `Retry-After` (ported from the Go client).
- API error bodies (`{error, message}`) surfaced via `fail_json` together with
  the HTTP status code.
- Missing required connection options fail early with an actionable message
  naming the env var fallback.

## Testing (full pyramid)

- **Sanity**: `ansible-test sanity --docker` — validate-modules, docs, import,
  and `no_log` checks. Any unavoidable ignores recorded under `tests/sanity/`.
- **Unit**: pytest via `ansible-test units`, mocking `open_url`. Cover argspec
  validation, idempotency/diff logic, secret handling, and error paths per
  module and for the shared client.
- **Integration**: `ansible-test integration` targets per module against a live
  Pocket-ID started via docker-compose. The database is seeded with a fixed
  token whose sha256 hash is inserted directly into SQLite, mirroring
  `scripts/prepare-test-db.sh`. Pocket-ID v1 is EOL, so tests run against the
  `v2` and `next` images. A GitHub Actions workflow runs sanity + units on every
  push and integration across a matrix of Pocket-ID image (`v2`, `next`) and a
  small `ansible-core` version range.

## Key decisions

1. **Fold** group membership and custom claims into the `user`/`group` modules
   rather than separate `*_membership` / `*_custom_claims` modules — more
   ergonomic and a single source of truth per object.
2. Use **`open_url`** (Ansible-vendored) instead of `requests` for zero runtime
   dependencies.
3. Keep the TF provider's env var names (`POCKETID_BASE_URL`,
   `POCKETID_API_TOKEN`) for operator familiarity.
4. Reuse the TF provider's DB-seeding strategy for integration test bootstrap.

## Open questions

None blocking. Galaxy publishing/release automation deferred to a later
iteration.
