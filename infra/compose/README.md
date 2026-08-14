# EOM Docker Compose

PostgreSQL runs only through Docker Compose. Do not install PostgreSQL as a host apt service.

## Image

- Image: `docker.io/library/postgres:18-bookworm`
- Digest: `sha256:7d2695c3aa88e792e8b3b233e7e4adb296a20412c6c0ca361e3edaaacfada108`
- Observed version annotation: `18.6-bookworm`
- Source: Docker Official Image `library/postgres`
- Variant: Debian bookworm

The tag is pinned with a digest in `compose.yml`; `latest` is not used for PostgreSQL.

## Secret File

Actual secrets live outside Git:

```bash
/etc/eom/secrets/postgres.env
```

Expected mode:

```text
owner root:eom
mode 0640
```

Do not print this file or commit it.

## Commands

```bash
docker compose --env-file /etc/eom/secrets/postgres.env -f /home/eom/EOM/infra/compose/compose.yml up -d
docker compose --env-file /etc/eom/secrets/postgres.env -f /home/eom/EOM/infra/compose/compose.yml ps
docker compose --env-file /etc/eom/secrets/postgres.env -f /home/eom/EOM/infra/compose/compose.yml logs --tail=100 eom-postgres
docker compose --env-file /etc/eom/secrets/postgres.env -f /home/eom/EOM/infra/compose/compose.yml down
```

Validate config without persisting output:

```bash
docker compose --env-file /etc/eom/secrets/postgres.env -f /home/eom/EOM/infra/compose/compose.yml config >/dev/null
```

## Port Binding

PostgreSQL binds to loopback only:

```text
127.0.0.1:5432:5432
```

It must not bind to `0.0.0.0` or IPv6 wildcard addresses.

## Storage

Primary data uses Docker named volume `eom_postgres_data`, backed by the Docker data root on local NVMe SSD. For PostgreSQL 18, the named volume is mounted at `/var/lib/postgresql` so the official image can keep major-version-specific data directories. Do not bind-mount NAS into PostgreSQL primary data paths. NAS is for backups and approved artifacts only.

Check the volume path:

```bash
docker volume inspect eom_postgres_data --format '{{ .Mountpoint }}'
findmnt -T "$(docker volume inspect eom_postgres_data --format '{{ .Mountpoint }}')"
```

## Backup and Restore Dry Run

```bash
/home/eom/EOM/scripts/infra/postgres_backup.sh
/home/eom/EOM/scripts/infra/postgres_restore_dry_run.sh /mnt/nas/eom/backups/postgresql/<backup-file>.dump
```

## Update and Rollback

To update PostgreSQL, inspect official image metadata, change both tag and digest in `compose.yml`, run restore dry-run on a fresh backup, then apply with a planned maintenance window.

Rollback uses the previous commit's Compose image digest and the preserved Docker named volume. Never delete `eom_postgres_data` until a backup and restore verification have succeeded.

Docker group is not granted to `eom` or worker users. Operations use root or explicit sudo because Docker socket access is effectively host-root access.
