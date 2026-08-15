# Observability Console Troubleshooting

## Health And Doctor

```bash
curl --fail http://127.0.0.1:8780/observe/api/v1/health/live
/srv/eom/conda/envs/eom-observe/bin/eom-observe doctor
/srv/eom/conda/envs/eom-observe/bin/eom-observe verify-readonly
```

Live health is intentionally minimal and public. Ready health, snapshot, details, and SSE require a
valid session cookie.

## Service Does Not Start

Check `systemctl status eom-observe.service` and recent, bounded service logs. Common causes are
unreadable config/secret files, a missing observer prefix, port 8780 already in use, or an invalid
database URL. Never print the environment file while diagnosing.

## Stale Or Degraded

`STALE` means the last PostgreSQL query failed and the last good snapshot remains visible. Verify the
loopback database, role default read-only setting, grants, and 1500 ms query timeout. Recovery is
automatic and produces a `recovered` SSE event.

## Stream Reconnects

The browser reconnects automatically. Each connection receives a full snapshot. Five clients are
allowed; additional clients receive a bounded error. Slow clients retain only the newest snapshot.

## Access Denied By Sandbox

NAS, Docker, worker homes, root Codex auth, and the platform PostgreSQL secret are deliberately
inaccessible. Do not weaken the unit to troubleshoot them because the observer never needs those paths.

## Removal

Stopping and disabling the service does not affect EOM runtime:

```bash
systemctl disable --now eom-observe.service
```

Remove runtime files only through a separately reviewed operations change. Do not remove PostgreSQL
platform tables or alter workflow services.
