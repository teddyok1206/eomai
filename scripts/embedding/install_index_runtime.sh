#!/usr/bin/env bash
# Fixed protected-prefix publication; no model/unit installation or runtime admission.
set -euo pipefail
export PATH=/usr/bin:/bin TZ=UTC LANG=C.UTF-8 LC_ALL=C
unset PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT BASH_ENV ENV
umask 077

REPOSITORY=/home/eom/EOM
HELPER_SOURCE=${REPOSITORY}/scripts/embedding/_install_experiment_snapshot.py
AUDIT_SOURCE=${REPOSITORY}/scripts/embedding/admit_index_runtime.py
OLD_PREFIX=/opt/eom/conda/envs/eom-embedding-experiment
ARCHIVE_ROOT=/opt/eom/embedding-runtime-archives
INSTALL_PHASE=NOT_STAGED
fail() { printf '%s\n' "$1" "install_phase=$INSTALL_PHASE" >&2; exit 1; }
hash_valid() { [[ "$1" =~ ^[0-9a-f]{64}$ ]]; }
commit_valid() { [[ "$1" =~ ^[0-9a-f]{40}$ ]]; }
root_directory() {
  [[ -d "$1" && ! -L "$1" && "$(stat -c %u "$1")" == 0 ]] || fail EMBEDDING_INDEX_PARENT_INVALID
  (( (8#$(stat -c %a "$1") & 8#022) == 0 )) || fail EMBEDDING_INDEX_PARENT_INVALID
}
fixed_parents() {
  local member
  for member in / /opt /opt/eom /opt/eom/conda /opt/eom/conda/envs; do
    if [[ ! -e "$member" && ! -L "$member" ]]; then mkdir -m 0755 "$member"; fi
    root_directory "$member"
  done
}
tree_digest() {
  (
    cd -- "$1"
    while IFS= read -r -d '' member; do
      [[ ! "$member" =~ [[:cntrl:]] ]] || fail EMBEDDING_INDEX_RUNTIME_MEMBER_INVALID
      if [[ -L "$member" ]]; then
        target=$(readlink -- "$member")
        [[ ! "$target" =~ [[:cntrl:]] ]] || fail EMBEDDING_INDEX_RUNTIME_LINK_INVALID
        printf 'L\0%s\0%s\0' "$member" "$target"
      elif [[ -d "$member" ]]; then printf 'D\0%s\0' "$member"
      elif [[ -f "$member" ]]; then
        [[ "$(stat -c %h "$member")" == 1 ]] || fail EMBEDDING_INDEX_RUNTIME_HARDLINK_INVALID
        digest=$(sha256sum -- "$member")
        printf 'F\0%s\0%s\0' "$member" "${digest:0:64}"
      else fail EMBEDDING_INDEX_RUNTIME_MEMBER_INVALID; fi
    done < <(find -P . -mindepth 1 -print0 | sort -z)
  ) | sha256sum | cut -c 1-64
}

mode=${1:-}; profile=${2:-}; shift 2 || fail EMBEDDING_INDEX_ARGUMENTS_INVALID
case "$profile" in
  CPU_INDEX_FP32) PREFIX=/opt/eom/conda/envs/eom-embedding-index-cpu ;;
  CUDA_INDEX_FP32) PREFIX=/opt/eom/conda/envs/eom-embedding-cuda ;;
  *) fail EMBEDDING_INDEX_PROFILE_INVALID ;;
esac
case "$mode" in
  fingerprint)
    [[ $# == 0 && -d "$PREFIX" && ! -L "$PREFIX" ]] || fail EMBEDDING_INDEX_RUNTIME_INPUT_INVALID
    tree_digest "$PREFIX"; exit 0 ;;
  prepare-prefix)
    [[ "$EUID" == 0 && $# == 0 ]] || fail EMBEDDING_INDEX_ROOT_REQUIRED
    fixed_parents
    [[ ! -e "$PREFIX" && ! -L "$PREFIX" ]] || fail EMBEDDING_INDEX_TARGET_EXISTS
    getent passwd eom >/dev/null || fail EMBEDDING_INDEX_DEVELOPER_MISSING
    install -d -o eom -g eom -m 0700 "$PREFIX"
    printf '%s\n' EMBEDDING_INDEX_PREFIX_PREPARED_NO_EXECUTION; exit 0 ;;
  publish) ;;
  *) fail EMBEDDING_INDEX_MODE_INVALID ;;
esac

# Fixed argument closure. CPU lease fields must be '-' rather than a hidden alternate input.
[[ "$EUID" == 0 && $# -ge 16 && $# -le 19 ]] || fail EMBEDDING_INDEX_ARGUMENTS_INVALID
RUNTIME_SHA=$1; HELPER_SHA=$2; PLATFORM_WHEEL=$3; PLATFORM_SHA=$4; PLATFORM_COMMIT=$5
PLATFORM_SOURCE=$6; PLATFORM_SOURCE_SHA=$7; LEASE_WHEEL=$8; LEASE_SHA=$9
shift 9
LEASE_COMMIT=$1; LEASE_SOURCE=$2; LEASE_SOURCE_SHA=$3; shift 3
AUDIT_INPUT_SOURCE=$1; AUDIT_INPUT_SHA=$2; AUDIT_LEAF_SHA=$3; shift 3
for digest in "$RUNTIME_SHA" "$HELPER_SHA" "$PLATFORM_SHA" "$PLATFORM_SOURCE_SHA" "$AUDIT_INPUT_SHA" "$AUDIT_LEAF_SHA"; do
  hash_valid "$digest" || fail EMBEDDING_INDEX_HASH_INVALID
done
commit_valid "$PLATFORM_COMMIT" || fail EMBEDDING_INDEX_PRIVATE_PINS_REQUIRED
[[ "$PLATFORM_WHEEL" == /tmp/eom-*/* && "$PLATFORM_SOURCE" == /tmp/eom-*/* ]] || fail EMBEDDING_INDEX_SOURCE_PATH_INVALID
if [[ "$profile" == CUDA_INDEX_FP32 ]]; then
  hash_valid "$LEASE_SHA" && hash_valid "$LEASE_SOURCE_SHA" && commit_valid "$LEASE_COMMIT" || fail EMBEDDING_INDEX_PRIVATE_PINS_REQUIRED
  [[ "$LEASE_WHEEL" == /tmp/eom-*/* && "$LEASE_SOURCE" == /tmp/eom-*/* ]] || fail EMBEDDING_INDEX_SOURCE_PATH_INVALID
else
  [[ "$LEASE_WHEEL" == - && "$LEASE_SHA" == - && "$LEASE_COMMIT" == - && "$LEASE_SOURCE" == - && "$LEASE_SOURCE_SHA" == - ]] || fail EMBEDDING_INDEX_PRIVATE_PINS_REQUIRED
fi
[[ "$AUDIT_INPUT_SOURCE" =~ ^/tmp/eom-[A-Za-z0-9_.-]+/prefix-audit-input\.json$ && -f "$AUDIT_INPUT_SOURCE" && ! -L "$AUDIT_INPUT_SOURCE" ]] || fail EMBEDDING_INDEX_AUDIT_INPUT_INVALID
(( $(stat -c %s -- "$AUDIT_INPUT_SOURCE") > 0 && $(stat -c %s -- "$AUDIT_INPUT_SOURCE") <= 131072 )) || fail EMBEDDING_INDEX_AUDIT_INPUT_INVALID
for directory in "$@"; do
  [[ "$directory" == /tmp/eom-* && -d "$directory" && ! -L "$directory" ]] || fail EMBEDDING_INDEX_WHEELHOUSE_INVALID
done
fixed_parents

# Root-private fixed lock inode; concurrent publication cannot replace the held reservation.
PUBLICATION_LOCK=/opt/eom/conda/envs/.embedding-index-${profile}.lock
if [[ ! -e "$PUBLICATION_LOCK" && ! -L "$PUBLICATION_LOCK" ]]; then
  (set -o noclobber; : > "$PUBLICATION_LOCK") 2>/dev/null || true
fi
[[ -f "$PUBLICATION_LOCK" && ! -L "$PUBLICATION_LOCK" && "$(stat -c %u "$PUBLICATION_LOCK")" == 0 && "$(stat -c %a "$PUBLICATION_LOCK")" == 600 && "$(stat -c %h "$PUBLICATION_LOCK")" == 1 ]] || fail EMBEDDING_INDEX_PUBLICATION_LOCK_INVALID
exec {PUBLICATION_FD}<>"$PUBLICATION_LOCK"
[[ "$(stat -Lc %d:%i /proc/$$/fd/$PUBLICATION_FD)" == "$(stat -c %d:%i "$PUBLICATION_LOCK")" ]] || fail EMBEDDING_INDEX_PUBLICATION_LOCK_INVALID
flock -n "$PUBLICATION_FD" || fail EMBEDDING_INDEX_PUBLICATION_BUSY
[[ -d "$PREFIX" && ! -L "$PREFIX" && "$(stat -c %u "$PREFIX")" == "$(id -u eom)" ]] || fail EMBEDDING_INDEX_RUNTIME_INPUT_INVALID

QUARANTINE=$(mktemp -d /opt/eom/conda/envs/.embedding-index-runtime-XXXXXXXX)
PRIVATE=$(mktemp -d /opt/eom/.embedding-index-install-XXXXXXXX)
chmod 0700 "$QUARANTINE" "$PRIVATE"
record_phase() { INSTALL_PHASE=$1; printf '%s\n' "$INSTALL_PHASE" >> "$PRIVATE/phase-receipt"; }
trap 'printf "%s\n" "EMBEDDING_INDEX_STOPPED install_phase=$INSTALL_PHASE" >&2' ERR
record_phase QUARANTINE_COPY
timeout --signal=KILL 900 cp -a --no-preserve=links,ownership,xattr,context -- "$PREFIX/." "$QUARANTINE/"
chown -hR root:root "$QUARANTINE"
[[ "$(tree_digest "$QUARANTINE")" == "$RUNTIME_SHA" ]] || fail EMBEDDING_INDEX_RUNTIME_TREE_HASH_MISMATCH
while IFS= read -r -d '' member; do
  if [[ -L "$member" ]]; then
    target=$(realpath -e -- "$member")
    [[ "$target" == "$QUARANTINE/"* ]] || fail EMBEDDING_INDEX_RUNTIME_LINK_ESCAPE
  else
    [[ -d "$member" || -f "$member" ]] || fail EMBEDDING_INDEX_RUNTIME_MEMBER_INVALID
    (( (8#$(stat -c %a "$member") & 8#6022) == 0 )) || fail EMBEDDING_INDEX_RUNTIME_MODE_INVALID
  fi
done < <(find -P "$QUARANTINE" -print0)
[[ -f "$QUARANTINE/bin/python3.12" && ! -L "$QUARANTINE/bin/python3.12" && -x "$QUARANTINE/bin/python3.12" ]] || fail EMBEDDING_INDEX_INTERPRETER_INVALID
install -m 0600 -- "$HELPER_SOURCE" "$PRIVATE/install.py"
[[ "$(sha256sum "$PRIVATE/install.py" | cut -c 1-64)" == "$HELPER_SHA" ]] || fail EMBEDDING_INDEX_HELPER_HASH_MISMATCH
mkdir -m 0700 "$PRIVATE/locks"
for name in eom-embedding-protected-runtime.requirements.proposal.lock eom-embedding-index-cpu.requirements.proposal.lock eom-embedding-cuda.requirements.proposal.lock; do
  install -m 0600 -- "$REPOSITORY/infra/conda/$name" "$PRIVATE/locks/$name"
done
for name in common-numeric-runtime-wheels.lock cuda-runtime-wheels.lock; do
  install -m 0600 -- "$REPOSITORY/scripts/embedding/$name" "$PRIVATE/locks/$name"
done
if [[ ! -e "$ARCHIVE_ROOT" && ! -L "$ARCHIVE_ROOT" ]]; then install -d -o root -g root -m 0755 "$ARCHIVE_ROOT"; fi
root_directory "$ARCHIVE_ROOT"
record_phase AUDIT_INPUT_COPY
(set -o noclobber; timeout --signal=KILL 10 head -c 131073 -- "$AUDIT_INPUT_SOURCE" > "$PRIVATE/prefix-audit-input.json")
[[ "$(stat -c %s "$PRIVATE/prefix-audit-input.json")" -le 131072 && "$(sha256sum "$PRIVATE/prefix-audit-input.json" | cut -c 1-64)" == "$AUDIT_INPUT_SHA" ]] || fail EMBEDDING_INDEX_AUDIT_INPUT_HASH_MISMATCH
[[ -f "$AUDIT_SOURCE" && ! -L "$AUDIT_SOURCE" && "$(stat -c %s "$AUDIT_SOURCE")" -le 1048576 ]] || fail EMBEDDING_INDEX_AUDIT_LEAF_INVALID
(set -o noclobber; timeout --signal=KILL 10 head -c 1048577 -- "$AUDIT_SOURCE" > "$PRIVATE/admit.py")
[[ "$(stat -c %s "$PRIVATE/admit.py")" -le 1048576 && "$(sha256sum "$PRIVATE/admit.py" | cut -c 1-64)" == "$AUDIT_LEAF_SHA" ]] || fail EMBEDDING_INDEX_AUDIT_LEAF_HASH_MISMATCH
mkdir -m 0700 "$PRIVATE/source" "$PRIVATE/source/eom_catalog_service"
for name in __init__.py embedding_runtime_files.py embedding_runtime_wheel_closure.py embedding_runtime_host_closure.py embedding_conda_runtime_closure.py embedding_runtime_prefix_closure.py embedding_host_configuration_capture.py; do
  source_member="$REPOSITORY/services/catalog_service/eom_catalog_service/$name"
  [[ -f "$source_member" && ! -L "$source_member" && "$(stat -c %s "$source_member")" -le 1048576 ]] || fail EMBEDDING_INDEX_AUDIT_MODULE_INVALID
  (set -o noclobber; timeout --signal=KILL 10 head -c 1048577 -- "$source_member" > "$PRIVATE/source/eom_catalog_service/$name")
  [[ "$(stat -c %s "$PRIVATE/source/eom_catalog_service/$name")" -le 1048576 ]] || fail EMBEDDING_INDEX_AUDIT_MODULE_INVALID
done
# The independently accepted old bootstrap is not re-certified here. Root OS/package
# maintenance must keep every admitted loader/library/prefix user drained through NEW.
root_directory "$OLD_PREFIX"
root_directory "$OLD_PREFIX/bin"
[[ -f "$OLD_PREFIX/bin/python3.12" && ! -L "$OLD_PREFIX/bin/python3.12" && -x "$OLD_PREFIX/bin/python3.12" && "$(stat -c %u "$OLD_PREFIX/bin/python3.12")" == 0 && "$(stat -c %h "$OLD_PREFIX/bin/python3.12")" == 1 ]] || fail EMBEDDING_INDEX_OLD_BOOTSTRAP_INVALID
(( (8#$(stat -c %a "$OLD_PREFIX/bin/python3.12") & 8#6022) == 0 )) || fail EMBEDDING_INDEX_OLD_BOOTSTRAP_INVALID
record_phase AUDIT_INPUTS_COPIED
# A missing snapshot namespace or changed host must fail before moving either prefix.
record_phase BEFORE_HOST_BYTES_PREFLIGHT
HOST_AUDIT_RECEIPT="$PRIVATE/host-bytes-audit.receipt"
if ! (
  set -o noclobber
  timeout --signal=KILL 60 env -i PATH=/usr/bin:/bin TZ=UTC LANG=C.UTF-8 "$OLD_PREFIX/bin/python3.12" -I -S -B "$PRIVATE/admit.py" host-bytes --profile "$profile" --owner-input "$PRIVATE/prefix-audit-input.json" --owner-input-sha256 "sha256:$AUDIT_INPUT_SHA" | head -c 129 > "$HOST_AUDIT_RECEIPT"
); then fail EMBEDDING_INDEX_HOST_PREFLIGHT_FAILED; fi
[[ -f "$HOST_AUDIT_RECEIPT" && ! -L "$HOST_AUDIT_RECEIPT" && "$(stat -c %s "$HOST_AUDIT_RECEIPT")" -le 128 ]] || fail EMBEDDING_INDEX_HOST_PREFLIGHT_INVALID
IFS= read -r HOST_AUDIT_STATUS < "$HOST_AUDIT_RECEIPT" || fail EMBEDDING_INDEX_HOST_PREFLIGHT_INVALID
[[ "$HOST_AUDIT_STATUS" =~ ^EMBEDDING_HOST_BYTES_AUDIT_PASS_NOT_ADMITTED\ sha256:[0-9a-f]{64}$ && "$(stat -c %s "$HOST_AUDIT_RECEIPT")" -eq $((${#HOST_AUDIT_STATUS} + 1)) ]] || fail EMBEDDING_INDEX_HOST_PREFLIGHT_INVALID
record_phase HOST_BYTES_PREFLIGHT_PASS_NOT_ADMITTED
BACKUP=/opt/eom/conda/envs/.embedding-index-prepublication-${profile}-$(basename "$PRIVATE")
[[ ! -e "$BACKUP" && ! -L "$BACKUP" ]] || fail EMBEDDING_INDEX_BACKUP_EXISTS
record_phase BEFORE_PREFIX_REPLACEMENT
mv -T -- "$PREFIX" "$BACKUP"
chmod 0700 "$BACKUP"
record_phase PREFIX_ABSENT_RETAINED_QUARANTINE
[[ ! -e "$PREFIX" && ! -L "$PREFIX" ]] || fail EMBEDDING_INDEX_TARGET_EXISTS
mv -T -- "$QUARANTINE" "$PREFIX"
chmod 0755 "$PREFIX"
record_phase STAGED_NOT_ADMITTED
record_phase BEFORE_OLD_PREFIX_BYTES_AUDIT
AUDIT_RECEIPT="$PRIVATE/prefix-bytes-audit.receipt"
AUDIT_INVENTORY="$PRIVATE/prefix-inventory.candidate.json"
# Open once before OLD captures directory epochs; fd3 is evidence output, never runtime authority.
(set -o noclobber; : > "$AUDIT_INVENTORY") || fail EMBEDDING_INDEX_INVENTORY_EXISTS
[[ -f "$AUDIT_INVENTORY" && ! -L "$AUDIT_INVENTORY" && "$(stat -c %u:%a:%h:%s "$AUDIT_INVENTORY")" == 0:600:1:0 ]] || fail EMBEDDING_INDEX_INVENTORY_INVALID
if ! (
  set -o noclobber
  timeout --signal=KILL 900 env -i PATH=/usr/bin:/bin TZ=UTC LANG=C.UTF-8 "$OLD_PREFIX/bin/python3.12" -I -S -B "$PRIVATE/admit.py" prefix-bytes --profile "$profile" --owner-input "$PRIVATE/prefix-audit-input.json" --owner-input-sha256 "sha256:$AUDIT_INPUT_SHA" 3<>"$AUDIT_INVENTORY" | head -c 129 > "$AUDIT_RECEIPT"
); then fail EMBEDDING_INDEX_OLD_PREFIX_AUDIT_FAILED; fi
[[ -f "$AUDIT_RECEIPT" && ! -L "$AUDIT_RECEIPT" && "$(stat -c %s "$AUDIT_RECEIPT")" -le 128 ]] || fail EMBEDDING_INDEX_AUDIT_RECEIPT_INVALID
IFS= read -r AUDIT_STATUS < "$AUDIT_RECEIPT" || fail EMBEDDING_INDEX_AUDIT_RECEIPT_INVALID
[[ "$AUDIT_STATUS" =~ ^EMBEDDING_PREFIX_BYTES_AUDIT_PASS_NOT_ADMITTED\ sha256:[0-9a-f]{64}$ && "$(stat -c %s "$AUDIT_RECEIPT")" -eq $((${#AUDIT_STATUS} + 1)) ]] || fail EMBEDDING_INDEX_AUDIT_RECEIPT_INVALID
[[ -f "$AUDIT_INVENTORY" && ! -L "$AUDIT_INVENTORY" && "$(stat -c %u:%a:%h "$AUDIT_INVENTORY")" == 0:600:1 ]] || fail EMBEDDING_INDEX_INVENTORY_INVALID
(( $(stat -c %s "$AUDIT_INVENTORY") > 0 && $(stat -c %s "$AUDIT_INVENTORY") <= 16777216 )) || fail EMBEDDING_INDEX_INVENTORY_INVALID
record_phase PREFIX_BYTES_AUDITED_NOT_ADMITTED
arguments=(index-runtime --profile "$profile" --lock-directory "$PRIVATE/locks"
  --platform-wheel "$PLATFORM_WHEEL" --platform-wheel-sha256 "$PLATFORM_SHA"
  --platform-source "$PLATFORM_SOURCE" --platform-source-sha256 "$PLATFORM_SOURCE_SHA"
  --platform-commit "$PLATFORM_COMMIT")
if [[ "$profile" == CUDA_INDEX_FP32 ]]; then
  arguments+=(--lease-wheel "$LEASE_WHEEL" --lease-wheel-sha256 "$LEASE_SHA"
    --lease-source "$LEASE_SOURCE" --lease-source-sha256 "$LEASE_SOURCE_SHA" --lease-commit "$LEASE_COMMIT")
fi
for directory in "$@"; do arguments+=(--wheelhouse "$directory"); done
timeout --signal=KILL 900 env -i PATH=/usr/bin:/bin TZ=UTC LANG=C.UTF-8 "$PREFIX/bin/python3.12" -I -S -B "$PRIVATE/install.py" "${arguments[@]}"
record_phase INSTALLED_NOT_ADMITTED
printf '%s\n' EMBEDDING_INDEX_INSTALL_STATUS=INSTALLED_NOT_ADMITTED EMBEDDING_INDEX_PROBE_STATUS=NOT_PROBED \
  "platform_source_commit=$PLATFORM_COMMIT" "runtime_backup=$BACKUP" "installer_quarantine=$PRIVATE"
