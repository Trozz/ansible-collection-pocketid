# Design: Ansible Collection `trozz.pocketid`

Date: 2026-06-16
Status: Approved (hardened after adversarial design review)

## Goal

Provide an Ansible collection that manages a [Pocket-ID](https://github.com/pocket-id/pocket-id)
instance through its REST API, reaching feature parity with the existing
[`terraform-provider-pocketid`](../../../../terraform-provider-pocketid). Users
manage users, groups, OIDC clients, application configuration, SCIM service
providers, group memberships, and (imperatively) one-time access tokens and
client-secret rotation from playbooks, and query the same objects from tasks and
inline lookups.

## Background

The Terraform provider talks to Pocket-ID over HTTP using an `X-API-KEY` header
against `/api/...` endpoints. Its internal client
(`internal/client/client.go`, `models.go`) defines the API surface we mirror.

Confirmed facts from the Pocket-ID backend source that shape this design:

- **Auth**: API tokens are stored as an unsalted SHA-256 hash
  (`utils.CreateSha256Hash(token)`) in `api_keys.Key`; the header is `X-API-Key`.
  All management endpoints are admin-scoped. (`internal/service/api_key_service.go`,
  `internal/middleware/api_key_auth.go`.)
- **App config PUT is destructive-by-omission**: `UpdateAppConfig` reflects over
  the *entire* `AppConfigUpdateDto`; any field whose value is `""` is **reset to
  its default**, not left unchanged. A partial body therefore resets every
  unspecified key. (`internal/service/app_config_service.go`.)
- **App config + UI lock**: when `UI_CONFIG_DISABLED=true`, the PUT returns
  `UiConfigDisabledError` (updates impossible) and the GET redacts sensitive
  values (`smtpPassword`, `ldapBindPassword`) to the literal `XXXXXXXXXX`;
  otherwise the GET returns them in plaintext. (`ToAppConfigVariableSlice`,
  `internal/model/app_config.go`.)
- **No by-name lookup endpoints**; list endpoints are paginated
  (`PaginatedResponse` with `currentPage`/`totalPages`).
- Auth env vars used by the provider, kept for consistency: `POCKETID_BASE_URL`,
  `POCKETID_API_TOKEN`.

Pocket-ID v1 is end-of-life. Integration tests target the `v2` (pinned, blocking)
and `next` (continue-on-error, informational) images only.

## Non-Goals

- Auto-generating modules from an OpenAPI spec (hand-written, idiomatic modules).
- A single mega-module dispatching on a `resource:` parameter.
- Managing passkeys/credentials or end-user authentication flows.
- Galaxy release automation (structure is Galaxy-ready; release is a later
  iteration).

## Architecture

Approach: thin per-resource modules over a shared `module_utils` HTTP client.

- One Python HTTP client in `plugins/module_utils/pocketid.py` ports the Go
  client but adapts to Python/urllib semantics (see HTTP client contract).
- The client uses `ansible.module_utils.urls.open_url`, so the collection has
  **zero runtime Python dependencies** (no `requests`).
- Modules execute where ansible-core runs (controller or a delegated host with a
  modern Python), so `open_url` uses a current TLS stack and no managed-node
  Python is required.
- Each resource is its own small, independently testable module.

### Collection layout

```
ansible_collections/trozz/pocketid/   (the canonical path ansible-test needs)
├── galaxy.yml                # collection metadata, version
├── meta/runtime.yml          # requires_ansible (>=2.15), action_groups
├── README.md, LICENSE, CHANGELOG.rst
├── plugins/
│   ├── module_utils/pocketid.py     # HTTP client + shared argspec helpers
│   ├── doc_fragments/pocketid.py    # shared connection docs (single source)
│   ├── modules/                     # resource + action + _info modules
│   └── lookup/                      # lookup plugins
├── tests/
│   ├── sanity/                      # ignore files if unavoidable
│   ├── unit/                        # pytest, mocked open_url
│   └── integration/targets/         # live-instance tests per module
├── changelogs/                      # antsibull-changelog config + fragments
└── .github/workflows/ci.yml         # sanity + units + integration matrix
```

`ansible-test` requires the collection at a path ending in
`ansible_collections/trozz/pocketid`. **CI** uses `actions/checkout` with
`path: ansible_collections/trozz/pocketid` and runs `ansible-test` from there. A
repo-root symlink into that layout is for local dev only.

## HTTP client contract (`PocketIDClient`)

The Go client returns a response struct and inspects `StatusCode`. `open_url`
instead **raises `urllib.error.HTTPError` on any non-2xx**. The port must:

- Wrap `open_url` in `try/except`, catching `HTTPError` (has `.code`, `.headers`,
  and is a one-shot readable body) separately from transport errors
  (`URLError`, `socket.timeout`, `SSLValidationError`/`ConnectionError`).
- On `HTTPError`, **read the body exactly once** into a variable before any
  branching (urllib bodies are not re-readable), then parse `{error, message}`
  and surface it with `.code` via `fail_json`.
- **Retry classification by integer status code and exception type, never by
  substring matching**: retry on `429, 500, 502, 503, 504` and on transport
  exception types. 4 total attempts (1 initial + 3 retries); pre-attempt backoff
  `1s / 2s / 4s`.
- `429`: replace backoff with `Retry-After`, parsed as **integer seconds OR
  HTTP-date** (`email.utils.parsedate_to_datetime`), floored at `>0`, defaulting
  to `60s` when absent/unparseable (mirrors Go `parseRetryAfter`).
- **Retries apply to idempotent methods (GET/PUT/DELETE).** POST is retried only
  when safe; `one_time_access_token` creation and client-secret rotation are
  **never auto-retried** (avoid minting duplicates).
- Encode request bodies with `json.dumps` → UTF-8 bytes; set `Content-Type`,
  `Accept`, and `X-API-Key` explicitly on every request. `api_token` is `no_log`.
- **Guard empty/whitespace response bodies** (DELETE/204) — do not `json.loads`
  them. **Authoritative list fields serialize as `[]`, never `null`** (so a
  replace-all actually purges).
- Per-call connections; no session/pool abstraction (would reintroduce a runtime
  dependency).
- Natural-key resolution **pages through all results** (`currentPage..totalPages`)
  before concluding an object is absent, because there is no server-side name
  filter.

## Connection options (all modules + lookups)

| Option           | Type | Default | Env fallback              | Notes                                   |
|------------------|------|---------|---------------------------|-----------------------------------------|
| `base_url`       | str  | —       | `POCKETID_BASE_URL`       | required                                |
| `api_token`      | str  | —       | `POCKETID_API_TOKEN`      | required, `no_log`                       |
| `validate_certs` | bool | `true`  | `POCKETID_VALIDATE_CERTS` | maps to `open_url(validate_certs=...)`   |
| `timeout`        | int  | `30`    | `POCKETID_TIMEOUT`        | per-attempt seconds                     |

- `validate_certs` keeps the Ansible polarity (`true` = verify), inverse of the
  Go `InsecureSkipVerify`. `POCKETID_VALIDATE_CERTS` is coerced via Ansible
  boolean parsing (`convert_bool`), never used as a raw string.
- `timeout` is per-attempt; with retries the worst-case wall time is
  `~(retries+1) * timeout + (1+2+4)s` backoff.
- Connection options live in **one `doc_fragment`** consumed by both modules and
  lookups. Lookups do not use `AnsibleModule` argspec — they declare options in
  `DOCUMENTATION` and resolve via `get_option()` with native `env:` fallbacks
  (not `os.environ`). A unit test asserts module-argspec keys == lookup-option
  keys == doc-fragment keys.
- `meta/runtime.yml` declares an `action_group` listing **all** modules
  (including every `*_info`) so `module_defaults` can set connection options
  once. **Lookups are not covered by `module_defaults`** and must receive
  connection options inline or via env — documented explicitly.

## Idempotency, identity, and diff (shared rules)

- **Identity**: each resource is located by a natural key (username / group name /
  client name) *or* an optional immutable **`id`** param. When `id` is set it
  anchors identity, enabling in-place rename and disambiguating non-unique names.
  A lookup returning multiple matches (client/group names are not unique) **fails
  with a disambiguation error** rather than guessing. Changing a natural key
  without an `id` anchor is create+orphan, documented as such.
- **Group references** (`user.groups`, `client.allowed_user_groups`,
  `group_membership`): accept canonical **IDs or unique names**. Names are
  resolved to IDs via the paginated group list before diffing/writing; mixed
  name/ID lists are rejected; not-found and ambiguous names fail explicitly.
  Comparison is an **unordered ID-set** comparison (never names-vs-IDs).
- **Writable-field allowlist**: each module defines an explicit allowlist of
  writable, round-trippable fields for diffing. Computed/read-only fields
  (`display_name` when unset, generated `client_id`, `has_logo`, counts,
  `createdAt`/`updatedAt`, `ldapId`, `lastSyncedAt`) and version-absent fields
  (PAR on older servers) are excluded. Null/empty normalization is explicit
  (e.g. `locale` null == `""`).
- **Shared normalization**: check_mode and live mode share one
  normalization+diff routine; comparison is normalized-desired vs current. A
  converged resource yields `changed=false` in both check and live mode (an
  acceptance criterion verified by idempotency tests).
- **LDAP-owned objects**: an object with a non-null `ldapId` is LDAP-owned. By
  default the module **fails fast** with an actionable message rather than
  diffing/writing/deleting it; an explicit `manage_ldap_synced: true` opts in.
  `ldapId` is never written.
- **Authoritative replace gating**: group/claim/allowed-group writes are
  authoritative full-replace, issued only when the current set was fully read
  (gated on successful pagination). `--diff` shows additions **and** removals.
- **Secrets in output**: modules build explicit before/after diff dicts with
  every secret/`no_log` key redacted; secret-bearing fields (client secret, SCIM
  token, smtp/ldap passwords) are excluded from both `--diff` and the idempotency
  comparison, are written only when the user supplies a value, and are stripped
  from the returned object. A test asserts no secret value appears in diff/result.

## Data flow (resource modules)

1. Resolve connection options (args → env fallback) and build a `PocketIDClient`.
2. Resolve the target object by `id` (if given) else by natural key, **paging all
   results**; multi-match fails.
3. Compute normalized-desired state; diff against normalized-current via the
   shared routine.
4. In check mode, report `changed` + diff without writing.
5. Otherwise issue minimal POST/PUT/DELETE; a create that returns 409/"exists"
   re-resolves the existing object instead of failing. Return the final object
   and `changed`.

## Modules (FQCN `trozz.pocketid.*`)

### Resource modules (`state: present|absent`, check_mode, `--diff`)

- **`user`** — `id?`, `username`, `email`, `first_name`, `last_name`,
  `display_name`, `email_verified`, `is_admin`, `locale`, `disabled`. Folds in:
  - `groups` — authoritative membership by IDs/unique names. **Omitted = leave
    untouched (no API call)**; `[]` = clear. No `append` mode.
  - `custom_claims` — dict. **Omitted/None = untouched**; `{}` = clear. Reserved
    keys (`email`, `groups`, `sub`) rejected client-side before any write.
  Membership via `/users/{id}/user-groups`; claims via `/custom-claims/user/{id}`.
- **`group`** — `id?`, `name`, `friendly_name`, folded `custom_claims` (same
  omitted/`{}` semantics + reserved-key rejection). **Membership-write-free**;
  exposes current members/`user_count` read-only for auditing.
- **`client`** — `id?`, `name`, `callback_urls`, `logout_callback_urls`,
  `is_public`, `pkce_enabled`, `requires_reauthentication`,
  `requires_pushed_authorization_requests` (version-absent aware),
  `launch_url`, `is_group_restricted`, `allowed_user_groups` (ID/name resolved),
  federated identity `credentials`. **Secret lifecycle**: the client secret is
  present in the return **only on the creating run** and is irretrievable
  thereafter; operators must register and persist it immediately. No
  `regenerate_secret` param (rotation is a separate action module).
- **`application_config`** — singleton, **read-modify-write overlay is mandatory**
  because the PUT resets every unspecified key to default. The module GETs
  `/application-configuration/all` immediately before the PUT, strips internal
  keys (`instanceId`) and any non-writable keys, overlays user-specified keys
  onto every current value, and PUTs the complete DTO. Specifics:
  - If `UI_CONFIG_DISABLED` is in effect, the PUT returns `UiConfigDisabledError`;
    the module detects this and **fails with a clear message** (no silent no-op).
  - Secret keys (`smtp_password`, `ldap_bind_password`) are `no_log`,
    change-only-on-explicit-input, and excluded from diff. The module **never
    sends the `XXXXXXXXXX` redaction sentinel** (fails if it would have to).
  - Config values are string-typed end-to-end (`true`/`false` lowercase); the GET
    `type` field is ignored. Enum options (`allow_user_signups`, `smtp_tls`) use
    argspec `choices`; shaped options (`smtp_from` email, `signup_default_*` JSON)
    are validated in-argspec so violations fail before the API call. The overlay
    forwards server-returned keys verbatim for forward-compatibility with
    newly-required fields. PUT 4xx surfaces the `{error, message}` body.
- **`scim_service_provider`** — `endpoint`, `token` (`no_log`, returned decrypted
  on GET → redacted in diff/return), `oidc_client_id`; full CRUD.

### Group membership

- **`group_membership`** — recommended interface for many-to-one membership and
  out-of-band drift reconciliation. Two mutually-exclusive forms: `user` +
  `groups`, or `group` + `users`. ID-based references (names resolved as above),
  authoritative full-replace (`[]` clears; omitted is invalid — one of the forms
  is required). **Single-writer rule**: `user.groups` and `group_membership` must
  not co-manage the same user (last-write-wins on the per-user whole-list PUT) —
  documented. Ship an example play sequencing groups → users → membership.

### Action modules (imperative, non-idempotent; no `state`)

These have their own data flow: validate → (check_mode) predict without calling
the API → POST and return. Always `changed=true`. No natural-key dedup/caching.

- **`one_time_access_token`** — mints a one-time access token for a user. `ttl`
  bounds validated in argspec before the POST. Returns the token (`no_log`).
  Never auto-retried.
- **`client_secret`** — rotates an OIDC client's secret. Returns the new secret
  (`no_log`) once. check_mode never rotates (rotation invalidates the live
  secret). Never auto-retried.

### Info modules (read-only; mirror the TF data sources)

- `user_info`, `group_info`, `client_info`, `application_config_info` — get by
  `id`/natural key or list-all with simple filters; never report `changed`.
  `application_config_info` **redacts/omits** sensitive keys (`smtp_password`,
  `ldap_bind_password`), since the underlying GET may return them in plaintext.

### Lookup plugins

- `user`, `group`, `client`, `application_config` — same reads, usable inline
  (e.g. `lookup('trozz.pocketid.user', 'alice')`). The `application_config`
  lookup applies the same secret redaction as the info module.

## Error handling

- Network/5xx/429 retried per the HTTP client contract; non-idempotent mints
  never retried.
- API error bodies (`{error, message}`) surfaced via `fail_json` with the HTTP
  status code (read once from the `HTTPError` body).
- Missing required connection options fail early, naming the env-var fallback.
- `application_config` surfaces `UiConfigDisabledError` and PUT 4xx field errors
  readably.

## Testing (full pyramid)

- **Sanity**: `ansible-test sanity --docker` (validate-modules, docs, import,
  `no_log` checks). Import sanity passes with only vendored deps. Any unavoidable
  ignores recorded under `tests/sanity/`. CI caches/pins the ansible-test image
  (the initial image/requirements fetch needs network).
- **Unit**: pytest via `ansible-test units`, mocking `open_url`. Required cases:
  HTTPError→`{error,message}` parse and status-based retry (mocked 503 ⇒ exactly
  4 calls + `1/2/4s` sleeps); `Retry-After` seconds and HTTP-date; empty/204 body
  not parsed; empty desired list serialized as `[]`; `validate_certs=False`
  (and env `false`/`0`/`no`) reaching `open_url`; name-on-page-2 resolution;
  per-module no-op idempotency; secret never in diff/result; `application_config`
  GET that omits/redacts `smtp_password` does not blank it; argspec ↔ lookup ↔
  doc-fragment key parity.
- **Integration**: `ansible-test integration` targets per module against a live
  Pocket-ID. **Topology**: Pocket-ID in Docker published on `localhost:1411`; the
  play runs in a host venv targeting `localhost`; `sqlite3` is an explicit
  dependency of the seeding step. **Bootstrap**: seed the DB with a fixed token
  whose unsalted SHA-256 hash is inserted into `api_keys`, bound to a seeded
  **admin** (`is_admin=1`) user. Seeding is **schema-aware** (`PRAGMA
  table_info(api_keys)`, build the column list dynamically; fail with an explicit
  schema-drift message rather than a raw SQLite error; avoid `INSERT OR REPLACE`
  that can null unspecified columns). A **pre-flight authenticated smoke check**
  (e.g. list users) must pass before the suite, asserting admin scope and
  catching token-hash/schema drift early.
  - **Non-idempotent modules** (`one_time_access_token`, `client_secret`) are
    exempt from converge-twice idempotence assertions; their targets instead
    assert check_mode performs no write/mint and a real run returns the
    secret/token exactly once.
- **CI**: `actions/checkout` into `ansible_collections/trozz/pocketid`; runs
  sanity + units on every push; integration across a matrix of Pocket-ID image
  (`v2` pinned/blocking, `next` continue-on-error/informational) and a small
  `ansible-core` version range.

## Key decisions

1. **Membership model**: fold `custom_claims` into `user`/`group` and fold
   convenience `groups` into `user`; add a dedicated `group_membership` module as
   the recommended many-to-one interface. The `group` module is
   membership-write-free but exposes members read-only. Authoritative replace
   only (no append); ID-based references; single-writer rule.
2. **`open_url`** (Ansible-vendored) instead of `requests` for zero runtime
   dependencies; modules run where ansible-core runs (current TLS stack).
3. Keep the TF provider env var names (`POCKETID_BASE_URL`, `POCKETID_API_TOKEN`).
4. **Integration bootstrap** reuses the provider's DB-seed strategy
   (unsalted-SHA-256 token hash) but schema-aware and pinned, with an admin user
   and pre-flight auth smoke check; `v2` blocking, `next` informational.
5. **Identity**: optional immutable `id` anchor enables rename and disambiguates
   non-unique names; multi-match fails.
6. **Non-idempotent operations** (`one_time_access_token`, `client_secret`
   rotation) are imperative action modules, not declarative resources.

## Resolved questions

- App-config overlay semantics, secret redaction, and `UiConfigDisabled` behavior
  — resolved from backend source (see Background / `application_config`).
- Bootstrap mechanism — DB-seed (no API-key-creation CLI exists); schema-aware,
  pinned, admin-scoped, smoke-checked.
- Integration topology — host venv targeting Dockerized Pocket-ID on
  `localhost:1411`.
- Group reference format — IDs or unique names (resolved). LDAP-owned objects —
  fail fast with `manage_ldap_synced` override. Renames — optional `id` anchor.
  Membership — authoritative replace only.

## Open questions

None blocking. Galaxy publishing/release automation deferred.
