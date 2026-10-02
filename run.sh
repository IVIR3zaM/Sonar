#!/usr/bin/env bash
# Start Sonar with the settings in .env (see .env.example).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f .env ]; then
  echo "No .env found: copy .env.example to .env and fill it in." >&2
  exit 1
fi

set -a
. ./.env
set +a

# The list in .env is authoritative; empty leaves the access list untouched.
if [ -n "${SONAR_ALLOWED_EMAILS-}" ]; then
  emails=()
  IFS=',' read -ra parts <<< "$SONAR_ALLOWED_EMAILS"
  for part in "${parts[@]}"; do
    email="${part#"${part%%[![:space:]]*}"}"
    email="${email%"${email##*[![:space:]]}"}"
    [ -n "$email" ] && emails+=("$email")
  done
  if [ "${#emails[@]}" -gt 0 ]; then
    uv run sonar sync-emails "${emails[@]}"
  fi
fi

exec uv run sonar
