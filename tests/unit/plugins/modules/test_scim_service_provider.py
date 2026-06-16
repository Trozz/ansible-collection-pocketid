# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import json

import pytest

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDError,
)
from ansible_collections.trozz.pocketid.plugins.modules.scim_service_provider import (
    run,
)


CLIENT_ID = "3f1c2b8a-1234-4d5e-9abc-0123456789ab"
SCIM_ID = "9a8b7c6d-1234-4d5e-9abc-0123456789ab"


class FakeClient:
    def __init__(self, existing=None, get_error=None):
        self._existing = existing
        self._get_error = get_error
        self.calls = []

    def get_client_scim_service_provider(self, client_id):
        self.calls.append(("get", client_id))
        if self._get_error is not None:
            raise self._get_error
        return self._existing

    def create_scim_service_provider(self, body):
        self.calls.append(("create", body))
        return {
            "id": SCIM_ID,
            "endpoint": body["endpoint"],
            "token": body.get("token"),
            "oidcClient": {"id": body["oidcClientId"], "name": "My App"},
            "createdAt": "2026-06-16T10:00:00Z",
        }

    def update_scim_service_provider(self, scim_id, body):
        self.calls.append(("update", scim_id, body))
        return {
            "id": scim_id,
            "endpoint": body["endpoint"],
            "token": body.get("token"),
            "oidcClient": {"id": body["oidcClientId"], "name": "My App"},
            "createdAt": "2026-06-16T10:00:00Z",
        }

    def delete_scim_service_provider(self, scim_id):
        self.calls.append(("delete", scim_id))
        return None


def _params(**overrides):
    base = {
        "id": None,
        "oidc_client_id": CLIENT_ID,
        "endpoint": "https://scim.example.com/v2",
        "token": None,
        "state": "present",
        "_ansible_check_mode": False,
    }
    base.update(overrides)
    return base


def _not_found():
    return PocketIDError("HTTP 404: not found", status=404, body="not found")


def test_create_when_absent():
    client = FakeClient(get_error=_not_found())
    result = run(_params(token="secret-token"), client)

    assert result["changed"] is True
    create_calls = [c for c in client.calls if c[0] == "create"]
    assert len(create_calls) == 1
    body = create_calls[0][1]
    assert body == {
        "endpoint": "https://scim.example.com/v2",
        "oidcClientId": CLIENT_ID,
        "token": "secret-token",
    }
    # token never returned
    assert "token" not in result["scim_service_provider"]


def test_create_requires_endpoint():
    client = FakeClient(get_error=_not_found())
    with pytest.raises(ValueError):
        run(_params(endpoint=None), client)


def test_update_endpoint_change():
    existing = {
        "id": SCIM_ID,
        "endpoint": "https://old.example.com/v2",
        "token": "stored-token",
        "oidcClient": {"id": CLIENT_ID, "name": "My App"},
    }
    client = FakeClient(existing=existing)
    result = run(_params(endpoint="https://new.example.com/v2"), client)

    assert result["changed"] is True
    update_calls = [c for c in client.calls if c[0] == "update"]
    assert len(update_calls) == 1
    assert update_calls[0][2]["endpoint"] == "https://new.example.com/v2"
    # token omitted from body since not supplied
    assert "token" not in update_calls[0][2]


def test_noop_idempotency():
    existing = {
        "id": SCIM_ID,
        "endpoint": "https://scim.example.com/v2",
        "token": "stored-token",
        "oidcClient": {"id": CLIENT_ID, "name": "My App"},
    }
    client = FakeClient(existing=existing)
    result = run(_params(), client)

    assert result["changed"] is False
    assert not [c for c in client.calls if c[0] in ("create", "update", "delete")]


def test_token_supplied_forces_change():
    existing = {
        "id": SCIM_ID,
        "endpoint": "https://scim.example.com/v2",
        "token": "stored-token",
        "oidcClient": {"id": CLIENT_ID, "name": "My App"},
    }
    client = FakeClient(existing=existing)
    result = run(_params(token="brand-new-token"), client)

    assert result["changed"] is True
    update_calls = [c for c in client.calls if c[0] == "update"]
    assert len(update_calls) == 1
    assert update_calls[0][2]["token"] == "brand-new-token"


def test_check_mode_no_write():
    existing = {
        "id": SCIM_ID,
        "endpoint": "https://old.example.com/v2",
        "token": "stored-token",
        "oidcClient": {"id": CLIENT_ID, "name": "My App"},
    }
    client = FakeClient(existing=existing)
    result = run(
        _params(endpoint="https://new.example.com/v2", _ansible_check_mode=True),
        client,
    )

    assert result["changed"] is True
    assert not [c for c in client.calls if c[0] in ("create", "update", "delete")]


def test_secret_never_in_diff_or_result():
    client = FakeClient(get_error=_not_found())
    result = run(_params(token="super-secret"), client)

    blob = json.dumps(result)
    assert "super-secret" not in blob
    # redaction sentinel present in diff after for the token? token not in
    # WRITABLE_FIELDS, so it should simply be absent from diff
    assert "token" not in result["diff"]["after"]
    assert "token" not in result["diff"]["before"]


def test_absent_deletes_existing():
    existing = {
        "id": SCIM_ID,
        "endpoint": "https://scim.example.com/v2",
        "token": "stored-token",
        "oidcClient": {"id": CLIENT_ID, "name": "My App"},
    }
    client = FakeClient(existing=existing)
    result = run(_params(state="absent"), client)

    assert result["changed"] is True
    assert ("delete", SCIM_ID) in client.calls
    assert result["scim_service_provider"] == {}


def test_absent_noop_when_missing():
    client = FakeClient(get_error=_not_found())
    result = run(_params(state="absent"), client)

    assert result["changed"] is False
    assert not [c for c in client.calls if c[0] == "delete"]


def test_absent_check_mode_no_delete():
    existing = {
        "id": SCIM_ID,
        "endpoint": "https://scim.example.com/v2",
        "token": "stored-token",
        "oidcClient": {"id": CLIENT_ID, "name": "My App"},
    }
    client = FakeClient(existing=existing)
    result = run(_params(state="absent", _ansible_check_mode=True), client)

    assert result["changed"] is True
    assert not [c for c in client.calls if c[0] == "delete"]


def test_id_anchor_mismatch_fails():
    existing = {
        "id": SCIM_ID,
        "endpoint": "https://scim.example.com/v2",
        "token": "stored-token",
        "oidcClient": {"id": CLIENT_ID, "name": "My App"},
    }
    client = FakeClient(existing=existing)
    with pytest.raises(ValueError):
        run(_params(id="some-other-id"), client)


def test_get_error_non_404_propagates():
    client = FakeClient(get_error=PocketIDError("HTTP 500", status=500))
    with pytest.raises(PocketIDError):
        run(_params(), client)
