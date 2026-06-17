# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
---
module: user_info
short_description: Retrieve information about Pocket-ID users
version_added: '0.1.0'
description:
  - Look up one or more users on a Pocket-ID instance.
  - Provide O(id), O(username), or O(email) to filter; with no filter every user
    is returned.
  - This module is read-only and never reports a change.
author:
  - trozz (@trozz)
options:
  id:
    description:
      - Immutable identifier of the user to retrieve.
      - When set, the user is fetched directly by ID. Mutually exclusive with
        O(username) and O(email).
    type: str
  username:
    description:
      - Username of the user to retrieve.
      - Mutually exclusive with O(id) and O(email).
    type: str
  email:
    description:
      - Email address of the user to retrieve.
      - Mutually exclusive with O(id) and O(username).
    type: str
extends_documentation_fragment:
  - trozz.pocketid.pocketid
'''

EXAMPLES = r'''
- name: List all users
  trozz.pocketid.user_info:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
  register: all_users

- name: Look up a user by username
  trozz.pocketid.user_info:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    username: alice
  register: alice

- name: Look up a user by email
  trozz.pocketid.user_info:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    email: alice@example.com
  register: alice_by_email

- name: Fetch a user by id
  trozz.pocketid.user_info:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    id: 7c9e6679-7425-40de-944b-e07fc1f90ae7
  register: one_user
'''

RETURN = r'''
users:
  description:
    - The list of users matching the filter, or all users when no filter is given.
    - Empty when no user matches.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 7c9e6679-7425-40de-944b-e07fc1f90ae7
      username: alice
      email: alice@example.com
      firstName: Alice
      lastName: Example
      isAdmin: false
      disabled: false
user:
  description:
    - The single matching user.
    - Returned only when exactly one user matches a filter.
  returned: when a single filter matches one user
  type: dict
  sample:
    id: 7c9e6679-7425-40de-944b-e07fc1f90ae7
    username: alice
    email: alice@example.com
    firstName: Alice
    lastName: Example
    isAdmin: false
    disabled: false
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
    pocketid_argument_spec,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    find_one_by_key,
)


def run(params, client):
    """Resolve users by id/username/email filter, else list all.

    Returns dict(changed=False, users=[...]) and adds a ``user`` key when a
    filter matches exactly one user. Never writes; never reports a change.
    """
    user_id = params.get("id")
    username = params.get("username")
    email = params.get("email")

    if user_id:
        users = [client.get_user(user_id)]
    elif username is not None:
        match = find_one_by_key(client.list_users(), "username", username)
        users = [match] if match else []
    elif email is not None:
        match = find_one_by_key(client.list_users(), "email", email)
        users = [match] if match else []
    else:
        users = client.list_users() or []

    result = {"changed": False, "users": users}
    if (user_id or username is not None or email is not None) and len(users) == 1:
        result["user"] = users[0]
    return result


def main():
    argument_spec = {
        **pocketid_argument_spec(),
        "id": dict(type="str"),
        "username": dict(type="str"),
        "email": dict(type="str"),
    }

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        mutually_exclusive=[["id", "username", "email"]],
    )

    client = PocketIDClient.from_module(module)

    try:
        result = run(module.params, client)
    except ValueError as exc:
        module.fail_json(msg=str(exc))
    except PocketIDError as exc:
        module.fail_json(msg=str(exc), status=getattr(exc, "status", None))

    module.exit_json(**result)


if __name__ == "__main__":
    main()
