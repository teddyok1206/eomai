#!/usr/bin/env bash
# Fixed new-prefix bootstrap only. No package/model/unit installation or runtime admission.
set -euo pipefail
export PATH=/usr/bin:/bin TZ=UTC LANG=C.UTF-8 LC_ALL=C
unset PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT BASH_ENV ENV
umask 077

REPOSITORY=/home/eom/EOM
HELPER_SOURCE=${REPOSITORY}/scripts/embedding/_install_experiment_snapshot.py
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
[[ "$EUID" == 0 && $# -ge 13 && $# -le 16 ]] || fail EMBEDDING_INDEX_ARGUMENTS_INVALID
RUNTIME_SHA=$1; HELPER_SHA=$2; PLATFORM_WHEEL=$3; PLATFORM_SHA=$4; PLATFORM_COMMIT=$5
PLATFORM_SOURCE=$6; PLATFORM_SOURCE_SHA=$7; LEASE_WHEEL=$8; LEASE_SHA=$9
shift 9
LEASE_COMMIT=$1; LEASE_SOURCE=$2; LEASE_SOURCE_SHA=$3; shift 3
for digest in "$RUNTIME_SHA" "$HELPER_SHA" "$PLATFORM_SHA" "$PLATFORM_SOURCE_SHA"; do
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
