# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
---
module: user
short_description: Manage Pocket-ID users
version_added: '0.1.0'
description:
  - Create, update, and delete users on a Pocket-ID instance.
  - Optionally manage a user's authoritative group membership and custom claims.
author:
  - trozz (@trozz)
extends_documentation_fragment:
  - trozz.pocketid.pocketid
options:
  id:
    description:
      - Immutable Pocket-ID identifier of the user.
      - When set, it anchors identity (enabling rename of O(username)) and
        disambiguates non-unique natural keys.
    type: str
  username:
    description:
      - Username of the user. This is the natural key when O(id) is not set.
      - Required when O(state=present).
    type: str
  email:
    description:
      - Email address of the user.
    type: str
  first_name:
    description:
      - First name of the user.
    type: str
  last_name:
    description:
      - Last name of the user.
    type: str
  display_name:
    description:
      - Display name of the user.
    type: str
  email_verified:
    description:
      - Whether the user's email address is verified.
    type: bool
  is_admin:
    description:
      - Whether the user is an administrator.
    type: bool
  locale:
    description:
      - Locale of the user, for example V(en) or V(de).
    type: str
  disabled:
    description:
      - Whether the user account is disabled.
    type: bool
  groups:
    description:
      - Authoritative list of groups the user belongs to, given as group IDs or
        unique group names.
      - When omitted, group membership is left untouched (no API call).
      - An empty list V([]) clears all group memberships.
    type: list
    elements: str
  custom_claims:
    description:
      - Authoritative mapping of custom claim keys to string values for the user.
      - When omitted or V(null), custom claims are left untouched (no API call).
      - An empty mapping V({}) clears all custom claims.
      - Reserved OIDC claim keys (for example V(email), V(groups), V(sub),
        V(preferred_username), V(name)) are rejected.
    type: dict
  manage_ldap_synced:
    description:
      - Allow managing a user that is owned by LDAP (carries an C(ldapId)).
      - By default the module fails fast on LDAP-synced users rather than
        modifying or deleting them.
    type: bool
    default: false
  state:
    description:
      - Whether the user should exist.
    type: str
    choices: [present, absent]
    default: present
'''

EXAMPLES = r'''
- name: Create a user
  trozz.pocketid.user:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    username: alice
    email: alice@example.com
    first_name: Alice
    last_name: Example
    is_admin: false
    state: present

- name: Set a user's groups and custom claims authoritatively
  trozz.pocketid.user:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    username: alice
    groups:
      - admins
      - developers
    custom_claims:
      department: engineering
      employee_id: "12345"

- name: Clear a user's group membership
  trozz.pocketid.user:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    username: alice
    groups: []

- name: Delete a user
  trozz.pocketid.user:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    username: alice
    state: absent
'''

RETURN = r'''
user:
  description: The resulting user object, or the deleted object on removal.
  returned: success
  type: dict
  sample:
    id: "b3f1c2d4-..."
    username: alice
    email: alice@example.com
    firstName: Alice
    lastName: Example
    isAdmin: false
    groups:
      - "g1-id"
      - "g2-id"
    customClaims:
      department: engineering
diff:
  description: Before/after view of the changed writable fields.
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
    resolve_group_refs,
    set_equal,
    validate_custom_claims,
)


# Writable, round-trippable user fields mapped from module option -> API field.
USER_FIELD_MAP = {
    "username": "username",
    "email": "email",
    "first_name": "firstName",
    "last_name": "lastName",
    "display_name": "displayName",
    "email_verified": "emailVerified",
    "is_admin": "isAdmin",
    "locale": "locale",
    "disabled": "disabled",
}

# API fields diffed for idempotency (the writable allowlist).
USER_ALLOWLIST = list(USER_FIELD_MAP.values())


def _desired_user_body(params):
    """Build the API user body from supplied (non-None) module params."""
    body = {}
    for option, api_field in USER_FIELD_MAP.items():
        value = params.get(option)
        if value is not None:
            body[api_field] = value
    return body


def _current_group_ids(user):
    """Return the set of group IDs the user currently belongs to."""
    return [g.get("id") for g in (user.get("userGroups") or []) if g.get("id")]


def _get_full_user(client, user_id):
    """Re-fetch the full user object so nested fields are present for diffing.

    The list endpoint returns lightweight DTOs that may omit ``customClaims``;
    diffing against them would break idempotency. A 404 is treated as absent.
    """
    try:
        return client.get_user(user_id)
    except PocketIDError as exc:
        if getattr(exc, "status", None) == 404:
            return None
        raise


def _find_user(client, params):
    """Resolve the target user by id anchor, else by username natural key.

    Resolution scans the paginated listing for the natural key, then re-fetches
    the matched user with a full GET so ``customClaims``/``userGroups`` are
    present for the idempotency comparison (mirrors group_membership.py).
    """
    user_id = params.get("id")
    if user_id:
        return _get_full_user(client, user_id)

    username = params.get("username")
    if not username:
        return None
    users = client.list_users() or []
    match = find_one_by_key(users, "username", username)
    if match is None:
        return None
    return _get_full_user(client, match["id"])


def run(params, client):
    """Pure core logic. Returns a result dict; raises on failures."""
    state = params.get("state")
    manage_ldap = params.get("manage_ldap_synced")

    custom_claims = params.get("custom_claims")
    validate_custom_claims(custom_claims)

    current = _find_user(client, params)

    if current is not None:
        ldap_guard(current, manage_ldap)

    if state == "absent":
        return _run_absent(params, client, current)

    if not params.get("username"):
        raise ValueError("username is required when state=present")

    return _run_present(params, client, current)


def _run_absent(params, client, current):
    if current is None:
        return {"changed": False, "user": None, "diff": {"before": {}, "after": {}}}

    diff = {"before": {"id": current.get("id")}, "after": {}}
    if not params.get("_check_mode"):
        client.delete_user(current["id"])
    return {"changed": True, "user": current, "diff": diff}


def _run_present(params, client, current):
    check_mode = params.get("_check_mode")
    desired = _desired_user_body(params)

    changed = False
    before = {}
    after = {}

    if current is None:
        changed = True
        before = {k: None for k in desired}
        after = dict(desired)
        if check_mode:
            user = dict(desired)
        else:
            user = client.create_user(desired)
    else:
        field_changed, fbefore, fafter = compute_diff(
            current, desired, USER_ALLOWLIST
        )
        before.update(fbefore)
        after.update(fafter)
        if field_changed:
            changed = True
            if check_mode:
                user = dict(current)
                user.update(desired)
            else:
                user = client.update_user(current["id"], desired)
        else:
            user = dict(current)

    user_id = user.get("id")

    groups_changed, gbefore, gafter = _reconcile_groups(
        params, client, current, user, user_id, check_mode
    )
    if groups_changed:
        changed = True
        before["groups"] = gbefore
        after["groups"] = gafter

    claims_changed, cbefore, cafter = _reconcile_claims(
        params, client, current, user, user_id, check_mode
    )
    if claims_changed:
        changed = True
        before["custom_claims"] = cbefore
        after["custom_claims"] = cafter

    return {
        "changed": changed,
        "user": user,
        "diff": {"before": before, "after": after},
    }


def _reconcile_groups(params, client, current, user, user_id, check_mode):
    refs = params.get("groups")
    if refs is None:
        return False, None, None

    desired_ids = resolve_group_refs(client, refs)
    current_ids = _current_group_ids(current) if current is not None else []

    if set_equal(current_ids, desired_ids):
        user["groups"] = list(current_ids)
        return False, None, None

    if not check_mode:
        client.set_user_groups(user_id, desired_ids)
    user["groups"] = list(desired_ids)
    return True, sorted(current_ids), sorted(desired_ids)


def _reconcile_claims(params, client, current, user, user_id, check_mode):
    desired_claims = params.get("custom_claims")
    if desired_claims is None:
        return False, None, None

    current_claims = (
        claims_list_to_dict(current.get("customClaims")) if current is not None else {}
    )

    if current_claims == desired_claims:
        user["customClaims"] = dict(current_claims)
        return False, None, None

    if not check_mode:
        client.set_user_custom_claims(user_id, claims_dict_to_list(desired_claims))
    user["customClaims"] = dict(desired_claims)
    return True, dict(current_claims), dict(desired_claims)


def main():
    argument_spec = {
        **pocketid_argument_spec(),
        "id": dict(type="str"),
        "username": dict(type="str"),
        "email": dict(type="str"),
        "first_name": dict(type="str"),
        "last_name": dict(type="str"),
        "display_name": dict(type="str"),
        "email_verified": dict(type="bool"),
        "is_admin": dict(type="bool"),
        "locale": dict(type="str"),
        "disabled": dict(type="bool"),
        "groups": dict(type="list", elements="str"),
        "custom_claims": dict(type="dict"),
        "manage_ldap_synced": dict(type="bool", default=False),
        "state": dict(type="str", choices=["present", "absent"], default="present"),
    }

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[("state", "present", ["username"])],
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

    module.exit_json(
        changed=result["changed"],
        user=result["user"],
        diff=result.get("diff", {"before": {}, "after": {}}),
    )


if __name__ == "__main__":
    main()
