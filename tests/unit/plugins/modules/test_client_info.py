# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.modules.client_info import run
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDError,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    REDACTED,
)


class FakeClient:
    """Minimal stand-in for PocketIDClient exposing only what client_info uses."""

    def __init__(self, clients=None, by_id=None):
        self._clients = clients or []
        self._by_id = by_id or {}
        self.list_calls = 0
        self.get_calls = []

    def list_clients(self):
        self.list_calls += 1
        return [dict(c) for c in self._clients]

    def get_client(self, client_id):
        self.get_calls.append(client_id)
        found = self._by_id.get(client_id)
        if found is None:
            raise PocketIDError("HTTP 404: not found", status=404)
        return dict(found)


CLIENT_A = {
    "id": "id-a",
    "name": "Grafana",
    "isPublic": False,
    "secret": "super-secret-a",
}
CLIENT_B = {
    "id": "id-b",
    "name": "SPA",
    "isPublic": True,
    "clientSecret": "super-secret-b",
}


def test_list_all_clients_redacts_secrets():
    client = FakeClient(clients=[CLIENT_A, CLIENT_B])

    result = run({"id": None, "name": None}, client)

    assert result["changed"] is False
    assert result["client"] is None
    assert client.list_calls == 1
    names = [c["name"] for c in result["clients"]]
    assert names == ["Grafana", "SPA"]
    assert result["clients"][0]["secret"] == REDACTED
    assert result["clients"][1]["clientSecret"] == REDACTED


def test_get_by_id_redacts_secret():
    client = FakeClient(by_id={"id-a": CLIENT_A})

    result = run({"id": "id-a", "name": None}, client)

    assert result["changed"] is False
    assert result["client"]["id"] == "id-a"
    assert result["client"]["secret"] == REDACTED
    assert result["clients"][0]["secret"] == REDACTED
    assert client.get_calls == ["id-a"]
    assert client.list_calls == 0


def test_get_by_id_not_found():
    client = FakeClient(by_id={})

    result = run({"id": "missing", "name": None}, client)

    assert result["changed"] is False
    assert result["client"] is None
    assert result["clients"] == []


def test_get_by_name():
    client = FakeClient(clients=[CLIENT_A, CLIENT_B])

    result = run({"id": None, "name": "SPA"}, client)

    assert result["changed"] is False
    assert result["client"]["id"] == "id-b"
    assert result["client"]["clientSecret"] == REDACTED
    assert result["clients"][0]["id"] == "id-b"
    assert client.get_calls == []


def test_get_by_name_not_found():
    client = FakeClient(clients=[CLIENT_A])

    result = run({"id": None, "name": "nope"}, client)

    assert result["changed"] is False
    assert result["client"] is None
    assert result["clients"] == []


def test_get_by_name_ambiguous_raises():
    dup1 = {"id": "id-1", "name": "Shared"}
    dup2 = {"id": "id-2", "name": "Shared"}
    client = FakeClient(clients=[dup1, dup2])

    with pytest.raises(ValueError):
        run({"id": None, "name": "Shared"}, client)


def test_never_changed_across_modes():
    client = FakeClient(clients=[CLIENT_A])
    assert run({"id": None, "name": None}, client)["changed"] is False


def test_returned_objects_do_not_mutate_source():
    client = FakeClient(clients=[CLIENT_A])

    run({"id": None, "name": None}, client)

    # The original secret in the backing store is untouched by redaction.
    assert client._clients[0]["secret"] == "super-secret-a"
