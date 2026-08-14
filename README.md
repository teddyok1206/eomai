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

This bootstrap phase establishes the infrastructure boundary only:

- Docker Engine and Docker Compose v2
- PostgreSQL via Docker Compose
- local Conda prefixes under `/srv/eom/conda/envs`
- isolated Codex worker Linux users
- local runtime directories
- NAS artifact and backup directories
- operational scripts and systemd unit drafts

The following are intentionally not implemented yet:

- actual science item authoring
- review prompts
- image generation
- HWPX generation
- orchestrator application logic
- PostgreSQL business schema
- Slack integration
- GitHub remote setup
- worker account login

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

## Security Boundary

Workers run as separate Linux users and use separate HOME directories. Workers do not receive sudo, Docker group access, or direct NAS write access. Generated HWPX, PNG, AI, PDF, backups, worker homes, workspaces, staging files, and secrets are not stored in Git.

Use UTC for system timestamps. Use Asia/Seoul only for user-facing display.

## Documentation

- Architecture decisions: `docs/adr/`
- Internal environment reports: `docs/internal/`
- Operations and rollback: `docs/operations/`
- Compose operations: `infra/compose/README.md`
