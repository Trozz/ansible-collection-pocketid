============================
trozz.pocketid Release Notes
============================

.. contents:: Topics

This changelog is managed by `antsibull-changelog
<https://github.com/ansible-community/antsibull-changelog>`_. Add change
fragments under ``changelogs/fragments/`` rather than editing this file by hand.

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
