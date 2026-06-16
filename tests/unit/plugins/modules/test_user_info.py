# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.modules.user_info import run


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
    def __init__(self, users=None, pages=None):
        self._users = users or []
        self.get_user_calls = []

    def list_users(self):
        return list(self._users)

    def get_user(self, user_id):
        self.get_user_calls.append(user_id)
        for user in self._users:
            if user["id"] == user_id:
                return user
        raise AssertionError("unexpected user_id %r" % user_id)


def test_list_all_users():
    client = FakeClient([ALICE, BOB])
    result = run({}, client)
    assert result["changed"] is False
    assert result["users"] == [ALICE, BOB]
    assert "user" not in result


def test_get_by_id():
    client = FakeClient([ALICE, BOB])
    result = run({"id": "id-bob"}, client)
    assert result["changed"] is False
    assert result["users"] == [BOB]
    assert result["user"] == BOB
    assert client.get_user_calls == ["id-bob"]


def test_get_by_username():
    client = FakeClient([ALICE, BOB])
    result = run({"username": "alice"}, client)
    assert result["users"] == [ALICE]
    assert result["user"] == ALICE


def test_get_by_email():
    client = FakeClient([ALICE, BOB])
    result = run({"email": "bob@example.com"}, client)
    assert result["users"] == [BOB]
    assert result["user"] == BOB


def test_username_not_found_returns_empty():
    client = FakeClient([ALICE, BOB])
    result = run({"username": "nobody"}, client)
    assert result["changed"] is False
    assert result["users"] == []
    assert "user" not in result


def test_email_not_found_returns_empty():
    client = FakeClient([ALICE, BOB])
    result = run({"email": "nobody@example.com"}, client)
    assert result["users"] == []
    assert "user" not in result


def test_duplicate_username_disambiguation_error():
    dup = dict(ALICE, id="id-alice-2")
    client = FakeClient([ALICE, dup])
    with pytest.raises(ValueError):
        run({"username": "alice"}, client)


def test_never_changed_in_all_modes():
    client = FakeClient([ALICE])
    assert run({}, client)["changed"] is False
    assert run({"id": "id-alice"}, client)["changed"] is False
    assert run({"username": "alice"}, client)["changed"] is False


def test_empty_instance_lists_nothing():
    client = FakeClient([])
    result = run({}, client)
    assert result["users"] == []
    assert "user" not in result
