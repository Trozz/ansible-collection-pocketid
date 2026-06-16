# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

from ansible_collections.trozz.pocketid.plugins.modules.application_config_info import (
    run,
)


class FakeClient:
    """Minimal stand-in exposing only what application_config_info uses."""

    def __init__(self, config_slice):
        self._config_slice = config_slice
        self.get_calls = 0

    def get_app_config_all(self):
        self.get_calls += 1
        return [dict(e) for e in self._config_slice]


CONFIG_SLICE = [
    {"key": "appName", "type": "string", "value": "My Company SSO"},
    {"key": "allowUserSignups", "type": "string", "value": "withToken"},
    {"key": "smtpHost", "type": "string", "value": "smtp.example.com"},
    {"key": "smtpPassword", "type": "string", "value": "super-secret-smtp"},
    {"key": "ldapEnabled", "type": "bool", "value": "true"},
    {"key": "ldapBindPassword", "type": "string", "value": "super-secret-ldap"},
    {"key": "instanceId", "type": "string", "value": "internal-instance-id"},
]


def test_returns_config_as_dict():
    client = FakeClient(CONFIG_SLICE)

    result = run({}, client)

    assert result["changed"] is False
    assert client.get_calls == 1
    cfg = result["application_config"]
    assert cfg["appName"] == "My Company SSO"
    assert cfg["allowUserSignups"] == "withToken"
    assert cfg["smtpHost"] == "smtp.example.com"
    assert cfg["ldapEnabled"] == "true"


def test_omits_sensitive_keys():
    client = FakeClient(CONFIG_SLICE)

    cfg = run({}, client)["application_config"]

    assert "smtpPassword" not in cfg
    assert "ldapBindPassword" not in cfg


def test_strips_internal_keys():
    client = FakeClient(CONFIG_SLICE)

    cfg = run({}, client)["application_config"]

    assert "instanceId" not in cfg


def test_never_changed():
    client = FakeClient(CONFIG_SLICE)

    assert run({}, client)["changed"] is False


def test_empty_config_slice():
    client = FakeClient([])

    result = run({}, client)

    assert result["changed"] is False
    assert result["application_config"] == {}


def test_skips_entries_without_key():
    client = FakeClient([
        {"type": "string", "value": "orphan"},
        {"key": "appName", "type": "string", "value": "Named"},
    ])

    cfg = run({}, client)["application_config"]

    assert cfg == {"appName": "Named"}
