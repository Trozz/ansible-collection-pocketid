# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.modules.group_info import run


class FakeClient:
    """Minimal stand-in for PocketIDClient exposing only what group_info uses."""

    def __init__(self, groups=None, by_id=None):
        self._groups = groups or []
        self._by_id = by_id or {}
        self.list_calls = 0
        self.get_calls = []

    def list_groups(self):
        self.list_calls += 1
        return list(self._groups)

    def get_group(self, group_id):
        self.get_calls.append(group_id)
        return self._by_id.get(group_id)


GROUP_A = {"id": "id-a", "name": "developers", "friendlyName": "Developers", "ldapId": None}
GROUP_B = {"id": "id-b", "name": "ops", "friendlyName": "Operations", "ldapId": None}


def test_list_all_groups():
    client = FakeClient(groups=[GROUP_A, GROUP_B])

    result = run({"id": None, "name": None}, client)

    assert result["changed"] is False
    assert result["groups"] == [GROUP_A, GROUP_B]
    assert result["group"] is None
    assert client.list_calls == 1


def test_get_by_id():
    client = FakeClient(by_id={"id-a": GROUP_A})

    result = run({"id": "id-a", "name": None}, client)

    assert result["changed"] is False
    assert result["group"] == GROUP_A
    assert result["groups"] == [GROUP_A]
    assert client.get_calls == ["id-a"]
    assert client.list_calls == 0


def test_get_by_id_not_found():
    client = FakeClient(by_id={})

    result = run({"id": "missing", "name": None}, client)

    assert result["changed"] is False
    assert result["group"] is None
    assert result["groups"] == []


def test_get_by_name_friendly_name():
    client = FakeClient(groups=[GROUP_A, GROUP_B])

    result = run({"id": None, "name": "Operations"}, client)

    assert result["changed"] is False
    assert result["group"] == GROUP_B
    assert result["groups"] == [GROUP_B]
    assert client.get_calls == []


def test_get_by_name_falls_back_to_name_field():
    client = FakeClient(groups=[GROUP_A, GROUP_B])

    result = run({"id": None, "name": "developers"}, client)

    assert result["group"] == GROUP_A


def test_get_by_name_not_found():
    client = FakeClient(groups=[GROUP_A])

    result = run({"id": None, "name": "nope"}, client)

    assert result["changed"] is False
    assert result["group"] is None
    assert result["groups"] == []


def test_get_by_name_ambiguous_raises():
    dup1 = {"id": "id-1", "name": "x", "friendlyName": "Shared"}
    dup2 = {"id": "id-2", "name": "y", "friendlyName": "Shared"}
    client = FakeClient(groups=[dup1, dup2])

    with pytest.raises(ValueError):
        run({"id": None, "name": "Shared"}, client)


def test_get_by_name_cross_field_ambiguous_raises():
    by_friendly = {"id": "id-1", "name": "x", "friendlyName": "developers"}
    by_name = {"id": "id-2", "name": "developers", "friendlyName": "Y"}
    client = FakeClient(groups=[by_friendly, by_name])

    with pytest.raises(ValueError):
        run({"id": None, "name": "developers"}, client)


def test_never_changed_across_modes():
    client = FakeClient(groups=[GROUP_A])
    assert run({"id": None, "name": None}, client)["changed"] is False
