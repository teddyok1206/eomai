# EOM Infrastructure Bootstrap Report

Generated at: `2026-08-14T04:27:16Z`

## 1. Executive Summary

Overall status: `PASS_WITH_MANUAL_ACTION`.

The new independent repository `/home/eom/EOM` was created on branch `chore/infra-bootstrap-v0`. Docker Engine and Docker Compose v2 were installed from the official Docker apt repository. PostgreSQL 18.6 runs through Compose, is healthy, binds only to `127.0.0.1:5432`, and stores primary data in Docker named volume `eom_postgres_data` on local ext4 SSD. Runtime directories, Conda environments, five worker users, worker HOME/workspace isolation, NAS smoke test, NAS artifact roots, backup, and restore dry-run were completed.

Manual action remains because the `eom` Git identity is not configured. Local Git commit was not created to avoid inventing identity.

## 2. 작업 범위

Completed infrastructure bootstrap only. No authoring, review, image generation, HWPX generation, orchestrator application, Slack integration, GitHub remote, Codex account login, or worker execution backend was implemented.

## 3. 기존 EOMIS 무변경 검증

Start baseline:

```text
status hash: 1d525ad0975924b57ca89bcd053698365e38e0f2f77c29521f7ee4d2580d949b
unstaged diff hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
staged diff hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

Start status was only:

```text
?? eom-infra-audit/
```

`check_repository_boundaries.sh /tmp/eom-bootstrap-20260814T041325Z` reported EOMIS status and diff matched baseline during validation. Final hash comparison:

```text
status hash: 1d525ad0975924b57ca89bcd053698365e38e0f2f77c29521f7ee4d2580d949b
unstaged diff hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
staged diff hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

Integrity result: `UNCHANGED`.

## 4. 신규 EOM Repository

- Path: `/home/eom/EOM`
- Owner: `eom:eom`
- Mode: `0750`
- Git root: `/home/eom/EOM`
- Branch: `chore/infra-bootstrap-v0`
- Remote: none
- Initial commit: pending Git identity
- Bootstrap commit: pending Git identity

## 5. 생성된 디렉터리

See `SYSTEM_CHANGE_LOG.md` for the full list. Local runtime paths are under `/srv/eom`, `/etc/eom`, and `/var/log/eom`. NAS persistent paths are under `/mnt/nas/eom`.

## 6. 설치된 Docker

| Item | Value |
| --- | --- |
| Docker Engine | Docker version 29.7.2, build a7dcaa6 |
| Docker Compose | Docker Compose version v5.4.0 |
| containerd | containerd v2.3.3 |
| Daemon | active, enabled |
| Storage driver | overlayfs |
| Data root | `/var/lib/docker` |
| Cgroup driver | systemd |
| Cgroup version | 2 |
| Logging driver | json-file |

Docker official apt repository was added using `/etc/apt/keyrings/docker.asc`.

## 7. PostgreSQL Compose

| Item | Value |
| --- | --- |
| Image | `docker.io/library/postgres:18-bookworm@sha256:7d2695c3aa88e792e8b3b233e7e4adb296a20412c6c0ca361e3edaaacfada108` |
| Observed version | PostgreSQL 18.6 |
| Container | `eom-postgres` |
| Health | healthy |
| Network | `eom_backend` |
| Bind | `127.0.0.1:5432` |
| Volume | `eom_postgres_data` |
| Volume path | `/var/lib/docker/volumes/eom_postgres_data/_data` |
| Volume filesystem | local ext4 on `/dev/mapper/ubuntu--vg-ubuntu--lv` |

The first PG18 attempt using `/var/lib/postgresql/data` failed because official PG18 images require the major-version directory layout. The newly created EOM-only failed container/volume was removed and Compose was corrected to mount the volume at `/var/lib/postgresql`.

## 8. PostgreSQL Role 구조

Observed roles:

```text
eom_admin|superuser=true|createdb=true|createrole=true|replication=true
eom_app|superuser=false|createdb=false|createrole=false|replication=false
```

Database owner:

```text
eom|eom_app
```

`eom_app` connection to database `eom` succeeded.

## 9. PostgreSQL Persistence 검증

Created `app.bootstrap_persistence_marker`, inserted one marker row, restarted only the PostgreSQL container, verified the marker row remained, then dropped the test table. Result: PASS.

## 10. Runtime Directory와 Permission

| Path | Owner | Mode |
| --- | --- | --- |
| `/srv/eom` | `root:eom` | `0711` |
| `/srv/eom/jobs` | `eom:eom` | `0750` |
| `/srv/eom/workspaces` | `root:root` | `0711` |
| `/srv/eom/cache` | `eom:eom` | `0750` |
| `/srv/eom/staging` | `eom:eom` | `0750` |
| `/srv/eom/state` | `eom:eom` | `0750` |
| `/srv/eom/backups` | `eom:eom` | `0750` |
| `/srv/eom/conda/envs` | `eom:eom` | `0755` |
| `/srv/eom/worker-homes` | `root:root` | `0711` |
| `/var/log/eom` | `eom:eom` | `0750` |
| `/etc/eom/secrets` | `root:eom` | `0750` |

`/srv/eom` uses `0711` to let workers traverse to their own directories without joining the `eom` group. Workers cannot list `/srv/eom`.

## 11. Conda Environment

| Environment | Python | pip | Owner | Mode |
| --- | --- | --- | --- | --- |
| `/srv/eom/conda/envs/eom-core` | 3.12.13 | 26.1.2 | `eom:eom` | `0775` |
| `/srv/eom/conda/envs/eom-hwpx` | 3.12.13 | 26.1.2 | `eom:eom` | `0775` |
| `/srv/eom/conda/envs/eom-image` | 3.11.15 | 26.1.2 | `eom:eom` | `0775` |

Existing Conda environments were not modified.

## 12. Worker Linux 사용자

Created users:

- `eom-cdx-01`
- `eom-cdx-02`
- `eom-cdx-03`
- `eom-cdx-04`
- `eom-cdx-05`

Each has a private primary group, locked password, HOME mode `0700`, `.codex` mode `0700`, and workspace mode `0770`.

## 13. Codex 격리 상태

`check_worker_isolation.sh` reported PASS for:

- own HOME isolation
- own workspace write
- `/root/.codex` unreadable
- no sudo
- no Docker socket write
- no NAS write
- Codex executable runs

Worker login status is currently not authenticated or unsupported, which is expected before manual login.

## 14. Root Codex Permission 보강

Before:

```text
/root/.codex root root 755 directory
/root/.codex/auth.json root root 600 regular file
```

After:

```text
/root/.codex root root 700 directory
/root/.codex/auth.json root root 600 regular file
```

Root `codex login status` succeeded after the permission change. Auth contents were not read.

## 15. NAS Smoke Test

Result: PASS. See `NAS_SMOKE_TEST_REPORT.md`.

Key values:

- write/read size: 64 MiB
- write throughput: about 106.51 MiB/s
- read throughput: about 106.42 MiB/s
- checksum: PASS
- rename: PASS
- lock: PASS
- cleanup: PASS

## 16. NAS 영구 저장 경로

Created or verified:

- `/mnt/nas/eom/artifacts`
- `/mnt/nas/eom/items`
- `/mnt/nas/eom/images`
- `/mnt/nas/eom/hwpx`
- `/mnt/nas/eom/manifests`
- `/mnt/nas/eom/backups`
- `/mnt/nas/eom/backups/postgresql`
- `/mnt/nas/eom/log-archive`

Workers cannot write these paths according to permission checks.

## 17. PostgreSQL Backup과 Restore Dry-Run

Backup: PASS

```text
/mnt/nas/eom/backups/postgresql/eom_20260814T042442Z_5d2ae8f6dde1.dump
/mnt/nas/eom/backups/postgresql/eom_20260814T042442Z_5d2ae8f6dde1.manifest.json
size_bytes=1028
sha256_prefix=5d2ae8f6dde1
```

Restore dry-run: PASS. Temporary database `eom_restore_20260814042443` was created, restored, queried, and removed. Production `eom` database was not overwritten.

## 18. 기존 8000 포트 서비스

Existing uvicorn service remained listening on `0.0.0.0:8000`. See `EXISTING_PORT_8000_SERVICE.md`. New EOM uses `127.0.0.1:8765` and did not alter the existing service.

## 19. systemd Unit 초안

Created repository-only examples:

- `infra/systemd/eom-worker@.service`
- `infra/systemd/eom-orchestrator.service.example`

No units were installed under `/etc/systemd/system`, enabled, or started.

## 20. 보안 검토

PASS:

- PostgreSQL loopback-only
- PostgreSQL data local, not NAS
- secret file outside Git
- workers have no sudo
- workers have no Docker socket write
- workers have no NAS write
- root Codex auth not copied
- no Git remote
- no push
- EOMIS unchanged

Warning:

- Docker installation created standard Docker networking and iptables integration.
- Docker hello-world default tag was used for the official install smoke test and immediately removed. PostgreSQL production Compose does not use `latest`.
- `/srv/eom` mode differs from initial recommendation for worker traversal, as documented above.
- `apt-get` reported existing packages not upgraded and a pending kernel notice through `needrestart`; no OS upgrade or reboot was performed.

## 21. 변경된 시스템 파일

- `/etc/apt/keyrings/docker.asc`
- `/etc/apt/sources.list.d/docker.list`
- `/etc/eom/secrets/postgres.env`
- `/root/.codex` mode
- `/srv/eom` tree
- `/var/log/eom`
- `/mnt/nas/eom` tree
- `/etc/passwd`, `/etc/group`, `/etc/shadow` via worker user creation

## 22. 설치된 패키지

See `SYSTEM_CHANGE_LOG.md`.

## 23. 실패 또는 미완료 항목

- Git commits are pending because `sudo -u eom -H git config --global user.name` and `user.email` returned no values.
- Worker Codex account login was intentionally not performed.
- Actual application code was intentionally not implemented.
- NVIDIA Container Toolkit was intentionally not installed.

Validation results:

- `doctor.sh`: PASS
- `check_worker_isolation.sh`: PASS
- `check_repository_boundaries.sh`: PASS
- `bash -n scripts/infra/*.sh infra/compose/initdb/001-create-app-role.sh`: PASS
- Docker Compose config: PASS
- Conda environment YAML dry-run as `eom`: PASS
- Secret scan: PASS
- Project ownership: PASS, no non-`eom` files under `/home/eom/EOM`
- Existing 8000 PID: unchanged at `3241999`
- Port 8765: unused

## 24. 수동으로 수행할 Codex 로그인

Follow `CODEX_ACCOUNT_LOGIN_CHECKLIST.md`.

## 25. Rollback 절차

See `docs/operations/INFRA_ROLLBACK.md`. Do not delete `/mnt/nas/eom` or `/var/lib/docker` wholesale.

## 26. 다음 구현 단계

1. JSON Schema protocol package
2. Pydantic protocol models
3. logical ID / revision ID / SHA-256 identifier package
4. PostgreSQL migration framework
5. job table
6. job event table
7. deterministic job state machine
8. worker slot registry
9. Codex one-shot subprocess adapter
10. result.json validation
11. artifact manifest
12. local staging service
13. NAS artifact commit service
14. eomctl system doctor
15. eomctl worker list
16. one placeholder job end-to-end test
