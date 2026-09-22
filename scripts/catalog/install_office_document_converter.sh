#!/usr/bin/env bash
set -euo pipefail

readonly PACKAGES=(libreoffice-writer libreoffice-h2orestart)
readonly LIBREOFFICE=/usr/bin/libreoffice
readonly H2ORESTART=/usr/lib/libreoffice/share/extensions/h2orestart/H2Orestart.jar

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$(id -u)" == "0" ]] || fail "Office converter installation requires root"
[[ -r /etc/os-release ]] || fail "Ubuntu release metadata is unavailable"
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] || \
  fail "reviewed Office converter packages are restricted to Ubuntu 24.04"

missing_packages=()
for package in "${PACKAGES[@]}"; do
  if ! dpkg-query -W -f='${Status}' "${package}" 2>/dev/null | grep -qx 'install ok installed'; then
    missing_packages+=("${package}")
  fi
done
if ((${#missing_packages[@]})); then
  export DEBIAN_FRONTEND=noninteractive
  apt-get install --no-install-recommends --yes "${missing_packages[@]}"
fi

libreoffice_resolved=$(readlink -f "${LIBREOFFICE}")
[[ -n "${libreoffice_resolved}" && -f "${libreoffice_resolved}" \
  && ! -L "${libreoffice_resolved}" && -x "${libreoffice_resolved}" ]] || \
  fail "fixed LibreOffice executable is unavailable"
[[ "$(stat -c '%U:%G' "${libreoffice_resolved}")" == "root:root" ]] || \
  fail "LibreOffice executable ownership is invalid"
(( (8#$(stat -c '%a' "${libreoffice_resolved}") & 8#022) == 0 )) || \
  fail "LibreOffice executable is group/world writable"
[[ -f "${H2ORESTART}" && ! -L "${H2ORESTART}" && -r "${H2ORESTART}" ]] || \
  fail "H2Orestart import filter is unavailable"
[[ "$(stat -c '%U:%G' "${H2ORESTART}")" == "root:root" ]] || \
  fail "H2Orestart import filter ownership is invalid"
(( (8#$(stat -c '%a' "${H2ORESTART}") & 8#022) == 0 )) || \
  fail "H2Orestart import filter is group/world writable"

libreoffice_version=$(dpkg-query -W -f='${Version}' libreoffice-writer)
h2orestart_version=$(dpkg-query -W -f='${Version}' libreoffice-h2orestart)
[[ "${libreoffice_version}" == 4:24.2.* || "${libreoffice_version}" == 24.2.* ]] || \
  fail "LibreOffice version is outside the reviewed 24.2 family"
[[ "${h2orestart_version}" == 0.6.* ]] || \
  fail "H2Orestart version is outside the reviewed 0.6 family"
"${LIBREOFFICE}" --headless --version >/dev/null

printf 'office_document_converter=READY\n'
printf 'libreoffice_writer_version=%s\n' "${libreoffice_version}"
printf 'h2orestart_version=%s\n' "${h2orestart_version}"
printf 'h2orestart_sha256=sha256:%s\n' "$(sha256sum "${H2ORESTART}" | cut -d' ' -f1)"
