# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import pytest

from ansible_collections.trozz.pocketid.plugins.modules.one_time_access_token import (
    run,
    _parse_ttl_seconds,
    MAX_TTL_SECONDS,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDError,
)


ALICE = {"id": "id-alice", "username": "alice"}
BOB = {"id": "id-bob", "username": "bob"}
DUP_A = {"id": "id-dup-a", "username": "dup"}
DUP_B = {"id": "id-dup-b", "username": "dup"}

TOKEN_VALUE = "tok-abc123"
BASE_URL = "https://id.example.com"


class FakeClient:
    def __init__(self, users=None, token=TOKEN_VALUE, error=None):
        self._users = users or []
        self._token = token
        self._error = error
        self.otat_calls = []
        self.list_calls = 0

    def list_users(self):
        self.list_calls += 1
        return list(self._users)

    def one_time_access_token(self, user_id, body):
        self.otat_calls.append((user_id, body))
        if self._error is not None:
            raise self._error
        return {"token": self._token}


def _params(**overrides):
    base = {"user_id": None, "username": None, "ttl": "15m"}
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# ttl parsing / bounds
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,expected",
    [
        ("3600", 3600),
        (900, 900),
        ("15m", 900),
        ("1h", 3600),
        ("1h30m", 5400),
        ("24h", 86400),
        ("45s", 45),
    ],
)
def test_parse_ttl_seconds(value, expected):
    assert _parse_ttl_seconds(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "10x", "h", "1.5h"])
def test_parse_ttl_invalid_raises(value):
    with pytest.raises(ValueError):
        _parse_ttl_seconds(value)


def test_ttl_zero_rejected():
    client = FakeClient(users=[ALICE])
    with pytest.raises(ValueError):
        run(_params(username="alice", ttl="0"), client, check_mode=False)
    assert client.otat_calls == []


def test_ttl_over_max_rejected():
    client = FakeClient(users=[ALICE])
    too_long = str(MAX_TTL_SECONDS + 1)
    with pytest.raises(ValueError):
        run(_params(username="alice", ttl=too_long), client, check_mode=False)
    assert client.otat_calls == []


def test_ttl_at_max_allowed():
    client = FakeClient(users=[ALICE])
    result = run(
        _params(username="alice", ttl=str(MAX_TTL_SECONDS)),
        client,
        check_mode=False,
    )
    assert result["changed"] is True
    assert client.otat_calls == [("id-alice", {"ttl": "%ds" % MAX_TTL_SECONDS})]


# --------------------------------------------------------------------------- #
# real run (mint)
# --------------------------------------------------------------------------- #


def test_mint_by_user_id_returns_token_and_link():
    client = FakeClient()
    result = run(
        _params(user_id="id-explicit", ttl="15m"),
        client,
        check_mode=False,
        base_url=BASE_URL,
    )

    assert result["changed"] is True
    assert result["user_id"] == "id-explicit"
    assert result["token"] == TOKEN_VALUE
    assert result["access_link"] == "%s/lc/%s" % (BASE_URL, TOKEN_VALUE)
    # user_id given: no username resolution.
    assert client.list_calls == 0
    assert client.otat_calls == [("id-explicit", {"ttl": "900s"})]


def test_mint_by_username_resolves_id():
    client = FakeClient(users=[ALICE, BOB])
    result = run(
        _params(username="bob", ttl="1h"),
        client,
        check_mode=False,
        base_url=BASE_URL,
    )

    assert result["changed"] is True
    assert result["user_id"] == "id-bob"
    assert result["token"] == TOKEN_VALUE
    assert client.otat_calls == [("id-bob", {"ttl": "3600s"})]


def test_access_link_strips_trailing_slash():
    client = FakeClient()
    result = run(
        _params(user_id="id-explicit", ttl="15m"),
        client,
        check_mode=False,
        base_url=BASE_URL + "/",
    )
    assert result["access_link"] == "%s/lc/%s" % (BASE_URL, TOKEN_VALUE)


def test_no_access_link_without_base_url():
    client = FakeClient()
    result = run(_params(user_id="id-explicit", ttl="15m"), client, check_mode=False)
    assert result["token"] == TOKEN_VALUE
    assert "access_link" not in result


# --------------------------------------------------------------------------- #
# username resolution failures
# --------------------------------------------------------------------------- #


def test_username_not_found_raises():
    client = FakeClient(users=[ALICE])
    with pytest.raises(ValueError):
        run(_params(username="nobody", ttl="15m"), client, check_mode=False)
    assert client.otat_calls == []


def test_username_multi_match_disambiguation_error():
    client = FakeClient(users=[DUP_A, DUP_B])
    with pytest.raises(ValueError):
        run(_params(username="dup", ttl="15m"), client, check_mode=False)
    assert client.otat_calls == []


# --------------------------------------------------------------------------- #
# check mode (predict; never mint)
# --------------------------------------------------------------------------- #


def test_check_mode_by_id_never_mints_and_omits_token():
    client = FakeClient()
    result = run(
        _params(user_id="id-explicit", ttl="15m"),
        client,
        check_mode=True,
        base_url=BASE_URL,
    )

    assert result["changed"] is True
    assert result["user_id"] == "id-explicit"
    assert "token" not in result
    assert "access_link" not in result
    # No API call at all in check mode (not even username resolution needed).
    assert client.otat_calls == []


def test_check_mode_by_username_resolves_but_never_mints():
    client = FakeClient(users=[ALICE])
    result = run(_params(username="alice", ttl="15m"), client, check_mode=True)

    assert result["changed"] is True
    assert result["user_id"] == "id-alice"
    assert "token" not in result
    assert client.otat_calls == []


# --------------------------------------------------------------------------- #
# secret containment / error propagation
# --------------------------------------------------------------------------- #


def test_token_only_under_token_key():
    client = FakeClient()
    result = run(
        _params(user_id="id-explicit", ttl="15m"),
        client,
        check_mode=False,
        base_url=BASE_URL,
    )
    # The raw token must not appear under any key other than 'token'
    # ('access_link' contains it by design as a convenience URL).
    leaked = [
        key
        for key, value in result.items()
        if key not in ("token", "access_link") and value == TOKEN_VALUE
    ]
    assert leaked == []
    assert result["token"] == TOKEN_VALUE


def test_check_mode_predicts_changed_without_token_leak():
    client = FakeClient()
    result = run(_params(user_id="id-explicit", ttl="15m"), client, check_mode=True)
    assert TOKEN_VALUE not in result.values()


def test_api_error_propagates():
    client = FakeClient(error=PocketIDError("boom", status=500))
    with pytest.raises(PocketIDError):
        run(_params(user_id="id-explicit", ttl="15m"), client, check_mode=False)
