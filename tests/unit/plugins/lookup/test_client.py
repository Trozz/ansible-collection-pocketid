# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.lookup.client import run, SECRET_KEYS
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDError,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    REDACTED,
)


class FakeClient:
    """Minimal stand-in for PocketIDClient exposing only what the lookup uses."""

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


def test_secret_keys_cover_both_field_names():
    assert "secret" in SECRET_KEYS
    assert "clientSecret" in SECRET_KEYS


def test_no_terms_lists_all_redacted():
    client = FakeClient(clients=[CLIENT_A, CLIENT_B])

    result = run([], client)

    assert [c["name"] for c in result] == ["Grafana", "SPA"]
    assert result[0]["secret"] == REDACTED
    assert result[1]["clientSecret"] == REDACTED
    assert client.list_calls == 1
    assert client.get_calls == []


def test_lookup_by_id():
    client = FakeClient(by_id={"id-a": CLIENT_A})

    result = run(["id-a"], client)

    assert len(result) == 1
    assert result[0]["id"] == "id-a"
    assert result[0]["secret"] == REDACTED
    assert client.get_calls == ["id-a"]
    # An id hit must not trigger a list fetch.
    assert client.list_calls == 0


def test_lookup_by_name_falls_back_to_list():
    client = FakeClient(clients=[CLIENT_A, CLIENT_B])

    result = run(["SPA"], client)

    assert result[0]["id"] == "id-b"
    assert result[0]["clientSecret"] == REDACTED
    # The name term first probes get_client, then resolves via the list.
    assert client.get_calls == ["SPA"]
    assert client.list_calls == 1


def test_multiple_terms_preserve_order_and_cache_list():
    client = FakeClient(
        clients=[CLIENT_A, CLIENT_B],
        by_id={"id-a": CLIENT_A, "id-b": CLIENT_B},
    )

    result = run(["SPA", "id-a", "Grafana"], client)

    assert [c["id"] for c in result] == ["id-b", "id-a", "id-a"]
    # Two name lookups but the client list is fetched exactly once (cached).
    assert client.list_calls == 1


def test_name_not_found_raises():
    client = FakeClient(clients=[CLIENT_A])

    with pytest.raises(ValueError):
        run(["nope"], client)


def test_ambiguous_name_raises():
    dup1 = {"id": "id-1", "name": "Shared"}
    dup2 = {"id": "id-2", "name": "Shared"}
    client = FakeClient(clients=[dup1, dup2])

    with pytest.raises(ValueError):
        run(["Shared"], client)


def test_returned_objects_do_not_mutate_source():
    client = FakeClient(clients=[CLIENT_A], by_id={"id-a": CLIENT_A})

    run(["id-a"], client)
    run([], client)

    # The backing store secret is untouched by redaction.
    assert client._clients[0]["secret"] == "super-secret-a"
    assert client._by_id["id-a"]["secret"] == "super-secret-a"


def test_no_secret_value_appears_in_output():
    client = FakeClient(clients=[CLIENT_A, CLIENT_B])

    result = run([], client)

    flat = repr(result)
    assert "super-secret-a" not in flat
    assert "super-secret-b" not in flat
