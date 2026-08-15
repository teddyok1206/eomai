#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Run as root.\n' >&2
  exit 1
fi

if ! getent passwd eom-hwpx >/dev/null; then
  useradd --system --home-dir /var/lib/eom-hwpx --create-home \
    --shell /usr/sbin/nologin eom-hwpx
fi
passwd -l eom-hwpx >/dev/null
install -d -o eom-hwpx -g eom-hwpx -m 0700 /var/lib/eom-hwpx
install -d -o root -g root -m 0755 /srv/eom/hwpx-workspaces

if id -nG eom-hwpx | tr ' ' '\n' | grep -Eq '^(sudo|docker|eom|eom-cdx)'; then
  printf 'eom-hwpx has a forbidden supplementary group.\n' >&2
  exit 1
fi
printf 'HWPX builder user boundary ready.\n'
