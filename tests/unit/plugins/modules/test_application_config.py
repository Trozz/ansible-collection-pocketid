# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDError,
)
from ansible_collections.trozz.pocketid.plugins.modules import application_config
from ansible_collections.trozz.pocketid.plugins.modules.application_config import (
    REDACTION_SENTINEL,
    run,
)


def _slice(**values):
    """Build a GET-style list of {key,type,value} from camelCase kwargs."""
    return [
        {"key": key, "type": "string", "value": value}
        for key, value in values.items()
    ]


class FakeClient(object):
    def __init__(self, config_slice, put_result=None, put_error=None):
        self._slice = config_slice
        self._put_result = put_result if put_result is not None else config_slice
        self._put_error = put_error
        self.put_body = None
        self.get_calls = 0
        self.put_calls = 0

    def get_app_config_all(self):
        self.get_calls += 1
        return self._slice

    def update_app_config(self, body):
        self.put_calls += 1
        self.put_body = body
        if self._put_error is not None:
            raise self._put_error
        return self._put_result


BASE = dict(
    instanceId="abc-123",
    appName="Old Name",
    allowUserSignups="disabled",
    smtpPassword="real-smtp-secret",
    ldapBindPassword="real-ldap-secret",
    ldapEnabled="false",
)


def _params(**overrides):
    params = {key: None for key in application_config.OPTION_TO_KEY}
    params["_check_mode"] = False
    params.update(overrides)
    return params


def test_update_changes_field_and_strips_internal_keys():
    client = FakeClient(_slice(**BASE))
    result = run(_params(app_name="New Name"), client)

    assert result["changed"] is True
    assert client.put_calls == 1
    assert client.get_calls == 1
    # The full DTO is sent with the overlay applied.
    assert client.put_body["appName"] == "New Name"
    # Internal keys are stripped before the PUT.
    assert "instanceId" not in client.put_body
    # Unspecified current values are preserved (no destructive omission).
    assert client.put_body["allowUserSignups"] == "disabled"


def test_noop_idempotency():
    client = FakeClient(_slice(**BASE))
    result = run(_params(app_name="Old Name", allow_user_signups="disabled"), client)

    assert result["changed"] is False
    assert client.put_calls == 0


def test_bool_coerced_to_lowercase_string():
    client = FakeClient(_slice(**BASE))
    result = run(_params(ldap_enabled=True), client)

    assert result["changed"] is True
    assert client.put_body["ldapEnabled"] == "true"


def test_check_mode_does_not_write():
    client = FakeClient(_slice(**BASE))
    params = _params(app_name="New Name")
    params["_check_mode"] = True
    result = run(params, client)

    assert result["changed"] is True
    assert client.put_calls == 0
    assert result["config"]["appName"] == "New Name"


def test_secret_excluded_from_diff_and_result():
    client = FakeClient(_slice(**BASE))
    result = run(_params(smtp_password="new-smtp-secret"), client)

    assert result["changed"] is True
    # Secret reaches the PUT body verbatim...
    assert client.put_body["smtpPassword"] == "new-smtp-secret"
    # ...but never appears in the diff or the returned config.
    diff = result["diff"]
    assert "smtpPassword" not in diff["before"]
    assert "smtpPassword" not in diff["after"]
    assert "new-smtp-secret" not in str(diff)
    assert "real-smtp-secret" not in str(result["config"])
    assert "new-smtp-secret" not in str(result["config"])


def test_secret_only_sent_on_explicit_input():
    client = FakeClient(_slice(**BASE))
    # Change a non-secret field; secrets are not in the overlay.
    run(_params(app_name="New Name"), client)
    # The full DTO carries the current secret value forward (read-modify-write),
    # but the module did not generate a secret change on its own.
    assert client.put_body["smtpPassword"] == "real-smtp-secret"


def test_redaction_sentinel_rejected():
    client = FakeClient(_slice(**BASE))
    with pytest.raises(ValueError) as exc:
        run(_params(smtp_password=REDACTION_SENTINEL), client)
    assert REDACTION_SENTINEL in str(exc.value)
    assert client.put_calls == 0


def test_carried_forward_redaction_sentinel_rejected():
    # A GET served under UI_CONFIG_DISABLED redacts secrets to the sentinel.
    redacted = dict(BASE)
    redacted["smtpPassword"] = REDACTION_SENTINEL
    client = FakeClient(_slice(**redacted))
    with pytest.raises(ValueError) as exc:
        run(_params(app_name="New Name"), client)
    assert REDACTION_SENTINEL in str(exc.value)
    assert "smtpPassword" in str(exc.value)
    assert client.put_calls == 0


def test_supplied_secret_overrides_carried_forward_sentinel():
    # The real secret supplied by the operator must not be blanked by the
    # carried-forward sentinel, and the sentinel must not reach the PUT body.
    redacted = dict(BASE)
    redacted["smtpPassword"] = REDACTION_SENTINEL
    client = FakeClient(_slice(**redacted))
    run(_params(smtp_password="real-smtp-secret"), client)
    assert client.put_body["smtpPassword"] == "real-smtp-secret"
    assert client.put_body["smtpPassword"] != REDACTION_SENTINEL


def test_ui_config_disabled_surfaced_clearly():
    # Only a 403 whose body identifies the UI-config lock is rewritten.
    err = PocketIDError(
        "HTTP 403: forbidden",
        status=403,
        body="The configuration can't be changed since the UI configuration is disabled",
    )
    client = FakeClient(_slice(**BASE), put_error=err)
    with pytest.raises(PocketIDError) as exc:
        run(_params(app_name="New Name"), client)
    assert "UI_CONFIG_DISABLED" in str(exc.value)


def test_other_403_surfaced_verbatim():
    # A 403 without the UI-config marker (e.g. a permission error) must not be
    # masked as "UI configuration disabled".
    err = PocketIDError("HTTP 403: insufficient permissions", status=403, body=None)
    client = FakeClient(_slice(**BASE), put_error=err)
    with pytest.raises(PocketIDError) as exc:
        run(_params(app_name="New Name"), client)
    assert "UI_CONFIG_DISABLED" not in str(exc.value)
    assert "insufficient permissions" in str(exc.value)


def test_invalid_json_option_rejected():
    client = FakeClient(_slice(**BASE))
    with pytest.raises(ValueError) as exc:
        run(_params(signup_default_custom_claims="{not json"), client)
    assert "valid JSON" in str(exc.value)
    assert client.put_calls == 0


def test_get_immediately_before_put():
    client = FakeClient(_slice(**BASE))
    run(_params(app_name="New Name"), client)
    assert client.get_calls == 1
    assert client.put_calls == 1


def test_server_keys_forwarded_for_forward_compat():
    extended = dict(BASE)
    extended["newRequiredField"] = "keepme"
    client = FakeClient(_slice(**extended))
    run(_params(app_name="New Name"), client)
    assert client.put_body["newRequiredField"] == "keepme"
