# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
name: group
short_description: Look up Pocket-ID user groups by id or unique name
version_added: '1.0.0'
author:
  - trozz (@trozz)
description:
  - Return one Pocket-ID user group object for each term, resolving each term
    either as an immutable group C(id) or as a unique group name
    (matched against C(friendlyName), then C(name)).
  - Terms that match neither an id nor a name fail. Terms whose name matches more
    than one group fail with a disambiguation error (group names are not
    guaranteed unique); resolve those by id instead.
  - This lookup performs read-only API calls and never reports a change.
notes:
  - Lookup plugins are not covered by C(module_defaults); supply the connection
    options inline (for example O(base_url) and O(api_token)) or through the
    documented environment variables.
options:
  _terms:
    description:
      - One or more group references. Each reference is an immutable group C(id)
        or a unique group name (C(friendlyName) or C(name)).
    type: list
    elements: str
    required: true
  base_url:
    description:
      - Base URL of the Pocket-ID instance, for example C(https://id.example.com).
      - Required. If not set, the value of the E(POCKETID_BASE_URL) environment
        variable is used.
    type: str
    required: true
    env:
      - name: POCKETID_BASE_URL
  api_token:
    description:
      - API token used to authenticate against the Pocket-ID admin API. Sent in
        the C(X-API-Key) request header.
      - Required. If not set, the value of the E(POCKETID_API_TOKEN) environment
        variable is used.
    type: str
    required: true
    env:
      - name: POCKETID_API_TOKEN
  validate_certs:
    description:
      - Whether to validate the TLS certificate of the Pocket-ID instance.
      - Set to V(false) only against trusted hosts with self-signed certificates.
      - If not set, the value of the E(POCKETID_VALIDATE_CERTS) environment
        variable is used (coerced as an Ansible boolean).
    type: bool
    default: true
    env:
      - name: POCKETID_VALIDATE_CERTS
  timeout:
    description:
      - Per-attempt HTTP timeout in seconds.
      - If not set, the value of the E(POCKETID_TIMEOUT) environment variable is
        used.
    type: int
    default: 30
    env:
      - name: POCKETID_TIMEOUT
'''

EXAMPLES = r'''
- name: Look up a group by id
  ansible.builtin.debug:
    msg: "{{ lookup('trozz.pocketid.group', 'b1c2d3e4-...', base_url='https://id.example.com', api_token=my_token) }}"

- name: Look up several groups by name (POCKETID_* env vars set)
  ansible.builtin.debug:
    msg: "{{ lookup('trozz.pocketid.group', 'Admins', 'Developers') }}"

- name: Use the friendly name to get the group id
  ansible.builtin.set_fact:
    admins_group_id: "{{ (lookup('trozz.pocketid.group', 'Administrators') | from_json).id }}"
'''

RETURN = r'''
_raw:
  description:
    - A list of group objects, one per term, in the order the terms were given.
  type: list
  elements: dict
  contains:
    id:
      description: Immutable group identifier.
      type: str
      returned: always
    name:
      description: Group name.
      type: str
      returned: always
    friendlyName:
      description: Human-friendly group name.
      type: str
      returned: when set
    userCount:
      description: Number of members in the group.
      type: int
      returned: when present
'''

from ansible.errors import AnsibleLookupError
from ansible.module_utils.common.text.converters import to_native
from ansible.plugins.lookup import LookupBase

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    find_one_by_key,
)


def resolve_group(client, term):
    """Resolve a single id-or-name term to a group object.

    A term that exactly matches a known group id is fetched by id. Otherwise it
    is treated as a name and matched against ``friendlyName`` then ``name`` over
    the full (paged) group list. Raises ValueError when nothing matches, or when
    a name matches more than one group (disambiguate by id).
    """
    groups = client.list_groups() or []
    by_id = {g.get("id"): g for g in groups if g.get("id") is not None}

    if term in by_id:
        return by_id[term]

    for field in ("friendlyName", "name"):
        match = find_one_by_key(groups, field, term)
        if match is not None:
            return match

    raise ValueError("no group found matching %r (by id or name)" % (term,))


def run(terms, client):
    """Resolve every term to a group object, preserving order.

    Pure core usable without the Ansible lookup harness: callers pass a fake
    client exposing ``list_groups``. Raises ValueError on a missing or ambiguous
    term.
    """
    return [resolve_group(client, term) for term in terms]


class _ParamClient(PocketIDClient):
    """A PocketIDClient built from lookup options rather than an AnsibleModule."""

    @classmethod
    def from_options(cls, base_url, api_token, validate_certs, timeout):
        if not base_url:
            raise AnsibleLookupError(
                "base_url is required (set the option or the "
                "POCKETID_BASE_URL environment variable)."
            )
        if not api_token:
            raise AnsibleLookupError(
                "api_token is required (set the option or the "
                "POCKETID_API_TOKEN environment variable)."
            )
        return cls(
            base_url=base_url,
            api_token=api_token,
            validate_certs=validate_certs,
            timeout=timeout,
        )


class LookupModule(LookupBase):

    def run(self, terms, variables=None, **kwargs):
        self.set_options(var_options=variables, direct=kwargs)

        client = _ParamClient.from_options(
            base_url=self.get_option("base_url"),
            api_token=self.get_option("api_token"),
            validate_certs=self.get_option("validate_certs"),
            timeout=self.get_option("timeout"),
        )

        try:
            return run(terms, client)
        except PocketIDError as exc:
            raise AnsibleLookupError(to_native(exc))
        except ValueError as exc:
            raise AnsibleLookupError(to_native(exc))
