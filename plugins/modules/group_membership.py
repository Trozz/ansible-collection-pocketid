# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
---
module: group_membership
short_description: Manage Pocket-ID group membership authoritatively
version_added: '1.0.0'
description:
  - Manage the membership relation between Pocket-ID users and user groups.
  - >-
    Two mutually-exclusive forms are supported. The B(user form)
    (O(user) plus O(groups)) authoritatively sets the complete set of groups a
    single user belongs to. The B(group form) (O(group) plus O(users))
    authoritatively sets the complete set of users that belong to a single
    group, while preserving each affected user's membership in I(other) groups.
  - >-
    References (O(user), O(group), O(groups), O(users)) may be given as
    canonical IDs or as unique names. Names are resolved to IDs via the
    paginated listing before diffing or writing. Mixed name/ID lists are
    rejected, and not-found or ambiguous names fail explicitly.
  - >-
    Membership is an authoritative full replacement. An empty list clears the
    relevant membership (the user form removes the user from all groups; the
    group form removes all users from the group). Exactly one of the two forms
    must be supplied.
author:
  - trozz (@trozz)
options:
  user:
    description:
      - A single user (by ID or unique username) whose group membership is
        managed authoritatively.
      - Mutually exclusive with O(group) and O(users); requires O(groups).
    type: str
  groups:
    description:
      - The complete set of groups (IDs or unique names) the O(user) must belong to.
      - An empty list removes the user from all groups.
      - Comparison is an unordered set comparison.
    type: list
    elements: str
  group:
    description:
      - A single group (by ID or unique name) whose membership is managed
        authoritatively for the listed users.
      - Mutually exclusive with O(user) and O(groups); requires O(users).
    type: str
  users:
    description:
      - The complete set of users (IDs or unique usernames) that must belong to O(group).
      - An empty list removes all listed users from the group; only membership
        in this single group is affected, other group memberships are preserved.
      - Comparison is an unordered set comparison.
    type: list
    elements: str
  manage_ldap_synced:
    description:
      - By default the module refuses to modify the membership of an LDAP-synced
        user or group (one carrying a non-null C(ldapId)), failing fast.
      - Set to V(true) to opt in to managing LDAP-synced objects.
    type: bool
    default: false
notes:
  - >-
    Single-writer rule. The Pocket-ID membership API is per-user. The group form
    therefore writes the whole group list of each affected user. The
    C(trozz.pocketid.user) module's O(groups) option and this module must not
    co-manage the same user, the per-user whole-list PUT is last-write-wins.
  - >-
    Sequence playbooks as groups, then users, then memberships so that all
    referenced objects exist before membership is resolved and written.
extends_documentation_fragment:
  - trozz.pocketid.pocketid
'''

EXAMPLES = r'''
- name: Set the complete set of groups for a user (user form)
  trozz.pocketid.group_membership:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    user: alice
    groups:
      - admins
      - developers

- name: Remove a user from all groups
  trozz.pocketid.group_membership:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    user: alice
    groups: []

- name: Set the complete membership of a group, preserving each user's other groups (group form)
  trozz.pocketid.group_membership:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    group: developers
    users:
      - alice
      - bob

- name: Reconcile membership in a sequenced play (groups, then users, then membership)
  trozz.pocketid.group_membership:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    group: "01HABCDEF0000000000000000"
    users: []
'''

RETURN = r'''
changed:
  description: Whether any membership write was performed.
  returned: always
  type: bool
  sample: true
user:
  description: The resolved user ID when the user form is used.
  returned: when O(user) is set
  type: str
  sample: "01HUSER000000000000000000"
group:
  description: The resolved group ID when the group form is used.
  returned: when O(group) is set
  type: str
  sample: "01HGROUP00000000000000000"
diff:
  description: Before/after membership sets, keyed by the managed object's ID.
  returned: always
  type: dict
  sample:
    before:
      groups: ["01HGROUP00000000000000000"]
    after:
      groups: ["01HGROUP00000000000000000", "01HGROUP11111111111111111"]
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
    pocketid_argument_spec,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    find_one_by_key,
    ldap_guard,
    resolve_group_refs,
    set_equal,
)


def _index_users(users):
    """Build (ids, name_to_ids) indices from a user list keyed on username."""
    ids = set()
    name_to_ids = {}
    for user in users or []:
        uid = user.get("id")
        if uid is not None:
            ids.add(uid)
        label = user.get("username")
        if not label:
            continue
        name_to_ids.setdefault(label, [])
        if uid is not None and uid not in name_to_ids[label]:
            name_to_ids[label].append(uid)
    return ids, name_to_ids


def resolve_user_refs(client, refs):
    """Resolve a list of user references (ids or unique usernames) to user ids.

    Mirrors resolve_group_refs: each ref is classified against the fetched user
    id set, mixed name/id lists are rejected, and not-found or ambiguous names
    fail with ValueError. Returns a list of ids (caller compares as a set).
    """
    if not refs:
        return []
    refs = list(refs)

    users = client.list_users() or []
    ids, name_to_ids = _index_users(users)

    is_id = [ref in ids for ref in refs]
    if any(is_id) and not all(is_id):
        raise ValueError(
            "user references must be all ids or all names, not a mix: %r" % (refs,)
        )

    if all(is_id):
        return list(refs)

    resolved = []
    not_found = []
    ambiguous = []
    for ref in refs:
        candidate_ids = name_to_ids.get(ref)
        if not candidate_ids:
            not_found.append(ref)
            continue
        if len(candidate_ids) > 1:
            ambiguous.append(ref)
            continue
        resolved.append(candidate_ids[0])

    if not_found:
        raise ValueError(
            "user(s) not found by name: %s" % ", ".join(repr(n) for n in not_found)
        )
    if ambiguous:
        raise ValueError(
            "user name(s) are ambiguous (resolve by id): %s"
            % ", ".join(repr(n) for n in ambiguous)
        )
    return resolved


def _resolve_single(client, ref, lister, kind):
    """Resolve a single id-or-name reference to an object id via a full listing."""
    items = client.__getattribute__(lister)() or []
    for item in items:
        if item.get("id") == ref:
            return ref
    field = "username" if kind == "user" else "friendlyName"
    match = find_one_by_key(items, field, ref)
    if match is None and kind == "group":
        match = find_one_by_key(items, "name", ref)
    if match is None:
        raise ValueError("%s not found: %r" % (kind, ref))
    return match["id"]


def _user_current_group_ids(user_obj):
    """Extract the set of group ids a user currently belongs to."""
    return [g.get("id") for g in (user_obj.get("userGroups") or []) if g.get("id")]


def _run_user_form(params, client):
    user_ref = params["user"]
    user_id = _resolve_single(client, user_ref, "list_users", "user")

    user_obj = client.get_user(user_id)
    ldap_guard(user_obj, params["manage_ldap_synced"])

    current_ids = _user_current_group_ids(user_obj)
    desired_ids = resolve_group_refs(client, params["groups"])

    changed = not set_equal(current_ids, desired_ids)
    diff = {
        "before": {"groups": sorted(current_ids)},
        "after": {"groups": sorted(desired_ids)},
    }

    if changed and not params["_check_mode"]:
        client.set_user_groups(user_id, desired_ids)

    return {"changed": changed, "user": user_id, "diff": diff}


def _run_group_form(params, client):
    group_ref = params["group"]
    group_id = _resolve_single(client, group_ref, "list_groups", "group")

    group_obj = client.get_group(group_id)
    ldap_guard(group_obj, params["manage_ldap_synced"])

    desired_user_ids = set(resolve_user_refs(client, params["users"]))

    # Determine the current member set of THIS group by reading affected users.
    current_member_ids = set(
        u.get("id")
        for u in (group_obj.get("users") or [])
        if u.get("id")
    )

    to_add = desired_user_ids - current_member_ids
    to_remove = current_member_ids - desired_user_ids
    affected = to_add | to_remove

    diff = {
        "before": {"users": sorted(current_member_ids)},
        "after": {"users": sorted(desired_user_ids)},
    }

    changed = bool(affected)
    if not changed:
        return {"changed": False, "group": group_id, "diff": diff}

    # Pre-pass: read and LDAP-guard every affected user before deciding to write.
    # This runs in both check and live mode so a --check plan fails identically
    # to a live run, and avoids partial writes when a later user is LDAP-synced.
    affected_users = {}
    for affected_user_id in sorted(affected):
        user_obj = client.get_user(affected_user_id)
        ldap_guard(user_obj, params["manage_ldap_synced"])
        affected_users[affected_user_id] = user_obj

    if params["_check_mode"]:
        return {"changed": True, "group": group_id, "diff": diff}

    # Authoritative for THIS group only: preserve each user's other groups.
    for affected_user_id in sorted(affected):
        user_obj = affected_users[affected_user_id]
        member_group_ids = set(_user_current_group_ids(user_obj))
        if affected_user_id in to_add:
            member_group_ids.add(group_id)
        else:
            member_group_ids.discard(group_id)
        client.set_user_groups(affected_user_id, sorted(member_group_ids))

    return {"changed": True, "group": group_id, "diff": diff}


def run(params, client):
    """Pure core logic. Raises ValueError/PocketIDError on failure.

    Expects params to carry the module options plus a ``_check_mode`` boolean.
    Returns dict(changed=..., user|group=..., diff=...).
    """
    if params.get("user") is not None:
        return _run_user_form(params, client)
    if params.get("group") is not None:
        return _run_group_form(params, client)
    raise ValueError("one of the forms (user+groups or group+users) is required")


def main():
    argument_spec = {
        **pocketid_argument_spec(),
        "user": dict(type="str"),
        "groups": dict(type="list", elements="str"),
        "group": dict(type="str"),
        "users": dict(type="list", elements="str"),
        "manage_ldap_synced": dict(type="bool", default=False),
    }

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=[["user", "group"]],
        mutually_exclusive=[["user", "group"], ["user", "users"], ["group", "groups"]],
        required_together=[["user", "groups"], ["group", "users"]],
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
