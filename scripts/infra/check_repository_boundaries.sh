#!/usr/bin/env bash
set -euo pipefail

EOM_ROOT="/home/eom/EOM"
EOMIS_ROOT="/home/eom/EOMIS"
BASELINE_DIR="${1:-}"
FAIL=0

emit() {
  local status="$1"
  local message="$2"
  printf '%s %s\n' "$status" "$message"
  [[ "$status" != "FAIL" ]] || FAIL=1
}

[[ "$(git -C "$EOM_ROOT" rev-parse --show-toplevel 2>/dev/null)" == "$EOM_ROOT" ]] && emit PASS "new Git root is $EOM_ROOT" || emit FAIL "new Git root mismatch"
[[ "$(git -C "$EOMIS_ROOT" rev-parse --show-toplevel 2>/dev/null)" == "$EOMIS_ROOT" ]] && emit PASS "legacy Git root is $EOMIS_ROOT" || emit FAIL "legacy Git root mismatch"
[[ "$(readlink -f "$EOM_ROOT/.git")" != "$(readlink -f "$EOMIS_ROOT/.git")" ]] && emit PASS "Git directories are independent" || emit FAIL "Git directories are shared"

if find "$EOM_ROOT" -xdev -type l -lname '/home/eom/EOMIS*' -print -quit | grep -q .; then
  emit FAIL "EOM contains symlink to EOMIS"
else
  emit PASS "no EOMIS symlink found"
fi

if find "$EOM_ROOT" -xdev -path '*/eom-infra-audit/*' -print -quit | grep -q .; then
  emit FAIL "raw audit directory copied into EOM"
else
  emit PASS "raw audit directory not copied"
fi

if find "$EOM_ROOT" -xdev \( -name auth.json -o -name '.env' -o -path '*/secrets/*' -o -path '*/postgres-data/*' -o -path '*/worker-homes/*' \) -print -quit | grep -q .; then
  emit FAIL "forbidden runtime/secret path found in repo"
else
  emit PASS "no forbidden runtime/secret path found"
fi

if git -C "$EOM_ROOT" grep -I -n -E 'BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|eom_(at|rt)_[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|xox[baprs]-' -- . >/dev/null 2>&1; then
  emit FAIL "secret-like content found in tracked files"
else
  emit PASS "no tracked secret-like content found"
fi

if [[ -n "$BASELINE_DIR" && -d "$BASELINE_DIR" ]]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  git -C "$EOMIS_ROOT" status --porcelain=v1 > "$tmp/status"
  git -C "$EOMIS_ROOT" diff --binary > "$tmp/diff"
  git -C "$EOMIS_ROOT" diff --cached --binary > "$tmp/diff.cached"
  if cmp -s "$BASELINE_DIR/eomis.status.before" "$tmp/status" && cmp -s "$BASELINE_DIR/eomis.diff.before" "$tmp/diff" && cmp -s "$BASELINE_DIR/eomis.diff.cached.before" "$tmp/diff.cached"; then
    emit PASS "EOMIS status and diff match baseline"
  else
    emit FAIL "EOMIS status or diff changed from baseline"
  fi
else
  emit WARN "baseline directory not supplied"
fi

exit "$FAIL"
