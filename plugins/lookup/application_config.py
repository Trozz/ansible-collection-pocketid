# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
name: application_config
short_description: Look up the Pocket-ID application configuration
version_added: '1.0.0'
description:
  - Returns the global Pocket-ID application configuration singleton as a flat
    dictionary keyed by the server's C(camelCase) field names.
  - When one or more terms are given, each term is treated as a configuration key
    and the lookup returns a dictionary containing only those keys; unknown keys
    are omitted. With no terms, the full configuration dictionary is returned.
  - Sensitive keys (C(smtpPassword), C(ldapBindPassword)) are omitted from the
    result, because the underlying API may return them in plaintext. Requesting a
    sensitive key explicitly still omits it.
  - This lookup is read-only.
author:
  - trozz (@trozz)
options:
  _terms:
    description:
      - Optional configuration keys to return. When omitted, the entire
        configuration dictionary is returned.
    type: list
    elements: str
    required: false
  base_url:
    env:
      - name: POCKETID_BASE_URL
  api_token:
    env:
      - name: POCKETID_API_TOKEN
  validate_certs:
    env:
      - name: POCKETID_VALIDATE_CERTS
  timeout:
    env:
      - name: POCKETID_TIMEOUT
extends_documentation_fragment:
  - trozz.pocketid.pocketid
notes:
  - Lookup plugins are not covered by C(module_defaults); connection options must
    be supplied inline (for example via O(base_url) and O(api_token) keyword
    arguments) or through the documented environment variables.
'''

EXAMPLES = r'''
- name: Fetch the full application configuration
  ansible.builtin.debug:
    msg: "{{ lookup('trozz.pocketid.application_config',
                    base_url='https://id.example.com',
                    api_token=pocketid_token) }}"

- name: Fetch only the application name
  ansible.builtin.set_fact:
    app_name: >-
      {{ lookup('trozz.pocketid.application_config', 'appName',
                base_url='https://id.example.com',
                api_token=pocketid_token)['appName'] }}

- name: Use environment-variable based connection options
  ansible.builtin.debug:
    msg: "{{ lookup('trozz.pocketid.application_config') }}"
'''

RETURN = r'''
_raw:
  description:
    - A single-element list whose element is the application configuration as a
      flat dictionary keyed by the server's C(camelCase) field names.
    - When terms are supplied, only the requested (and non-sensitive, known) keys
      are present.
    - Sensitive keys (C(smtpPassword), C(ldapBindPassword)) are always omitted.
  type: list
  elements: dict
'''

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
)


# Internal/non-writable keys returned by the GET that are not part of the
# configuration surface; instanceId is an internal instance identifier.
INTERNAL_KEYS = frozenset(("instanceId",))

# Sensitive keys (camelCase) that must never be returned; the GET may serve
# these in plaintext, so they are omitted entirely from the output.
SECRET_KEYS = frozenset(("smtpPassword", "ldapBindPassword"))

# Connection option keys this lookup resolves (mirrors the shared argspec /
# doc fragment). Declared in DOCUMENTATION via the doc fragment so that
# get_option() can apply the native env: fallbacks.
CONNECTION_OPTIONS = ("base_url", "api_token", "validate_certs", "timeout")


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


def run(terms, params, client):
    """Return the application configuration dict, optionally filtered by terms.

    terms: optional iterable of configuration key names to keep. Empty/None
        returns the full (non-sensitive) configuration. Sensitive and unknown
        keys are never returned.
    params: resolved connection params (unused here; accepted for parity with
        the module run() contract and for client construction by the caller).
    client: an object exposing get_app_config_all().

    Returns the configuration dictionary. Raises PocketIDError on API failure.
    """
    config = _config_from_slice(client.get_app_config_all())

    selected = [t for t in (terms or []) if t]
    if not selected:
        return config

    return {key: config[key] for key in selected if key in config}


class LookupModule(LookupBase):

    def run(self, terms, variables=None, **kwargs):
        self.set_options(var_options=variables, direct=kwargs)

        params = {opt: self.get_option(opt) for opt in CONNECTION_OPTIONS}

        if not params.get("base_url"):
            raise AnsibleError(
                "base_url is required (set the base_url option or the "
                "POCKETID_BASE_URL environment variable)."
            )
        if not params.get("api_token"):
            raise AnsibleError(
                "api_token is required (set the api_token option or the "
                "POCKETID_API_TOKEN environment variable)."
            )

        client = PocketIDClient(
            base_url=params["base_url"],
            api_token=params["api_token"],
            validate_certs=params.get("validate_certs", True),
            timeout=params.get("timeout", 30),
        )

        try:
            config = run(terms, params, client)
        except PocketIDError as exc:
            raise AnsibleError(to_native_error(exc))

        return [config]


def to_native_error(exc):
    """Format a PocketIDError for an AnsibleError message."""
    status = getattr(exc, "status", None)
    if status is not None:
        return "Pocket-ID request failed (HTTP %s): %s" % (status, exc)
    return "Pocket-ID request failed: %s" % (exc,)
