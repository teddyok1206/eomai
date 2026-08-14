# Codex Account Login Checklist

Observed CLI help:

```text
codex login [OPTIONS] [COMMAND]
codex login status [OPTIONS]
codex login --device-auth
codex login --with-api-key
codex login --with-access-token
```

This bootstrap did not perform worker login. Do not copy root auth or another worker's auth.

## Rules

- Run login as the target worker user.
- Use that worker's HOME.
- Do not copy `/root/.codex`.
- Do not symlink auth files.
- Do not print tokens.
- Do not put tokens in shell history.
- Do not store account mapping in Git with secrets.

## Worker Login Commands

Run one account at a time:

```bash
sudo -u eom-cdx-01 -H /usr/local/bin/codex login --device-auth
sudo -u eom-cdx-02 -H /usr/local/bin/codex login --device-auth
sudo -u eom-cdx-03 -H /usr/local/bin/codex login --device-auth
sudo -u eom-cdx-04 -H /usr/local/bin/codex login --device-auth
sudo -u eom-cdx-05 -H /usr/local/bin/codex login --device-auth
```

If the CLI opens a browser or asks for MFA, complete the browser/MFA flow for that worker account only.

## Status Checks

```bash
sudo -u eom-cdx-01 -H /usr/local/bin/codex login status
sudo -u eom-cdx-02 -H /usr/local/bin/codex login status
sudo -u eom-cdx-03 -H /usr/local/bin/codex login status
sudo -u eom-cdx-04 -H /usr/local/bin/codex login status
sudo -u eom-cdx-05 -H /usr/local/bin/codex login status
```

Login status may fail before login. That is expected.

## Permission Checks After Login

For each worker:

```bash
stat -c '%n %U %G %a %F' /srv/eom/worker-homes/eom-cdx-01/.codex
find /srv/eom/worker-homes/eom-cdx-01/.codex -maxdepth 1 -printf '%f %M %u %g\n'
```

Expected:

- `.codex` owner is the worker user.
- auth files are not world-readable.
- no worker can read another worker HOME.

## Logout Procedure

Use the CLI logout command if available in the installed version. If no logout command exists, stop workers, archive no tokens, and remove only that worker user's auth files after operator approval. Do not touch other worker auth.

## Account Mapping Record

Record non-secret mapping in an operations-only document or database:

```text
slot 01 -> eom-cdx-01 -> account label, no token
slot 02 -> eom-cdx-02 -> account label, no token
slot 03 -> eom-cdx-03 -> account label, no token
slot 04 -> eom-cdx-04 -> account label, no token
slot 05 -> eom-cdx-05 -> account label, no token
```

## Failure Checks

- `HOME` must resolve to `/srv/eom/worker-homes/<worker>`.
- `/usr/local/bin/codex --version` must run for the worker.
- `/root/.codex` must not be readable by the worker.
- Worker must not have sudo.
- Worker must not have Docker socket access.
- Worker must not write NAS.
