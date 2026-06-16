# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDError,
)
from ansible_collections.trozz.pocketid.plugins.modules.user import run


class FakeClient(object):
    """Minimal in-memory stand-in for PocketIDClient used by run()."""

    def __init__(self, users=None, groups=None):
        self.users = list(users or [])
        self.groups = list(groups or [])
        self.created = []
        self.updated = []
        self.deleted = []
        self.group_sets = []
        self.claim_sets = []
        self.list_dtos = None

    def list_users(self):
        if self.list_dtos is not None:
            return list(self.list_dtos)
        return list(self.users)

    def get_user(self, user_id):
        for user in self.users:
            if user.get("id") == user_id:
                return dict(user)
        raise PocketIDError("not found", status=404)

    def list_groups(self):
        return list(self.groups)

    def create_user(self, body):
        created = dict(body)
        created["id"] = "new-user-id"
        self.created.append(body)
        self.users.append(created)
        return created

    def update_user(self, user_id, body):
        self.updated.append((user_id, body))
        for user in self.users:
            if user.get("id") == user_id:
                user.update(body)
                return dict(user)
        raise PocketIDError("not found", status=404)

    def delete_user(self, user_id):
        self.deleted.append(user_id)

    def set_user_groups(self, user_id, group_ids):
        self.group_sets.append((user_id, list(group_ids)))

    def set_user_custom_claims(self, user_id, claims):
        self.claim_sets.append((user_id, list(claims)))


def base_params(**overrides):
    params = {
        "id": None,
        "username": None,
        "email": None,
        "first_name": None,
        "last_name": None,
        "display_name": None,
        "email_verified": None,
        "is_admin": None,
        "locale": None,
        "disabled": None,
        "groups": None,
        "custom_claims": None,
        "manage_ldap_synced": False,
        "state": "present",
        "_check_mode": False,
    }
    params.update(overrides)
    return params


def test_create_user():
    client = FakeClient()
    params = base_params(username="alice", email="alice@example.com", is_admin=False)

    result = run(params, client)

    assert result["changed"] is True
    assert len(client.created) == 1
    assert client.created[0]["username"] == "alice"
    assert client.created[0]["email"] == "alice@example.com"
    assert result["user"]["id"] == "new-user-id"


def test_no_op_idempotency():
    existing = {
        "id": "u1",
        "username": "alice",
        "email": "alice@example.com",
        "isAdmin": False,
    }
    client = FakeClient(users=[existing])
    params = base_params(username="alice", email="alice@example.com", is_admin=False)

    result = run(params, client)

    assert result["changed"] is False
    assert client.updated == []
    assert client.created == []


def test_update_user_field():
    existing = {
        "id": "u1",
        "username": "alice",
        "email": "old@example.com",
        "isAdmin": False,
    }
    client = FakeClient(users=[existing])
    params = base_params(username="alice", email="new@example.com")

    result = run(params, client)

    assert result["changed"] is True
    assert client.updated[0][0] == "u1"
    assert client.updated[0][1]["email"] == "new@example.com"
    assert result["diff"]["before"]["email"] == "old@example.com"
    assert result["diff"]["after"]["email"] == "new@example.com"


def test_check_mode_no_write():
    existing = {
        "id": "u1",
        "username": "alice",
        "email": "old@example.com",
        "isAdmin": False,
    }
    client = FakeClient(users=[existing])
    params = base_params(
        username="alice", email="new@example.com", _check_mode=True
    )

    result = run(params, client)

    assert result["changed"] is True
    assert client.updated == []
    assert client.created == []


def test_groups_omitted_untouched():
    existing = {
        "id": "u1",
        "username": "alice",
        "email": "alice@example.com",
        "userGroups": [{"id": "g1"}],
    }
    client = FakeClient(users=[existing])
    params = base_params(username="alice", email="alice@example.com")

    result = run(params, client)

    assert result["changed"] is False
    assert client.group_sets == []


def test_groups_resolved_by_name_and_replaced():
    existing = {
        "id": "u1",
        "username": "alice",
        "email": "alice@example.com",
        "userGroups": [{"id": "g1"}],
    }
    groups = [
        {"id": "g1", "name": "admins", "friendlyName": "Admins"},
        {"id": "g2", "name": "devs", "friendlyName": "Developers"},
    ]
    client = FakeClient(users=[existing], groups=groups)
    params = base_params(
        username="alice", email="alice@example.com", groups=["Developers"]
    )

    result = run(params, client)

    assert result["changed"] is True
    assert client.group_sets == [("u1", ["g2"])]
    assert result["diff"]["before"]["groups"] == ["g1"]
    assert result["diff"]["after"]["groups"] == ["g2"]


def test_groups_empty_clears():
    existing = {
        "id": "u1",
        "username": "alice",
        "email": "alice@example.com",
        "userGroups": [{"id": "g1"}],
    }
    client = FakeClient(users=[existing], groups=[{"id": "g1", "name": "admins"}])
    params = base_params(username="alice", email="alice@example.com", groups=[])

    result = run(params, client)

    assert result["changed"] is True
    assert client.group_sets == [("u1", [])]


def test_custom_claims_set():
    existing = {
        "id": "u1",
        "username": "alice",
        "email": "alice@example.com",
        "customClaims": [],
    }
    client = FakeClient(users=[existing])
    params = base_params(
        username="alice",
        email="alice@example.com",
        custom_claims={"department": "engineering"},
    )

    result = run(params, client)

    assert result["changed"] is True
    assert client.claim_sets[0][0] == "u1"
    assert client.claim_sets[0][1] == [{"key": "department", "value": "engineering"}]


def test_custom_claims_no_op():
    existing = {
        "id": "u1",
        "username": "alice",
        "email": "alice@example.com",
        "customClaims": [{"key": "department", "value": "engineering"}],
    }
    client = FakeClient(users=[existing])
    params = base_params(
        username="alice",
        email="alice@example.com",
        custom_claims={"department": "engineering"},
    )

    result = run(params, client)

    assert result["changed"] is False
    assert client.claim_sets == []


def test_custom_claims_no_op_when_list_dto_omits_claims():
    # The list endpoint returns lightweight DTOs without customClaims, but the
    # full GET carries them. Resolution must re-fetch so a converged claim set
    # reports changed=False rather than re-issuing a redundant PUT every run.
    full = {
        "id": "u1",
        "username": "alice",
        "email": "alice@example.com",
        "customClaims": [{"key": "department", "value": "engineering"}],
    }
    client = FakeClient(users=[full])
    client.list_dtos = [
        {"id": "u1", "username": "alice", "email": "alice@example.com"}
    ]
    params = base_params(
        username="alice",
        email="alice@example.com",
        custom_claims={"department": "engineering"},
    )

    result = run(params, client)

    assert result["changed"] is False
    assert client.claim_sets == []


def test_custom_claims_reserved_key_rejected():
    client = FakeClient()
    params = base_params(
        username="alice", email="alice@example.com", custom_claims={"sub": "x"}
    )

    with pytest.raises(ValueError):
        run(params, client)


def test_secret_redaction_no_secret_in_diff_or_result():
    # The user module carries no secret-bearing fields; verify no claim values
    # marked secret leak and that the diff only contains writable/allowlisted keys.
    existing = {
        "id": "u1",
        "username": "alice",
        "email": "old@example.com",
        "isAdmin": False,
    }
    client = FakeClient(users=[existing])
    params = base_params(username="alice", email="new@example.com", api_token="SECRET")

    result = run(params, client)

    serialized = repr(result)
    assert "SECRET" not in serialized
    assert "api_token" not in result["diff"]["before"]
    assert "api_token" not in result["diff"]["after"]


def test_ldap_guard_blocks_by_default():
    existing = {
        "id": "u1",
        "username": "alice",
        "email": "alice@example.com",
        "ldapId": "ldap-123",
    }
    client = FakeClient(users=[existing])
    params = base_params(username="alice", email="changed@example.com")

    with pytest.raises(ValueError):
        run(params, client)


def test_ldap_guard_override_allows():
    existing = {
        "id": "u1",
        "username": "alice",
        "email": "alice@example.com",
        "ldapId": "ldap-123",
    }
    client = FakeClient(users=[existing])
    params = base_params(
        username="alice",
        email="changed@example.com",
        manage_ldap_synced=True,
    )

    result = run(params, client)

    assert result["changed"] is True
    assert client.updated[0][1]["email"] == "changed@example.com"


def test_resolve_by_id_anchor():
    existing = {
        "id": "u1",
        "username": "old-name",
        "email": "alice@example.com",
    }
    client = FakeClient(users=[existing])
    params = base_params(id="u1", username="new-name", email="alice@example.com")

    result = run(params, client)

    assert result["changed"] is True
    assert client.updated[0][1]["username"] == "new-name"


def test_absent_deletes_existing():
    existing = {"id": "u1", "username": "alice", "email": "alice@example.com"}
    client = FakeClient(users=[existing])
    params = base_params(username="alice", state="absent")

    result = run(params, client)

    assert result["changed"] is True
    assert client.deleted == ["u1"]


def test_absent_no_op_when_missing():
    client = FakeClient()
    params = base_params(username="ghost", state="absent")

    result = run(params, client)

    assert result["changed"] is False
    assert client.deleted == []


def test_absent_check_mode_no_delete():
    existing = {"id": "u1", "username": "alice", "email": "alice@example.com"}
    client = FakeClient(users=[existing])
    params = base_params(username="alice", state="absent", _check_mode=True)

    result = run(params, client)

    assert result["changed"] is True
    assert client.deleted == []


def test_present_requires_username():
    client = FakeClient()
    params = base_params(username=None, email="x@example.com")

    with pytest.raises(ValueError):
        run(params, client)
