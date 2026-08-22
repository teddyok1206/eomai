#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
CONFIG_ROOT="/etc/eom"
WORKFLOW_ROOT="${CONFIG_ROOT}/workflows"
PROMPT_ROOT="${CONFIG_ROOT}/workflow-prompts"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$(id -u)" == "0" ]] || fail "workflow runner configuration install requires root"
[[ "$(git -C "${REPOSITORY_ROOT}" rev-parse --show-toplevel)" == "${REPOSITORY_ROOT}" ]] || \
  fail "repository root mismatch"

declare -A FILES=(
  ["${REPOSITORY_ROOT}/config/workflows/generic-item-development.v1.4.yaml"]="${WORKFLOW_ROOT}/generic-item-development.yaml"
  ["${REPOSITORY_ROOT}/config/human-actors.example.yaml"]="${CONFIG_ROOT}/human-actors.yaml"
  ["${REPOSITORY_ROOT}/config/workflow-runner.example.yaml"]="${CONFIG_ROOT}/workflow-runner.yaml"
  ["${REPOSITORY_ROOT}/content/prompt-templates/placeholders/authoring.txt"]="${PROMPT_ROOT}/authoring.txt"
  ["${REPOSITORY_ROOT}/content/prompt-templates/placeholders/image.txt"]="${PROMPT_ROOT}/image.txt"
  ["${REPOSITORY_ROOT}/content/prompt-templates/placeholders/review.txt"]="${PROMPT_ROOT}/review.txt"
  ["${REPOSITORY_ROOT}/content/prompt-templates/placeholders/registration.txt"]="${PROMPT_ROOT}/registration.txt"
)

for source in "${!FILES[@]}"; do
  [[ -f "${source}" && ! -L "${source}" ]] || fail "unsafe configuration source"
done

[[ -d "${CONFIG_ROOT}" && ! -L "${CONFIG_ROOT}" ]] || fail "operator config root is unavailable"
install -d -o root -g eom -m 0750 "${WORKFLOW_ROOT}" "${PROMPT_ROOT}"
for source in "${!FILES[@]}"; do
  target="${FILES[${source}]}"
  install -o root -g eom -m 0640 "${source}" "${target}"
  cmp -s "${source}" "${target}" || fail "installed configuration content mismatch"
  [[ "$(stat -c '%U:%G:%a' "${target}")" == "root:eom:640" ]] || \
    fail "installed configuration metadata mismatch"
done

for directory in "${WORKFLOW_ROOT}" "${PROMPT_ROOT}"; do
  [[ ! -L "${directory}" && "$(stat -c '%U:%G:%a' "${directory}")" == "root:eom:750" ]] || \
    fail "installed configuration directory metadata mismatch"
done

printf '%s\n' "workflow_runner_configuration=INSTALLED"
