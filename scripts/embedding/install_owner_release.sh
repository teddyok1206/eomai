#!/usr/bin/env bash
# Stage one reviewed owner wheel only. Never replace or admit a numerical runtime.
set -euo pipefail
export PATH=/usr/bin:/bin TZ=UTC LANG=C.UTF-8 LC_ALL=C
unset PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT BASH_ENV ENV
umask 077

fail() { printf '%s\n' "$1" >&2; exit 1; }
[[ "$EUID" == 0 && ( $# == 3 || $# == 5 ) ]] || fail NATIVE_OWNER_INSTALL_ARGUMENTS_INVALID
source_commit=$1
source_wheel=$2
wheel_sha256=$3
[[ "$source_commit" =~ ^[0-9a-f]{40}$ && "$wheel_sha256" =~ ^[0-9a-f]{64}$ ]] || fail NATIVE_OWNER_INSTALL_PINS_INVALID
[[ "$source_wheel" =~ ^/tmp/eom-api-build/[0-9a-f]{40}\.[A-Za-z0-9]+/dist/eom_platform-0\.1\.0-py3-none-any\.whl$ ]] || fail NATIVE_OWNER_WHEEL_PATH_INVALID
[[ "$source_wheel" == /tmp/eom-api-build/"$source_commit".*/dist/eom_platform-0.1.0-py3-none-any.whl ]] || fail NATIVE_OWNER_WHEEL_SOURCE_MISMATCH
[[ -f "$source_wheel" && ! -L "$source_wheel" ]] || fail NATIVE_OWNER_WHEEL_UNAVAILABLE
contracts_wheel=${4:-}
contracts_sha256=${5:-}
if [[ $# == 5 ]]; then
  [[ "$contracts_sha256" =~ ^[0-9a-f]{64}$ \
    && "$contracts_wheel" == "$(dirname "$source_wheel")/eom_api_contracts-0.1.0-py3-none-any.whl" \
    && -f "$contracts_wheel" && ! -L "$contracts_wheel" ]] || fail NATIVE_OWNER_API_CONTRACTS_INVALID
fi

release_root=/opt/eom/embedding-owner-releases
target="$release_root/$source_commit"
for node in / /opt /opt/eom "$release_root"; do
  [[ -d "$node" && ! -L "$node" && "$(stat -c %u "$node")" == 0 ]] || fail NATIVE_OWNER_PARENT_INVALID
  (( (8#$(stat -c %a "$node") & 8#022) == 0 )) || fail NATIVE_OWNER_PARENT_INVALID
done
[[ ! -e "$target" && ! -L "$target" ]] || fail NATIVE_OWNER_RELEASE_EXISTS

# A partial stage is retained on failure. Existing releases and all CPU files stay intact.
stage=$(mktemp -d "$release_root/.owner-stage-XXXXXXXX")
install -o root -g root -m 0600 "$source_wheel" "$stage/eom_platform-0.1.0-py3-none-any.whl"
[[ "$(sha256sum "$stage/eom_platform-0.1.0-py3-none-any.whl" | cut -d' ' -f1)" == "$wheel_sha256" ]] || fail NATIVE_OWNER_WHEEL_HASH_MISMATCH
staged_wheels=("$stage/eom_platform-0.1.0-py3-none-any.whl")
if [[ -n "$contracts_wheel" ]]; then
  # The existing inference-transfer extra belongs only to the owner release,
  # never to the separately frozen numerical interpreter or the running API.
  install -o root -g root -m 0600 "$contracts_wheel" "$stage/eom_api_contracts-0.1.0-py3-none-any.whl"
  [[ "$(sha256sum "$stage/eom_api_contracts-0.1.0-py3-none-any.whl" | cut -d' ' -f1)" == "$contracts_sha256" ]] || fail NATIVE_OWNER_API_CONTRACTS_HASH_MISMATCH
  staged_wheels+=("$stage/eom_api_contracts-0.1.0-py3-none-any.whl")
  verification_mode=--owner-pair
else
  verification_mode=--platform-only
fi
/srv/eom/conda/envs/eom-api/bin/python -I -B \
  /home/eom/EOM/scripts/api/verify_release_wheel_records.py \
  "$verification_mode" "${staged_wheels[@]}"
/srv/eom/conda/envs/eom-api/bin/python -I -B -m pip install \
  --no-deps --no-index --no-compile --no-cache-dir \
  --target "$stage/site-packages" "${staged_wheels[@]}"
[[ -f "$stage/site-packages/eom_workflow_runner/local_embedding_native_executor.py" \
  && -f "$stage/site-packages/eom_workflow/resources/native-embedding-coordinator-v1.schema.json" ]] || fail NATIVE_OWNER_EXECUTOR_MISSING
[[ -z "$(find -P "$stage" -type l -print -quit)" ]] || fail NATIVE_OWNER_RELEASE_LINK_INVALID
chown -R root:root "$stage"
find -P "$stage" -type d -exec chmod 0755 {} +
find -P "$stage" -type f -exec chmod 0444 {} +
# mkdir is the no-clobber reservation. Concurrent publication never replaces a release.
mkdir -m 0755 "$target" || fail NATIVE_OWNER_RELEASE_EXISTS
mv -T "$stage/site-packages" "$target/site-packages"
mv -T "$stage/eom_platform-0.1.0-py3-none-any.whl" "$target/eom_platform-0.1.0-py3-none-any.whl"
if [[ -n "$contracts_wheel" ]]; then
  mv -T "$stage/eom_api_contracts-0.1.0-py3-none-any.whl" "$target/eom_api_contracts-0.1.0-py3-none-any.whl"
  printf 'NATIVE_OWNER_API_CONTRACTS_INSTALLED=PASS\napi_contracts_wheel_sha256=%s\n' "$contracts_sha256"
fi
printf 'NATIVE_OWNER_WHEEL_INSTALLED=PASS\nsource_commit=%s\nwheel_sha256=%s\nowner_release=%s\n' \
  "$source_commit" "$wheel_sha256" "$target"
printf '%s\n' 'CPU_RUNTIME=UNCHANGED' 'OWNER_ACTIVATION=NOT_PERFORMED'
