#!/bin/sh
# Terraform external-data adapter. It emits only a boolean, never credentials
# or the server response. The query JSON is intentionally unused.
set -eu

cat >/dev/null
: "${JFROG_URL:?JFROG_URL is required}"
: "${JFROG_ACCESS_TOKEN:?JFROG_ACCESS_TOKEN is required}"

response=$(printf 'Authorization: Bearer %s\n' "$JFROG_ACCESS_TOKEN" |
  curl --fail --silent --show-error --header @- \
    "${JFROG_URL}/artifactory/api/securityconfig")

if printf '%s' "$response" | grep -Eq '"hideUnauthorizedResources"[[:space:]]*:[[:space:]]*true'; then
  value=true
elif printf '%s' "$response" | grep -Eq '"hideUnauthorizedResources"[[:space:]]*:[[:space:]]*false'; then
  value=false
else
  echo 'resource-hiding field missing or not boolean' >&2
  exit 1
fi

printf '{"value":"%s"}\n' "$value"
