# Application API Troubleshooting

Start with sanitized checks that do not reveal secret values:

```bash
sudo -n systemd-run --quiet --wait --pipe --collect \
  --uid=eom-api --gid=eom-api \
  --property=EnvironmentFile=/etc/eom/secrets/api.env \
  --setenv=EOM_API_CONFIG=/etc/eom-api/api.yaml \
  /srv/eom/conda/envs/eom-api/bin/eom-api doctor
systemctl status eom-api.service --no-pager
journalctl -u eom-api.service --since '-10 minutes' --no-pager
scripts/api/smoke_test.sh --health-only
```

Do not paste the environment file, database URL, Authorization header, token, password, request
body, or full journal into a report. Structured logs contain request ID, operation ID, target,
outcome, status, duration, and stable error code; correlate with `X-Request-ID`.

`NOT_READY` usually means configuration validation, database connectivity, migration revision, or
built-in RBAC seed failed. Apply migrations using the migration owner, not `eom_api_runtime`. The
expected revision for V0 is `20260817_0006`. Re-run the runtime-role bootstrap only after confirming
the service user exists; repeat execution retains the runtime password and HMAC keys while removing
privilege drift. A missing-table grant after migration is a fail-closed signal to review the access
plan and rerun bootstrap, not a reason to grant all tables or default privileges.

For `AUTH_INVALID_CREDENTIALS`, do not try to distinguish unknown, disabled, locked, or incorrect
password from the response. Check sanitized audit state as an Administrator. Account lock expires
automatically; disabling an Operator and password changes revoke sessions by design.

For `AUTH_REFRESH_TOKEN_REUSED`, discard the entire local session family and perform a new login.
Concurrent refresh permits one winner and treats reuse of the consumed token as a security event.

For 428, repeat the mutation with the current response ETag. For 412, re-read the resource before
making a new decision. For 409 idempotency-in-progress, honor `Retry-After` and retry the identical
request and key. Never create a new key merely to bypass an uncertain command result.

If the process listens on `0.0.0.0:8765`, `[::]:8765`, port 8000, or port 8780, stop it and restore
the reviewed unit/configuration. Do not modify UFW, router forwarding, or the Observability service.
Use `sudo -n scripts/api/verify_runtime_isolation.sh` after every unit change.

Secret metadata failures belong to the privileged deployment verifier, not runtime doctor:

```bash
sudo -n /usr/local/libexec/eom-api/verify-deployment-metadata
```

The verifier must report only the failing path or invariant. Do not relax
`/etc/eom/secrets` from `root:eom:0750`, add `eom-api` to `eom`, or copy secrets into the state
directory to make the runtime doctor pass.

Never run API integration or concurrency tests against the deployed database. Use
`API_INTEGRATION_TEST_DATABASE.md`; the harness refuses production names and cleanup requires the
database owner plus database and role marker comments to match its manifest.

The default Infrastructure doctor reports restricted Docker socket visibility as
`WARN EXPECTED_LEAST_PRIVILEGE_WARNING` when its independent PostgreSQL application connection
succeeds. `RESULT pass_with_warnings` is the expected least-privilege classification, not a Docker
health assertion. A failed PostgreSQL connection or a failed privileged Docker inspection remains
`FAIL`. Use `scripts/infra/doctor.sh --privileged` only from an explicit root operator phase; the
normal doctor never probes sudo.
