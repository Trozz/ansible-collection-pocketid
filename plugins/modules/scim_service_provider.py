# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
---
module: scim_service_provider
short_description: Manage a SCIM service provider for a Pocket-ID OIDC client
version_added: '1.0.0'
description:
  - Create, update, or delete the SCIM service provider configuration attached to
    an OIDC client in Pocket-ID.
  - A SCIM service provider lets Pocket-ID provision users and groups to an
    external service. Each OIDC client may have at most one SCIM service provider.
  - The existing configuration is located via the client's
    C(/oidc/clients/{id}/scim-service-provider) endpoint, so no natural-key
    pagination is required.
author:
  - trozz (@trozz)
options:
  id:
    description:
      - Immutable identifier of the SCIM service provider configuration.
      - Optional anchor used only as a cross-check against the configuration
        resolved from O(oidc_client_id); identity is determined by the client.
    type: str
  oidc_client_id:
    description:
      - ID of the OIDC client this SCIM service provider configuration belongs to.
    type: str
    required: true
  endpoint:
    description:
      - SCIM endpoint base URL of the external service to provision to.
      - Required when O(state=present).
    type: str
  token:
    description:
      - Bearer token used to authenticate against the SCIM endpoint.
      - This value is sensitive. It is returned decrypted on read but is redacted
        from diff output and stripped from the returned object.
      - The token is written only when supplied; omitting it leaves the stored
        token unchanged.
    type: str
  state:
    description:
      - Whether the SCIM service provider configuration should exist.
    type: str
    choices: [present, absent]
    default: present
extends_documentation_fragment:
  - trozz.pocketid.pocketid
'''

EXAMPLES = r'''
- name: Configure a SCIM service provider for a client
  trozz.pocketid.scim_service_provider:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    oidc_client_id: 3f1c2b8a-1234-4d5e-9abc-0123456789ab
    endpoint: https://scim.example.com/v2
    token: "{{ scim_bearer_token }}"
    state: present

- name: Update only the SCIM endpoint, leaving the token untouched
  trozz.pocketid.scim_service_provider:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    oidc_client_id: 3f1c2b8a-1234-4d5e-9abc-0123456789ab
    endpoint: https://scim.example.com/v2/new

- name: Remove a SCIM service provider
  trozz.pocketid.scim_service_provider:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    oidc_client_id: 3f1c2b8a-1234-4d5e-9abc-0123456789ab
    state: absent
'''

RETURN = r'''
scim_service_provider:
  description:
    - The SCIM service provider configuration after the operation.
    - Empty when O(state=absent). The O(token) value is never returned.
  returned: success
  type: dict
  sample:
    id: 9a8b7c6d-1234-4d5e-9abc-0123456789ab
    endpoint: https://scim.example.com/v2
    oidcClient:
      id: 3f1c2b8a-1234-4d5e-9abc-0123456789ab
      name: My App
    lastSyncedAt: null
    createdAt: '2026-06-16T10:00:00Z'
diff:
  description: Before/after view of the writable fields, with secrets redacted.
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
    compute_diff,
    redact,
)


# Writable, round-trippable fields used for diffing. The secret token is handled
# separately (change-only-on-explicit-input) and is excluded here so it never
# leaks into diff output or the idempotency comparison.
WRITABLE_FIELDS = ("endpoint",)

# Secret keys redacted from diff and stripped from the returned object.
SECRET_KEYS = ("token",)


def _get_existing(client, oidc_client_id):
    """Return the existing SCIM service provider, or None when absent (404)."""
    try:
        return client.get_client_scim_service_provider(oidc_client_id)
    except PocketIDError as exc:
        if exc.status == 404:
            return None
        raise


def _public(provider):
    """Strip secret keys from a provider object for return."""
    if not provider:
        return {}
    out = dict(provider)
    for key in SECRET_KEYS:
        out.pop(key, None)
    return out


def run(params, client):
    """Pure core logic. Returns a result dict; raises PocketIDError/ValueError.

    Identity is the SCIM service provider attached to ``oidc_client_id``. The
    optional ``id`` anchor is cross-checked against the resolved object.
    """
    oidc_client_id = params["oidc_client_id"]
    state = params["state"]
    anchor_id = params.get("id")
    check_mode = params.get("_ansible_check_mode", False)

    existing = _get_existing(client, oidc_client_id)

    if existing and anchor_id and existing.get("id") != anchor_id:
        raise ValueError(
            "id %r does not match the SCIM service provider %r resolved for "
            "oidc_client_id %r" % (anchor_id, existing.get("id"), oidc_client_id)
        )

    if state == "absent":
        return _run_absent(client, existing, check_mode)

    return _run_present(client, params, existing, oidc_client_id, check_mode)


def _run_absent(client, existing, check_mode):
    if not existing:
        return dict(changed=False, scim_service_provider={}, diff=_diff({}, {}))

    diff = _diff({"endpoint": existing.get("endpoint")}, {})
    if not check_mode:
        client.delete_scim_service_provider(existing["id"])
    return dict(changed=True, scim_service_provider={}, diff=diff)


def _run_present(client, params, existing, oidc_client_id, check_mode):
    endpoint = params.get("endpoint")
    if endpoint is None:
        raise ValueError("endpoint is required when state=present")

    token = params.get("token")

    desired = {"endpoint": endpoint}
    current = existing or {}
    changed, before, after = compute_diff(current, desired, WRITABLE_FIELDS)

    # The token is written only when supplied; the GET returns it decrypted so we
    # compare the supplied value against the stored value and skip the write when
    # unchanged (avoids perpetual changed).
    token_change = token is not None and (not existing or token != existing.get("token"))
    if token_change:
        changed = True

    diff = dict(
        before=redact(before, SECRET_KEYS),
        after=redact(after, SECRET_KEYS),
    )

    if not changed:
        return dict(
            changed=False, scim_service_provider=_public(existing), diff=diff
        )

    if check_mode:
        return dict(changed=True, scim_service_provider=_public(existing), diff=diff)

    body = {"endpoint": endpoint, "oidcClientId": oidc_client_id}
    if token is not None:
        body["token"] = token

    if existing:
        result = client.update_scim_service_provider(existing["id"], body)
    else:
        result = client.create_scim_service_provider(body)

    return dict(changed=True, scim_service_provider=_public(result), diff=diff)


def _diff(before, after):
    return dict(
        before=redact(before, SECRET_KEYS),
        after=redact(after, SECRET_KEYS),
    )


def main():
    argument_spec = {
        **pocketid_argument_spec(),
        "id": dict(type="str"),
        "oidc_client_id": dict(type="str", required=True),
        "endpoint": dict(type="str"),
        "token": dict(type="str", no_log=True),
        "state": dict(type="str", choices=["present", "absent"], default="present"),
    }

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[("state", "present", ["endpoint"])],
    )

    client = PocketIDClient.from_module(module)

    params = dict(module.params)
    params["_ansible_check_mode"] = module.check_mode

    try:
        result = run(params, client)
    except PocketIDError as exc:
        module.fail_json(msg=str(exc), status=getattr(exc, "status", None))
    except ValueError as exc:
        module.fail_json(msg=str(exc))

    module.exit_json(**result)


if __name__ == "__main__":
    main()
