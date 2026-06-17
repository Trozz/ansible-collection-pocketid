# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

import json
import socket
import ssl
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

from ansible.module_utils.basic import env_fallback
from ansible.module_utils.six.moves.urllib.error import HTTPError, URLError
from ansible.module_utils.urls import open_url, ConnectionError, SSLValidationError


# Integer status codes that are safe to retry (transient server/rate conditions).
RETRYABLE_STATUS_CODES = frozenset((429, 500, 502, 503, 504))

# HTTP methods that are idempotent and therefore safe to retry automatically.
IDEMPOTENT_METHODS = frozenset(("GET", "PUT", "DELETE"))

# Total attempts = 1 initial + 3 retries. Pre-attempt backoff: 1s, 2s, 4s.
MAX_RETRIES = 3

# Default Retry-After when the header is absent or unparseable (mirrors Go).
DEFAULT_RETRY_AFTER = 60


def pocketid_argument_spec():
    """Return the shared connection argument spec with env-var fallbacks.

    Consumed by every resource/action/info module. The same option keys are
    declared in the ``pocketid`` doc fragment and the lookup plugins.
    """
    return dict(
        base_url=dict(
            type="str",
            required=True,
            fallback=(env_fallback, ["POCKETID_BASE_URL"]),
        ),
        api_token=dict(
            type="str",
            required=True,
            no_log=True,
            fallback=(env_fallback, ["POCKETID_API_TOKEN"]),
        ),
        validate_certs=dict(
            type="bool",
            default=True,
            fallback=(env_fallback, ["POCKETID_VALIDATE_CERTS"]),
        ),
        timeout=dict(
            type="int",
            default=30,
            fallback=(env_fallback, ["POCKETID_TIMEOUT"]),
        ),
    )


class PocketIDError(Exception):
    """An error talking to the Pocket-ID API.

    Carries the integer HTTP ``status`` (None for transport errors), a
    human-readable ``message`` (parsed from the API ``{error, message}`` body
    when available), and the raw response ``body``.
    """

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body


def _parse_retry_after(value):
    """Parse a Retry-After header value into a positive integer of seconds.

    Accepts either integer seconds or an HTTP-date. Returns DEFAULT_RETRY_AFTER
    when the value is absent or unparseable, and floors the result at > 0.
    """
    if value is None:
        return DEFAULT_RETRY_AFTER

    value = value.strip()
    if not value:
        return DEFAULT_RETRY_AFTER

    try:
        seconds = int(value)
        if seconds > 0:
            return seconds
    except (TypeError, ValueError):
        pass

    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER

    if when is None:
        return DEFAULT_RETRY_AFTER

    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    delay = (when - datetime.now(timezone.utc)).total_seconds()
    if delay > 0:
        return max(1, int(delay))

    return DEFAULT_RETRY_AFTER


class PocketIDClient(object):
    """HTTP client for the Pocket-ID admin REST API.

    Ports terraform-provider-pocketid's Go client to urllib semantics: per-call
    connections via ``open_url``, status/exception-typed retry classification,
    and ``X-API-Key`` auth. Holds no session/pool to keep the collection free of
    runtime Python dependencies.
    """

    def __init__(self, base_url, api_token, validate_certs=True, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.validate_certs = validate_certs
        self.timeout = timeout

    @classmethod
    def from_module(cls, module):
        """Build a client from an ``AnsibleModule``'s resolved params.

        Fails via ``module.fail_json`` (naming the env-var fallback) when a
        required connection option is missing.
        """
        params = module.params
        base_url = params.get("base_url")
        api_token = params.get("api_token")

        if not base_url:
            module.fail_json(
                msg="base_url is required (set the option or the "
                "POCKETID_BASE_URL environment variable)."
            )
        if not api_token:
            module.fail_json(
                msg="api_token is required (set the option or the "
                "POCKETID_API_TOKEN environment variable)."
            )

        return cls(
            base_url=base_url,
            api_token=api_token,
            validate_certs=params.get("validate_certs", True),
            timeout=params.get("timeout", 30),
        )

    def _sleep(self, seconds):
        """Sleep for backoff. Isolated so unit tests can monkeypatch it."""
        time.sleep(seconds)

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-Key": self.api_token,
        }

    def request(self, method, endpoint, body=None, allow_retry=None):
        """Perform a request and return parsed JSON (or None for empty bodies).

        method: HTTP verb.
        endpoint: path beginning with ``/`` (joined onto ``base_url``).
        body: optional Python object, JSON-encoded as UTF-8 bytes.
        allow_retry: override automatic retry. Defaults to True for idempotent
            methods (GET/PUT/DELETE) and False otherwise; POST callers that must
            not be retried (token mint, secret rotation) pass allow_retry=False.

        Raises PocketIDError on HTTP errors (status set) or transport failures
        (status None) once retries are exhausted.
        """
        method = method.upper()
        if allow_retry is None:
            allow_retry = method in IDEMPOTENT_METHODS

        url = "%s%s" % (self.base_url, endpoint)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                backoff = 1 << (attempt - 1)  # 1, 2, 4
                if isinstance(last_error, PocketIDError) and last_error.status == 429:
                    backoff = last_error.retry_after
                self._sleep(backoff)

            try:
                return self._do_single_request(method, url, data)
            except PocketIDError as exc:
                last_error = exc
                # A 429 is a pre-processing rejection (rate limited): the request
                # was never applied, so retrying is always safe, even for a
                # non-idempotent POST that otherwise disables retries.
                if exc.status == 429:
                    continue
                if not allow_retry:
                    raise
                if exc.status is not None and exc.status not in RETRYABLE_STATUS_CODES:
                    raise
                # exc.status None means a transport error: retryable by type.

        raise last_error

    def _do_single_request(self, method, url, data):
        try:
            resp = open_url(
                url,
                method=method,
                data=data,
                headers=self._headers(),
                validate_certs=self.validate_certs,
                timeout=self.timeout,
            )
        except HTTPError as exc:
            # urllib HTTPError bodies are one-shot: read exactly once, up front.
            raw = exc.read()
            raise self._http_error(exc, raw)
        except (URLError, SSLValidationError, ConnectionError, socket.timeout, ssl.SSLError) as exc:
            # Transport failures: status None marks them retryable by type.
            raise PocketIDError(
                "request to %s failed: %s" % (url, exc),
                status=None,
                body=None,
            )

        raw = resp.read()
        return self._parse_body(raw)

    def _http_error(self, exc, raw):
        status = exc.code
        text = self._decode(raw)

        message = text
        try:
            parsed = json.loads(text) if text else {}
        except ValueError:
            parsed = {}
        if isinstance(parsed, dict):
            message = parsed.get("error") or parsed.get("message") or text or exc.reason

        error = PocketIDError(
            "HTTP %s: %s" % (status, message),
            status=status,
            body=text,
        )
        if status == 429:
            retry_after = None
            headers = getattr(exc, "headers", None)
            if headers is not None:
                retry_after = headers.get("Retry-After")
            error.retry_after = _parse_retry_after(retry_after)
        return error

    @staticmethod
    def _decode(raw):
        if raw is None:
            return ""
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return raw

    def _parse_body(self, raw):
        text = self._decode(raw)
        # Guard empty/whitespace bodies (e.g. 204 from DELETE); never json.loads "".
        if not text or not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError:
            # A 2xx body that is not valid JSON (e.g. an HTML proxy page) must
            # surface through the PocketIDError contract, not a raw ValueError.
            raise PocketIDError(
                "could not parse JSON response body", status=None, body=text
            )

    def get_paginated(self, endpoint):
        """Page through ``currentPage..totalPages`` and return all data items.

        There is no server-side name filter, so natural-key resolution must read
        every page before concluding an object is absent.
        """
        items = []
        page = 1
        while True:
            sep = "&" if "?" in endpoint else "?"
            url = "%s%spage=%d" % (endpoint, sep, page)
            payload = self.request("GET", url)

            if payload is None:
                break
            if isinstance(payload, list):
                items.extend(payload)
                break

            data = payload.get("data", [])
            items.extend(data)

            pagination = payload.get("pagination") or {}
            total_pages = pagination.get("totalPages") or 0
            current_page = pagination.get("currentPage") or page
            if current_page >= total_pages or not data:
                break
            page = current_page + 1

        return items

    # ------------------------------------------------------------------ #
    # Users
    # ------------------------------------------------------------------ #

    def list_users(self):
        """Return all users (paged)."""
        return self.get_paginated("/api/users")

    def get_user(self, user_id):
        """Return a single user by ID."""
        return self.request("GET", "/api/users/%s" % user_id)

    def create_user(self, body):
        """Create a user; return the created object."""
        return self.request("POST", "/api/users", body)

    def update_user(self, user_id, body):
        """Update a user by ID; return the updated object."""
        return self.request("PUT", "/api/users/%s" % user_id, body)

    def delete_user(self, user_id):
        """Delete a user by ID."""
        return self.request("DELETE", "/api/users/%s" % user_id)

    def set_user_groups(self, user_id, group_ids):
        """Authoritative full-replace of a user's group membership by ID set."""
        body = {"userGroupIds": list(group_ids) if group_ids else []}
        return self.request("PUT", "/api/users/%s/user-groups" % user_id, body)

    def set_user_custom_claims(self, user_id, claims):
        """Authoritative full-replace of a user's custom claims; return result."""
        body = list(claims) if claims else []
        return self.request("PUT", "/api/custom-claims/user/%s" % user_id, body)

    # ------------------------------------------------------------------ #
    # Groups
    # ------------------------------------------------------------------ #

    def list_groups(self):
        """Return all user groups (paged)."""
        return self.get_paginated("/api/user-groups")

    def get_group(self, group_id):
        """Return a single user group by ID."""
        return self.request("GET", "/api/user-groups/%s" % group_id)

    def create_group(self, body):
        """Create a user group; return the created object."""
        return self.request("POST", "/api/user-groups", body)

    def update_group(self, group_id, body):
        """Update a user group by ID; return the updated object."""
        return self.request("PUT", "/api/user-groups/%s" % group_id, body)

    def delete_group(self, group_id):
        """Delete a user group by ID."""
        return self.request("DELETE", "/api/user-groups/%s" % group_id)

    def set_group_custom_claims(self, group_id, claims):
        """Authoritative full-replace of a group's custom claims; return result."""
        body = list(claims) if claims else []
        return self.request("PUT", "/api/custom-claims/user-group/%s" % group_id, body)

    # ------------------------------------------------------------------ #
    # OIDC clients
    # ------------------------------------------------------------------ #

    def list_clients(self):
        """Return all OIDC clients (paged)."""
        return self.get_paginated("/api/oidc/clients")

    def get_client(self, client_id):
        """Return a single OIDC client by ID."""
        return self.request("GET", "/api/oidc/clients/%s" % client_id)

    def create_client(self, body):
        """Create an OIDC client; return the created object."""
        return self.request("POST", "/api/oidc/clients", body)

    def update_client(self, client_id, body):
        """Update an OIDC client by ID; return the updated object."""
        return self.request("PUT", "/api/oidc/clients/%s" % client_id, body)

    def delete_client(self, client_id):
        """Delete an OIDC client by ID."""
        return self.request("DELETE", "/api/oidc/clients/%s" % client_id)

    def set_client_allowed_groups(self, client_id, group_ids):
        """Authoritative full-replace of a client's allowed user groups by ID set."""
        body = {"userGroupIds": list(group_ids) if group_ids else []}
        return self.request(
            "PUT", "/api/oidc/clients/%s/allowed-user-groups" % client_id, body
        )

    def generate_client_secret(self, client_id):
        """Rotate and return a client's secret. Never auto-retried (would mint dupes)."""
        return self.request(
            "POST", "/api/oidc/clients/%s/secret" % client_id, allow_retry=False
        )

    # ------------------------------------------------------------------ #
    # Application configuration (singleton)
    # ------------------------------------------------------------------ #

    def get_app_config_all(self):
        """Return the full app-config variable slice (incl. private values)."""
        return self.request("GET", "/api/application-configuration/all")

    def update_app_config(self, body):
        """PUT the complete app-config DTO; return the resulting variable slice."""
        return self.request("PUT", "/api/application-configuration", body)

    # ------------------------------------------------------------------ #
    # SCIM service providers
    # ------------------------------------------------------------------ #

    def create_scim_service_provider(self, body):
        """Create a SCIM service provider; return the created object."""
        return self.request("POST", "/api/scim/service-provider", body)

    def get_client_scim_service_provider(self, client_id):
        """Return the SCIM service provider for a client (token decrypted)."""
        return self.request(
            "GET", "/api/oidc/clients/%s/scim-service-provider" % client_id
        )

    def update_scim_service_provider(self, scim_id, body):
        """Update a SCIM service provider by ID; return the updated object."""
        return self.request("PUT", "/api/scim/service-provider/%s" % scim_id, body)

    def delete_scim_service_provider(self, scim_id):
        """Delete a SCIM service provider by ID."""
        return self.request("DELETE", "/api/scim/service-provider/%s" % scim_id)

    # ------------------------------------------------------------------ #
    # One-time access token (imperative; never auto-retried)
    # ------------------------------------------------------------------ #

    def one_time_access_token(self, user_id, body):
        """Mint a one-time access token for a user. Never auto-retried."""
        return self.request(
            "POST",
            "/api/users/%s/one-time-access-token" % user_id,
            body,
            allow_retry=False,
        )
