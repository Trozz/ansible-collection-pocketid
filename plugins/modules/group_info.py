# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
---
module: group_info
short_description: Fetch information about Pocket-ID user groups
version_added: '0.1.0'
description:
  - Read-only module that returns one or more Pocket-ID user groups.
  - Look up a single group by its immutable O(id) or by its natural key O(name)
    (matched against the group C(friendlyName) and C(name) fields), or list all
    groups when neither is given.
  - This module never reports a change.
author:
  - trozz (@trozz)
options:
  id:
    description:
      - Immutable identifier of the group to fetch.
      - Mutually exclusive with O(name).
    type: str
  name:
    description:
      - Natural-key name of the group to fetch, matched against the group
        C(friendlyName) and falling back to C(name).
      - Fails when more than one group carries the name; resolve by O(id) instead.
      - Mutually exclusive with O(id).
    type: str
extends_documentation_fragment:
  - trozz.pocketid.pocketid
'''

EXAMPLES = r'''
- name: List all groups
  trozz.pocketid.group_info:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
  register: all_groups

- name: Fetch a single group by id
  trozz.pocketid.group_info:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    id: 7c9e6679-7425-40de-944b-e07fc1f90ae7
  register: one_group

- name: Fetch a single group by name
  trozz.pocketid.group_info:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    name: developers
  register: dev_group
'''

RETURN = r'''
groups:
  description:
    - The list of matching groups. Contains every group when neither O(id) nor
      O(name) is given, otherwise the single resolved group.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 7c9e6679-7425-40de-944b-e07fc1f90ae7
      name: developers
      friendlyName: Developers
      ldapId: null
group:
  description:
    - The single resolved group when exactly one is requested via O(id) or
      O(name). Null when listing all groups or when no group matched.
  returned: when O(id) or O(name) is given
  type: dict
  sample:
    id: 7c9e6679-7425-40de-944b-e07fc1f90ae7
    name: developers
    friendlyName: Developers
    ldapId: null
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
    pocketid_argument_spec,
)


def _resolve_by_name(client, name):
    """Return the single group whose friendlyName or name equals ``name``.

    Pages all groups (no server-side name filter). Treats friendlyName and name
    as one unified namespace (mirroring resolve_group_refs): collects every group
    matching either field, deduped by id. Returns None when nothing matches;
    raises ValueError when more than one distinct group matches.
    """
    groups = client.list_groups() or []
    matches = {}
    for group in groups:
        if group.get("friendlyName") == name or group.get("name") == name:
            matches[group.get("id")] = group
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(
            "found %d groups matching name=%r; cannot disambiguate "
            "(set an explicit id)" % (len(matches), name)
        )
    return next(iter(matches.values()))


def run(params, client):
    """Pure core logic: resolve group(s) and return a result dict.

    Never reports a change. Raises ValueError/PocketIDError on failure.
    """
    group_id = params.get("id")
    name = params.get("name")

    if group_id is not None:
        group = client.get_group(group_id)
        return dict(changed=False, groups=[group] if group else [], group=group)

    if name is not None:
        group = _resolve_by_name(client, name)
        return dict(changed=False, groups=[group] if group else [], group=group)

    groups = client.list_groups() or []
    return dict(changed=False, groups=groups, group=None)


def main():
    argument_spec = {
        **pocketid_argument_spec(),
        "id": dict(type="str"),
        "name": dict(type="str"),
    }
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        mutually_exclusive=[("id", "name")],
    )

    client = PocketIDClient.from_module(module)

    try:
        result = run(module.params, client)
    except PocketIDError as exc:
        module.fail_json(msg=str(exc), status=getattr(exc, "status", None))
    except ValueError as exc:
        module.fail_json(msg=str(exc))

    module.exit_json(**result)


if __name__ == "__main__":
    main()
