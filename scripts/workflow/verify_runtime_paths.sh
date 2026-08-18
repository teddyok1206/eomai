#!/usr/bin/env bash
set -euo pipefail

[[ "$(id -un)" == eom ]] || {
  printf '%s\n' 'Workflow runtime verification must run as eom.' >&2
  exit 1
}

WORKERS=(eom-cdx-01 eom-cdx-02 eom-cdx-03 eom-cdx-04 eom-cdx-05)
CATALOG_STAGING=/srv/eom/staging/catalog

[[ ! -L "${CATALOG_STAGING}" && -d "${CATALOG_STAGING}" ]]
[[ "$(stat -c '%U:%G:%a' "${CATALOG_STAGING}")" == eom:eom:750 ]]
[[ -w "${CATALOG_STAGING}" && -x "${CATALOG_STAGING}" ]]

for worker in "${WORKERS[@]}"; do
  path="/srv/eom/workspaces/${worker}"
  id -nG | tr ' ' '\n' | grep -Fxq "${worker}"
  [[ ! -L "${path}" && -d "${path}" ]]
  [[ "$(stat -c '%U:%G:%a' "${path}")" == "${worker}:${worker}:2770" ]]
  [[ -w "${path}" && -x "${path}" ]]
done

printf '%s\n' 'Workflow runtime path verification PASS.'
