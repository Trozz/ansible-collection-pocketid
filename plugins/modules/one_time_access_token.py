# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
---
module: one_time_access_token
short_description: Mint a one-time access token for a Pocket-ID user
version_added: '1.0.0'
description:
  - Mints a one-time access token for a Pocket-ID user. These tokens let a user
    authenticate once when they do not have access to their passkey.
  - This is an imperative action module, not a declarative resource. It is
    B(not idempotent) - a real run always mints a new token and reports
    C(changed=true).
  - The token value is returned only once on creation. Pocket-ID exposes no
    endpoint to read it back and no endpoint to revoke it, so it cannot be
    refreshed or deleted. The request is never automatically retried.
author:
  - trozz (@trozz)
options:
  user_id:
    description:
      - The ID of the user to mint the token for.
      - Mutually exclusive with O(username); exactly one of O(user_id) or
        O(username) is required.
    type: str
  username:
    description:
      - The username of the user to mint the token for. Resolved to a user ID
        via the users list.
      - Mutually exclusive with O(user_id); exactly one of O(user_id) or
        O(username) is required.
    type: str
  ttl:
    description:
      - Lifetime of the token.
      - May be given as an integer (or integer-valued string) number of seconds,
        or as a Go-style duration string such as V(15m), V(1h) or V(24h).
      - Must be greater than 0 seconds and at most 31 days (V(2678400) seconds /
        V(744h)).
    type: str
    required: true
extends_documentation_fragment:
  - trozz.pocketid.pocketid
'''

EXAMPLES = r'''
- name: Mint a 15 minute token by user ID
  trozz.pocketid.one_time_access_token:
    base_url: https://id.example.com
    api_token: "{{ pocketid_api_token }}"
    user_id: 7c2a1f3e-0000-4000-8000-000000000001
    ttl: 15m
  register: otat

- name: Use the access link
  ansible.builtin.debug:
    msg: "Sign in once at {{ otat.access_link }}"

- name: Mint a token by username with a numeric TTL (1 hour)
  trozz.pocketid.one_time_access_token:
    base_url: https://id.example.com
    api_token: "{{ pocketid_api_token }}"
    username: jdoe
    ttl: 3600
'''

RETURN = r'''
changed:
  description: Always V(true) on a real run; V(true) is also predicted in check mode.
  type: bool
  returned: always
  sample: true
user_id:
  description: The resolved ID of the user the token was minted for.
  type: str
  returned: always
  sample: 7c2a1f3e-0000-4000-8000-000000000001
token:
  description:
    - The one-time access token value. Returned only on a real run.
    - Treated as a secret (C(no_log)); not returned in check mode.
  type: str
  returned: success and not check mode
  sample: a1b2c3d4e5f6
access_link:
  description:
    - Convenience sign-in URL of the form C(<base_url>/lc/<token>).
    - Returned only on a real run.
  type: str
  returned: success and not check mode
  sample: https://id.example.com/lc/a1b2c3d4e5f6
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


# Pocket-ID caps one-time access tokens at 31 days.
MAX_TTL_SECONDS = 31 * 24 * 60 * 60

# Go-style duration unit multipliers (seconds). Mirrors what the API accepts.
_DURATION_UNITS = (
    ("h", 3600),
    ("m", 60),
    ("s", 1),
)


def _parse_ttl_seconds(value):
    """Parse a ttl into a positive integer number of seconds.

    Accepts a bare integer (seconds) or a Go-style duration string built from
    ``h``/``m``/``s`` units (e.g. ``15m``, ``1h30m``, ``24h``). Raises
    ValueError on an unparseable value.
    """
    if value is None:
        raise ValueError("ttl is required")

    text = str(value).strip()
    if not text:
        raise ValueError("ttl must not be empty")

    # Bare integer number of seconds.
    try:
        return int(text)
    except ValueError:
        pass

    remaining = text
    total = 0
    matched = False
    while remaining:
        idx = 0
        while idx < len(remaining) and (remaining[idx].isdigit()):
            idx += 1
        if idx == 0:
            raise ValueError(
                "invalid ttl %r: expected an integer of seconds or a duration "
                "string such as '15m', '1h' or '24h'" % (value,)
            )
        number = int(remaining[:idx])
        rest = remaining[idx:]
        unit_seconds = None
        for unit, seconds in _DURATION_UNITS:
            if rest.startswith(unit):
                unit_seconds = seconds
                rest = rest[len(unit):]
                break
        if unit_seconds is None:
            raise ValueError(
                "invalid ttl %r: unknown or missing time unit (use h, m or s)"
                % (value,)
            )
        total += number * unit_seconds
        matched = True
        remaining = rest

    if not matched:
        raise ValueError(
            "invalid ttl %r: expected an integer of seconds or a duration "
            "string such as '15m', '1h' or '24h'" % (value,)
        )
    return total


def _resolve_user_id(params, client):
    """Return the user id from explicit user_id or by resolving username."""
    user_id = params.get("user_id")
    if user_id:
        return user_id

    username = params.get("username")
    users = client.list_users() or []
    match = find_one_by_key(users, "username", username)
    if match is None:
        raise ValueError("user not found by username: %r" % (username,))
    resolved = match.get("id")
    if not resolved:
        raise ValueError("resolved user has no id: username=%r" % (username,))
    return resolved


def run(params, client, check_mode=False, base_url=None):
    """Mint a one-time access token (imperative; never idempotent).

    In check mode the API is not called: changed is predicted true and no token
    is returned. On a real run the token is minted and returned along with a
    convenience access link.

    Raises ValueError on invalid input (bad ttl, unknown user) and PocketIDError
    on an API failure.
    """
    ttl_seconds = _parse_ttl_seconds(params.get("ttl"))
    if ttl_seconds <= 0:
        raise ValueError("ttl must be greater than 0 seconds")
    if ttl_seconds > MAX_TTL_SECONDS:
        raise ValueError(
            "ttl must be at most 31 days (%d seconds)" % MAX_TTL_SECONDS
        )

    user_id = _resolve_user_id(params, client)

    result = {"changed": True, "user_id": user_id}

    if check_mode:
        return result

    body = {"ttl": "%ds" % ttl_seconds}
    response = client.one_time_access_token(user_id, body) or {}
    token = response.get("token")
    result["token"] = token

    if token and base_url:
        result["access_link"] = "%s/lc/%s" % (base_url.rstrip("/"), token)

    return result


def main():
    argument_spec = {
        **pocketid_argument_spec(),
        "user_id": dict(type="str"),
        "username": dict(type="str"),
        "ttl": dict(type="str", required=True),
    }

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        mutually_exclusive=[("user_id", "username")],
        required_one_of=[("user_id", "username")],
    )

    client = PocketIDClient.from_module(module)

    try:
        result = run(
            module.params,
            client,
            check_mode=module.check_mode,
            base_url=module.params.get("base_url"),
        )
    except ValueError as exc:
        module.fail_json(msg=str(exc))
    except PocketIDError as exc:
        module.fail_json(msg=str(exc), status=getattr(exc, "status", None))

    module.exit_json(**result)


if __name__ == "__main__":
    main()
