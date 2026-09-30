#!/bin/sh
# Terraform local-exec adapter for the provider gap. Token stays in the
# inherited environment and is never placed in HCL, state, or command output.
set -eu

: "${JFROG_URL:?JFROG_URL is required}"
: "${JFROG_ACCESS_TOKEN:?JFROG_ACCESS_TOKEN is required}"

read_value() {
  printf 'Authorization: Bearer %s\n' "$JFROG_ACCESS_TOKEN" |
    curl --fail --silent --show-error --header @- \
      "${JFROG_URL}/artifactory/api/securityconfig" |
    grep -Eo '"hideUnauthorizedResources"[[:space:]]*:[[:space:]]*(true|false)' |
    sed -E 's/.*:[[:space:]]*(true|false)/\1/'
}

current=$(read_value)
case "$current" in
  true) exit 0 ;;
  false) ;;
  *) echo 'resource-hiding field missing or not boolean' >&2; exit 1 ;;
esac

printf 'Authorization: Bearer %s\n' "$JFROG_ACCESS_TOKEN" |
  curl --fail --silent --show-error --request PATCH --header @- \
    --header 'Content-Type: application/yaml' \
    --data 'security:
  hideUnauthorizedResources: true
' \
    "${JFROG_URL}/artifactory/api/system/configuration" >/dev/null

[ "$(read_value)" = true ] || {
  echo 'resource-hiding patch did not persist' >&2
  exit 1
}
