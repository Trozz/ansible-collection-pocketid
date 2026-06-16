# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.lookup.group import (
    resolve_group,
    run,
)


class FakeClient:
    """Minimal stand-in for PocketIDClient exposing only list_groups."""

    def __init__(self, groups):
        self._groups = groups
        self.calls = 0

    def list_groups(self):
        self.calls += 1
        return list(self._groups)


GROUPS = [
    {"id": "id-admins", "name": "admins", "friendlyName": "Administrators", "userCount": 3},
    {"id": "id-devs", "name": "developers", "friendlyName": "Developers", "userCount": 7},
    {"id": "id-dup-a", "name": "support-a", "friendlyName": "Support"},
    {"id": "id-dup-b", "name": "support-b", "friendlyName": "Support"},
]


def test_resolve_by_id():
    client = FakeClient(GROUPS)
    obj = resolve_group(client, "id-devs")
    assert obj["id"] == "id-devs"
    assert obj["friendlyName"] == "Developers"


def test_resolve_by_friendly_name():
    client = FakeClient(GROUPS)
    obj = resolve_group(client, "Administrators")
    assert obj["id"] == "id-admins"


def test_resolve_by_name_fallback():
    client = FakeClient(GROUPS)
    obj = resolve_group(client, "developers")
    assert obj["id"] == "id-devs"


def test_resolve_not_found_raises():
    client = FakeClient(GROUPS)
    with pytest.raises(ValueError) as exc:
        resolve_group(client, "missing-group")
    assert "no group found" in str(exc.value)


def test_resolve_ambiguous_name_raises():
    client = FakeClient(GROUPS)
    with pytest.raises(ValueError) as exc:
        resolve_group(client, "Support")
    assert "disambiguate" in str(exc.value)


def test_id_takes_precedence_over_name_collision():
    # A term equal to a known id is resolved as an id even though names exist.
    client = FakeClient(GROUPS)
    obj = resolve_group(client, "id-admins")
    assert obj["name"] == "admins"


def test_run_preserves_order_and_returns_full_objects():
    client = FakeClient(GROUPS)
    result = run(["Developers", "id-admins"], client)
    assert [g["id"] for g in result] == ["id-devs", "id-admins"]
    # Full objects returned, including read-only fields.
    assert result[0]["userCount"] == 7


def test_run_empty_terms_returns_empty_list():
    client = FakeClient(GROUPS)
    assert run([], client) == []


def test_argspec_lookup_docfragment_key_parity():
    # Lookup option keys must equal the module connection argspec keys, which
    # equal the doc-fragment keys.
    import yaml

    from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
        pocketid_argument_spec,
    )
    from ansible_collections.trozz.pocketid.plugins.doc_fragments.pocketid import (
        ModuleDocFragment,
    )
    from ansible_collections.trozz.pocketid.plugins.lookup import group as group_lookup

    argspec_keys = set(pocketid_argument_spec().keys())

    fragment = yaml.safe_load(ModuleDocFragment.DOCUMENTATION)
    fragment_keys = set(fragment["options"].keys())

    lookup_doc = yaml.safe_load(group_lookup.DOCUMENTATION)
    lookup_keys = set(lookup_doc["options"].keys()) - {"_terms"}

    assert lookup_keys == argspec_keys
    assert fragment_keys == argspec_keys
