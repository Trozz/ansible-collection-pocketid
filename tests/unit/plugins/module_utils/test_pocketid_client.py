# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Unit tests for the PocketIDClient HTTP contract (mocked open_url)."""

from __future__ import annotations

__metaclass__ = type

import io
import json

import pytest

from ansible.module_utils.six.moves.urllib.error import HTTPError, URLError

from ansible_collections.trozz.pocketid.plugins.module_utils import pocketid as mod
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
    _parse_retry_after,
)


def _client():
    return PocketIDClient("https://id.example.com/", "tok", validate_certs=True, timeout=7)


class _Resp:
    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")

    def read(self):
        return self._body


def _http_error(status, body="", headers=None):
    return HTTPError(
        "https://id.example.com/x", status, "err", headers or {}, io.BytesIO(body.encode("utf-8"))
    )


def test_base_url_trailing_slash_stripped():
    assert _client().base_url == "https://id.example.com"


def test_success_parses_json(monkeypatch):
    monkeypatch.setattr(mod, "open_url", lambda *a, **k: _Resp(json.dumps({"id": "1"})))
    assert _client().request("GET", "/api/users/1") == {"id": "1"}


def test_empty_body_returns_none(monkeypatch):
    # 204/DELETE: empty body must not be passed to json.loads.
    monkeypatch.setattr(mod, "open_url", lambda *a, **k: _Resp(""))
    assert _client().request("DELETE", "/api/users/1") is None


def test_malformed_2xx_body_raises_pocketiderror(monkeypatch):
    monkeypatch.setattr(mod, "open_url", lambda *a, **k: _Resp("<html>not json</html>"))
    with pytest.raises(PocketIDError):
        _client().request("GET", "/api/users")


def test_validate_certs_and_method_reach_open_url(monkeypatch):
    seen = {}

    def fake(url, **kwargs):
        seen.update(kwargs)
        seen["url"] = url
        return _Resp("{}")

    monkeypatch.setattr(mod, "open_url", fake)
    c = PocketIDClient("https://h", "tok", validate_certs=False, timeout=11)
    c.request("PUT", "/api/x", body={"a": 1})
    assert seen["validate_certs"] is False
    assert seen["method"] == "PUT"
    assert seen["timeout"] == 11
    assert seen["data"] == json.dumps({"a": 1}).encode("utf-8")
    assert seen["headers"]["X-API-Key"] == "tok"


def test_error_body_parsed_to_message(monkeypatch):
    def fake(*a, **k):
        raise _http_error(404, json.dumps({"error": "not found"}))

    monkeypatch.setattr(mod, "open_url", fake)
    with pytest.raises(PocketIDError) as exc:
        _client().request("GET", "/api/users/zzz")
    assert exc.value.status == 404
    assert "not found" in str(exc.value)


def test_non_retryable_status_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        raise _http_error(404, "{}")

    monkeypatch.setattr(mod, "open_url", fake)
    with pytest.raises(PocketIDError):
        _client().request("GET", "/api/users/zzz")
    assert calls["n"] == 1


def test_503_retried_four_times_with_backoff(monkeypatch):
    calls = {"n": 0}
    sleeps = []

    def fake(*a, **k):
        calls["n"] += 1
        raise _http_error(503, "{}")

    monkeypatch.setattr(mod, "open_url", fake)
    c = _client()
    monkeypatch.setattr(c, "_sleep", sleeps.append)
    with pytest.raises(PocketIDError):
        c.request("GET", "/api/users")
    assert calls["n"] == 4  # 1 initial + 3 retries
    assert sleeps == [1, 2, 4]


def test_post_mint_never_retried(monkeypatch):
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        raise _http_error(503, "{}")

    monkeypatch.setattr(mod, "open_url", fake)
    c = _client()
    monkeypatch.setattr(c, "_sleep", lambda s: None)
    with pytest.raises(PocketIDError):
        c.request("POST", "/api/users/1/one-time-access-token", allow_retry=False)
    assert calls["n"] == 1


def test_transport_error_retried(monkeypatch):
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        raise URLError("connection refused")

    monkeypatch.setattr(mod, "open_url", fake)
    c = _client()
    monkeypatch.setattr(c, "_sleep", lambda s: None)
    with pytest.raises(PocketIDError) as exc:
        c.request("GET", "/api/users")
    assert calls["n"] == 4
    assert exc.value.status is None


def test_429_retried_even_for_post_mint(monkeypatch):
    # A 429 is a pre-processing rejection, so even a non-retryable POST mint is
    # retried (the request was never applied; no duplicate risk).
    seq = [_http_error(429, "{}", {"Retry-After": "1"}), _Resp(json.dumps({"token": "t"}))]

    def fake(*a, **k):
        item = seq.pop(0)
        if isinstance(item, HTTPError):
            raise item
        return item

    monkeypatch.setattr(mod, "open_url", fake)
    c = _client()
    monkeypatch.setattr(c, "_sleep", lambda s: None)
    assert c.request("POST", "/api/x", allow_retry=False) == {"token": "t"}


def test_429_uses_retry_after(monkeypatch):
    seq = [_http_error(429, "{}", {"Retry-After": "5"}), _Resp("{}")]
    sleeps = []

    def fake(*a, **k):
        item = seq.pop(0)
        if isinstance(item, HTTPError):
            raise item
        return item

    monkeypatch.setattr(mod, "open_url", fake)
    c = _client()
    monkeypatch.setattr(c, "_sleep", sleeps.append)
    c.request("GET", "/api/users")
    assert sleeps == [5]


def test_parse_retry_after_seconds():
    assert _parse_retry_after("5") == 5


def test_parse_retry_after_http_date_floor():
    # An unparseable / absent value floors to the 60s default.
    assert _parse_retry_after(None) == 60
    assert _parse_retry_after("0") == 60


def test_get_paginated_walks_all_pages(monkeypatch):
    pages = {
        1: {"data": [{"id": "a"}], "pagination": {"currentPage": 1, "totalPages": 2}},
        2: {"data": [{"id": "b"}], "pagination": {"currentPage": 2, "totalPages": 2}},
    }

    def fake_request(method, url, body=None, allow_retry=None):
        page = 2 if "page=2" in url else 1
        return pages[page]

    c = _client()
    monkeypatch.setattr(c, "request", fake_request)
    items = c.get_paginated("/api/users")
    assert [i["id"] for i in items] == ["a", "b"]


def test_get_paginated_bare_list(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "request", lambda *a, **k: [{"id": "a"}, {"id": "b"}])
    assert len(c.get_paginated("/api/users")) == 2


def test_get_paginated_single_page(monkeypatch):
    c = _client()
    monkeypatch.setattr(
        c, "request",
        lambda *a, **k: {"data": [{"id": "a"}], "pagination": {"currentPage": 1, "totalPages": 1}},
    )
    assert len(c.get_paginated("/api/users")) == 1
