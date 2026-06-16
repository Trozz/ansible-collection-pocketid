# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.modules.group import run


class FakeClient:
    """Minimal fake exposing only the methods group.run() needs."""

    def __init__(self, groups=None):
        self._groups = {g["id"]: dict(g) for g in (groups or [])}
        self._seq = 0
        self.create_calls = []
        self.update_calls = []
        self.delete_calls = []
        self.set_claims_calls = []

    def list_groups(self):
        return [dict(g) for g in self._groups.values()]

    def get_group(self, group_id):
        return dict(self._groups[group_id])

    def create_group(self, body):
        self.create_calls.append(dict(body))
        self._seq += 1
        gid = "new-%d" % self._seq
        obj = {
            "id": gid,
            "name": body.get("name"),
            "friendlyName": body.get("friendlyName", ""),
            "users": [],
            "userCount": 0,
            "customClaims": [],
            "ldapId": None,
        }
        self._groups[gid] = dict(obj)
        return dict(obj)

    def update_group(self, group_id, body):
        self.update_calls.append((group_id, dict(body)))
        self._groups[group_id].update(
            {"name": body.get("name"), "friendlyName": body.get("friendlyName")}
        )
        return dict(self._groups[group_id])

    def delete_group(self, group_id):
        self.delete_calls.append(group_id)
        return self._groups.pop(group_id, None)

    def set_group_custom_claims(self, group_id, claims):
        self.set_claims_calls.append((group_id, list(claims)))
        self._groups[group_id]["customClaims"] = list(claims)
        return list(claims)


def _group(gid, name, friendly=None, claims=None, users=None, ldap=None):
    return {
        "id": gid,
        "name": name,
        "friendlyName": friendly if friendly is not None else name,
        "customClaims": [{"key": k, "value": v} for k, v in (claims or {}).items()],
        "users": users or [],
        "userCount": len(users or []),
        "ldapId": ldap,
    }


def _params(**kw):
    base = {
        "id": None,
        "name": None,
        "friendly_name": None,
        "custom_claims": None,
        "manage_ldap_synced": False,
        "state": "present",
        "_check_mode": False,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_group():
    client = FakeClient()
    result = run(_params(name="devs", friendly_name="Developers"), client)

    assert result["changed"] is True
    assert client.create_calls == [{"name": "devs", "friendlyName": "Developers"}]
    assert result["group"]["name"] == "devs"
    assert result["group"]["friendly_name"] == "Developers"
    assert result["diff"]["before"] == {}
    assert result["diff"]["after"]["name"] == "devs"


def test_create_with_custom_claims():
    client = FakeClient()
    result = run(
        _params(name="devs", custom_claims={"department": "eng"}), client
    )

    assert result["changed"] is True
    assert len(client.create_calls) == 1
    assert client.set_claims_calls == [("new-1", [{"key": "department", "value": "eng"}])]
    assert result["group"]["custom_claims"] == {"department": "eng"}


def test_create_check_mode_does_not_write():
    client = FakeClient()
    result = run(_params(name="devs", _check_mode=True), client)

    assert result["changed"] is True
    assert client.create_calls == []
    assert client.set_claims_calls == []


# ---------------------------------------------------------------------------
# update / idempotency
# ---------------------------------------------------------------------------


def test_noop_when_converged():
    client = FakeClient(groups=[_group("g1", "devs", friendly="Developers")])
    result = run(_params(name="devs", friendly_name="Developers"), client)

    assert result["changed"] is False
    assert client.update_calls == []
    assert client.set_claims_calls == []


def test_rename_in_place_by_id():
    client = FakeClient(groups=[_group("g1", "devs", friendly="Developers")])
    result = run(
        _params(id="g1", name="engineering", friendly_name="Engineering"), client
    )

    assert result["changed"] is True
    assert client.update_calls == [
        ("g1", {"name": "engineering", "friendlyName": "Engineering"})
    ]
    assert result["group"]["name"] == "engineering"
    assert result["diff"]["before"]["name"] == "devs"
    assert result["diff"]["after"]["name"] == "engineering"


def test_update_custom_claims():
    client = FakeClient(
        groups=[_group("g1", "devs", claims={"old": "1"})]
    )
    result = run(_params(name="devs", custom_claims={"new": "2"}), client)

    assert result["changed"] is True
    assert client.update_calls == []
    assert client.set_claims_calls == [("g1", [{"key": "new", "value": "2"}])]
    assert result["group"]["custom_claims"] == {"new": "2"}


def test_custom_claims_omitted_leaves_untouched():
    client = FakeClient(groups=[_group("g1", "devs", claims={"keep": "1"})])
    result = run(_params(name="devs"), client)

    assert result["changed"] is False
    assert client.set_claims_calls == []


def test_custom_claims_empty_dict_clears():
    client = FakeClient(groups=[_group("g1", "devs", claims={"drop": "1"})])
    result = run(_params(name="devs", custom_claims={}), client)

    assert result["changed"] is True
    assert client.set_claims_calls == [("g1", [])]
    assert result["group"]["custom_claims"] == {}


def test_custom_claims_noop_when_equal():
    client = FakeClient(groups=[_group("g1", "devs", claims={"a": "1"})])
    result = run(_params(name="devs", custom_claims={"a": "1"}), client)

    assert result["changed"] is False
    assert client.set_claims_calls == []


def test_update_check_mode_does_not_write():
    client = FakeClient(groups=[_group("g1", "devs", friendly="Developers")])
    result = run(
        _params(id="g1", name="engineering", _check_mode=True), client
    )

    assert result["changed"] is True
    assert client.update_calls == []
    assert result["diff"]["after"]["name"] == "engineering"


# ---------------------------------------------------------------------------
# reserved claim rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reserved", ["email", "groups", "sub"])
def test_reserved_claim_key_rejected(reserved):
    client = FakeClient()
    with pytest.raises(ValueError):
        run(_params(name="devs", custom_claims={reserved: "x"}), client)
    assert client.create_calls == []
    assert client.set_claims_calls == []


# ---------------------------------------------------------------------------
# read-only membership exposure
# ---------------------------------------------------------------------------


def test_members_and_user_count_exposed_readonly():
    client = FakeClient(
        groups=[_group("g1", "devs", users=[{"id": "u1"}, {"id": "u2"}])]
    )
    result = run(_params(name="devs", friendly_name="devs"), client)

    assert result["group"]["user_count"] == 2
    assert result["group"]["members"] == [{"id": "u1"}, {"id": "u2"}]


# ---------------------------------------------------------------------------
# identity / disambiguation
# ---------------------------------------------------------------------------


def test_ambiguous_name_fails():
    client = FakeClient(
        groups=[_group("g1", "devs"), _group("g2", "devs")]
    )
    with pytest.raises(ValueError):
        run(_params(name="devs"), client)


# ---------------------------------------------------------------------------
# LDAP guard
# ---------------------------------------------------------------------------


def test_ldap_group_fails_fast():
    client = FakeClient(groups=[_group("g1", "devs", ldap="LDAP1")])
    with pytest.raises(ValueError):
        run(_params(name="devs", friendly_name="changed"), client)


def test_ldap_group_managed_when_opted_in():
    client = FakeClient(groups=[_group("g1", "devs", friendly="old", ldap="LDAP1")])
    result = run(
        _params(name="devs", friendly_name="new", manage_ldap_synced=True), client
    )
    assert result["changed"] is True
    assert client.update_calls == [("g1", {"name": "devs", "friendlyName": "new"})]


# ---------------------------------------------------------------------------
# absent
# ---------------------------------------------------------------------------


def test_absent_deletes_existing():
    client = FakeClient(groups=[_group("g1", "devs")])
    result = run(_params(name="devs", state="absent"), client)

    assert result["changed"] is True
    assert client.delete_calls == ["g1"]
    assert result["diff"]["after"] == {}


def test_absent_noop_when_missing():
    client = FakeClient()
    result = run(_params(name="devs", state="absent"), client)

    assert result["changed"] is False
    assert client.delete_calls == []


def test_absent_check_mode_does_not_delete():
    client = FakeClient(groups=[_group("g1", "devs")])
    result = run(_params(name="devs", state="absent", _check_mode=True), client)

    assert result["changed"] is True
    assert client.delete_calls == []
