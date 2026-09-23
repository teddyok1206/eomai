#!/usr/bin/env bash
set -euo pipefail

readonly PACKAGES=(libreoffice-writer libreoffice-h2orestart unzip)
readonly LIBREOFFICE=/usr/bin/libreoffice
readonly H2ORESTART_VERSION=0.7.14-eom.1
readonly H2ORESTART_DECLARED_VERSION=0.7.14.1
readonly H2ORESTART_SHA256=2b3ead8f1c782ba47cdc800262e99196850b525347843f0bd9b76e8431a7de96
readonly H2ORESTART_PATCH_SHA256=ea68732e8ac46f088cdff378c3b184d9251e8703874446c382b04393b0405fa2
readonly SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
readonly REPOSITORY_ROOT=$(cd -- "${SCRIPT_DIRECTORY}/../.." && pwd)
readonly H2ORESTART_PROVENANCE_DIRECTORY=${REPOSITORY_ROOT}/third_party/h2orestart/${H2ORESTART_VERSION}
readonly H2ORESTART_PATCH_SOURCE=${H2ORESTART_PROVENANCE_DIRECTORY}/ConvGraphics-crop-compatibility.patch
readonly H2ORESTART_README_SOURCE=${H2ORESTART_PROVENANCE_DIRECTORY}/README.md
readonly H2ORESTART_DIRECTORY=/srv/eom/vendor/h2orestart/${H2ORESTART_VERSION}
readonly H2ORESTART=${H2ORESTART_DIRECTORY}/H2Orestart.oxt
readonly H2ORESTART_PATCH=${H2ORESTART_DIRECTORY}/ConvGraphics-crop-compatibility.patch
readonly H2ORESTART_README=${H2ORESTART_DIRECTORY}/README.md

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$(id -u)" == "0" ]] || fail "Office converter installation requires root"
(( $# <= 1 )) || fail "usage: $0 [/path/to/H2Orestart-0.7.14-eom.1.oxt]"
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
    grep -Fq "<version value=\"${H2ORESTART_DECLARED_VERSION}\"/>" || \
    fail "H2Orestart release bundle version differs"
  [[ -f "${H2ORESTART_PATCH_SOURCE}" && ! -L "${H2ORESTART_PATCH_SOURCE}" ]] || \
    fail "H2Orestart compatibility patch source is unavailable"
  [[ "$(sha256sum "${H2ORESTART_PATCH_SOURCE}" | cut -d' ' -f1)" == \
    "${H2ORESTART_PATCH_SHA256}" ]] || fail "H2Orestart compatibility patch hash differs"
  [[ -f "${H2ORESTART_README_SOURCE}" && ! -L "${H2ORESTART_README_SOURCE}" ]] || \
    fail "H2Orestart compatibility provenance is unavailable"
  install -d -o root -g root -m 0755 "${H2ORESTART_DIRECTORY}"
  install -o root -g root -m 0644 "${source_bundle}" "${H2ORESTART}"
  install -o root -g root -m 0644 "${H2ORESTART_PATCH_SOURCE}" "${H2ORESTART_PATCH}"
  install -o root -g root -m 0644 "${H2ORESTART_README_SOURCE}" "${H2ORESTART_README}"
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
[[ -f "${H2ORESTART_PATCH}" && ! -L "${H2ORESTART_PATCH}" ]] || \
  fail "installed H2Orestart compatibility patch is unavailable"
[[ "$(stat -c '%U:%G %a' "${H2ORESTART_PATCH}")" == "root:root 644" ]] || \
  fail "installed H2Orestart compatibility patch metadata differs"
[[ "$(sha256sum "${H2ORESTART_PATCH}" | cut -d' ' -f1)" == \
  "${H2ORESTART_PATCH_SHA256}" ]] || fail "installed H2Orestart compatibility patch hash differs"
[[ -f "${H2ORESTART_README}" && ! -L "${H2ORESTART_README}" ]] || \
  fail "installed H2Orestart compatibility provenance is unavailable"

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
printf 'h2orestart_declared_version=%s\n' "${H2ORESTART_DECLARED_VERSION}"
printf 'h2orestart_sha256=sha256:%s\n' "$(sha256sum "${H2ORESTART}" | cut -d' ' -f1)"
