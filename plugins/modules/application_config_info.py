# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
---
module: application_config_info
short_description: Fetch the Pocket-ID application configuration
version_added: '1.0.0'
description:
  - Read-only module that returns the global Pocket-ID application configuration
    singleton as a flat dictionary keyed by the server's C(camelCase) field names.
  - Sensitive keys (C(smtpPassword), C(ldapBindPassword)) are omitted from the
    returned dictionary, because the underlying API may return them in plaintext.
  - This module takes no filters and never reports a change.
author:
  - trozz (@trozz)
extends_documentation_fragment:
  - trozz.pocketid.pocketid
'''

EXAMPLES = r'''
- name: Fetch the application configuration
  trozz.pocketid.application_config_info:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
  register: app_config

- name: Show the configured application name
  ansible.builtin.debug:
    var: app_config.application_config.appName
'''

RETURN = r'''
application_config:
  description:
    - The application configuration as a flat dictionary keyed by the server's
      C(camelCase) field names.
    - Sensitive keys (C(smtpPassword), C(ldapBindPassword)) are omitted.
  returned: always
  type: dict
  sample:
    appName: My Company SSO
    allowUserSignups: withToken
    smtpHost: smtp.example.com
    ldapEnabled: "true"
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
    pocketid_argument_spec,
)


# Internal/non-writable keys returned by the GET that are not part of the
# configuration surface; instanceId is an internal instance identifier.
INTERNAL_KEYS = frozenset(("instanceId",))

# Sensitive keys (camelCase) that must never be returned; the GET may serve
# these in plaintext, so they are omitted entirely from the output.
SECRET_KEYS = frozenset(("smtpPassword", "ldapBindPassword"))


def _config_from_slice(config_slice):
    """Build a {key: value} dict from the GET's list of {key,type,value}.

    Strips internal keys and omits sensitive keys outright. The 'type' field is
    ignored; configuration values are strings end-to-end.
    """
    config = {}
    for entry in config_slice or []:
        key = entry.get("key")
        if not key or key in INTERNAL_KEYS or key in SECRET_KEYS:
            continue
        config[key] = entry.get("value")
    return config


def run(params, client):
    """Fetch the application configuration singleton.

    Returns dict(changed=False, application_config={...}) with sensitive keys
    omitted. Never writes; never reports a change. Raises PocketIDError on
    failure.
    """
    config_slice = client.get_app_config_all()
    return dict(
        changed=False,
        application_config=_config_from_slice(config_slice),
    )


def main():
    argument_spec = {**pocketid_argument_spec()}

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    client = PocketIDClient.from_module(module)

    try:
        result = run(module.params, client)
    except PocketIDError as exc:
        module.fail_json(msg=str(exc), status=getattr(exc, "status", None))

    module.exit_json(**result)


if __name__ == "__main__":
    main()
