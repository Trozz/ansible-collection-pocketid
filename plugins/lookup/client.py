# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
name: client
short_description: Look up Pocket-ID OIDC clients by id or name
version_added: '1.0.0'
author:
  - trozz (@trozz)
description:
  - Return one or more Pocket-ID OIDC client objects.
  - Each search term is resolved either as an immutable client C(id) or, when it
    does not match a known id, as the natural-key client C(name).
  - Resolving a name that matches more than one client fails with a
    disambiguation error; pass the immutable id instead.
  - Client secrets are never returned; any secret field is redacted.
  - This lookup is not covered by C(module_defaults); pass the connection options
    inline or through the C(POCKETID_*) environment variables.
options:
  _terms:
    description:
      - One or more OIDC client ids or names to look up.
      - When no term is given, every client is returned.
    type: list
    elements: str
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
'''

EXAMPLES = r'''
- name: Look up a single client by name
  ansible.builtin.debug:
    msg: "{{ lookup('trozz.pocketid.client', 'Grafana', base_url='https://id.example.com', api_token=token) }}"

- name: Look up a client by immutable id
  ansible.builtin.set_fact:
    grafana: "{{ lookup('trozz.pocketid.client', '3f9c1d2e-7425-40de-944b-e07fc1f90ae7') }}"

- name: Look up several clients at once (relies on POCKETID_* environment variables)
  ansible.builtin.debug:
    msg: "{{ lookup('trozz.pocketid.client', 'Grafana', 'SPA') }}"

- name: Return all clients
  ansible.builtin.debug:
    msg: "{{ query('trozz.pocketid.client', base_url='https://id.example.com', api_token=token) }}"
'''

RETURN = r'''
_raw:
  description:
    - The resolved OIDC client objects, in the order the terms were given, with
      any secret field redacted.
    - When no term is given, contains every client.
  type: list
  elements: dict
'''

from ansible.errors import AnsibleLookupError
from ansible.plugins.lookup import LookupBase

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    find_one_by_key,
    redact,
)


# Secret-bearing keys that must never be returned in lookup output.
SECRET_KEYS = ("secret", "clientSecret")


def _scrub(obj):
    """Return a copy of a client object with secret fields redacted.

    None passes through unchanged so callers can scrub optional results.
    """
    if not obj:
        return obj
    return redact(obj, SECRET_KEYS)


def run(terms, client):
    """Resolve each term to a redacted client object; list all when no terms.

    A term equal to a known client id is resolved by id; otherwise it is treated
    as a natural-key name and matched against the client list. A name matching no
    client raises ValueError; a name matching more than one client raises
    ValueError (disambiguation). Resolving names from the listing avoids placing
    an arbitrary name into a request path. Returns a list of redacted client
    dicts. Raises ValueError/PocketIDError on failure.
    """
    clients = client.list_clients() or []
    if not terms:
        return [_scrub(c) for c in clients]

    by_id = {c.get("id"): c for c in clients if c.get("id") is not None}

    results = []
    for term in terms:
        if term in by_id:
            results.append(_scrub(by_id[term]))
            continue

        by_name = find_one_by_key(clients, "name", term)
        if by_name is None:
            raise ValueError("no Pocket-ID client found for %r" % (term,))
        results.append(_scrub(by_name))

    return results


class LookupModule(LookupBase):

    def _build_client(self):
        base_url = self.get_option("base_url")
        api_token = self.get_option("api_token")

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

        validate_certs = self.get_option("validate_certs")
        if validate_certs is None:
            validate_certs = True
        timeout = self.get_option("timeout")
        if timeout is None:
            timeout = 30

        return PocketIDClient(
            base_url=base_url,
            api_token=api_token,
            validate_certs=validate_certs,
            timeout=timeout,
        )

    def run(self, terms, variables=None, **kwargs):
        self.set_options(var_options=variables, direct=kwargs)

        client = self._build_client()

        try:
            return run(terms, client)
        except (ValueError, PocketIDError) as exc:
            raise AnsibleLookupError(str(exc))
