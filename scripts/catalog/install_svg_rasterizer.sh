#!/usr/bin/env bash
set -euo pipefail

PACKAGE="librsvg2-bin"
BINARY="/usr/bin/rsvg-convert"
FONT_PACKAGE="fonts-droid-fallback"
FONT="/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"

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
for package in "${PACKAGE}" "${FONT_PACKAGE}"; do
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
[[ -f "${FONT}" && ! -L "${FONT}" && -r "${FONT}" ]] || \
  fail "fixed SVG font is unavailable"
[[ "$(stat -c '%U:%G:%a' "${FONT}")" == "root:root:644" ]] || \
  fail "fixed SVG font metadata is invalid"

version="$(dpkg-query -W -f='${Version}' "${PACKAGE}")"
[[ "${version}" == 2.58.* ]] || fail "SVG rasterizer version is outside the reviewed family"
"${BINARY}" --version >/dev/null

printf 'svg_rasterizer=READY\n'
printf 'svg_rasterizer_package=%s\n' "${PACKAGE}"
printf 'svg_rasterizer_version=%s\n' "${version}"
printf 'svg_font_package=%s\n' "${FONT_PACKAGE}"
printf 'svg_font_family=Droid Sans Fallback\n'
