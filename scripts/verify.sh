#!/usr/bin/env bash
# Materialize the collection into a real ansible_collections tree and run sanity.
set -u
REPO="/Users/trozz/git/trozz/ansible-module-pocketid"
VBIN="$REPO/.venv/bin"
SAN="/tmp/pocketid-sanity"
rm -rf "$SAN"
mkdir -p "$SAN/ansible_collections/trozz/pocketid"
rsync -a --exclude '.git' --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' --exclude 'tests/output' "$REPO/" "$SAN/ansible_collections/trozz/pocketid/"
cd "$SAN/ansible_collections/trozz/pocketid" || exit 1
export PATH="$VBIN:$PATH"
TESTS="${1:-validate-modules yamllint pep8 pylint import compile ansible-doc}"
rc=0
for t in $TESTS; do
  echo "===== sanity: $t ====="
  ansible-test sanity --local --test "$t"
  [ "${PIPESTATUS[0]:-$?}" -ne 0 ] && rc=1
done
exit $rc
