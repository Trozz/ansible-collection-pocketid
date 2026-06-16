# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.lookup.user import lookup_user


ALICE = {
    "id": "id-alice",
    "username": "alice",
    "email": "alice@example.com",
    "firstName": "Alice",
}
BOB = {
    "id": "id-bob",
    "username": "bob",
    "email": "bob@example.com",
    "firstName": "Bob",
}


class FakeClient:
    def __init__(self, users=None):
        self._users = users or []
        self.list_calls = 0

    def list_users(self):
        self.list_calls += 1
        return list(self._users)


def test_lookup_by_username():
    client = FakeClient([ALICE, BOB])
    assert lookup_user("alice", client) == ALICE


def test_lookup_by_id():
    client = FakeClient([ALICE, BOB])
    assert lookup_user("id-bob", client) == BOB


def test_id_match_takes_precedence_over_pagination_scan():
    # An id-equal term is returned without raising even if usernames collide.
    client = FakeClient([ALICE, BOB])
    assert lookup_user("id-alice", client) == ALICE


def test_not_found_returns_empty_dict():
    client = FakeClient([ALICE, BOB])
    assert lookup_user("nobody", client) == {}


def test_empty_instance_returns_empty_dict():
    client = FakeClient([])
    assert lookup_user("alice", client) == {}


def test_duplicate_username_raises():
    dup = dict(ALICE, id="id-alice-2")
    client = FakeClient([ALICE, dup])
    with pytest.raises(ValueError):
        lookup_user("alice", client)


def test_one_entry_per_term_ordering():
    client = FakeClient([ALICE, BOB])
    terms = ["id-bob", "alice", "nobody"]
    results = [lookup_user(term, client) for term in terms]
    assert results == [BOB, ALICE, {}]


def test_documentation_option_keys_cover_connection_options():
    import yaml

    from ansible_collections.trozz.pocketid.plugins.lookup import user as user_lookup

    doc = yaml.safe_load(user_lookup.DOCUMENTATION)
    options = doc["options"]

    for key in ("base_url", "api_token", "validate_certs", "timeout"):
        assert key in options, "missing connection option %r" % key

    # Connection options expose the documented env-var fallbacks.
    env_names = {
        key: [entry["name"] for entry in options[key].get("env", [])]
        for key in ("base_url", "api_token", "validate_certs", "timeout")
    }
    assert env_names["base_url"] == ["POCKETID_BASE_URL"]
    assert env_names["api_token"] == ["POCKETID_API_TOKEN"]
    assert env_names["validate_certs"] == ["POCKETID_VALIDATE_CERTS"]
    assert env_names["timeout"] == ["POCKETID_TIMEOUT"]
