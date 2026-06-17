# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type


class ModuleDocFragment(object):

    # Shared connection options for all trozz.pocketid modules and lookups.
    DOCUMENTATION = r'''
options:
  base_url:
    description:
      - Base URL of the Pocket-ID instance, for example C(https://id.example.com).
      - Required. If not set, the value of the E(POCKETID_BASE_URL) environment
        variable is used.
    type: str
    required: true
  api_token:
    description:
      - API token used to authenticate against the Pocket-ID admin API. Sent in
        the C(X-API-Key) request header.
      - Required. If not set, the value of the E(POCKETID_API_TOKEN) environment
        variable is used.
    type: str
    required: true
  validate_certs:
    description:
      - Whether to validate the TLS certificate of the Pocket-ID instance.
      - Set to V(false) only against trusted hosts with self-signed certificates.
      - If not set, the value of the E(POCKETID_VALIDATE_CERTS) environment
        variable is used (coerced as an Ansible boolean).
    type: bool
    default: true
  timeout:
    description:
      - Per-attempt HTTP timeout in seconds. With retries, the worst-case wall
        time is roughly (retries + 1) * timeout plus backoff.
      - If not set, the value of the E(POCKETID_TIMEOUT) environment variable is
        used.
    type: int
    default: 30
requirements:
  - python >= 3.9
author:
  - trozz (@trozz)
'''
