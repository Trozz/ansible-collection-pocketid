============================
trozz.pocketid Release Notes
============================

.. contents:: Topics

This changelog is managed by `antsibull-changelog
<https://github.com/ansible-community/antsibull-changelog>`_. Add change
fragments under ``changelogs/fragments/`` rather than editing this file by hand.

v1.0.3
======

Bugfixes
--------

- The ``trozz.pocketid.client`` lookup failed to resolve client names
  containing spaces (or other URL-unsafe characters) because it placed the raw
  name in the request path, raising ``URL can't contain control characters``
  before it could fall back to a listing. It now resolves names from the client
  listing like the ``group`` lookup does, never putting an arbitrary name into a
  URL path.

v1.0.2
======

Bugfixes
--------

- Replace the ``M()`` module-reference markup in the ``group`` and
  ``group_membership`` documentation with plain ``C()`` code markup. The
  Ansible Galaxy UI threw while resolving the cross-plugin links, which made
  those two plugin pages fail to render with "cannot parse plugin
  documentation".

v1.0.1
======

Bugfixes
--------

- Fix the shared connection-options doc fragment so plugin pages render on
  Ansible Galaxy. An unbalanced parenthesis inside a ``C()`` markup macro in
  the ``timeout`` description broke the Galaxy documentation parser for every
  module and lookup that extends the fragment.

v1.0.0
======

Release Summary
---------------

Initial public release of the trozz.pocketid collection: modules and lookup
plugins to manage Pocket-ID users, groups, OIDC clients, application
configuration, SCIM service providers, group memberships, one-time access
tokens and client-secret rotation over the REST API, backed by a shared HTTP
client and connection options doc fragment.
