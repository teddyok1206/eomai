#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
readonly REPOSITORY=$(cd -- "${SCRIPT_DIRECTORY}/../.." && pwd)
# Fixed successor selection, never an executable/bundle path supplied by a worker.
if [[ "${1:-}" == --choices-v3 ]]; then
  shift
  readonly PROVENANCE=${REPOSITORY}/third_party/h2orestart/0.7.14-eom.3
  readonly TARGET=/srv/eom/vendor/h2orestart/0.7.14-eom.3
  readonly BUNDLE_SHA256=1aaabf0114d6ec1cee130c9f5b01d756a321ba0525d0ea211cccec01acfeb99a
  readonly UNIT=eom-office-choice-converter@.service
  readonly RULE=45-eom-office-choices.rules
  readonly PROFILE_ARGUMENT=--choices-v3
  readonly PROVENANCE_MEMBERS=(README.md ConvTable-choice-cell-compatibility.patch HancomChoiceCellLayout.java)
else
  readonly PROVENANCE=${REPOSITORY}/third_party/h2orestart/0.7.14-eom.2
  readonly TARGET=/srv/eom/vendor/h2orestart/0.7.14-eom.2
  readonly BUNDLE_SHA256=50d8cf433f12270b5ee44fa974993bc36b5804ef550f0ce09b39266305b1b2cb
  readonly UNIT=eom-office-equation-converter@.service
  readonly RULE=45-eom-office-equations.rules
  readonly PROFILE_ARGUMENT=--equations-v2
  readonly PROVENANCE_MEMBERS=(README.md ConvEquation-style-compatibility.patch HancomEquationStyle.java)
fi
readonly DROPIN_DIRECTORY=/etc/systemd/system/${UNIT}.d
readonly DROPIN=${DROPIN_DIRECTORY}/42-eom-equation-installed-release.conf
readonly TEMPLATE=${REPOSITORY}/infra/systemd/eom-office-equation-installed-release.conf.in

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
[[ "$(id -u)" == 0 ]] || fail "Office equation converter installation requires root"
verify_only=false
expected_commit=""
while (($#)); do
  case "$1" in
    --verify) verify_only=true; shift ;;
    --source-commit) (($# >= 2)) || fail "source commit missing"; expected_commit=$2; shift 2 ;;
    --*) fail "unsupported argument" ;;
    *) break ;;
  esac
done
(( $# <= 1 )) || fail "usage: $0 [--verify] [exact-reviewed.oxt]"
[[ "${verify_only}" == false || $# == 0 ]] || fail "--verify does not accept a bundle"
if [[ -z "${expected_commit}" && "${verify_only}" == true ]]; then
  [[ -f "${DROPIN}" && ! -L "${DROPIN}" ]] || fail "installed source pin missing"
  [[ "$(stat -c '%U:%G:%a' "${DROPIN}")" == root:root:644 ]] || fail "installed source pin metadata differs"
  expected_commit=$(sed -n 's/^# source_commit=\([0-9a-f]\{40\}\)$/\1/p' "${DROPIN}")
fi
[[ "${expected_commit}" =~ ^[0-9a-f]{40}$ ]] || fail "exact installed source commit is required"
readonly PREFIX=/opt/eom/embedding-owner-releases/${expected_commit}/site-packages
for directory in /opt/eom/embedding-owner-releases "/opt/eom/embedding-owner-releases/${expected_commit}" "${PREFIX}" "${PREFIX}/eom_catalog_service"; do
  [[ -d "${directory}" && ! -L "${directory}" && "$(stat -c '%u:%g' "${directory}")" == 0:0 ]] || fail "protected source prefix metadata differs"
  (( (8#$(stat -c '%a' "${directory}") & 8#022) == 0 )) || fail "protected source prefix is writable"
done
for member in office_converter_worker.py office_conversion_profiles.py office_pdf_quality.py; do
  path=${PREFIX}/eom_catalog_service/${member}
  [[ -f "${path}" && ! -L "${path}" && "$(stat -c '%U:%G:%a' "${path}")" == root:root:644 ]] || fail "pinned converter module metadata differs"
  cmp -s "${REPOSITORY}/services/catalog_service/eom_catalog_service/${member}" "${path}" || fail "pinned converter module bytes differ"
done
unit_candidate=$(mktemp /tmp/eom-office-equation-unit.XXXXXXXX)
trap 'rm -f -- "${unit_candidate}"' EXIT
sed -e "s/@EOM_EQUATION_SOURCE@/${expected_commit}/g" \
  -e "s/--equations-v2/${PROFILE_ARGUMENT}/g" "${TEMPLATE}" >"${unit_candidate}"
bash "${SCRIPT_DIRECTORY}/install_office_document_converter.sh" --verify
if [[ "${verify_only}" == false ]]; then
  (( $# == 1 )) || fail "exact reviewed equation-compatible OXT is required"
  [[ -f "$1" && ! -L "$1" ]] || fail "bundle must be a regular file"
  [[ "$(sha256sum -- "$1" | cut -d' ' -f1)" == "${BUNDLE_SHA256}" ]] || fail "bundle hash differs"
  install -d -o root -g root -m 0755 "${TARGET}"
  install -o root -g root -m 0644 -- "$1" "${TARGET}/H2Orestart.oxt"
  for member in "${PROVENANCE_MEMBERS[@]}"; do
    install -o root -g root -m 0644 "${PROVENANCE}/${member}" "${TARGET}/${member}"
  done
  install -o root -g root -m 0644 "${REPOSITORY}/infra/systemd/${UNIT}" "/etc/systemd/system/${UNIT}"
  install -o root -g root -m 0644 "${REPOSITORY}/infra/polkit/${RULE}" "/etc/polkit-1/rules.d/${RULE}"
  # An unreleased candidate used 55, which the shared 50 rule denied first.
  # Remove only those exact reviewed bytes, never an unrelated local rule.
  retired_rule=/etc/polkit-1/rules.d/55-eom-office-equations.rules
  if [[ -e "${retired_rule}" || -L "${retired_rule}" ]]; then
    [[ -f "${retired_rule}" && ! -L "${retired_rule}" && "$(stat -c '%U:%G:%a' "${retired_rule}")" == root:root:644 ]] || fail "retired equation rule metadata differs"
    [[ "$(sha256sum "${retired_rule}" | cut -d' ' -f1)" == fb0c80fa403a222a42ea94755b7661845684485709ea3d35fa6bb70674794423 ]] || fail "retired equation rule bytes differ"
    rm -- "${retired_rule}"
  fi
  install -d -o root -g root -m 0755 "${DROPIN_DIRECTORY}"
  install -o root -g root -m 0644 "${unit_candidate}" "${DROPIN}"
  systemctl daemon-reload
fi
[[ "$(sha256sum "${TARGET}/H2Orestart.oxt" | cut -d' ' -f1)" == "${BUNDLE_SHA256}" ]] || fail "installed bundle hash differs"
for member in H2Orestart.oxt "${PROVENANCE_MEMBERS[@]}"; do
  [[ -f "${TARGET}/${member}" && ! -L "${TARGET}/${member}" ]] || fail "installed provenance missing"
  [[ "$(stat -c '%U:%G:%a' "${TARGET}/${member}")" == root:root:644 ]] || fail "installed provenance metadata differs"
done
for member in "${PROVENANCE_MEMBERS[@]}"; do
  cmp -s "${PROVENANCE}/${member}" "${TARGET}/${member}" || fail "installed provenance bytes differ"
done
cmp -s "${REPOSITORY}/infra/systemd/${UNIT}" "/etc/systemd/system/${UNIT}" || fail "installed converter unit differs"
cmp -s "${REPOSITORY}/infra/polkit/${RULE}" "/etc/polkit-1/rules.d/${RULE}" || fail "installed converter rule differs"
cmp -s "${unit_candidate}" "${DROPIN}" || fail "installed converter source pin differs"
for path in "/etc/systemd/system/${UNIT}" "/etc/polkit-1/rules.d/${RULE}" "${DROPIN}"; do
  [[ -f "${path}" && ! -L "${path}" && "$(stat -c '%U:%G:%a' "${path}")" == root:root:644 ]] || fail "installed fixed unit/rule metadata differs"
done
systemd-analyze verify "/etc/systemd/system/${UNIT}"
printf 'office_equation_converter=READY\nlegacy_converter=PRESERVED\n'
