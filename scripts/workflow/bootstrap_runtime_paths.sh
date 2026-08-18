#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || {
  printf '%s\n' 'Workflow runtime path bootstrap requires UID 0.' >&2
  exit 1
}

CATALOG_STAGING=/srv/eom/staging/catalog
CATALOG_PROMPT_STAGING=/srv/eom/staging/catalog/workflow-prompts
WORKSPACE_PARENT=/srv/eom/workspaces
WORKERS=(eom-cdx-01 eom-cdx-02 eom-cdx-03 eom-cdx-04 eom-cdx-05)

require_real_directory() {
  local path="$1"
  [[ ! -L "${path}" && -d "${path}" ]] || {
    printf 'Unsafe runtime parent: %s\n' "${path}" >&2
    exit 1
  }
}

reconcile_directory() {
  local path="$1" owner="$2" group="$3" mode="$4"
  [[ ! -L "${path}" ]] || {
    printf 'Refusing symlink runtime path: %s\n' "${path}" >&2
    exit 1
  }
  if [[ -e "${path}" && ! -d "${path}" ]]; then
    printf 'Refusing non-directory runtime path: %s\n' "${path}" >&2
    exit 1
  fi
  install -d -o "${owner}" -g "${group}" -m "${mode}" "${path}"
}

require_real_directory /srv/eom
require_real_directory /srv/eom/staging
require_real_directory "${WORKSPACE_PARENT}"
getent passwd eom >/dev/null
getent group eom >/dev/null

reconcile_directory "${CATALOG_STAGING}" eom eom 0750
reconcile_directory "${CATALOG_PROMPT_STAGING}" eom eom 0750
for worker in "${WORKERS[@]}"; do
  getent passwd "${worker}" >/dev/null
  getent group "${worker}" >/dev/null
  reconcile_directory "${WORKSPACE_PARENT}/${worker}" "${worker}" "${worker}" 2770
done

printf '%s\n' 'Workflow runtime paths reconciled.'
