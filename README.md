# EOM

EOM is the new independent platform repository for producing Korean integrated science assessment items with local AI workers.

This repository is separate from `/home/eom/EOMIS`. Do not import, copy, or modify EOMIS files as part of this system. EOMIS remains a legacy project and an operational reference only.

## Paths

- Source repository: `/home/eom/EOM`
- Runtime data: `/srv/eom`
- System configuration: `/etc/eom`
- Short-term logs: `/var/log/eom`
- NAS artifact root: `/mnt/nas/eom`
- Reserved API bind: `127.0.0.1:8765`

## Current Phase

Platform skeleton v0 implements one executable vertical slice:

```text
eomctl job submit
  -> PostgreSQL job and deterministic events
  -> eom-cdx-01 one-shot codex exec
  -> schema-validated result.json
  -> canonical SHA-256 and artifact manifest
  -> local staging and immutable NAS revision
  -> PostgreSQL artifact history
```

Integrated-science domain behavior, review, image generation, HWPX, Slack, an API service, and a
GUI remain out of scope. The authoring worker only implements the
`EOM_PLATFORM_SMOKE_TEST` placeholder.

## Operating Commands

Use root or an approved operations account for Docker administration:

```bash
docker compose --env-file /etc/eom/secrets/postgres.env -f /home/eom/EOM/infra/compose/compose.yml ps
/home/eom/EOM/scripts/infra/doctor.sh
/home/eom/EOM/scripts/infra/check_worker_isolation.sh
```

Use explicit Conda prefixes:

```bash
/srv/eom/conda/envs/eom-core/bin/python --version
/srv/eom/conda/envs/eom-hwpx/bin/python --version
/srv/eom/conda/envs/eom-image/bin/python --version
```

Install this repository and its development checks only into `eom-core`:

```bash
/srv/eom/conda/envs/eom-core/bin/python -m pip install -e '.[dev]'
```

Apply the migration and run the control CLI:

```bash
/srv/eom/conda/envs/eom-core/bin/alembic upgrade head
/srv/eom/conda/envs/eom-core/bin/eomctl system doctor
/srv/eom/conda/envs/eom-core/bin/eomctl worker list
/srv/eom/conda/envs/eom-core/bin/eomctl job submit --message EOM_PLATFORM_SMOKE_TEST
/srv/eom/conda/envs/eom-core/bin/eomctl job inspect <JOB_ID>
/srv/eom/conda/envs/eom-core/bin/eomctl job events <JOB_ID>
```

`job submit` needs permission to create a transient systemd unit because that unit changes to the
isolated worker Linux user and makes `/mnt/nas` and the Docker socket inaccessible. Database
credentials are loaded from `EOM_DATABASE_URL` or `/etc/eom/secrets/postgres.env`; they are never
printed or logged.

## Security Boundary

Workers run as separate Linux users and use separate HOME directories. Workers do not receive sudo, Docker group access, or direct NAS write access. Generated HWPX, PNG, AI, PDF, backups, worker homes, workspaces, staging files, and secrets are not stored in Git.

Use UTC for system timestamps. Use Asia/Seoul only for user-facing display.

## Documentation

- Architecture decisions: `docs/adr/`
- Platform skeleton architecture: `docs/architecture/PLATFORM_SKELETON_V0.md`
- Live smoke test: `docs/operations/PLATFORM_SMOKE_TEST.md`
- Internal environment reports: `docs/internal/`
- Operations and rollback: `docs/operations/`
- Compose operations: `infra/compose/README.md`
