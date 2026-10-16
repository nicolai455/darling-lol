#!/usr/bin/env bash
set -euo pipefail
: "${DARLING_HOST_UID:?missing Darling user namespace}"
: "${DARLING_WORKSPACE:?missing Darling workspace}"
# This is namespace root (a subordinate host UID), not host root. Keep real
# UID/GID intact so Darling initializes the correct guest account and ownership.
exec setpriv --euid 0 --egid 0 --keep-groups \
  "$DARLING_WORKSPACE/usr-local/bin/darling" "$@"
