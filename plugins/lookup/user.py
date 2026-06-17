# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
name: user
author:
  - trozz (@trozz)
version_added: '0.1.0'
short_description: Look up Pocket-ID users by id or username
description:
  - Return the user object for each term, where a term is either an immutable
    user id or a username.
  - A term is treated as an id when it matches a known user id, otherwise it is
    resolved as a username via the paginated user list.
  - Returns one entry per term, in the order the terms are given. A term that
    matches no user yields an empty dict for that position.
options:
  _terms:
    description:
      - One or more user ids or usernames to look up.
    type: list
    elements: str
    required: true
  base_url:
    description:
      - Base URL of the Pocket-ID instance, for example C(https://id.example.com).
    type: str
    required: true
    env:
      - name: POCKETID_BASE_URL
  api_token:
    description:
      - API token used to authenticate against the Pocket-ID admin API. Sent in
        the C(X-API-Key) request header.
    type: str
    required: true
    env:
      - name: POCKETID_API_TOKEN
  validate_certs:
    description:
      - Whether to validate the TLS certificate of the Pocket-ID instance.
      - Set to V(false) only against trusted hosts with self-signed certificates.
    type: bool
    default: true
    env:
      - name: POCKETID_VALIDATE_CERTS
  timeout:
    description:
      - Per-attempt HTTP timeout in seconds.
    type: int
    default: 30
    env:
      - name: POCKETID_TIMEOUT
notes:
  - Lookup plugins are not covered by C(module_defaults); supply connection
    options inline as keyword arguments or via the documented environment
    variables.
'''

EXAMPLES = r'''
- name: Look up a single user by username
  ansible.builtin.debug:
    msg: "{{ lookup('trozz.pocketid.user', 'alice', base_url='https://id.example.com', api_token=pocketid_token) }}"

- name: Look up several users by id or username
  ansible.builtin.debug:
    msg: "{{ lookup('trozz.pocketid.user', 'alice', 'id-bob', base_url=url, api_token=token) }}"

- name: Rely on environment variables for connection options
  ansible.builtin.debug:
    msg: "{{ lookup('trozz.pocketid.user', 'alice') }}"
'''

RETURN = r'''
_raw:
  description:
    - A list with one entry per term.
    - Each entry is the matching user object, or an empty dict when no user
      matches that term.
  type: list
  elements: dict
'''

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    find_one_by_key,
)


def lookup_user(term, client):
    """Return the user object for a single term (id or username), or {}.

    The term is treated as an id when it matches a known user id, otherwise it
    is resolved as a username. A duplicate username raises ValueError (via the
    shared resolver). A not-found term yields an empty dict.
    """
    users = client.list_users() or []
    for user in users:
        if user.get("id") == term:
            return user

    match = find_one_by_key(users, "username", term)
    return match if match else {}


class LookupModule(LookupBase):

    def run(self, terms, variables=None, **kwargs):
        self.set_options(var_options=variables, direct=kwargs)

        base_url = self.get_option("base_url")
        api_token = self.get_option("api_token")

        if not base_url:
            raise AnsibleError(
                "base_url is required (set the option or the "
                "POCKETID_BASE_URL environment variable)."
            )
        if not api_token:
            raise AnsibleError(
                "api_token is required (set the option or the "
                "POCKETID_API_TOKEN environment variable)."
            )

        client = PocketIDClient(
            base_url=base_url,
            api_token=api_token,
            validate_certs=self.get_option("validate_certs"),
            timeout=self.get_option("timeout"),
        )

        try:
            return [lookup_user(term, client) for term in terms]
        except ValueError as exc:
            raise AnsibleError(str(exc))
        except PocketIDError as exc:
            raise AnsibleError(str(exc))
