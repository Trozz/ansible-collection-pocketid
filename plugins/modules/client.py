# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r"""
module: client
short_description: Manage OIDC clients in Pocket-ID
version_added: '0.1.0'
description:
  - Create, update, and delete OIDC clients in a Pocket-ID instance.
  - >-
    On creation of a confidential client (O(is_public=false)), a client secret is
    generated and returned exactly once in RV(client_secret). The secret is
    irretrievable thereafter and is never returned on subsequent runs; persist it
    immediately.
author:
  - trozz (@trozz)
options:
  id:
    description:
      - Immutable ID of the OIDC client.
      - When set, it anchors identity (enabling in-place rename and disambiguating
        non-unique names). When unset, the client is located by its O(name).
    type: str
  name:
    description:
      - Display name of the OIDC client.
      - Required when O(state=present). When O(state=absent) a client may be
        located by O(id) alone.
    type: str
  callback_urls:
    description:
      - List of allowed callback (redirect) URLs for the OIDC client.
    type: list
    elements: str
  logout_callback_urls:
    description:
      - List of allowed logout callback URLs for the OIDC client.
    type: list
    elements: str
  is_public:
    description:
      - Whether this is a public client (no client secret).
      - A confidential client (V(false)) gets a generated secret on creation.
    type: bool
  pkce_enabled:
    description:
      - Whether PKCE is enabled for this client.
    type: bool
  requires_reauthentication:
    description:
      - Whether this client requires reauthentication for certain flows.
    type: bool
  requires_pushed_authorization_requests:
    description:
      - Whether this client requires Pushed Authorization Requests (PAR, RFC 9126).
      - >-
        Version-absent aware. It is only diffed and sent when the server object
        carries the field (Pocket-ID v2.9.0+) or when explicitly set here. Older
        servers that omit the field leave it untouched.
    type: bool
  launch_url:
    description:
      - Optional launch URL associated with the client.
    type: str
  is_group_restricted:
    description:
      - Whether use of this client is restricted to O(allowed_user_groups).
      - When unset, it is derived from whether O(allowed_user_groups) is non-empty.
    type: bool
  allowed_user_groups:
    description:
      - List of user groups allowed to use this client, by ID or by unique name.
      - Names are resolved to IDs against the group list; mixed name/ID lists, and
        not-found or ambiguous names, fail explicitly. Compared as an unordered ID set.
    type: list
    elements: str
  credentials:
    description:
      - Federated identities (workload identity federation) allowed to authenticate
        as this client.
    type: list
    elements: dict
    suboptions:
      issuer:
        description:
          - Issuer of the federated identity token.
        type: str
        required: true
      subject:
        description:
          - Expected subject of the federated identity token.
        type: str
      audience:
        description:
          - Expected audience of the federated identity token.
        type: str
      jwks:
        description:
          - Optional JWKS used to validate the federated identity token.
        type: str
  state:
    description:
      - Whether the client should be present or absent.
    type: str
    choices: [present, absent]
    default: present
extends_documentation_fragment:
  - trozz.pocketid.pocketid
"""

EXAMPLES = r"""
- name: Create a confidential OIDC client and capture its secret
  trozz.pocketid.client:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    name: Grafana
    callback_urls:
      - https://grafana.example.com/login/generic_oauth
    is_public: false
  register: grafana_client
  no_log: true  # keep the returned client_secret out of logs

- name: Persist the one-time client secret
  ansible.builtin.copy:
    content: "{{ grafana_client.client_secret }}"
    dest: /etc/grafana/oidc_secret
  when: grafana_client.client_secret is defined

- name: Create a public PKCE client restricted to a group
  trozz.pocketid.client:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    name: SPA Dashboard
    callback_urls:
      - https://spa.example.com/callback
    is_public: true
    pkce_enabled: true
    allowed_user_groups:
      - Engineering

- name: Delete a client by name
  trozz.pocketid.client:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    name: Old App
    state: absent
"""

RETURN = r"""
client:
  description: The resulting OIDC client object (secret excluded).
  type: dict
  returned: when O(state=present)
  sample:
    id: 3f9c1d2e
    name: Grafana
    callbackURLs:
      - https://grafana.example.com/login/generic_oauth
    isPublic: false
    pkceEnabled: true
client_secret:
  description:
    - The generated client secret, returned only once on the run that creates a
      confidential client. Irretrievable thereafter.
  type: str
  returned: only on creation of a confidential client
client_id:
  description: The ID of the OIDC client.
  type: str
  returned: when O(state=present)
diff:
  description: Before/after of the writable fields (secrets redacted).
  type: dict
  returned: when changed
"""

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
    pocketid_argument_spec,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    compute_diff,
    find_one_by_key,
    resolve_group_refs,
    set_equal,
)


# Writable, round-trippable fields used for the diff/payload. PAR is handled
# separately because it is version-absent aware.
WRITABLE_FIELDS = (
    "name",
    "callbackURLs",
    "logoutCallbackURLs",
    "isPublic",
    "pkceEnabled",
    "requiresReauthentication",
    "launchURL",
    "isGroupRestricted",
    "credentials",
)

PAR_FIELD = "requiresPushedAuthorizationRequests"

# Maps Ansible option names to their API field names for the client body.
_OPTION_TO_FIELD = {
    "name": "name",
    "callback_urls": "callbackURLs",
    "logout_callback_urls": "logoutCallbackURLs",
    "is_public": "isPublic",
    "pkce_enabled": "pkceEnabled",
    "requires_reauthentication": "requiresReauthentication",
    "launch_url": "launchURL",
}


def _normalize_credentials(creds):
    """Normalize a federated-identity list into a comparable, serializable form.

    Mirrors the backend DTO's ``omitempty`` serialization: only ``issuer`` is
    always present; optional fields are included only when truthy so a GET that
    omits empty optional keys compares equal to the desired state (idempotency).
    """
    out = []
    for cred in creds or []:
        if not cred:
            continue
        item = {"issuer": cred.get("issuer") or ""}
        for key in ("subject", "audience", "jwks"):
            value = cred.get(key)
            if value:
                item[key] = value
        out.append(item)
    return out


def _canonicalize(fields):
    """Return a copy of an API-field dict in a canonical, comparable form.

    Callback-URL allow-lists are semantically unordered, so they are sorted; the
    nested ``credentials`` object is projected to the same round-trippable shape
    as the desired state (issuer + truthy optionals only). Applying this to both
    current and desired before diffing prevents false ``changed`` from URL
    reordering or server-populated credential subkeys.
    """
    out = dict(fields)
    for key in ("callbackURLs", "logoutCallbackURLs"):
        if isinstance(out.get(key), list):
            out[key] = sorted(out[key])
    creds = out.get("credentials")
    if isinstance(creds, dict):
        out["credentials"] = {
            "federatedIdentities": _normalize_credentials(
                creds.get("federatedIdentities")
            )
        }
    return out


def _build_desired(params, current):
    """Build the normalized-desired API field dict from module params.

    ``current`` is the current client object (or None) used only to decide
    whether the version-absent PAR field participates.
    """
    desired = {}

    desired["name"] = params["name"]
    desired["callbackURLs"] = list(params["callback_urls"] or [])

    if params.get("logout_callback_urls") is not None:
        desired["logoutCallbackURLs"] = list(params["logout_callback_urls"])

    for option in (
        "is_public",
        "pkce_enabled",
        "requires_reauthentication",
        "launch_url",
    ):
        if params.get(option) is not None:
            desired[_OPTION_TO_FIELD[option]] = params[option]

    if params.get("credentials") is not None:
        desired["credentials"] = {
            "federatedIdentities": _normalize_credentials(params["credentials"])
        }

    # is_group_restricted: explicit value wins; otherwise derive from groups.
    if params.get("is_group_restricted") is not None:
        desired["isGroupRestricted"] = params["is_group_restricted"]
    elif params.get("allowed_user_groups") is not None:
        desired["isGroupRestricted"] = bool(params["allowed_user_groups"])

    # PAR is version-absent aware: only participate when the user set it or the
    # current server object already carries the field.
    user_set_par = params.get("requires_pushed_authorization_requests") is not None
    server_has_par = bool(current) and PAR_FIELD in current
    if user_set_par or server_has_par:
        if user_set_par:
            desired[PAR_FIELD] = params["requires_pushed_authorization_requests"]
        else:
            desired[PAR_FIELD] = current.get(PAR_FIELD)

    return desired


def _diff_fields(desired):
    """Return the ordered list of diffable API fields for a desired dict."""
    fields = list(WRITABLE_FIELDS)
    if PAR_FIELD in desired:
        fields.append(PAR_FIELD)
    return fields


def _current_allowed_group_ids(current):
    """Extract the current allowed-user-group ID set from a client object."""
    groups = (current or {}).get("allowedUserGroups") or []
    return [g.get("id") for g in groups if g.get("id") is not None]


def _resolve_client(params, client):
    """Locate the target client by id (anchor) or by name. Multi-match fails."""
    cid = params.get("id")
    if cid:
        try:
            return client.get_client(cid)
        except PocketIDError as exc:
            if getattr(exc, "status", None) == 404:
                return None
            raise
    clients = client.list_clients()
    match = find_one_by_key(clients, "name", params["name"])
    if match is None:
        return None
    # The list endpoint returns a lightweight DTO (allowedUserGroupsCount, no
    # populated allowedUserGroups array). Re-fetch the full object so group and
    # other sub-resource comparisons are accurate (idempotency).
    return client.get_client(match["id"])


def run(params, client):
    """Pure core: create/update/delete an OIDC client.

    Returns dict(changed, client, client_id?, client_secret?, diff?).
    Raises ValueError / PocketIDError on failure.
    """
    state = params.get("state", "present")
    check_mode = params.get("_check_mode", False)

    current = _resolve_client(params, client)

    if state == "absent":
        if current is None:
            return {"changed": False}
        result = {
            "changed": True,
            "diff": {"before": {"name": current.get("name")}, "after": {}},
        }
        if not check_mode:
            client.delete_client(current["id"])
        return result

    desired = _build_desired(params, current)
    diff_fields = _diff_fields(desired)

    # Resolve allowed-user-groups (names -> ids) and compare as an unordered set.
    manage_groups = params.get("allowed_user_groups") is not None
    desired_group_ids = []
    if manage_groups:
        desired_group_ids = resolve_group_refs(client, params["allowed_user_groups"])

    if current is None:
        return _create(params, client, desired, diff_fields, manage_groups,
                       desired_group_ids, check_mode)

    return _update(params, client, current, desired, diff_fields, manage_groups,
                   desired_group_ids, check_mode)


def _build_create_body(desired):
    """Build the POST body, defaulting authoritative list fields to []."""
    body = dict(desired)
    body.setdefault("callbackURLs", [])
    if "logoutCallbackURLs" not in body:
        body["logoutCallbackURLs"] = []
    if "credentials" not in body:
        body["credentials"] = {"federatedIdentities": []}
    return body


def _create(params, client, desired, diff_fields, manage_groups, desired_group_ids,
            check_mode):
    after = {f: desired.get(f) for f in diff_fields if f in desired}
    if manage_groups:
        after["allowedUserGroups"] = list(desired_group_ids)
    result = {"changed": True, "diff": {"before": {}, "after": after}}

    is_public = bool(desired.get("isPublic"))

    if check_mode:
        result["client"] = dict(desired)
        return result

    created = client.create_client(_build_create_body(desired))
    client_id = created["id"]
    result["client_id"] = client_id

    if not is_public:
        secret_resp = client.generate_client_secret(client_id)
        secret = None
        if isinstance(secret_resp, dict):
            secret = secret_resp.get("secret")
        elif isinstance(secret_resp, str):
            secret = secret_resp
        if secret:
            result["client_secret"] = secret

    if manage_groups:
        client.set_client_allowed_groups(client_id, desired_group_ids)

    result["client"] = client.get_client(client_id)
    return result


def _update(params, client, current, desired, diff_fields, manage_groups,
            desired_group_ids, check_mode):
    fields_changed, before, after = compute_diff(
        _canonicalize(current), _canonicalize(desired), diff_fields
    )

    groups_changed = False
    if manage_groups:
        current_group_ids = _current_allowed_group_ids(current)
        if not set_equal(current_group_ids, desired_group_ids):
            groups_changed = True
            before["allowedUserGroups"] = list(current_group_ids)
            after["allowedUserGroups"] = list(desired_group_ids)

    changed = fields_changed or groups_changed
    result = {"changed": changed, "client_id": current["id"]}
    if changed:
        result["diff"] = {"before": before, "after": after}

    if not changed or check_mode:
        result["client"] = current
        return result

    client_id = current["id"]
    if fields_changed:
        # desired already carries current PAR forward (see _build_desired) when
        # the server has the field but the user did not set it.
        client.update_client(client_id, dict(desired))

    if groups_changed:
        client.set_client_allowed_groups(client_id, desired_group_ids)

    result["client"] = client.get_client(client_id)
    return result


def main():
    argument_spec = {
        **pocketid_argument_spec(),
        "id": {"type": "str"},
        "name": {"type": "str"},
        "callback_urls": {"type": "list", "elements": "str"},
        "logout_callback_urls": {"type": "list", "elements": "str"},
        "is_public": {"type": "bool"},
        "pkce_enabled": {"type": "bool"},
        "requires_reauthentication": {"type": "bool"},
        "requires_pushed_authorization_requests": {"type": "bool"},
        "launch_url": {"type": "str"},
        "is_group_restricted": {"type": "bool"},
        "allowed_user_groups": {"type": "list", "elements": "str"},
        "credentials": {
            "type": "list",
            "elements": "dict",
            "options": {
                "issuer": {"type": "str", "required": True},
                "subject": {"type": "str"},
                "audience": {"type": "str"},
                "jwks": {"type": "str", "no_log": False},
            },
        },
        "state": {
            "type": "str",
            "choices": ["present", "absent"],
            "default": "present",
        },
    }

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        # name is the natural key only when creating/updating; an id anchor is
        # enough to locate a client for deletion or id-based management.
        required_if=[("state", "present", ("name",))],
    )

    client = PocketIDClient.from_module(module)

    params = dict(module.params)
    params["_check_mode"] = module.check_mode

    try:
        result = run(params, client)
    except (PocketIDError, ValueError) as exc:
        module.fail_json(msg=str(exc), status=getattr(exc, "status", None))

    # client_secret is returned (only on creation) so the caller can persist it;
    # it is deliberately NOT added to no_log_values, which would also mask it in
    # the registered result. Set no_log: true on the task to keep it out of logs.
    module.exit_json(**result)


if __name__ == "__main__":
    main()
