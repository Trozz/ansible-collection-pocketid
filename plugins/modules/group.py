# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
---
module: group
short_description: Manage Pocket-ID user groups
version_added: '1.0.0'
description:
  - Create, update, and delete user groups on a Pocket-ID instance.
  - >-
    This module is membership-write-free. It never modifies the members of a
    group. Use the M(trozz.pocketid.group_membership) module (or the C(groups)
    option of M(trozz.pocketid.user)) to manage membership. The current members
    and member count are exposed read-only for auditing.
  - >-
    Groups owned by an external LDAP directory (those carrying an C(ldapId)) are
    refused by default. Set O(manage_ldap_synced=true) to opt in to managing
    them.
author:
  - trozz (@trozz)
options:
  id:
    description:
      - Immutable identifier of the group.
      - >-
        When set, it anchors identity, enabling an in-place rename and
        disambiguating non-unique names. When omitted, the group is located by
        its O(name).
    type: str
  name:
    description:
      - Unique name of the group.
      - Required when O(state=present).
    type: str
  friendly_name:
    description:
      - Human-friendly display name of the group.
    type: str
  custom_claims:
    description:
      - >-
        Custom claims to include in the OIDC tokens of users in this group, as a
        map of claim name to value.
      - Omitting this option (or setting it to V(null)) leaves the existing custom claims untouched.
      - Setting it to an empty mapping (V({})) clears all custom claims.
      - >-
        Setting this option replaces all custom claims for the group
        authoritatively. Reserved claim names (for example V(email), V(groups),
        V(sub)) are rejected before any write.
    type: dict
  manage_ldap_synced:
    description:
      - Allow managing a group that is owned by an external LDAP directory.
      - >-
        By default the module fails fast on an LDAP-synced group (one with a
        non-null C(ldapId)) rather than modifying or deleting it.
    type: bool
    default: false
  state:
    description:
      - Whether the group should exist or not.
    type: str
    choices: [present, absent]
    default: present
extends_documentation_fragment:
  - trozz.pocketid.pocketid
'''

EXAMPLES = r'''
- name: Ensure a group exists
  trozz.pocketid.group:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    name: developers
    friendly_name: Developers

- name: Rename a group in place using its immutable id
  trozz.pocketid.group:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    id: 0d9f4c8e-1b2a-4c3d-9e8f-7a6b5c4d3e2f
    name: engineering
    friendly_name: Engineering

- name: Set custom claims on a group
  trozz.pocketid.group:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    name: developers
    custom_claims:
      department: engineering
      tier: gold

- name: Clear all custom claims from a group
  trozz.pocketid.group:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    name: developers
    custom_claims: {}

- name: Remove a group
  trozz.pocketid.group:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    name: developers
    state: absent
'''

RETURN = r'''
group:
  description: The resulting group object, or the previous object when removed.
  returned: success
  type: dict
  contains:
    id:
      description: Immutable identifier of the group.
      type: str
      returned: success
    name:
      description: Unique name of the group.
      type: str
      returned: success
    friendly_name:
      description: Human-friendly display name of the group.
      type: str
      returned: success
    custom_claims:
      description: Custom claims set on the group as a map of name to value.
      type: dict
      returned: success
    members:
      description: Read-only list of members currently in the group.
      type: list
      elements: dict
      returned: success
    user_count:
      description: Read-only count of members in the group.
      type: int
      returned: success
diff:
  description: The before/after writable state of the group.
  returned: when supported
  type: dict
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
    pocketid_argument_spec,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    claims_dict_to_list,
    claims_list_to_dict,
    compute_diff,
    find_one_by_key,
    ldap_guard,
    validate_custom_claims,
)


# Writable, round-trippable fields used for diffing (scalar group attributes).
WRITABLE_FIELDS = ("name", "friendlyName")


def _present_group(client, group):
    """Shape an API group object into the module's returned representation."""
    members = group.get("users") or []
    return {
        "id": group.get("id"),
        "name": group.get("name"),
        "friendly_name": group.get("friendlyName"),
        "custom_claims": claims_list_to_dict(group.get("customClaims")),
        "members": members,
        "user_count": group.get("userCount", len(members)),
    }


def _resolve_group(client, params):
    """Locate the target group by id (if given) else by unique name."""
    group_id = params.get("id")
    if group_id:
        try:
            return client.get_group(group_id)
        except PocketIDError as exc:
            if getattr(exc, "status", None) == 404:
                return None
            raise
    name = params.get("name")
    if not name:
        return None
    groups = client.list_groups()
    match = find_one_by_key(groups, "name", name)
    if match is None:
        return None
    # The list endpoint returns a lightweight DTO that may omit customClaims;
    # re-fetch the full group so custom-claim comparison is accurate.
    return client.get_group(match["id"])


def run(params, client):
    """Pure core logic. Returns dict(changed, group, diff); raises on failure."""
    state = params.get("state")
    custom_claims = params.get("custom_claims")
    manage_ldap_synced = params.get("manage_ldap_synced")
    check_mode = params.get("_check_mode", False)

    validate_custom_claims(custom_claims)

    existing = _resolve_group(client, params)

    if existing is not None:
        ldap_guard(existing, manage_ldap_synced)

    if state == "absent":
        if existing is None:
            return {"changed": False, "group": None, "diff": {"before": {}, "after": {}}}
        before = {"name": existing.get("name"), "friendlyName": existing.get("friendlyName")}
        if not check_mode:
            client.delete_group(existing["id"])
        return {
            "changed": True,
            "group": _present_group(client, existing),
            "diff": {"before": before, "after": {}},
        }

    if not params.get("name"):
        raise ValueError("name is required when state is present")

    desired = {"name": params.get("name")}
    if params.get("friendly_name") is not None:
        desired["friendlyName"] = params.get("friendly_name")

    if existing is None:
        # The API requires friendlyName on creation; default it to the name so a
        # caller that omits friendly_name does not hit an HTTP 400. On update an
        # omitted friendly_name is left untouched (not reset).
        desired.setdefault("friendlyName", params.get("name"))
        return _create(client, params, desired, custom_claims, check_mode)

    return _update(client, existing, desired, custom_claims, check_mode)


def _create(client, params, desired, custom_claims, check_mode):
    """Create a new group (and set initial custom claims when provided)."""
    body = {"name": desired["name"], "friendlyName": desired.get("friendlyName", "")}
    after = dict(desired)

    claims_after = None
    if custom_claims is not None:
        claims_after = dict(custom_claims)

    if check_mode:
        result_group = {
            "id": None,
            "name": body["name"],
            "friendlyName": body["friendlyName"],
            "customClaims": claims_dict_to_list(claims_after),
            "users": [],
            "userCount": 0,
        }
        diff = {"before": {}, "after": after}
        if claims_after is not None:
            diff["after"] = dict(after, custom_claims=claims_after)
        return {"changed": True, "group": _present_group(client, result_group), "diff": diff}

    created = client.create_group(body)
    if custom_claims is not None:
        client.set_group_custom_claims(created["id"], claims_dict_to_list(custom_claims))
        created = client.get_group(created["id"])

    diff = {"before": {}, "after": after}
    if claims_after is not None:
        diff["after"] = dict(after, custom_claims=claims_after)
    return {"changed": True, "group": _present_group(client, created), "diff": diff}


def _update(client, existing, desired, custom_claims, check_mode):
    """Update scalar fields and/or custom claims of an existing group."""
    scalar_changed, before, after = compute_diff(existing, desired, WRITABLE_FIELDS)

    current_claims = claims_list_to_dict(existing.get("customClaims"))
    claims_changed = False
    if custom_claims is not None and custom_claims != current_claims:
        claims_changed = True
        before["custom_claims"] = current_claims
        after["custom_claims"] = dict(custom_claims)

    changed = scalar_changed or claims_changed
    diff = {"before": before, "after": after}

    if not changed:
        return {"changed": False, "group": _present_group(client, existing), "diff": diff}

    if check_mode:
        merged = dict(existing)
        if scalar_changed:
            merged.update({k: desired[k] for k in desired})
        if claims_changed:
            merged["customClaims"] = claims_dict_to_list(custom_claims)
        return {"changed": True, "group": _present_group(client, merged), "diff": diff}

    result = existing
    if scalar_changed:
        body = {
            "name": desired.get("name", existing.get("name")),
            "friendlyName": desired.get("friendlyName", existing.get("friendlyName") or ""),
        }
        result = client.update_group(existing["id"], body)

    if claims_changed:
        client.set_group_custom_claims(existing["id"], claims_dict_to_list(custom_claims))
        result = client.get_group(existing["id"])

    return {"changed": True, "group": _present_group(client, result), "diff": diff}


def main():
    argument_spec = {
        **pocketid_argument_spec(),
        "id": {"type": "str"},
        "name": {"type": "str"},
        "friendly_name": {"type": "str"},
        "custom_claims": {"type": "dict"},
        "manage_ldap_synced": {"type": "bool", "default": False},
        "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
    }

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[("state", "present", ["name"])],
    )

    client = PocketIDClient.from_module(module)

    params = dict(module.params)
    params["_check_mode"] = module.check_mode

    try:
        result = run(params, client)
    except PocketIDError as exc:
        module.fail_json(msg=str(exc), status=getattr(exc, "status", None))
    except ValueError as exc:
        module.fail_json(msg=str(exc))

    module.exit_json(**result)


if __name__ == "__main__":
    main()
