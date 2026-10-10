#!/usr/bin/env bash
# Fixed-prefix snapshot publisher. Never run mutable Conda/Python/pip/post-link as root.
set -euo pipefail
export PATH=/usr/bin:/bin TZ=UTC LANG=C.UTF-8 LC_ALL=C
unset PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH BASH_ENV ENV
umask 077

PREFIX=/opt/eom/conda/envs/eom-embedding-experiment
MODEL_STORE=/opt/eom/embedding-models
REPOSITORY=/home/eom/EOM
CPU_USER=eom-embedding-experiment
OWNER_USER=eom-workflow-runner
HELPER_SOURCE=${REPOSITORY}/scripts/embedding/_install_experiment_snapshot.py

INSTALL_PHASE=NOT_STAGED
fail() { printf '%s\n' "$1" "install_phase=$INSTALL_PHASE" >&2; exit 1; }
hash_valid() { [[ "$1" =~ ^[0-9a-f]{64}$ ]]; }
root_directory() {
  local member="$1"
  [[ -d "$member" && ! -L "$member" ]] || fail EMBEDDING_INSTALL_PARENT_INVALID
  [[ "$(stat -c %u "$member")" == 0 ]] || fail EMBEDDING_INSTALL_PARENT_INVALID
  (( (8#$(stat -c %a "$member") & 8#022) == 0 )) || fail EMBEDDING_INSTALL_PARENT_INVALID
}
fixed_parents() {
  local member
  for member in / /opt /opt/eom /opt/eom/conda /opt/eom/conda/envs; do
    if [[ ! -e "$member" && ! -L "$member" ]]; then mkdir -m 0755 "$member"; fi
    root_directory "$member"
  done
}

# This byte-tree digest has no reliance on the staged runtime interpreter/RECORD.
# Stable sorted NUL-delimited D/F/L records; paths/link targets cannot contain controls.
tree_digest() {
  (
    cd -- "$1"
    while IFS= read -r -d '' member; do
      [[ ! "$member" =~ [[:cntrl:]] ]] || fail EMBEDDING_RUNTIME_MEMBER_INVALID
      if [[ -L "$member" ]]; then
        target=$(readlink -- "$member")
        [[ ! "$target" =~ [[:cntrl:]] ]] || fail EMBEDDING_RUNTIME_LINK_INVALID
        printf 'L\0%s\0%s\0' "$member" "$target"
      elif [[ -d "$member" ]]; then
        printf 'D\0%s\0' "$member"
      elif [[ -f "$member" ]]; then
        [[ "$(stat -c %h "$member")" == 1 ]] || fail EMBEDDING_RUNTIME_HARDLINK_INVALID
        digest=$(sha256sum -- "$member")
        printf 'F\0%s\0%s\0' "$member" "${digest:0:64}"
      else fail EMBEDDING_RUNTIME_MEMBER_INVALID
      fi
    done < <(find -P . -mindepth 1 -print0 | sort -z)
  ) | sha256sum | cut -c 1-64
}

mode=${1:-}; shift || true
case "$mode" in
  fingerprint)
    [[ $# == 0 && -d "$PREFIX" && ! -L "$PREFIX" ]] || fail EMBEDDING_RUNTIME_INPUT_INVALID
    tree_digest "$PREFIX"
    exit 0;;
  prepare-prefix)
    [[ "$EUID" == 0 && $# == 0 ]] || fail EMBEDDING_INSTALL_ROOT_REQUIRED
    fixed_parents
    [[ ! -e "$PREFIX" && ! -L "$PREFIX" ]] || fail EMBEDDING_RUNTIME_TARGET_EXISTS
    getent passwd eom >/dev/null || fail EMBEDDING_DEVELOPER_IDENTITY_MISSING
    install -d -o eom -g eom -m 0700 "$PREFIX"
    printf '%s\n' EMBEDDING_PREFIX_PREPARED_NO_RUNTIME_EXECUTION
    exit 0;;
  publish) ;;
  *) fail EMBEDDING_INSTALL_MODE_INVALID;;
esac

[[ "$EUID" == 0 && $# == 9 ]] || fail EMBEDDING_INSTALL_ARGUMENTS_INVALID
# All hashes are independently reviewed root-approval inputs, never inferred from source metadata.
RUNTIME_SHA=$1; HELPER_SHA=$2; WHEEL=$3; WHEEL_SHA=$4; MODEL_SOURCE=$5
PREPARE_SHA=$6; MAIN_SHA=$7; PROBE_SHA=$8; POLKIT_SHA=$9
for digest in "$RUNTIME_SHA" "$HELPER_SHA" "$WHEEL_SHA" "$PREPARE_SHA" "$MAIN_SHA" "$PROBE_SHA" "$POLKIT_SHA"; do
  hash_valid "$digest" || fail EMBEDDING_INSTALL_HASH_INVALID
done
fixed_parents
[[ -d "$PREFIX" && ! -L "$PREFIX" && "$(stat -c %u "$PREFIX")" == "$(id -u eom)" ]] || fail EMBEDDING_RUNTIME_INPUT_INVALID
[[ "$WHEEL" == /tmp/eom-*/*.whl || "$WHEEL" == /tmp/eom-*/*/*.whl ]] || fail EMBEDDING_PLATFORM_WHEEL_PATH_INVALID
[[ -f "$WHEEL" && ! -L "$WHEEL" ]] || fail EMBEDDING_PLATFORM_WHEEL_INVALID
# Existing terminal/uncertain identities are evidence; installation never resets/relaunches them.
[[ -z "$(systemctl list-units --all --no-legend 'eom-embedding-experiment@*.service' 'eom-embedding-experiment-prepare@*.service' 'eom-embedding-experiment-probe.service')" ]] || fail EMBEDDING_CPU_HISTORY_REQUIRES_REVIEW

QUARANTINE=$(mktemp -d /opt/eom/conda/envs/.embedding-runtime-XXXXXXXX)
chmod 0700 "$QUARANTINE"
PRIVATE=$(mktemp -d /opt/eom/.embedding-install-XXXXXXXX)
chmod 0700 "$PRIVATE"
record_phase() {
  INSTALL_PHASE=$1
  printf '%s\n' "$INSTALL_PHASE" >> "$PRIVATE/phase-receipt"
}
trap 'printf "%s\n" "EMBEDDING_INSTALL_STOPPED install_phase=$INSTALL_PHASE" >&2' ERR
record_phase QUARANTINE_COPY
# cp -a copies symbolic links themselves; never follows a source link. Disable link/owner preservation.
timeout --signal=KILL 900 cp -a --no-preserve=links,ownership,xattr,context -- "$PREFIX/." "$QUARANTINE/"
chown -hR root:root "$QUARANTINE"
[[ "$(tree_digest "$QUARANTINE")" == "$RUNTIME_SHA" ]] || fail EMBEDDING_RUNTIME_TREE_HASH_MISMATCH
# Before the first interpreter instruction, reject external links and special/suid/writable members.
while IFS= read -r -d '' member; do
  if [[ -L "$member" ]]; then
    target=$(realpath -e -- "$member")
    [[ "$target" == "$QUARANTINE/"* ]] || fail EMBEDDING_RUNTIME_LINK_ESCAPE
  else
    [[ -d "$member" || -f "$member" ]] || fail EMBEDDING_RUNTIME_MEMBER_INVALID
    (( (8#$(stat -c %a "$member") & 8#6022) == 0 )) || fail EMBEDDING_RUNTIME_MODE_INVALID
  fi
done < <(find -P "$QUARANTINE" -print0)
[[ -x "$QUARANTINE/bin/python" ]] || fail EMBEDDING_RUNTIME_INTERPRETER_MISSING
timeout --signal=KILL 30 install -m 0600 -- "$HELPER_SOURCE" "$PRIVATE/install.py"
timeout --signal=KILL 120 install -m 0600 -- "$WHEEL" "$PRIVATE/platform.whl"
[[ "$(sha256sum "$PRIVATE/install.py" | cut -c 1-64)" == "$HELPER_SHA" ]] || fail EMBEDDING_INSTALLER_HASH_MISMATCH
[[ "$(sha256sum "$PRIVATE/platform.whl" | cut -c 1-64)" == "$WHEEL_SHA" ]] || fail EMBEDDING_PLATFORM_WHEEL_HASH_MISMATCH
for pair in "eom-embedding-experiment-prepare@.service:$PREPARE_SHA" "eom-embedding-experiment@.service:$MAIN_SHA" "eom-embedding-experiment-probe.service:$PROBE_SHA"; do
  member=${pair%:*}; digest=${pair##*:}
  timeout --signal=KILL 30 install -m 0600 -- "$REPOSITORY/infra/systemd/$member" "$PRIVATE/$member"
  [[ "$(sha256sum "$PRIVATE/$member" | cut -c 1-64)" == "$digest" ]] || fail EMBEDDING_UNIT_HASH_MISMATCH
done
timeout --signal=KILL 30 install -m 0600 -- "$REPOSITORY/infra/polkit/50-eom-worker-units.rules" "$PRIVATE/polkit.rules"
[[ "$(sha256sum "$PRIVATE/polkit.rules" | cut -c 1-64)" == "$POLKIT_SHA" ]] || fail EMBEDDING_POLKIT_HASH_MISMATCH

getent group "$CPU_USER" >/dev/null || /usr/sbin/groupadd --system "$CPU_USER"
getent passwd "$CPU_USER" >/dev/null || /usr/sbin/useradd --system --gid "$CPU_USER" --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin "$CPU_USER"
[[ "$(id -gn "$CPU_USER")" == "$CPU_USER" && "$(id -nG "$CPU_USER")" == "$CPU_USER" ]] || fail EMBEDDING_CPU_IDENTITY_OVERPRIVILEGED
[[ "$(getent passwd "$CPU_USER" | cut -d: -f6-7)" == /nonexistent:/usr/sbin/nologin ]] || fail EMBEDDING_CPU_IDENTITY_INVALID
if [[ ! -e "$MODEL_STORE" && ! -L "$MODEL_STORE" ]]; then install -d -o root -g "$CPU_USER" -m 0750 "$MODEL_STORE"; fi
root_directory "$MODEL_STORE"
# Conda/ELF configuration can name the original prefix. Replace it BEFORE any interpreter
# instruction, so absolute-prefix loading cannot reach developer-writable bytes.
# The retained mutable backup is evidence only, never executed or treated as root-private.
BACKUP=/opt/eom/conda/envs/.embedding-prepublication-$(basename "$PRIVATE")
[[ ! -e "$BACKUP" && ! -L "$BACKUP" ]] || fail EMBEDDING_RUNTIME_BACKUP_EXISTS
mv -T -- "$PREFIX" "$BACKUP"
chmod 0700 "$BACKUP"
mv -T -- "$QUARANTINE" "$PREFIX"
chmod 0755 "$PREFIX"
record_phase STAGED_NOT_ACTIVATED
# -S avoids site startup while checking the independently approved fixed tree.
env -i PATH=/usr/bin:/bin TZ=UTC LANG=C.UTF-8 "$PREFIX/bin/python" -I -S -B "$PRIVATE/install.py" \
  --runtime "$PREFIX" --wheel "$PRIVATE/platform.whl" --wheel-sha256 "$WHEEL_SHA" \
  --model-source "$MODEL_SOURCE" --source-uid "$(id -u eom)" --cpu-gid "$(id -g "$CPU_USER")"
record_phase MODEL_AND_WHEEL_VERIFIED
for member in eom-embedding-experiment-prepare@.service eom-embedding-experiment@.service eom-embedding-experiment-probe.service; do
  install -o root -g root -m 0644 -- "$PRIVATE/$member" "/etc/systemd/system/$member"
done
install -o root -g root -m 0644 -- "$PRIVATE/polkit.rules" /etc/polkit-1/rules.d/50-eom-worker-units.rules
getent passwd "$OWNER_USER" >/dev/null || fail EMBEDDING_OWNER_IDENTITY_MISSING
OWNER_GID=$(id -g "$OWNER_USER")
for member in /run/eom-embedding-experiments; do
  if [[ ! -e "$member" && ! -L "$member" ]]; then install -d -o root -g "$OWNER_GID" -m 0750 "$member"; fi
  root_directory "$member"
  [[ "$(stat -c %g "$member")" == "$OWNER_GID" && "$(stat -c %a "$member")" == 750 ]] || fail EMBEDDING_HANDOFF_ROOT_INVALID
done
systemctl daemon-reload
record_phase INSTALLED_NOT_PROBED
printf '%s\n' EMBEDDING_RUNTIME_INSTALLED_PROBE_AND_INFERENCE_NOT_RUN "runtime_backup=$BACKUP" "installer_quarantine=$PRIVATE"
