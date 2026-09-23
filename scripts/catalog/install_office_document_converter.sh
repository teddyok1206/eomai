#!/usr/bin/env bash
set -euo pipefail

readonly PACKAGES=(libreoffice-writer libreoffice-h2orestart unzip)
readonly LIBREOFFICE=/usr/bin/libreoffice
readonly H2ORESTART_VERSION=0.7.14
readonly H2ORESTART_SHA256=cbea23bc37861361bbc534bc0675e5bc67b36f712072490f82a9bf410d7c04d8
readonly H2ORESTART_DIRECTORY=/srv/eom/vendor/h2orestart/${H2ORESTART_VERSION}
readonly H2ORESTART=${H2ORESTART_DIRECTORY}/H2Orestart.oxt

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$(id -u)" == "0" ]] || fail "Office converter installation requires root"
(( $# <= 1 )) || fail "usage: $0 [/path/to/H2Orestart-v0.7.14.oxt]"
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

if (( $# == 1 )); then
  source_bundle=$1
  [[ -f "${source_bundle}" && ! -L "${source_bundle}" ]] || \
    fail "H2Orestart release bundle is not one regular file"
  [[ "$(sha256sum "${source_bundle}" | cut -d' ' -f1)" == "${H2ORESTART_SHA256}" ]] || \
    fail "H2Orestart release bundle hash differs from the reviewed release"
  unzip -tqq "${source_bundle}" >/dev/null || fail "H2Orestart release bundle is not a valid OXT"
  unzip -p "${source_bundle}" description.xml | \
    grep -Fq '<version value="0.7.14"/>' || fail "H2Orestart release bundle version differs"
  install -d -o root -g root -m 0755 "${H2ORESTART_DIRECTORY}"
  install -o root -g root -m 0644 "${source_bundle}" "${H2ORESTART}"
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
  fail "reviewed H2Orestart release bundle is unavailable"
[[ "$(stat -c '%U:%G' "${H2ORESTART}")" == "root:root" ]] || \
  fail "H2Orestart release bundle ownership is invalid"
(( (8#$(stat -c '%a' "${H2ORESTART}") & 8#022) == 0 )) || \
  fail "H2Orestart release bundle is group/world writable"
[[ "$(sha256sum "${H2ORESTART}" | cut -d' ' -f1)" == "${H2ORESTART_SHA256}" ]] || \
  fail "installed H2Orestart release bundle hash differs"

libreoffice_version=$(dpkg-query -W -f='${Version}' libreoffice-writer)
distribution_h2orestart_version=$(dpkg-query -W -f='${Version}' libreoffice-h2orestart)
[[ "${libreoffice_version}" == 4:24.2.* || "${libreoffice_version}" == 24.2.* ]] || \
  fail "LibreOffice version is outside the reviewed 24.2 family"
[[ "${distribution_h2orestart_version}" == 0.6.* ]] || \
  fail "H2Orestart version is outside the reviewed 0.6 family"
"${LIBREOFFICE}" --headless --version >/dev/null

printf 'office_document_converter=READY\n'
printf 'libreoffice_writer_version=%s\n' "${libreoffice_version}"
printf 'distribution_h2orestart_version=%s\n' "${distribution_h2orestart_version}"
printf 'h2orestart_version=%s\n' "${H2ORESTART_VERSION}"
printf 'h2orestart_sha256=sha256:%s\n' "$(sha256sum "${H2ORESTART}" | cut -d' ' -f1)"
