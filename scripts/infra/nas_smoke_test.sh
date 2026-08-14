#!/usr/bin/env bash
set -euo pipefail

TEST_ROOT="/mnt/nas/eom/_infra-test"
SIZE_MIB="${1:-64}"

usage() {
  cat <<'USAGE'
Usage: nas_smoke_test.sh [size_mib]

Runs a bounded NAS smoke test under /mnt/nas/eom/_infra-test.
Must be executed as user eom. Maximum size is 256 MiB.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "$(id -un)" != "eom" ]]; then
  echo "FAIL: run as user eom" >&2
  exit 2
fi

if ! [[ "$SIZE_MIB" =~ ^[0-9]+$ ]]; then
  echo "FAIL: size_mib must be an integer" >&2
  exit 2
fi

if (( SIZE_MIB < 1 || SIZE_MIB > 256 )); then
  echo "FAIL: size_mib must be between 1 and 256" >&2
  exit 2
fi

for cmd in findmnt realpath sha256sum dd flock stat date mkdir rm mv cmp sync awk; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "FAIL: missing command $cmd" >&2; exit 3; }
done

findmnt -T /mnt/nas >/dev/null 2>&1 || { echo "FAIL: /mnt/nas is not mounted" >&2; exit 4; }

if [[ -L /mnt/nas/eom ]]; then
  echo "FAIL: /mnt/nas/eom is a symlink" >&2
  exit 5
fi

mkdir -p "$TEST_ROOT"
ROOT_REAL="$(realpath -m "$TEST_ROOT")"
case "$ROOT_REAL" in
  /mnt/nas/eom/_infra-test) ;;
  *) echo "FAIL: invalid test root $ROOT_REAL" >&2; exit 6 ;;
esac

TS="$(date -u +%Y%m%dT%H%M%SZ)"
TEST_DIR="$TEST_ROOT/$TS-$$"
TEST_REAL="$(realpath -m "$TEST_DIR")"
case "$TEST_REAL" in
  /mnt/nas/eom/_infra-test/*) ;;
  *) echo "FAIL: invalid test path $TEST_REAL" >&2; exit 6 ;;
esac

cleanup() {
  if [[ -n "${TEST_REAL:-}" && "$TEST_REAL" == /mnt/nas/eom/_infra-test/* && -d "$TEST_REAL" ]]; then
    rm -rf -- "$TEST_REAL"
  fi
}
trap cleanup EXIT

mkdir "$TEST_REAL"
TEXT_FILE="$TEST_REAL/payload.txt"
printf 'eom nas smoke test %s\n' "$TS" > "$TEXT_FILE"
sha256sum "$TEXT_FILE" > "$TEST_REAL/payload.sha256"
sha256sum -c "$TEST_REAL/payload.sha256" >/dev/null
mv "$TEXT_FILE" "$TEST_REAL/payload.renamed.txt"

LOCK_OK=false
if flock -n "$TEST_REAL/test.lock" -c 'true'; then
  LOCK_OK=true
fi

WRITE_FILE="$TEST_REAL/blob.bin"
READ_FILE="$TEST_REAL/blob.read"
WRITE_LOG="$TEST_REAL/write.log"
READ_LOG="$TEST_REAL/read.log"

WRITE_START_NS="$(date +%s%N)"
dd if=/dev/zero of="$WRITE_FILE" bs=1M count="$SIZE_MIB" conv=fsync status=none 2>"$WRITE_LOG"
sync
WRITE_END_NS="$(date +%s%N)"
sha256sum "$WRITE_FILE" > "$TEST_REAL/blob.sha256"
READ_START_NS="$(date +%s%N)"
dd if="$WRITE_FILE" of="$READ_FILE" bs=1M status=none 2>"$READ_LOG"
READ_END_NS="$(date +%s%N)"
cmp "$WRITE_FILE" "$READ_FILE"

WRITE_BYTES=$(stat -c '%s' "$WRITE_FILE")
READ_BYTES=$(stat -c '%s' "$READ_FILE")

echo "PASS nas_smoke_test"
echo "timestamp_utc=$TS"
echo "test_path=$TEST_REAL"
echo "size_mib=$SIZE_MIB"
echo "write_bytes=$WRITE_BYTES"
echo "read_bytes=$READ_BYTES"
awk -v bytes="$WRITE_BYTES" -v start="$WRITE_START_NS" -v end="$WRITE_END_NS" 'BEGIN { sec=(end-start)/1000000000; if (sec <= 0) sec=0.001; printf "write_mib_per_sec=%.2f\n", bytes/1048576/sec }'
awk -v bytes="$READ_BYTES" -v start="$READ_START_NS" -v end="$READ_END_NS" 'BEGIN { sec=(end-start)/1000000000; if (sec <= 0) sec=0.001; printf "read_mib_per_sec=%.2f\n", bytes/1048576/sec }'
echo "checksum=pass"
echo "rename=pass"
echo "lock=$LOCK_OK"
echo "cleanup=scheduled"
