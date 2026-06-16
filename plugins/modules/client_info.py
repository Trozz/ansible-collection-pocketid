# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
---
module: client_info
short_description: Fetch information about Pocket-ID OIDC clients
version_added: '1.0.0'
description:
  - Read-only module that returns one or more Pocket-ID OIDC clients.
  - Look up a single client by its immutable O(id) or by its natural key O(name)
    (matched against the client C(name) field), or list all clients when neither
    is given.
  - Client secrets are never returned; any secret field is redacted from the
    output.
  - This module never reports a change.
author:
  - trozz (@trozz)
options:
  id:
    description:
      - Immutable identifier of the OIDC client to fetch.
      - Mutually exclusive with O(name).
    type: str
  name:
    description:
      - Natural-key name of the OIDC client to fetch, matched against the client
        C(name) field.
      - Fails when more than one client carries the name; resolve by O(id) instead.
      - Mutually exclusive with O(id).
    type: str
extends_documentation_fragment:
  - trozz.pocketid.pocketid
'''

EXAMPLES = r'''
- name: List all OIDC clients
  trozz.pocketid.client_info:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
  register: all_clients

- name: Fetch a single client by id
  trozz.pocketid.client_info:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    id: 3f9c1d2e-7425-40de-944b-e07fc1f90ae7
  register: one_client

- name: Fetch a single client by name
  trozz.pocketid.client_info:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    name: Grafana
  register: grafana_client
'''

RETURN = r'''
clients:
  description:
    - The list of matching OIDC clients with any secret field redacted.
    - Contains every client when neither O(id) nor O(name) is given, otherwise
      the single resolved client.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 3f9c1d2e-7425-40de-944b-e07fc1f90ae7
      name: Grafana
      isPublic: false
      pkceEnabled: true
      callbackURLs:
        - https://grafana.example.com/login/generic_oauth
client:
  description:
    - The single resolved OIDC client when exactly one is requested via O(id) or
      O(name), with any secret field redacted. Null when listing all clients or
      when no client matched.
  returned: when O(id) or O(name) is given
  type: dict
  sample:
    id: 3f9c1d2e-7425-40de-944b-e07fc1f90ae7
    name: Grafana
    isPublic: false
    pkceEnabled: true
    callbackURLs:
      - https://grafana.example.com/login/generic_oauth
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
    pocketid_argument_spec,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    find_one_by_key,
    redact,
)


# Secret-bearing keys that must never be returned in client info output.
SECRET_KEYS = ("secret", "clientSecret")


def _scrub(obj):
    """Return a copy of a client object with secret fields redacted.

    None passes through unchanged so callers can scrub optional results.
    """
    if not obj:
        return obj
    return redact(obj, SECRET_KEYS)


def run(params, client):
    """Resolve client(s) by id/name filter, else list all.

    Returns dict(changed=False, clients=[...], client=...). Secret fields are
    redacted from every returned object. Never writes; never reports a change.
    Raises ValueError/PocketIDError on failure.
    """
    client_id = params.get("id")
    name = params.get("name")

    if client_id is not None:
        try:
            match = client.get_client(client_id)
        except PocketIDError as exc:
            if getattr(exc, "status", None) == 404:
                match = None
            else:
                raise
        clients = [_scrub(match)] if match else []
        return dict(changed=False, clients=clients, client=_scrub(match))

    if name is not None:
        match = find_one_by_key(client.list_clients(), "name", name)
        clients = [_scrub(match)] if match else []
        return dict(changed=False, clients=clients, client=_scrub(match))

    clients = client.list_clients() or []
    return dict(changed=False, clients=[_scrub(c) for c in clients], client=None)


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
    except ValueError as exc:
        module.fail_json(msg=str(exc))
    except PocketIDError as exc:
        module.fail_json(msg=str(exc), status=getattr(exc, "status", None))

    module.exit_json(**result)


if __name__ == "__main__":
    main()
