# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    REDACTED,
    compute_diff,
    find_one_by_key,
    ldap_guard,
    normalize_bool_to_str,
    redact,
    resolve_group_refs,
    set_equal,
)


class FakeClient:
    def __init__(self, groups):
        self._groups = groups
        self.calls = 0

    def list_groups(self):
        self.calls += 1
        return self._groups


GROUPS = [
    {"id": "id-admins", "name": "admins", "friendlyName": "Administrators"},
    {"id": "id-devs", "name": "devs", "friendlyName": "Developers"},
    {"id": "id-ops", "name": "ops", "friendlyName": "Operations"},
]


# --------------------------------------------------------------------------- #
# set_equal
# --------------------------------------------------------------------------- #


def test_set_equal_unordered_true():
    assert set_equal(["a", "b"], ["b", "a"]) is True


def test_set_equal_dedups():
    assert set_equal(["a", "a", "b"], ["b", "a"]) is True


def test_set_equal_false():
    assert set_equal(["a"], ["a", "b"]) is False


def test_set_equal_none_and_empty():
    assert set_equal(None, []) is True


# --------------------------------------------------------------------------- #
# normalize_bool_to_str
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, "true"),
        (False, "false"),
        ("true", "true"),
        ("False", "false"),
        ("TRUE", "true"),
        ("1", "true"),
        ("0", "false"),
        ("yes", "true"),
        ("no", "false"),
        ("", "false"),
        (None, "false"),
        (1, "true"),
        (0, "false"),
    ],
)
def test_normalize_bool_to_str(value, expected):
    assert normalize_bool_to_str(value) == expected


# --------------------------------------------------------------------------- #
# find_one_by_key
# --------------------------------------------------------------------------- #


def test_find_one_by_key_match():
    items = [{"name": "a", "id": 1}, {"name": "b", "id": 2}]
    assert find_one_by_key(items, "name", "b") == {"name": "b", "id": 2}


def test_find_one_by_key_none():
    items = [{"name": "a"}]
    assert find_one_by_key(items, "name", "z") is None


def test_find_one_by_key_empty_items():
    assert find_one_by_key([], "name", "a") is None
    assert find_one_by_key(None, "name", "a") is None


def test_find_one_by_key_multiple_raises():
    items = [{"name": "dup", "id": 1}, {"name": "dup", "id": 2}]
    with pytest.raises(ValueError) as exc:
        find_one_by_key(items, "name", "dup")
    assert "disambiguate" in str(exc.value)


# --------------------------------------------------------------------------- #
# resolve_group_refs
# --------------------------------------------------------------------------- #


def test_resolve_group_refs_empty():
    client = FakeClient(GROUPS)
    assert resolve_group_refs(client, []) == []
    assert resolve_group_refs(client, None) == []
    # No list fetch needed for empty input.
    assert client.calls == 0


def test_resolve_group_refs_all_ids_passthrough():
    client = FakeClient(GROUPS)
    out = resolve_group_refs(client, ["id-admins", "id-ops"])
    assert out == ["id-admins", "id-ops"]


def test_resolve_group_refs_friendly_names():
    client = FakeClient(GROUPS)
    out = resolve_group_refs(client, ["Administrators", "Developers"])
    assert set(out) == {"id-admins", "id-devs"}


def test_resolve_group_refs_plain_names_fallback():
    client = FakeClient(GROUPS)
    out = resolve_group_refs(client, ["ops"])
    assert out == ["id-ops"]


def test_resolve_group_refs_mixed_rejected():
    client = FakeClient(GROUPS)
    with pytest.raises(ValueError) as exc:
        resolve_group_refs(client, ["id-admins", "Developers"])
    assert "all ids or all names" in str(exc.value)


def test_resolve_group_refs_not_found():
    client = FakeClient(GROUPS)
    with pytest.raises(ValueError) as exc:
        resolve_group_refs(client, ["ghosts"])
    assert "not found" in str(exc.value)


def test_resolve_group_refs_ambiguous():
    groups = [
        {"id": "id-1", "name": "team", "friendlyName": "Shared"},
        {"id": "id-2", "name": "other", "friendlyName": "Shared"},
    ]
    client = FakeClient(groups)
    with pytest.raises(ValueError) as exc:
        resolve_group_refs(client, ["Shared"])
    assert "ambiguous" in str(exc.value)


def test_resolve_group_refs_returns_set_comparable():
    client = FakeClient(GROUPS)
    out = resolve_group_refs(client, ["Developers", "Administrators"])
    assert set(out) == {"id-devs", "id-admins"}


# --------------------------------------------------------------------------- #
# compute_diff
# --------------------------------------------------------------------------- #


def test_compute_diff_no_change():
    current = {"name": "a", "email": "a@x", "extra": "ignored"}
    desired = {"name": "a", "email": "a@x"}
    changed, before, after = compute_diff(current, desired, ["name", "email"])
    assert changed is False
    assert before == {"name": "a", "email": "a@x"}
    assert after == {"name": "a", "email": "a@x"}


def test_compute_diff_change():
    current = {"name": "a"}
    desired = {"name": "b"}
    changed, before, after = compute_diff(current, desired, ["name"])
    assert changed is True
    assert before == {"name": "a"}
    assert after == {"name": "b"}


def test_compute_diff_null_empty_equivalent():
    current = {"locale": None}
    desired = {"locale": ""}
    changed, before, after = compute_diff(current, desired, ["locale"])
    assert changed is False


def test_compute_diff_only_allowlisted_and_specified_keys():
    current = {"name": "a", "secret": "s", "computed": "c"}
    desired = {"name": "a"}
    changed, before, after = compute_diff(current, desired, ["name", "email"])
    assert changed is False
    # email is in allowlist but not desired -> excluded; secret not allowlisted.
    assert before == {"name": "a"}
    assert after == {"name": "a"}


def test_compute_diff_handles_none_inputs():
    changed, before, after = compute_diff(None, None, ["name"])
    assert changed is False
    assert before == {}
    assert after == {}


# --------------------------------------------------------------------------- #
# redact
# --------------------------------------------------------------------------- #


def test_redact_masks_present_secret():
    out = redact({"name": "a", "token": "shh"}, ["token"])
    assert out == {"name": "a", "token": REDACTED}


def test_redact_does_not_mutate_input():
    src = {"token": "shh"}
    redact(src, ["token"])
    assert src == {"token": "shh"}


def test_redact_skips_absent_or_none():
    out = redact({"token": None}, ["token", "missing"])
    assert out == {"token": None}
    assert "missing" not in out


def test_redact_none_dict():
    assert redact(None, ["token"]) == {}


# --------------------------------------------------------------------------- #
# ldap_guard
# --------------------------------------------------------------------------- #


def test_ldap_guard_allows_non_ldap():
    ldap_guard({"id": "u1", "ldapId": None}, manage_ldap_synced=False)


def test_ldap_guard_allows_when_opted_in():
    ldap_guard({"ldapId": "x"}, manage_ldap_synced=True)


def test_ldap_guard_blocks_ldap_synced():
    with pytest.raises(ValueError) as exc:
        ldap_guard({"ldapId": "x"}, manage_ldap_synced=False)
    assert "manage_ldap_synced" in str(exc.value)


def test_ldap_guard_empty_object():
    ldap_guard(None, manage_ldap_synced=False)
    ldap_guard({}, manage_ldap_synced=False)
