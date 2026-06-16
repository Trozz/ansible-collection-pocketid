# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0-or-later (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.lookup.application_config import (
    SECRET_KEYS,
    run,
)

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDError,
)


class FakeClient:
    """Minimal stand-in exposing only what the lookup uses."""

    def __init__(self, config_slice=None, error=None):
        self._config_slice = config_slice or []
        self._error = error
        self.get_calls = 0

    def get_app_config_all(self):
        self.get_calls += 1
        if self._error is not None:
            raise self._error
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


def test_returns_full_config_when_no_terms():
    client = FakeClient(CONFIG_SLICE)

    config = run([], {}, client)

    assert client.get_calls == 1
    assert config["appName"] == "My Company SSO"
    assert config["allowUserSignups"] == "withToken"
    assert config["smtpHost"] == "smtp.example.com"
    assert config["ldapEnabled"] == "true"


def test_none_terms_returns_full_config():
    client = FakeClient(CONFIG_SLICE)

    config = run(None, {}, client)

    assert config["appName"] == "My Company SSO"


def test_filters_to_requested_terms():
    client = FakeClient(CONFIG_SLICE)

    config = run(["appName", "smtpHost"], {}, client)

    assert config == {
        "appName": "My Company SSO",
        "smtpHost": "smtp.example.com",
    }


def test_unknown_term_is_omitted():
    client = FakeClient(CONFIG_SLICE)

    config = run(["appName", "doesNotExist"], {}, client)

    assert config == {"appName": "My Company SSO"}


def test_secret_keys_omitted_from_full_config():
    client = FakeClient(CONFIG_SLICE)

    config = run([], {}, client)

    for key in SECRET_KEYS:
        assert key not in config
    assert "super-secret-smtp" not in config.values()
    assert "super-secret-ldap" not in config.values()


def test_secret_keys_omitted_even_when_requested():
    client = FakeClient(CONFIG_SLICE)

    config = run(["appName", "smtpPassword", "ldapBindPassword"], {}, client)

    assert config == {"appName": "My Company SSO"}
    assert "super-secret-smtp" not in config.values()


def test_internal_keys_stripped():
    client = FakeClient(CONFIG_SLICE)

    config = run([], {}, client)

    assert "instanceId" not in config


def test_empty_config_slice():
    client = FakeClient([])

    assert run([], {}, client) == {}


def test_skips_entries_without_key():
    client = FakeClient([
        {"type": "string", "value": "orphan"},
        {"key": "appName", "type": "string", "value": "Named"},
    ])

    assert run([], {}, client) == {"appName": "Named"}


def test_empty_string_term_ignored():
    client = FakeClient(CONFIG_SLICE)

    config = run(["", "appName"], {}, client)

    assert config == {"appName": "My Company SSO"}


def test_api_error_propagates():
    client = FakeClient(error=PocketIDError("boom", status=503))

    with pytest.raises(PocketIDError):
        run([], {}, client)
