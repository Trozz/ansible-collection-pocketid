# Ansible Collection: trozz.pocketid

Manage a [Pocket-ID](https://github.com/pocket-id/pocket-id) instance from
Ansible. The collection provides per-resource modules over a shared HTTP client
that talks to the Pocket-ID REST API (`X-API-Key` auth), with **zero runtime
Python dependencies** (it uses ansible-core's vendored `open_url`).

Modules run wherever ansible-core runs (the controller or a delegated host with
a modern Python and TLS stack); no managed-node Python is required.

## Installation

From Ansible Galaxy:

```bash
ansible-galaxy collection install trozz.pocketid
```

For local development, `ansible-test` requires the collection at a path ending
in `ansible_collections/trozz/pocketid`. Symlink this checkout into your
collections path:

```bash
mkdir -p ~/.ansible/collections/ansible_collections/trozz
ln -s "$(pwd)" ~/.ansible/collections/ansible_collections/trozz/pocketid
```

## Connection and authentication

Every module (and lookup) accepts the same connection options. Each has an
environment-variable fallback so credentials need not appear in playbooks.

| Option           | Type | Default | Env fallback              | Notes                |
|------------------|------|---------|---------------------------|----------------------|
| `base_url`       | str  | —       | `POCKETID_BASE_URL`       | required             |
| `api_token`      | str  | —       | `POCKETID_API_TOKEN`      | required, `no_log`   |
| `validate_certs` | bool | `true`  | `POCKETID_VALIDATE_CERTS` | `true` = verify TLS  |
| `timeout`        | int  | `30`    | `POCKETID_TIMEOUT`        | per-attempt seconds  |

Set connection options once for all modules with `module_defaults` and the
`group/trozz.pocketid.pocketid` action group:

```yaml
- hosts: localhost
  module_defaults:
    group/trozz.pocketid.pocketid:
      base_url: "https://id.example.com"
      api_token: "{{ pocketid_token }}"
  tasks:
    - trozz.pocketid.user:
        username: alice
        email: alice@example.com
```

> **Note:** `module_defaults` action groups cover **modules only**. Lookups are
> **not** covered by `module_defaults`; pass connection options to a lookup
> inline or rely on the `POCKETID_*` environment variables.

## Module index

### Resource modules (`state: present|absent`, check_mode, `--diff`)

| Module                  | Manages                                            |
|-------------------------|----------------------------------------------------|
| `user`                  | Users; folds in `groups` and `custom_claims`       |
| `group`                 | User groups; folds in `custom_claims`              |
| `client`                | OIDC clients; allowed groups, federated identities |
| `application_config`    | Singleton app configuration (read-modify-write)    |
| `scim_service_provider` | SCIM service provider attached to a client         |
| `group_membership`      | Authoritative many-to-one membership reconciliation|

### Action modules (imperative, always `changed`)

| Module                   | Action                                  |
|--------------------------|-----------------------------------------|
| `one_time_access_token`  | Mint a one-time access token for a user |
| `client_secret`          | Rotate an OIDC client's secret          |

### Info modules (read-only)

| Module                     | Reads                          |
|----------------------------|--------------------------------|
| `user_info`                | Users by id/natural key or all |
| `group_info`               | Groups by id/natural key or all|
| `client_info`              | Clients by id/natural key or all|
| `application_config_info`  | App config (secrets redacted)  |

### Lookup plugins

`user`, `group`, `client`, `application_config` — the same reads usable inline,
e.g. `lookup('trozz.pocketid.user', 'alice')`.

## Testing

All tests run with `ansible-test`, which requires the collection at a path
ending in `ansible_collections/trozz/pocketid` (see Installation).

```bash
# Sanity (validate-modules, docs, import, no_log checks)
ansible-test sanity --docker -v

# Unit tests (pytest via ansible-test, mocking open_url)
ansible-test units --docker -v
# or directly with pytest:
pip install -r tests/unit/requirements.txt && pytest tests/unit

# Integration (live Pocket-ID in Docker on localhost:1411)
bash scripts/integration-bootstrap.sh     # start + seed admin/API key + smoke check
ansible-test integration --local -v
bash scripts/integration-bootstrap.sh --down
```

`scripts/integration-bootstrap.sh` starts the `docker-compose.test.yml` stack
(`ghcr.io/pocket-id/pocket-id:v2` by default; override with `POCKET_ID_IMAGE`),
seeds an admin user and an API key into the SQLite DB (schema-aware), runs an
authenticated smoke check, and renders `tests/integration/integration_config.yml`
from its template. It requires `docker`, `sqlite3`, and `curl`. See
[tests/integration/targets/README.md](tests/integration/targets/README.md) for
details. CI runs sanity + units on every push and integration across the
Pocket-ID `v2` (blocking) and `next` (informational) images.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
