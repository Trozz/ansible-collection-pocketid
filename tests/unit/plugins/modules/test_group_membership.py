# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.modules.group_membership import run


class FakeClient:
    """Minimal fake exposing only the methods group_membership.run() needs."""

    def __init__(self, users=None, groups=None):
        self._users = {u["id"]: u for u in (users or [])}
        self._groups = {g["id"]: g for g in (groups or [])}
        self.set_user_groups_calls = []

    def list_users(self):
        return list(self._users.values())

    def list_groups(self):
        return list(self._groups.values())

    def get_user(self, user_id):
        return self._users[user_id]

    def get_group(self, group_id):
        return self._groups[group_id]

    def set_user_groups(self, user_id, group_ids):
        self.set_user_groups_calls.append((user_id, list(group_ids)))
        self._users[user_id]["userGroups"] = [{"id": g} for g in group_ids]
        return None


def _group(gid, name, friendly=None, users=None, ldap=None):
    return {
        "id": gid,
        "name": name,
        "friendlyName": friendly or name,
        "users": users or [],
        "ldapId": ldap,
    }


def _user(uid, username, group_ids=None, ldap=None):
    return {
        "id": uid,
        "username": username,
        "userGroups": [{"id": g} for g in (group_ids or [])],
        "ldapId": ldap,
    }


def _params(**kw):
    base = {
        "user": None,
        "groups": None,
        "group": None,
        "users": None,
        "manage_ldap_synced": False,
        "_check_mode": False,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# user form
# ---------------------------------------------------------------------------


def test_user_form_adds_groups_by_name():
    client = FakeClient(
        users=[_user("u1", "alice", group_ids=["g1"])],
        groups=[_group("g1", "admins"), _group("g2", "devs")],
    )
    result = run(_params(user="alice", groups=["admins", "devs"]), client)

    assert result["changed"] is True
    assert result["user"] == "u1"
    assert len(client.set_user_groups_calls) == 1
    call_user, call_groups = client.set_user_groups_calls[0]
    assert call_user == "u1"
    assert set(call_groups) == {"g1", "g2"}
    assert result["diff"]["before"]["groups"] == ["g1"]
    assert result["diff"]["after"]["groups"] == ["g1", "g2"]


def test_user_form_by_id():
    client = FakeClient(
        users=[_user("u1", "alice", group_ids=[])],
        groups=[_group("g1", "admins")],
    )
    result = run(_params(user="u1", groups=["g1"]), client)
    assert result["changed"] is True
    assert client.set_user_groups_calls == [("u1", ["g1"])]


def test_user_form_noop_when_already_converged():
    client = FakeClient(
        users=[_user("u1", "alice", group_ids=["g1", "g2"])],
        groups=[_group("g1", "admins"), _group("g2", "devs")],
    )
    # order should not matter (unordered set comparison)
    result = run(_params(user="alice", groups=["devs", "admins"]), client)
    assert result["changed"] is False
    assert client.set_user_groups_calls == []


def test_user_form_empty_list_clears():
    client = FakeClient(
        users=[_user("u1", "alice", group_ids=["g1"])],
        groups=[_group("g1", "admins")],
    )
    result = run(_params(user="alice", groups=[]), client)
    assert result["changed"] is True
    assert client.set_user_groups_calls == [("u1", [])]
    assert result["diff"]["after"]["groups"] == []


def test_user_form_check_mode_does_not_write():
    client = FakeClient(
        users=[_user("u1", "alice", group_ids=["g1"])],
        groups=[_group("g1", "admins"), _group("g2", "devs")],
    )
    result = run(_params(user="alice", groups=["g1", "g2"], _check_mode=True), client)
    assert result["changed"] is True
    assert client.set_user_groups_calls == []


def test_user_form_ldap_guard_fails():
    client = FakeClient(
        users=[_user("u1", "alice", group_ids=[], ldap="LDAP1")],
        groups=[_group("g1", "admins")],
    )
    with pytest.raises(ValueError):
        run(_params(user="alice", groups=["g1"]), client)


def test_user_form_ldap_managed_when_opted_in():
    client = FakeClient(
        users=[_user("u1", "alice", group_ids=[], ldap="LDAP1")],
        groups=[_group("g1", "admins")],
    )
    result = run(
        _params(user="alice", groups=["g1"], manage_ldap_synced=True), client
    )
    assert result["changed"] is True


def test_user_form_unknown_group_name_fails():
    client = FakeClient(
        users=[_user("u1", "alice")],
        groups=[_group("g1", "admins")],
    )
    with pytest.raises(ValueError):
        run(_params(user="alice", groups=["nope"]), client)


# ---------------------------------------------------------------------------
# group form
# ---------------------------------------------------------------------------


def test_group_form_adds_and_removes_preserving_other_groups():
    # group g1 currently has bob (b) as member; alice (a) has another group g2.
    client = FakeClient(
        users=[
            _user("a", "alice", group_ids=["g2"]),
            _user("b", "bob", group_ids=["g1"]),
        ],
        groups=[
            _group("g1", "devs", users=[{"id": "b"}]),
            _group("g2", "ops"),
        ],
    )
    result = run(_params(group="devs", users=["alice"]), client)

    assert result["changed"] is True
    assert result["group"] == "g1"
    calls = dict(client.set_user_groups_calls)
    # alice gains g1 while keeping g2
    assert set(calls["a"]) == {"g1", "g2"}
    # bob loses g1 (had only g1)
    assert set(calls["b"]) == set()


def test_group_form_noop_when_membership_matches():
    client = FakeClient(
        users=[_user("b", "bob", group_ids=["g1"])],
        groups=[_group("g1", "devs", users=[{"id": "b"}])],
    )
    result = run(_params(group="devs", users=["bob"]), client)
    assert result["changed"] is False
    assert client.set_user_groups_calls == []


def test_group_form_empty_clears_membership():
    client = FakeClient(
        users=[_user("b", "bob", group_ids=["g1", "g2"])],
        groups=[
            _group("g1", "devs", users=[{"id": "b"}]),
            _group("g2", "ops"),
        ],
    )
    result = run(_params(group="devs", users=[]), client)
    assert result["changed"] is True
    # bob loses g1 but keeps g2
    assert client.set_user_groups_calls == [("b", ["g2"])]


def test_group_form_check_mode_does_not_write():
    client = FakeClient(
        users=[_user("a", "alice", group_ids=[])],
        groups=[_group("g1", "devs")],
    )
    result = run(_params(group="devs", users=["alice"], _check_mode=True), client)
    assert result["changed"] is True
    assert client.set_user_groups_calls == []


def test_group_form_ldap_group_fails():
    client = FakeClient(
        users=[_user("a", "alice")],
        groups=[_group("g1", "devs", ldap="LDAP1")],
    )
    with pytest.raises(ValueError):
        run(_params(group="devs", users=["alice"]), client)


def test_group_form_ldap_affected_user_fails():
    client = FakeClient(
        users=[_user("a", "alice", group_ids=[], ldap="LDAP1")],
        groups=[_group("g1", "devs")],
    )
    with pytest.raises(ValueError):
        run(_params(group="devs", users=["alice"]), client)
    assert client.set_user_groups_calls == []


def test_group_form_ldap_affected_user_fails_in_check_mode():
    # check mode must fail identically to live: the affected-user LDAP guard
    # runs before the check_mode branch (check-mode/live parity).
    client = FakeClient(
        users=[_user("a", "alice", group_ids=[], ldap="LDAP1")],
        groups=[_group("g1", "devs")],
    )
    with pytest.raises(ValueError):
        run(_params(group="devs", users=["alice"], _check_mode=True), client)
    assert client.set_user_groups_calls == []


def test_group_form_no_partial_write_when_later_user_ldap_synced():
    # bob is added first (sorted), carol is LDAP-synced and must abort the whole
    # operation before any write, not after bob is already written.
    client = FakeClient(
        users=[
            _user("a_bob", "bob", group_ids=[]),
            _user("z_carol", "carol", group_ids=[], ldap="LDAP1"),
        ],
        groups=[_group("g1", "devs")],
    )
    with pytest.raises(ValueError):
        run(_params(group="devs", users=["bob", "carol"]), client)
    assert client.set_user_groups_calls == []


# ---------------------------------------------------------------------------
# form selection
# ---------------------------------------------------------------------------


def test_no_form_raises():
    client = FakeClient()
    with pytest.raises(ValueError):
        run(_params(), client)
