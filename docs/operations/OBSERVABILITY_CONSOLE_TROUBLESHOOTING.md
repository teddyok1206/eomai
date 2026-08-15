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

Confirm the deployment boundary before changing configuration:

```bash
/srv/eom/conda/envs/eom-observe/bin/python -c \
  'import eom_observe; print(eom_observe.__file__)'
systemctl show eom-observe.service --property=WorkingDirectory --value
scripts/observe/deploy_release.sh --verify
```

The import must be below `site-packages`, and the working directory must be
`/var/lib/eom-observe`. An import below `/home/eom/EOM`, an `__editable__` `.pth` or finder, or an
editable `direct_url.json` is a failed deployment. Rebuild from a clean committed revision and use
`deploy_release.sh --install`; do not add `PYTHONPATH` or relax source-tree isolation.

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
The Git checkout is also intentionally inaccessible. Static assets, schemas, and deployment metadata
must come from the installed wheel.

## Rollback After A Failed Upgrade

Deployment records and the prior unit copy are under `/var/lib/eom-observe/deployments/`. Restore only
a previously inspected wheel and its matching unit, then run `systemctl daemon-reload`, restart, and
execute `deploy_release.sh --verify`. Repository imports are not an acceptable emergency fallback.

## Removal

Stopping and disabling the service does not affect EOM runtime:

```bash
systemctl disable --now eom-observe.service
```

Remove runtime files only through a separately reviewed operations change. Do not remove PostgreSQL
platform tables or alter workflow services.
