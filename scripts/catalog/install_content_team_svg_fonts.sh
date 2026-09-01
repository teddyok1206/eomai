#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="/usr/local/share/fonts/eom"
KOREAN_TARGET="${TARGET_DIR}/SMJGothicStd-Regular.otf"
KOREAN_FALLBACK_TARGET="${TARGET_DIR}/NotoSansCJKkr-Regular.otf"
LATIN_TARGET="${TARGET_DIR}/CenturyOldStyle-Regular.otf"
LATIN_ITALIC_TARGET="${TARGET_DIR}/CenturyOldStyle-Italic.otf"
MATH_TARGET="/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"

KOREAN_SHA256="9200e1e46cca77f0ff9481c5345c3333caf22d50487418df74f830e4221adea1"
KOREAN_FALLBACK_SHA256="6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a"
LATIN_SHA256="7f9420403e10e7e74f002fbb48e8034d48f64cbdbef556d4f964b266043de338"
LATIN_ITALIC_SHA256="44b00cbdab9fdb7b4307db79784c5b90cbc52c5ffb0add32ac8239d73e567809"
MATH_SHA256="8f2c103bfa3fd5de71f1b92b18f21906b5a26871fb7e19a9a4c9af539c3cc7ab"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

sha256_of() {
  sha256sum -- "$1" | cut -d' ' -f1
}

require_font() {
  local path="$1"
  local expected="$2"
  [[ -f "${path}" && ! -L "${path}" ]] || fail "reviewed font is unavailable"
  [[ "$(sha256_of "${path}")" == "${expected}" ]] || fail "reviewed font hash mismatch"
}

require_target() {
  local path="$1"
  local expected="$2"
  require_font "${path}" "${expected}"
  [[ "$(stat -c '%U:%G:%a' "${path}")" == "root:root:644" ]] || \
    fail "installed font metadata is invalid"
}

require_safe_target_slot() {
  local path="$1"
  if [[ -e "${path}" || -L "${path}" ]]; then
    [[ -f "${path}" && ! -L "${path}" ]] || fail "font target is unsafe"
  fi
}

verify_family() {
  local query="$1"
  local expected_path="$2"
  local resolved
  resolved="$(fc-match -f '%{file}' "${query}")"
  [[ "${resolved}" == "${expected_path}" ]] || fail "fontconfig resolved an unexpected font"
}

[[ "$(id -u)" == "0" ]] || fail "content-team font installation requires root"
[[ -r /etc/os-release ]] || fail "Ubuntu release metadata is unavailable"
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] || \
  fail "content-team font installation is restricted to Ubuntu 24.04"

mode="install"
source_dir=""
korean_fallback_source=""
while (($#)); do
  case "$1" in
    --source-dir)
      (($# >= 2)) || fail "--source-dir requires one value"
      source_dir="$2"
      shift 2
      ;;
    --korean-fallback-source)
      (($# >= 2)) || fail "--korean-fallback-source requires one value"
      korean_fallback_source="$2"
      shift 2
      ;;
    --verify-only)
      mode="verify"
      shift
      ;;
    *)
      fail "unsupported argument"
      ;;
  esac
done

if [[ "${mode}" == "install" ]]; then
  [[ -n "${source_dir}" && -d "${source_dir}" && ! -L "${source_dir}" ]] || \
    fail "a non-symlink reviewed source directory is required"
  [[ -n "${korean_fallback_source}" ]] || fail "a reviewed Korean fallback source is required"
  korean_source="${source_dir}/SM중고딕.OTF"
  latin_source="${source_dir}/CenturyOldStyle-Regular.otf"
  latin_italic_source="${source_dir}/CenturyOldStyle-Italic.otf"
  require_font "${korean_source}" "${KOREAN_SHA256}"
  require_font "${korean_fallback_source}" "${KOREAN_FALLBACK_SHA256}"
  require_font "${latin_source}" "${LATIN_SHA256}"
  require_font "${latin_italic_source}" "${LATIN_ITALIC_SHA256}"

  if [[ -e "${TARGET_DIR}" ]]; then
    [[ -d "${TARGET_DIR}" && ! -L "${TARGET_DIR}" ]] || \
      fail "font target directory is unsafe"
    [[ "$(stat -c '%U' "${TARGET_DIR}")" == "root" ]] || \
      fail "font target directory metadata is invalid"
  else
    install -d -o root -g root -m 0755 "${TARGET_DIR}"
  fi
  chown root:root "${TARGET_DIR}"
  # GNU chmod preserves set-ID bits on directories unless they are explicitly
  # named.  The system font parent is setgid, so clear inherited set-ID bits
  # before enforcing this reviewed root-owned 0755 boundary.
  chmod u-s,g-s "${TARGET_DIR}"
  chmod 0755 "${TARGET_DIR}"
  require_safe_target_slot "${KOREAN_TARGET}"
  require_safe_target_slot "${KOREAN_FALLBACK_TARGET}"
  require_safe_target_slot "${LATIN_TARGET}"
  require_safe_target_slot "${LATIN_ITALIC_TARGET}"
  install -o root -g root -m 0644 -- "${korean_source}" "${KOREAN_TARGET}"
  install -o root -g root -m 0644 -- \
    "${korean_fallback_source}" "${KOREAN_FALLBACK_TARGET}"
  install -o root -g root -m 0644 -- "${latin_source}" "${LATIN_TARGET}"
  install -o root -g root -m 0644 -- "${latin_italic_source}" "${LATIN_ITALIC_TARGET}"
  fc-cache -f "${TARGET_DIR}" >/dev/null
  chmod u-s,g-s "${TARGET_DIR}"
  chmod 0755 "${TARGET_DIR}"
fi

require_target "${KOREAN_TARGET}" "${KOREAN_SHA256}"
require_target "${KOREAN_FALLBACK_TARGET}" "${KOREAN_FALLBACK_SHA256}"
require_target "${LATIN_TARGET}" "${LATIN_SHA256}"
require_target "${LATIN_ITALIC_TARGET}" "${LATIN_ITALIC_SHA256}"
require_target "${MATH_TARGET}" "${MATH_SHA256}"
[[ "$(stat -c '%U:%G:%a' "${TARGET_DIR}")" == "root:root:755" ]] || \
  fail "installed font directory metadata is invalid"
verify_family "SM JGothic Std" "${KOREAN_TARGET}"
verify_family "Noto Sans CJK KR" "${KOREAN_FALLBACK_TARGET}"
verify_family "Century Old Style:style=Regular" "${LATIN_TARGET}"
verify_family "Century Old Style:style=Italic" "${LATIN_ITALIC_TARGET}"
verify_family "DejaVu Serif" "${MATH_TARGET}"

printf 'content_team_svg_fonts=READY\n'
printf 'font_profile=eom-content-team-diagram-fonts/1.0\n'
printf 'korean_family=SM JGothic Std, Noto Sans CJK KR\n'
printf 'latin_family=Century Old Style\n'
printf 'math_family=DejaVu Serif\n'
