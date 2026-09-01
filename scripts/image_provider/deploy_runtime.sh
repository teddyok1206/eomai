#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
IMAGE_ENV=/srv/eom/conda/envs/eom-image
CONTRACT_WHEEL=${1:-}
CONTRACT_SHA256=${2:-}
PROVIDER_WHEEL=${3:-}
PROVIDER_SHA256=${4:-}
SOURCE_COMMIT=${5:-}
UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-provider@.service
UNIT_TARGET=/etc/systemd/system/eom-image-provider@.service
RUNNER_SOURCE=${REPOSITORY}/infra/systemd/eom-workflow-runner.service
RUNNER_TARGET=/etc/systemd/system/eom-workflow-runner.service
POLKIT_SOURCE=${REPOSITORY}/infra/polkit/50-eom-worker-units.rules
POLKIT_TARGET=/etc/polkit-1/rules.d/50-eom-worker-units.rules
BINDING_SOURCE=${REPOSITORY}/config/local-image-provider.ssd1b.json
BINDING_TARGET=/etc/eom/local-image-provider.json

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "LOCAL_IMAGE_RUNTIME_ROOT_REQUIRED"
[[ "${SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || fail "LOCAL_IMAGE_SOURCE_COMMIT_INVALID"
[[ "${CONTRACT_SHA256}" =~ ^[0-9a-f]{64}$ ]] || fail "LOCAL_IMAGE_WHEEL_HASH_INVALID"
[[ "${PROVIDER_SHA256}" =~ ^[0-9a-f]{64}$ ]] || fail "LOCAL_IMAGE_WHEEL_HASH_INVALID"
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "${SOURCE_COMMIT}" ]] || \
  fail "LOCAL_IMAGE_SOURCE_COMMIT_MISMATCH"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain)" ]] || \
  fail "LOCAL_IMAGE_SOURCE_TREE_DIRTY"
for wheel in "${CONTRACT_WHEEL}" "${PROVIDER_WHEEL}"; do
  [[ "${wheel}" == /tmp/eom-image-provider-build/*/*.whl ]] || \
    fail "LOCAL_IMAGE_WHEEL_PATH_INVALID"
  [[ -f "${wheel}" && ! -L "${wheel}" ]] || fail "LOCAL_IMAGE_WHEEL_INVALID"
done
[[ "$(sha256sum "${CONTRACT_WHEEL}" | cut -d' ' -f1)" == "${CONTRACT_SHA256}" ]] || \
  fail "LOCAL_IMAGE_WHEEL_HASH_MISMATCH"
[[ "$(sha256sum "${PROVIDER_WHEEL}" | cut -d' ' -f1)" == "${PROVIDER_SHA256}" ]] || \
  fail "LOCAL_IMAGE_WHEEL_HASH_MISMATCH"
[[ -f "${BINDING_SOURCE}" && ! -L "${BINDING_SOURCE}" ]] || \
  fail "LOCAL_IMAGE_BINDING_SOURCE_INVALID"
if systemctl list-units --type=service --state=activating,active --no-legend \
  'eom-image-provider@*.service' | grep -q .; then
  fail "LOCAL_IMAGE_PROVIDER_ACTIVE"
fi

getent group eom-image >/dev/null || groupadd --system eom-image
if ! getent passwd eom-image >/dev/null; then
  useradd --system --gid eom-image --home-dir /var/lib/eom-image \
    --no-create-home --shell /usr/sbin/nologin eom-image
fi
[[ "$(id -gn eom-image)" == "eom-image" ]] || fail "LOCAL_IMAGE_IDENTITY_INVALID"
for forbidden in eom sudo docker lxd adm; do
  if id -nG eom-image | tr ' ' '\n' | grep -Fxq "${forbidden}"; then
    fail "LOCAL_IMAGE_IDENTITY_OVERPRIVILEGED"
  fi
done
usermod --append --groups eom-image eom-workflow-runner

[[ -d /etc/eom && ! -L /etc/eom ]] || fail "LOCAL_IMAGE_SHARED_CONFIG_ROOT_INVALID"
[[ "$(stat -c '%U:%G:%a' /etc/eom)" == "root:root:755" ]] || \
  fail "LOCAL_IMAGE_SHARED_CONFIG_ROOT_DRIFT"
binding_temporary=$(mktemp /etc/eom/.local-image-provider.XXXXXX)
trap 'rm -f "${binding_temporary}"' EXIT
install -o root -g root -m 0644 "${BINDING_SOURCE}" "${binding_temporary}"
mv -f "${binding_temporary}" "${BINDING_TARGET}"
trap - EXIT
install -d -o root -g eom-image -m 03770 /srv/eom/image-workspaces

"${IMAGE_ENV}/bin/python" -m pip install --no-deps --force-reinstall "${CONTRACT_WHEEL}"
"${IMAGE_ENV}/bin/python" -m pip install --no-deps --force-reinstall "${PROVIDER_WHEEL}"
"${IMAGE_ENV}/bin/python" "${REPOSITORY}/scripts/image_provider/normalize_runtime_permissions.py" \
  --binding "${BINDING_TARGET}" --model-store-root /srv/eom/models/image

install -o root -g root -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
install -o root -g root -m 0644 "${RUNNER_SOURCE}" "${RUNNER_TARGET}"
install -o root -g root -m 0644 "${POLKIT_SOURCE}" "${POLKIT_TARGET}"
systemctl daemon-reload
systemd-analyze verify "${UNIT_TARGET}"
cmp -s "${UNIT_SOURCE}" "${UNIT_TARGET}" || fail "LOCAL_IMAGE_UNIT_DRIFT"
cmp -s "${RUNNER_SOURCE}" "${RUNNER_TARGET}" || fail "LOCAL_IMAGE_RUNNER_UNIT_DRIFT"
cmp -s "${POLKIT_SOURCE}" "${POLKIT_TARGET}" || fail "LOCAL_IMAGE_POLKIT_DRIFT"
cmp -s "${BINDING_SOURCE}" "${BINDING_TARGET}" || fail "LOCAL_IMAGE_BINDING_DRIFT"

runuser -u eom-image -g eom-image -- env -i \
  HOME=/var/lib/eom-image PATH=${IMAGE_ENV}/bin:/usr/bin:/bin PYTHONNOUSERSITE=1 \
  "${IMAGE_ENV}/bin/python" -I -c \
  'import eom_image_contracts, eom_image_provider; print("LOCAL_IMAGE_IMPORT=PASS")'

printf 'LOCAL_IMAGE_RUNTIME_PREPARED=YES\n'
printf 'SOURCE_COMMIT=%s\n' "${SOURCE_COMMIT}"
printf 'CONTRACT_WHEEL_SHA256=%s\n' "${CONTRACT_SHA256}"
printf 'PROVIDER_WHEEL_SHA256=%s\n' "${PROVIDER_SHA256}"
printf 'WORKSPACE_ROOT=root:eom-image:3770\n'
printf 'MODEL_STORE=root:eom-image:0750_0640\n'
printf 'RUNNER_RESTART_REQUIRED=YES\n'
printf 'CONTENT_PACK_ACTIVATION_REQUIRED=generated-knowledge-item@1.6.0\n'
