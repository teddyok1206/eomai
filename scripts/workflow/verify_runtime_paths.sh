#!/usr/bin/env bash
set -euo pipefail

[[ "$(id -un)" == eom ]] || {
  printf '%s\n' 'Workflow runtime verification must run as eom.' >&2
  exit 1
}

WORKERS=(eom-cdx-01 eom-cdx-02 eom-cdx-03 eom-cdx-04 eom-cdx-05)
CATALOG_STAGING=/srv/eom/staging/catalog
CATALOG_FIXED_STAGING=(
  /srv/eom/staging/catalog/content-packs
  /srv/eom/staging/catalog/registry
  /srv/eom/staging/catalog/workflow-prompts
)

verify_catalog_directory() {
  local path="$1" probe probe_file probe_value status=0
  [[ ! -L "${path}" && -d "${path}" ]]
  [[ "$(stat -c '%U:%G:%a' "${path}")" == eom:eom:750 ]]
  [[ -w "${path}" && -x "${path}" ]]
  probe="$(mktemp -d "${path}/.eom-runtime-probe.XXXXXX")"
  probe_file="${probe}/probe"
  (umask 077 && printf '%s\n' ready >"${probe_file}") || status=1
  [[ ! -L "${probe_file}" && -f "${probe_file}" ]] || status=1
  IFS= read -r probe_value <"${probe_file}" || status=1
  [[ "${probe_value:-}" == ready ]] || status=1
  rm -f -- "${probe_file}"
  rmdir -- "${probe}"
  return "${status}"
}

verify_catalog_directory "${CATALOG_STAGING}"
for path in "${CATALOG_FIXED_STAGING[@]}"; do
  verify_catalog_directory "${path}"
done

for worker in "${WORKERS[@]}"; do
  path="/srv/eom/workspaces/${worker}"
  id -nG | tr ' ' '\n' | grep -Fxq "${worker}"
  [[ ! -L "${path}" && -d "${path}" ]]
  [[ "$(stat -c '%U:%G:%a' "${path}")" == "${worker}:${worker}:2770" ]]
  [[ -w "${path}" && -x "${path}" ]]
done

printf '%s\n' 'Workflow runtime path verification PASS.'
