# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type


REDACTED = "********"


def set_equal(a, b):
    """Return True if iterables ``a`` and ``b`` contain the same elements (unordered)."""
    return set(a or []) == set(b or [])


def normalize_bool_to_str(value):
    """Coerce a boolean-ish value to the lowercase string ``'true'``/``'false'``.

    App-config values are string-typed end-to-end; this mirrors the backend's
    lowercase boolean encoding. Already-correct strings pass through; other
    values fall back to Python truthiness.
    """
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "false"):
            return lowered
        if lowered in ("1", "yes", "on"):
            return "true"
        if lowered in ("0", "no", "off", ""):
            return "false"
    return "true" if value else "false"


def find_one_by_key(items, field, value):
    """Return the single item in ``items`` whose ``field`` equals ``value``.

    Returns None when nothing matches. Raises ValueError when more than one
    item matches (a disambiguation error: names are not guaranteed unique).
    """
    matches = [item for item in (items or []) if item.get(field) == value]
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(
            "found %d objects with %s=%r; cannot disambiguate "
            "(set an explicit id)" % (len(matches), field, value)
        )
    return matches[0]


def _index_groups(groups):
    """Build (ids, name_to_ids) indices from a group list.

    ``name_to_ids`` maps every candidate friendly name to the list of group ids
    that carry it. A group contributes its ``friendlyName`` (preferred) and, as
    a fallback, its ``name``; duplicates across groups produce ambiguity.
    """
    ids = set()
    name_to_ids = {}
    for group in groups or []:
        gid = group.get("id")
        if gid is not None:
            ids.add(gid)
        for key in ("friendlyName", "name"):
            label = group.get(key)
            if not label:
                continue
            name_to_ids.setdefault(label, [])
            if gid is not None and gid not in name_to_ids[label]:
                name_to_ids[label].append(gid)
    return ids, name_to_ids


def resolve_group_refs(client, refs):
    """Resolve a list of group references (ids or unique names) to group ids.

    Each ref is classified by matching against the fetched group id set: a ref
    equal to a known group id is treated as an id, otherwise as a name. Mixed
    name/id lists are rejected. Names are resolved via ``client.list_groups()``;
    a not-found name or an ambiguous name (duplicate friendlyName/name across
    groups) raises ValueError. Returns a list of ids (caller compares as a set).
    """
    if refs is None:
        return []
    refs = list(refs)
    if not refs:
        return []

    groups = client.list_groups() or []
    ids, name_to_ids = _index_groups(groups)

    is_id = [ref in ids for ref in refs]
    if any(is_id) and not all(is_id):
        raise ValueError(
            "group references must be all ids or all names, not a mix: %r" % (refs,)
        )

    if all(is_id):
        return list(refs)

    resolved = []
    not_found = []
    ambiguous = []
    for ref in refs:
        candidate_ids = name_to_ids.get(ref)
        if not candidate_ids:
            not_found.append(ref)
            continue
        if len(candidate_ids) > 1:
            ambiguous.append(ref)
            continue
        resolved.append(candidate_ids[0])

    if not_found:
        raise ValueError(
            "group(s) not found by name: %s" % ", ".join(repr(n) for n in not_found)
        )
    if ambiguous:
        raise ValueError(
            "group name(s) are ambiguous (resolve by id): %s"
            % ", ".join(repr(n) for n in ambiguous)
        )
    return resolved


def _normalize_value(value):
    """Normalize a single value for comparison: None and '' are equivalent."""
    if value is None:
        return ""
    return value


def compute_diff(current, desired, allowlist):
    """Compare ``current`` vs ``desired`` over ``allowlist`` keys only.

    Applies null/empty normalization (None == '' for string fields) so an
    unset field and an empty string do not register as a change. Returns
    ``(changed, before, after)`` where before/after are redactable dicts
    containing only the allowlisted keys that the desired state specifies.
    """
    current = current or {}
    desired = desired or {}
    before = {}
    after = {}
    changed = False
    for key in allowlist:
        if key not in desired:
            continue
        cur = current.get(key)
        des = desired.get(key)
        before[key] = cur
        after[key] = des
        if _normalize_value(cur) != _normalize_value(des):
            changed = True
    return changed, before, after


def redact(d, secret_keys):
    """Return a shallow copy of dict ``d`` with each key in ``secret_keys`` masked.

    A key is masked only when present with a non-None value; absent or None
    values are left untouched so a redaction sentinel is never invented.
    """
    secret_keys = set(secret_keys or [])
    out = dict(d or {})
    for key in secret_keys:
        if out.get(key) is not None:
            out[key] = REDACTED
    return out


def ldap_guard(obj, manage_ldap_synced):
    """Fail fast on an LDAP-owned object unless management is opted in.

    An object is LDAP-owned when it carries a non-null ``ldapId``. Raises
    ValueError with an actionable message unless ``manage_ldap_synced`` is true.
    """
    if not obj:
        return
    if obj.get("ldapId") is None:
        return
    if manage_ldap_synced:
        return
    raise ValueError(
        "object is LDAP-synced (ldapId=%r); refusing to manage it. "
        "Set manage_ldap_synced: true to override." % (obj.get("ldapId"),)
    )


# Authoritative reserved custom-claim keys, mirroring the Pocket-ID backend's
# isReservedClaim (internal/service/custom_claim_service.go). These are rejected
# client-side before any write so users get a clear error instead of an HTTP 400.
RESERVED_CLAIM_KEYS = frozenset((
    "given_name",
    "family_name",
    "name",
    "email",
    "email_verified",
    "preferred_username",
    "display_name",
    "groups",
    "type",
    "sub",
    "iss",
    "aud",
    "exp",
    "iat",
    "auth_time",
    "nonce",
    "acr",
    "amr",
    "azp",
    "nbf",
    "jti",
))


def claims_list_to_dict(claims):
    """Convert an API custom-claims list of ``{key, value}`` into a flat dict."""
    out = {}
    for claim in claims or []:
        key = claim.get("key")
        if key is not None:
            out[key] = claim.get("value")
    return out


def claims_dict_to_list(claims):
    """Convert a flat custom-claims dict into the API list of ``{key, value}``."""
    return [{"key": key, "value": value} for key, value in (claims or {}).items()]


def validate_custom_claims(claims):
    """Reject reserved custom-claim keys before any write.

    Raises ValueError naming the offending key(s). A falsy/empty value is a
    no-op (clearing claims is allowed).
    """
    if not claims:
        return
    bad = sorted(set(claims) & RESERVED_CLAIM_KEYS)
    if bad:
        raise ValueError(
            "custom_claims contains reserved claim name(s): %s"
            % ", ".join(repr(k) for k in bad)
        )
