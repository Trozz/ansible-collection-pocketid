# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.modules.client_secret import run
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDError,
)


WEB_APP = {"id": "id-web", "name": "Web App"}
API_APP = {"id": "id-api", "name": "API App"}
DUP_A = {"id": "id-dup-a", "name": "Dup"}
DUP_B = {"id": "id-dup-b", "name": "Dup"}

NEW_SECRET = "s3cr3t-rotated-value"


class FakeClient:
    def __init__(self, clients=None, secret=NEW_SECRET, error=None):
        self._clients = clients or []
        self._secret = secret
        self._error = error
        self.generate_calls = []
        self.list_calls = 0

    def list_clients(self):
        self.list_calls += 1
        return list(self._clients)

    def generate_client_secret(self, client_id):
        self.generate_calls.append(client_id)
        if self._error is not None:
            raise self._error
        return {"secret": self._secret}


def test_rotate_by_id_returns_secret_and_changed():
    client = FakeClient()
    result = run({"client_id": "id-web", "name": None}, client, check_mode=False)

    assert result["changed"] is True
    assert result["client_id"] == "id-web"
    assert result["secret"] == NEW_SECRET
    assert client.generate_calls == ["id-web"]
    # client_id given: no name resolution needed.
    assert client.list_calls == 0


def test_rotate_by_name_resolves_id():
    client = FakeClient(clients=[WEB_APP, API_APP])
    result = run({"client_id": None, "name": "API App"}, client, check_mode=False)

    assert result["changed"] is True
    assert result["client_id"] == "id-api"
    assert result["secret"] == NEW_SECRET
    assert client.generate_calls == ["id-api"]


def test_name_not_found_raises():
    client = FakeClient(clients=[WEB_APP])
    with pytest.raises(ValueError):
        run({"client_id": None, "name": "Nope"}, client, check_mode=False)
    assert client.generate_calls == []


def test_name_multi_match_disambiguation_error():
    client = FakeClient(clients=[DUP_A, DUP_B])
    with pytest.raises(ValueError):
        run({"client_id": None, "name": "Dup"}, client, check_mode=False)
    assert client.generate_calls == []


def test_check_mode_never_rotates_and_omits_secret():
    client = FakeClient(clients=[WEB_APP])
    result = run({"client_id": None, "name": "Web App"}, client, check_mode=True)

    assert result["changed"] is True
    assert result["client_id"] == "id-web"
    assert "secret" not in result
    # No rotation request issued in check mode.
    assert client.generate_calls == []


def test_check_mode_by_id_never_rotates():
    client = FakeClient()
    result = run({"client_id": "id-web", "name": None}, client, check_mode=True)

    assert result["changed"] is True
    assert result["client_id"] == "id-web"
    assert "secret" not in result
    assert client.generate_calls == []


def test_secret_not_leaked_via_resolution_path():
    # Real run by name: secret only appears under the 'secret' key, redactable
    # by Ansible's no_log; nothing else in the result carries it.
    client = FakeClient(clients=[WEB_APP])
    result = run({"client_id": None, "name": "Web App"}, client, check_mode=False)

    leaked = [
        key for key, value in result.items() if key != "secret" and value == NEW_SECRET
    ]
    assert leaked == []
    assert result["secret"] == NEW_SECRET


def test_api_error_propagates():
    client = FakeClient(error=PocketIDError("boom", status=500))
    with pytest.raises(PocketIDError):
        run({"client_id": "id-web", "name": None}, client, check_mode=False)
