#!/usr/bin/env bash
set -euo pipefail

PACKAGE="librsvg2-bin"
BINARY="/usr/bin/rsvg-convert"
LEGACY_FONT_PACKAGE="fonts-droid-fallback"
LEGACY_FONT="/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
LEGACY_FONT_SHA256="acb6440a713d880a13a21b468ba7cd43f5a2b2934972e51be791c880730777b8"
FONT_INSTALLER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install_content_team_svg_fonts.sh"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$(id -u)" == "0" ]] || fail "SVG rasterizer installation requires root"
[[ -r /etc/os-release ]] || fail "Ubuntu release metadata is unavailable"
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] || \
  fail "reviewed SVG rasterizer package is restricted to Ubuntu 24.04"

missing_packages=()
for package in "${PACKAGE}" "${LEGACY_FONT_PACKAGE}"; do
  if ! dpkg-query -W -f='${Status}' "${package}" 2>/dev/null | grep -qx 'install ok installed'; then
    missing_packages+=("${package}")
  fi
done
if ((${#missing_packages[@]})); then
  export DEBIAN_FRONTEND=noninteractive
  apt-get install --no-install-recommends --yes "${missing_packages[@]}"
fi

[[ -f "${BINARY}" && ! -L "${BINARY}" && -x "${BINARY}" ]] || \
  fail "fixed SVG rasterizer executable is unavailable"
[[ "$(stat -c '%U:%G:%a' "${BINARY}")" == "root:root:755" ]] || \
  fail "fixed SVG rasterizer metadata is invalid"
[[ -f "${LEGACY_FONT}" && ! -L "${LEGACY_FONT}" ]] || fail "legacy SVG font is unavailable"
[[ "$(stat -c '%U:%G:%a' "${LEGACY_FONT}")" == "root:root:644" ]] || \
  fail "legacy SVG font metadata is invalid"
[[ "$(sha256sum "${LEGACY_FONT}" | cut -d' ' -f1)" == "${LEGACY_FONT_SHA256}" ]] || \
  fail "legacy SVG font hash is invalid"
[[ -x "${FONT_INSTALLER}" && ! -L "${FONT_INSTALLER}" ]] || \
  fail "content-team font verifier is unavailable"
"${FONT_INSTALLER}" --verify-only >/dev/null

version="$(dpkg-query -W -f='${Version}' "${PACKAGE}")"
[[ "${version}" == 2.58.* ]] || fail "SVG rasterizer version is outside the reviewed family"
"${BINARY}" --version >/dev/null

printf 'svg_rasterizer=READY\n'
printf 'svg_rasterizer_package=%s\n' "${PACKAGE}"
printf 'svg_rasterizer_version=%s\n' "${version}"
printf 'svg_font_profile=eom-content-team-diagram-fonts/1.0\n'
