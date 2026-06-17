# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
---
module: client_secret
short_description: Rotate an OIDC client's secret in Pocket-ID
version_added: '1.0.0'
description:
  - Rotates (regenerates) the secret of an OIDC client managed by Pocket-ID.
  - This is an imperative action module with no state. On a real run it always
    reports C(changed=true) and is never automatically retried, because a
    rotation request is not idempotent.
  - Rotating the secret B(invalidates the previous secret immediately). Any
    integration still using the old secret will stop working until it is updated.
  - The new secret is returned B(only once) in the module result and cannot be
    retrieved again later. Capture and store it immediately. Use the C(no_log)
    task keyword to keep the secret out of console and log output while still
    registering it.
  - In check mode the secret is never rotated; the module reports C(changed=true)
    without contacting the rotation endpoint and without returning a secret.
author:
  - trozz (@trozz)
extends_documentation_fragment:
  - trozz.pocketid.pocketid
options:
  client_id:
    description:
      - Immutable ID of the OIDC client whose secret should be rotated.
      - Mutually exclusive with O(name); exactly one of O(client_id) or O(name)
        is required.
    type: str
  name:
    description:
      - Name of the OIDC client whose secret should be rotated.
      - The name is resolved to a client ID via the paginated client list. If
        more than one client shares the same name the module fails with a
        disambiguation error; supply O(client_id) instead.
      - Mutually exclusive with O(client_id); exactly one of O(client_id) or
        O(name) is required.
    type: str
'''

EXAMPLES = r'''
- name: Rotate a client secret by ID
  trozz.pocketid.client_secret:
    base_url: https://id.example.com
    api_token: "{{ pocketid_api_token }}"
    client_id: 3f1a2b3c-0000-4444-8888-aaaaaaaaaaaa
  register: rotation

- name: Persist the new secret immediately (shown only once)
  ansible.builtin.copy:
    content: "{{ rotation.secret }}"
    dest: /etc/myapp/oidc_client_secret
    mode: '0600'
  no_log: true

- name: Rotate a client secret by name
  trozz.pocketid.client_secret:
    base_url: https://id.example.com
    api_token: "{{ pocketid_api_token }}"
    name: My Web App
'''

RETURN = r'''
changed:
  description: Always V(true) on a real run; V(true) in check mode without rotating.
  type: bool
  returned: always
client_id:
  description: The resolved ID of the OIDC client whose secret was rotated.
  type: str
  returned: always
secret:
  description:
    - The newly generated client secret.
    - Returned only on a real run (never in check mode), and only this once;
      it cannot be retrieved again afterwards.
  type: str
  returned: on a real (non-check-mode) run
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


def _resolve_client_id(params, client):
    """Resolve the target client ID from client_id or name (multi-match fails)."""
    client_id = params.get("client_id")
    if client_id:
        return client_id

    name = params.get("name")
    clients = client.list_clients() or []
    match = find_one_by_key(clients, "name", name)
    if match is None:
        raise ValueError("no OIDC client found with name=%r" % (name,))
    resolved = match.get("id")
    if not resolved:
        raise ValueError("resolved OIDC client with name=%r has no id" % (name,))
    return resolved


def run(params, client, check_mode=False):
    """Rotate a client secret. Pure logic; raises ValueError/PocketIDError on failure."""
    client_id = _resolve_client_id(params, client)

    if check_mode:
        # Never rotate in check mode: rotation invalidates the live secret.
        return dict(changed=True, client_id=client_id)

    result = client.generate_client_secret(client_id)
    secret = None
    if isinstance(result, dict):
        secret = result.get("secret")
    elif isinstance(result, str):
        secret = result

    return dict(changed=True, client_id=client_id, secret=secret)


def main():
    argument_spec = {
        **pocketid_argument_spec(),
        "client_id": dict(type="str"),
        "name": dict(type="str"),
    }

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        mutually_exclusive=[("client_id", "name")],
        required_one_of=[("client_id", "name")],
    )

    client = PocketIDClient.from_module(module)

    try:
        result = run(module.params, client, check_mode=module.check_mode)
    except PocketIDError as exc:
        module.fail_json(msg=str(exc), status=getattr(exc, "status", None))
    except ValueError as exc:
        module.fail_json(msg=str(exc))

    # The secret is the module's primary output and must remain retrievable from
    # the registered result, so it is NOT added to no_log_values (that would mask
    # it in the registered variable too). Callers should set no_log: true on the
    # task to keep it out of console/log output; see EXAMPLES.
    module.exit_json(**result)


if __name__ == "__main__":
    main()
