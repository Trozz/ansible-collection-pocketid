# -*- coding: utf-8 -*-

# Copyright: (c) 2026, trozz
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

__metaclass__ = type

DOCUMENTATION = r'''
---
module: application_config
short_description: Manage the Pocket-ID application configuration singleton
version_added: '0.1.0'
author:
  - trozz (@trozz)
description:
  - Manage the global Pocket-ID application configuration.
  - This is a singleton resource; there is no C(state) parameter, the module
    always overlays the supplied options onto the current configuration.
  - The Pocket-ID configuration PUT is destructive-by-omission, every unspecified
    field is reset to its default. To avoid that, the module performs a mandatory
    read-modify-write, it GETs the current configuration immediately before the
    PUT, strips internal and non-writable keys, overlays the options you supply,
    and PUTs the complete configuration.
  - Configuration values are strings end-to-end. Booleans you pass are coerced to
    the lowercase strings V(true)/V(false).
  - When the Pocket-ID instance runs with C(UI_CONFIG_DISABLED=true) the update is
    rejected by the server; this module surfaces that as a clear failure rather
    than a silent no-op.
extends_documentation_fragment:
  - trozz.pocketid.pocketid
options:
  app_name:
    description: The display name of the application.
    type: str
  session_duration:
    description: The session duration (in minutes, as a string).
    type: str
  home_page_url:
    description: The home page URL.
    type: str
  emails_verified:
    description: Whether user emails are considered verified.
    type: bool
  disable_animations:
    description: Whether UI animations are disabled.
    type: bool
  allow_own_account_edit:
    description: Whether users may edit their own account.
    type: bool
  allow_user_signups:
    description: The user signup policy.
    type: str
    choices: [disabled, withToken, open]
  signup_default_user_group_ids:
    description:
      - JSON-encoded string array of default user group IDs assigned on signup.
    type: str
  signup_default_custom_claims:
    description:
      - JSON-encoded string of default custom claims assigned on signup.
    type: str
  accent_color:
    description: The UI accent color.
    type: str
  require_user_email:
    description: Whether a user email is required.
    type: bool
  smtp_host:
    description: The SMTP server host.
    type: str
  smtp_port:
    description: The SMTP server port (as a string).
    type: str
  smtp_from:
    description: The SMTP from address. Validated as an email address.
    type: str
  smtp_user:
    description: The SMTP authentication user.
    type: str
  smtp_password:
    description:
      - The SMTP authentication password.
      - Only sent when explicitly provided. Excluded from diff and return output.
    type: str
  smtp_tls:
    description: The SMTP TLS mode.
    type: str
    choices: [none, starttls, tls]
  smtp_skip_cert_verify:
    description: Whether to skip SMTP certificate verification.
    type: bool
  email_one_time_access_as_admin_enabled:
    description: Whether admins can use email one-time access.
    type: bool
  email_one_time_access_as_unauthenticated_enabled:
    description: Whether unauthenticated users can use email one-time access.
    type: bool
  email_login_notification_enabled:
    description: Whether login notification emails are enabled.
    type: bool
  email_api_key_expiration_enabled:
    description: Whether API key expiration emails are enabled.
    type: bool
  email_verification_enabled:
    description: Whether email verification is enabled.
    type: bool
  ldap_enabled:
    description: Whether LDAP is enabled.
    type: bool
  ldap_url:
    description: The LDAP server URL.
    type: str
  ldap_bind_dn:
    description: The LDAP bind DN.
    type: str
  ldap_bind_password:
    description:
      - The LDAP bind password.
      - Only sent when explicitly provided. Excluded from diff and return output.
    type: str
  ldap_base:
    description: The LDAP search base.
    type: str
  ldap_user_search_filter:
    description: The LDAP user search filter.
    type: str
  ldap_user_group_search_filter:
    description: The LDAP user group search filter.
    type: str
  ldap_skip_cert_verify:
    description: Whether to skip LDAP certificate verification.
    type: bool
  ldap_attribute_user_unique_identifier:
    description: The LDAP attribute for the user unique identifier.
    type: str
  ldap_attribute_user_username:
    description: The LDAP attribute for the username.
    type: str
  ldap_attribute_user_email:
    description: The LDAP attribute for the user email.
    type: str
  ldap_attribute_user_first_name:
    description: The LDAP attribute for the user first name.
    type: str
  ldap_attribute_user_last_name:
    description: The LDAP attribute for the user last name.
    type: str
  ldap_attribute_user_display_name:
    description: The LDAP attribute for the user display name.
    type: str
  ldap_attribute_user_profile_picture:
    description: The LDAP attribute for the user profile picture.
    type: str
  ldap_attribute_group_member:
    description: The LDAP attribute for group membership.
    type: str
  ldap_attribute_group_unique_identifier:
    description: The LDAP attribute for the group unique identifier.
    type: str
  ldap_attribute_group_name:
    description: The LDAP attribute for the group name.
    type: str
  ldap_admin_group_name:
    description: The LDAP admin group name.
    type: str
  ldap_soft_delete_users:
    description: Whether LDAP users are soft-deleted.
    type: bool
'''

EXAMPLES = r'''
- name: Set the application name and signup policy
  trozz.pocketid.application_config:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    app_name: My Company SSO
    allow_user_signups: withToken

- name: Configure SMTP
  trozz.pocketid.application_config:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    smtp_host: smtp.example.com
    smtp_port: "587"
    smtp_from: noreply@example.com
    smtp_user: apikey
    smtp_password: "{{ smtp_secret }}"
    smtp_tls: starttls

- name: Enable LDAP with defaults preserved
  trozz.pocketid.application_config:
    base_url: https://id.example.com
    api_token: "{{ pocketid_token }}"
    ldap_enabled: true
    ldap_url: ldaps://ldap.example.com
    ldap_bind_dn: cn=admin,dc=example,dc=com
    ldap_bind_password: "{{ ldap_secret }}"
    ldap_base: dc=example,dc=com
'''

RETURN = r'''
config:
  description:
    - The resulting application configuration after the overlay.
    - Secret keys (C(smtpPassword), C(ldapBindPassword)) are stripped.
  returned: success
  type: dict
  sample:
    appName: My Company SSO
    allowUserSignups: withToken
diff:
  description: The before/after configuration with secrets redacted.
  returned: when in diff mode
  type: dict
'''

import json

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid import (
    PocketIDClient,
    PocketIDError,
    pocketid_argument_spec,
)
from ansible_collections.trozz.pocketid.plugins.module_utils.pocketid_utils import (
    compute_diff,
    normalize_bool_to_str,
    redact,
)


# The redaction sentinel the server returns for sensitive values when the GET is
# served under UI_CONFIG_DISABLED. We must never PUT this literal back.
REDACTION_SENTINEL = "XXXXXXXXXX"

# Internal/non-writable keys returned by the GET that must be stripped before the
# PUT. instanceId is internal and not part of the writable AppConfigUpdateDto.
INTERNAL_KEYS = frozenset(("instanceId",))

# Secret keys (camelCase) that are no_log, sent only on explicit input, and
# excluded from diff and return output.
SECRET_KEYS = ("smtpPassword", "ldapBindPassword")

# Option name (snake_case) -> server key (camelCase) for every writable field in
# AppConfigUpdateDto. The keys of this map are also the module's resource options.
OPTION_TO_KEY = {
    "app_name": "appName",
    "session_duration": "sessionDuration",
    "home_page_url": "homePageUrl",
    "emails_verified": "emailsVerified",
    "disable_animations": "disableAnimations",
    "allow_own_account_edit": "allowOwnAccountEdit",
    "allow_user_signups": "allowUserSignups",
    "signup_default_user_group_ids": "signupDefaultUserGroupIDs",
    "signup_default_custom_claims": "signupDefaultCustomClaims",
    "accent_color": "accentColor",
    "require_user_email": "requireUserEmail",
    "smtp_host": "smtpHost",
    "smtp_port": "smtpPort",
    "smtp_from": "smtpFrom",
    "smtp_user": "smtpUser",
    "smtp_password": "smtpPassword",
    "smtp_tls": "smtpTls",
    "smtp_skip_cert_verify": "smtpSkipCertVerify",
    "email_one_time_access_as_admin_enabled": "emailOneTimeAccessAsAdminEnabled",
    "email_one_time_access_as_unauthenticated_enabled": (
        "emailOneTimeAccessAsUnauthenticatedEnabled"
    ),
    "email_login_notification_enabled": "emailLoginNotificationEnabled",
    "email_api_key_expiration_enabled": "emailApiKeyExpirationEnabled",
    "email_verification_enabled": "emailVerificationEnabled",
    "ldap_enabled": "ldapEnabled",
    "ldap_url": "ldapUrl",
    "ldap_bind_dn": "ldapBindDn",
    "ldap_bind_password": "ldapBindPassword",
    "ldap_base": "ldapBase",
    "ldap_user_search_filter": "ldapUserSearchFilter",
    "ldap_user_group_search_filter": "ldapUserGroupSearchFilter",
    "ldap_skip_cert_verify": "ldapSkipCertVerify",
    "ldap_attribute_user_unique_identifier": "ldapAttributeUserUniqueIdentifier",
    "ldap_attribute_user_username": "ldapAttributeUserUsername",
    "ldap_attribute_user_email": "ldapAttributeUserEmail",
    "ldap_attribute_user_first_name": "ldapAttributeUserFirstName",
    "ldap_attribute_user_last_name": "ldapAttributeUserLastName",
    "ldap_attribute_user_display_name": "ldapAttributeUserDisplayName",
    "ldap_attribute_user_profile_picture": "ldapAttributeUserProfilePicture",
    "ldap_attribute_group_member": "ldapAttributeGroupMember",
    "ldap_attribute_group_unique_identifier": "ldapAttributeGroupUniqueIdentifier",
    "ldap_attribute_group_name": "ldapAttributeGroupName",
    "ldap_admin_group_name": "ldapAdminGroupName",
    "ldap_soft_delete_users": "ldapSoftDeleteUsers",
}

# Options whose value is a boolean and must be encoded as 'true'/'false'.
BOOL_OPTIONS = frozenset((
    "emails_verified",
    "disable_animations",
    "allow_own_account_edit",
    "require_user_email",
    "smtp_skip_cert_verify",
    "email_one_time_access_as_admin_enabled",
    "email_one_time_access_as_unauthenticated_enabled",
    "email_login_notification_enabled",
    "email_api_key_expiration_enabled",
    "email_verification_enabled",
    "ldap_enabled",
    "ldap_skip_cert_verify",
    "ldap_soft_delete_users",
))

# JSON-string options validated before any API call.
JSON_OPTIONS = frozenset((
    "signup_default_user_group_ids",
    "signup_default_custom_claims",
))


def _current_from_slice(config_slice):
    """Build a {key: value} dict from the GET's list of {key,type,value}.

    Strips internal/non-writable keys. The 'type' field is ignored; values are
    strings end-to-end.
    """
    current = {}
    for entry in config_slice or []:
        key = entry.get("key")
        if not key or key in INTERNAL_KEYS:
            continue
        current[key] = entry.get("value")
    return current


def _desired_overlay(params):
    """Compute the {server_key: value} overlay from the supplied options.

    Booleans become 'true'/'false'; JSON-string options are validated; secret
    options are included only when explicitly supplied. Returns the overlay dict.
    """
    overlay = {}
    for option, key in OPTION_TO_KEY.items():
        value = params.get(option)
        if value is None:
            continue
        if option in JSON_OPTIONS:
            _validate_json(option, value)
            overlay[key] = value
            continue
        if option in BOOL_OPTIONS:
            overlay[key] = normalize_bool_to_str(value)
            continue
        overlay[key] = value
    return overlay


def _validate_json(option, value):
    try:
        json.loads(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "%s must be a valid JSON string: %s" % (option, exc)
        )


def run(params, client):
    """Read-modify-write the application configuration singleton.

    GETs the current config immediately before the PUT, strips internal keys,
    overlays the supplied options, and (outside check mode) PUTs the complete
    DTO. Returns dict(changed, config, diff).
    """
    overlay = _desired_overlay(params)

    config_slice = client.get_app_config_all()
    current = _current_from_slice(config_slice)

    # Build the full DTO: every current writable key, overlaid with desired.
    desired = dict(current)
    desired.update(overlay)

    # Reject sending the redaction sentinel for any secret, whether it came from
    # user input (overlay) or was carried forward from a GET served under
    # UI_CONFIG_DISABLED (which redacts secrets to the sentinel). The spec
    # requires the module to fail rather than ever PUT the sentinel.
    for key in SECRET_KEYS:
        if desired.get(key) == REDACTION_SENTINEL:
            raise ValueError(
                "refusing to send the redaction sentinel %r for %s; supply the "
                "real secret value" % (REDACTION_SENTINEL, key)
            )

    # Diff over the union of writable keys, excluding secrets.
    diff_keys = [k for k in current if k not in SECRET_KEYS]
    for key in overlay:
        if key not in SECRET_KEYS and key not in diff_keys:
            diff_keys.append(key)

    changed, before, after = compute_diff(current, desired, diff_keys)

    # Secrets are change-only-on-explicit-input: a supplied secret forces a write
    # but is never compared or shown.
    secret_overlay = any(key in overlay for key in SECRET_KEYS)
    if secret_overlay:
        changed = True

    diff = {
        "before": redact(before, SECRET_KEYS),
        "after": redact(after, SECRET_KEYS),
    }

    if not changed:
        return {
            "changed": False,
            "config": redact(current, SECRET_KEYS),
            "diff": diff,
        }

    if params.get("_check_mode"):
        return {
            "changed": True,
            "config": redact(desired, SECRET_KEYS),
            "diff": diff,
        }

    try:
        result = client.update_app_config(desired)
    except PocketIDError as exc:
        if _is_ui_config_disabled(exc):
            raise PocketIDError(
                "cannot update application configuration: the UI configuration "
                "is disabled on this Pocket-ID instance (UI_CONFIG_DISABLED must "
                "be false to manage the configuration via the API).",
                status=getattr(exc, "status", None),
                body=getattr(exc, "body", None),
            )
        raise

    result_dict = _current_from_slice(result) if isinstance(result, list) else (result or desired)

    return {
        "changed": True,
        "config": redact(result_dict, SECRET_KEYS),
        "diff": diff,
    }


def _is_ui_config_disabled(exc):
    # Only a 403 whose body identifies the UI-config lock counts; other 403s
    # (e.g. a permission error) must surface verbatim rather than be masked.
    if getattr(exc, "status", None) != 403:
        return False
    haystack = "%s %s" % (
        getattr(exc, "message", "") or "",
        getattr(exc, "body", "") or "",
    )
    return "UI configuration is disabled" in haystack or "UiConfigDisabled" in haystack


def main():
    argument_spec = {**pocketid_argument_spec()}
    argument_spec.update(dict(
        app_name=dict(type="str"),
        session_duration=dict(type="str"),
        home_page_url=dict(type="str"),
        emails_verified=dict(type="bool"),
        disable_animations=dict(type="bool"),
        allow_own_account_edit=dict(type="bool"),
        allow_user_signups=dict(type="str", choices=["disabled", "withToken", "open"]),
        signup_default_user_group_ids=dict(type="str"),
        signup_default_custom_claims=dict(type="str"),
        accent_color=dict(type="str"),
        require_user_email=dict(type="bool"),
        smtp_host=dict(type="str"),
        smtp_port=dict(type="str"),
        smtp_from=dict(type="str"),
        smtp_user=dict(type="str"),
        smtp_password=dict(type="str", no_log=True),
        smtp_tls=dict(type="str", choices=["none", "starttls", "tls"]),
        smtp_skip_cert_verify=dict(type="bool"),
        email_one_time_access_as_admin_enabled=dict(type="bool"),
        email_one_time_access_as_unauthenticated_enabled=dict(type="bool"),
        email_login_notification_enabled=dict(type="bool"),
        email_api_key_expiration_enabled=dict(type="bool"),
        email_verification_enabled=dict(type="bool"),
        ldap_enabled=dict(type="bool"),
        ldap_url=dict(type="str"),
        ldap_bind_dn=dict(type="str"),
        ldap_bind_password=dict(type="str", no_log=True),
        ldap_base=dict(type="str"),
        ldap_user_search_filter=dict(type="str"),
        ldap_user_group_search_filter=dict(type="str"),
        ldap_skip_cert_verify=dict(type="bool"),
        ldap_attribute_user_unique_identifier=dict(type="str"),
        ldap_attribute_user_username=dict(type="str"),
        ldap_attribute_user_email=dict(type="str"),
        ldap_attribute_user_first_name=dict(type="str"),
        ldap_attribute_user_last_name=dict(type="str"),
        ldap_attribute_user_display_name=dict(type="str"),
        ldap_attribute_user_profile_picture=dict(type="str"),
        ldap_attribute_group_member=dict(type="str"),
        ldap_attribute_group_unique_identifier=dict(type="str"),
        ldap_attribute_group_name=dict(type="str"),
        ldap_admin_group_name=dict(type="str"),
        ldap_soft_delete_users=dict(type="bool"),
    ))

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    client = PocketIDClient.from_module(module)

    params = dict(module.params)
    params["_check_mode"] = module.check_mode

    smtp_from = params.get("smtp_from")
    if smtp_from is not None and "@" not in smtp_from:
        module.fail_json(msg="smtp_from must be a valid email address")

    try:
        result = run(params, client)
    except (PocketIDError, ValueError) as exc:
        module.fail_json(msg=str(exc), status=getattr(exc, "status", None))

    diff = result.pop("diff", None)
    if module._diff and diff is not None:
        module.exit_json(diff=diff, **result)
    module.exit_json(**result)


if __name__ == "__main__":
    main()
