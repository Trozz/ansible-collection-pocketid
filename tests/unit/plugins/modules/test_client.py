# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.modules.client import run


SECRET = "s3cr3t-value-do-not-leak"


class FakeClient:
    """Minimal stand-in for PocketIDClient exercised by run()."""

    def __init__(self, clients=None, groups=None, created=None):
        self._clients = list(clients or [])
        self._groups = list(groups or [])
        self._next = dict(created) if created else None
        self.calls = []

    # --- clients ---
    def list_clients(self):
        self.calls.append(("list_clients",))
        return list(self._clients)

    def get_client(self, client_id):
        self.calls.append(("get_client", client_id))
        for c in self._clients:
            if c.get("id") == client_id:
                return c
        if self._next and self._next.get("id") == client_id:
            return self._next
        return None

    def create_client(self, body):
        self.calls.append(("create_client", body))
        created = dict(body)
        created["id"] = "new-id"
        self._next = created
        self._clients.append(created)
        return created

    def update_client(self, client_id, body):
        self.calls.append(("update_client", client_id, body))
        for c in self._clients:
            if c.get("id") == client_id:
                c.update(body)
                return c
        return body

    def delete_client(self, client_id):
        self.calls.append(("delete_client", client_id))

    def set_client_allowed_groups(self, client_id, group_ids):
        self.calls.append(("set_client_allowed_groups", client_id, list(group_ids)))

    def generate_client_secret(self, client_id):
        self.calls.append(("generate_client_secret", client_id))
        return {"secret": SECRET}

    # --- groups (for resolve_group_refs) ---
    def list_groups(self):
        self.calls.append(("list_groups",))
        return list(self._groups)


def _called(client, name):
    return [c for c in client.calls if c[0] == name]


def base_params(**overrides):
    params = {
        "id": None,
        "name": "App",
        "callback_urls": ["https://app.example.com/cb"],
        "logout_callback_urls": None,
        "is_public": None,
        "pkce_enabled": None,
        "requires_reauthentication": None,
        "requires_pushed_authorization_requests": None,
        "launch_url": None,
        "is_group_restricted": None,
        "allowed_user_groups": None,
        "credentials": None,
        "state": "present",
        "_check_mode": False,
    }
    params.update(overrides)
    return params


def test_create_confidential_returns_secret_once():
    client = FakeClient()
    result = run(base_params(is_public=False), client)

    assert result["changed"] is True
    assert result["client_secret"] == SECRET
    assert len(_called(client, "generate_client_secret")) == 1
    assert len(_called(client, "create_client")) == 1


def test_create_public_does_not_generate_secret():
    client = FakeClient()
    result = run(base_params(is_public=True), client)

    assert result["changed"] is True
    assert "client_secret" not in result
    assert _called(client, "generate_client_secret") == []


def test_create_sends_authoritative_empty_lists():
    client = FakeClient()
    run(base_params(is_public=True), client)

    body = _called(client, "create_client")[0][1]
    assert body["callbackURLs"] == ["https://app.example.com/cb"]
    assert body["logoutCallbackURLs"] == []
    assert body["credentials"] == {"federatedIdentities": []}


def test_update_changes_callbacks():
    existing = {
        "id": "c1",
        "name": "App",
        "callbackURLs": ["https://app.example.com/old"],
        "isPublic": False,
        "pkceEnabled": True,
    }
    client = FakeClient(clients=[existing])
    result = run(
        base_params(
            callback_urls=["https://app.example.com/new"],
            pkce_enabled=True,
            is_public=False,
        ),
        client,
    )

    assert result["changed"] is True
    assert result["diff"]["before"]["callbackURLs"] == ["https://app.example.com/old"]
    assert result["diff"]["after"]["callbackURLs"] == ["https://app.example.com/new"]
    assert len(_called(client, "update_client")) == 1
    # Update never rotates the secret.
    assert _called(client, "generate_client_secret") == []
    assert "client_secret" not in result


def test_noop_idempotent():
    existing = {
        "id": "c1",
        "name": "App",
        "callbackURLs": ["https://app.example.com/cb"],
        "isPublic": True,
        "pkceEnabled": True,
        "requiresReauthentication": False,
        "isGroupRestricted": False,
    }
    client = FakeClient(clients=[existing])
    result = run(
        base_params(
            is_public=True,
            pkce_enabled=True,
            requires_reauthentication=False,
        ),
        client,
    )

    assert result["changed"] is False
    assert "diff" not in result
    assert _called(client, "update_client") == []


def test_check_mode_create_no_writes():
    client = FakeClient()
    result = run(base_params(is_public=False, _check_mode=True), client)

    assert result["changed"] is True
    assert _called(client, "create_client") == []
    assert _called(client, "generate_client_secret") == []
    assert "client_secret" not in result


def test_par_version_absent_not_diffed():
    # Server object lacks the PAR field and user did not set it -> no diff.
    existing = {
        "id": "c1",
        "name": "App",
        "callbackURLs": ["https://app.example.com/cb"],
        "isPublic": True,
        "pkceEnabled": True,
    }
    client = FakeClient(clients=[existing])
    result = run(base_params(is_public=True, pkce_enabled=True), client)

    assert result["changed"] is False


def test_par_user_set_triggers_change_on_absent_server_field():
    existing = {
        "id": "c1",
        "name": "App",
        "callbackURLs": ["https://app.example.com/cb"],
        "isPublic": False,
        "pkceEnabled": True,
    }
    client = FakeClient(clients=[existing])
    result = run(
        base_params(
            is_public=False,
            pkce_enabled=True,
            requires_pushed_authorization_requests=True,
        ),
        client,
    )

    assert result["changed"] is True
    body = _called(client, "update_client")[0][2]
    assert body["requiresPushedAuthorizationRequests"] is True


def test_allowed_groups_resolved_by_name_and_set():
    existing = {
        "id": "c1",
        "name": "App",
        "callbackURLs": ["https://app.example.com/cb"],
        "isPublic": True,
        "pkceEnabled": True,
        "allowedUserGroups": [],
    }
    groups = [{"id": "g-eng", "friendlyName": "Engineering", "name": "eng"}]
    client = FakeClient(clients=[existing], groups=groups)
    result = run(
        base_params(
            is_public=True,
            pkce_enabled=True,
            allowed_user_groups=["Engineering"],
        ),
        client,
    )

    assert result["changed"] is True
    call = _called(client, "set_client_allowed_groups")[0]
    assert call[2] == ["g-eng"]


def test_allowed_groups_unordered_noop():
    existing = {
        "id": "c1",
        "name": "App",
        "callbackURLs": ["https://app.example.com/cb"],
        "isPublic": True,
        "pkceEnabled": True,
        "isGroupRestricted": True,
        "allowedUserGroups": [{"id": "g1"}, {"id": "g2"}],
    }
    groups = [{"id": "g1", "name": "one"}, {"id": "g2", "name": "two"}]
    client = FakeClient(clients=[existing], groups=groups)
    result = run(
        base_params(
            is_public=True,
            pkce_enabled=True,
            is_group_restricted=True,
            allowed_user_groups=["g2", "g1"],
        ),
        client,
    )

    assert result["changed"] is False
    assert _called(client, "set_client_allowed_groups") == []


def test_credentials_issuer_only_idempotent():
    # Server omits empty optional federated-identity keys (omitempty); desired
    # with only an issuer must compare equal and not trigger an update.
    existing = {
        "id": "c1",
        "name": "App",
        "callbackURLs": ["https://app.example.com/cb"],
        "isPublic": True,
        "pkceEnabled": True,
        "credentials": {"federatedIdentities": [{"issuer": "https://idp"}]},
    }
    client = FakeClient(clients=[existing])
    result = run(
        base_params(
            is_public=True,
            pkce_enabled=True,
            credentials=[
                {
                    "issuer": "https://idp",
                    "subject": None,
                    "audience": None,
                    "jwks": None,
                }
            ],
        ),
        client,
    )

    assert result["changed"] is False
    assert _called(client, "update_client") == []


def test_delete_present():
    existing = {"id": "c1", "name": "App"}
    client = FakeClient(clients=[existing])
    result = run(base_params(state="absent"), client)

    assert result["changed"] is True
    assert _called(client, "delete_client")[0][1] == "c1"


def test_delete_absent_noop():
    client = FakeClient()
    result = run(base_params(state="absent"), client)

    assert result["changed"] is False
    assert _called(client, "delete_client") == []


def test_secret_never_in_diff_or_client():
    client = FakeClient()
    result = run(base_params(is_public=False), client)

    diff = result.get("diff", {})
    assert SECRET not in repr(diff)
    assert SECRET not in repr(result.get("client", {}))
    # The secret is only ever exposed via the dedicated client_secret key.
    assert result["client_secret"] == SECRET


def test_resolve_by_id_anchor():
    existing = {
        "id": "anchored",
        "name": "Old Name",
        "callbackURLs": ["https://app.example.com/cb"],
        "isPublic": True,
        "pkceEnabled": True,
    }
    client = FakeClient(clients=[existing])
    result = run(
        base_params(id="anchored", name="New Name", is_public=True, pkce_enabled=True),
        client,
    )

    assert result["changed"] is True
    assert result["diff"]["after"]["name"] == "New Name"
    assert _called(client, "list_clients") == []
    assert _called(client, "get_client")[0][1] == "anchored"


def test_multi_match_fails():
    clients = [
        {"id": "a", "name": "Dup"},
        {"id": "b", "name": "Dup"},
    ]
    client = FakeClient(clients=clients)
    with pytest.raises(ValueError):
        run(base_params(name="Dup", is_public=True), client)
