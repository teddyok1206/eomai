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
- Read-only observability bind: `127.0.0.1:8780`

## Current Phase

Platform Skeleton V0 remains available as one executable job slice:

```text
eomctl job submit
  -> PostgreSQL job and deterministic events
  -> eom-cdx-01 one-shot codex exec
  -> schema-validated result.json
  -> canonical SHA-256 and artifact manifest
  -> local staging and immutable NAS revision
  -> PostgreSQL artifact history
```

Workflow Engine V0 adds a domain-neutral, versioned multi-role path:

```text
request -> authoring -> image decision -> review -> human CLI gate
        -> approval or immutable rework attempts -> registration -> completed
```

All role results are strict placeholder JSON. There is no real domain content, generated image,
production HWPX, main GUI, or external LLM API. Slack is not a workflow feature;
`eom_dev_reporter` is a separate, best-effort developer milestone sender using only an Incoming
Webhook.

Observability Console V0 is a separate, replaceable read-only process at `/observe/`. It projects
existing PostgreSQL audit data through a versioned `/observe/api/v1/` contract and a shared SSE
poller. It cannot enqueue commands, mutate database rows, access NAS, inspect worker homes, or run
Codex. Stopping `eom-observe.service` has no effect on the platform or workflow runtime.

HWPX POC V0 is a separate reference-template-first pipeline. It validates bounded ZIP/XML input,
compiles template-hash-bound marker and object bindings, replaces placeholder text, a fixed table,
one PNG, and one observed equation source, then performs structural and semantic round-trip
validation. The isolated `eom-hwpx` builder is file-only; eom-core owns DB and artifact commit.
Synthetic fixtures are not Hancom compatibility evidence, and completion requires a manual Windows
Hancom open/edit/save gate.

Manual Content Intake V0 adds an artifact-backed boundary for files received from content leads.
Raw files, manual external analysis, and canonical Content Pack source are separate; deterministic
validation and a human decision are required before import. Content leads do not need Git, and the
server does not call ChatGPT or any external LLM API.

Content Pack V0 compiles accepted placeholder policy into a deterministic `.eompack`, commits one
canonical bundle artifact revision, and records immutable releases plus environment activation.
Prompt profiles use scalar dot-path substitution only; executable expressions are rejected.

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

Validate, import, and run the placeholder workflow:

```bash
/srv/eom/conda/envs/eom-core/bin/eomctl workflow definition validate config/workflows/generic-item-development.v1.yaml
/srv/eom/conda/envs/eom-core/bin/eomctl workflow definition import config/workflows/generic-item-development.v1.yaml
/srv/eom/conda/envs/eom-core/bin/eomctl workflow start --definition generic-item-development --version 1.0.0 --request-name PLACEHOLDER_REQUEST --image-mode skip --idempotency-key <KEY>
/srv/eom/conda/envs/eom-core/bin/eomctl workflow approve <WORKFLOW_ID> --actor-id reviewer_01
/srv/eom/conda/envs/eom-core/bin/eomctl workflow inspect <WORKFLOW_ID>
/srv/eom/conda/envs/eom-core/bin/eomctl workflow events <WORKFLOW_ID>
/srv/eom/conda/envs/eom-core/bin/eomctl workflow steps <WORKFLOW_ID>
```

The runner also exposes `run-once`, `serve`, and `reconcile` modes through
`/srv/eom/conda/envs/eom-core/bin/eom-workflow-runner`. CLI approval, rework, cancellation, and
reconciliation enqueue commands; only the deterministic engine changes workflow state.

Observability operations use their own Python 3.12 prefix and CLI:

```bash
/srv/eom/conda/envs/eom-observe/bin/eom-observe doctor
/srv/eom/conda/envs/eom-observe/bin/eom-observe snapshot
systemctl status eom-observe.service
```

Access remains loopback-only. Forward local port 8780 and open `http://127.0.0.1:8780/observe/`.
The one-time initial token file is `/home/eom/.eom-observe-initial-token`; its value is never logged
or stored in Git.

HWPX toolkit operations use their own Python 3.12 prefix. Until an approved reference is imported,
doctor reports `REFERENCE_TEMPLATE=PENDING_MANUAL_ACTION`:

```bash
/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx doctor
/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx inspect-package --input <HWPX> --output <REPORT>
/srv/eom/conda/envs/eom-core/bin/eomctl hwpx doctor
/home/eom/EOM/scripts/hwpx/deploy_builder.sh --verify
```

Manual Intake and Content Pack commands run in `eom-core`:

```bash
/srv/eom/conda/envs/eom-core/bin/eomctl content intake doctor
/srv/eom/conda/envs/eom-core/bin/eomctl content pack validate \
  content/packs/generic-placeholder/0.1.0
/srv/eom/conda/envs/eom-core/bin/eomctl content pack doctor
/srv/eom/conda/envs/eom-core/bin/eomctl content pack resolve \
  --pack-key generic-placeholder --environment development
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
- Workflow engine architecture: `docs/architecture/WORKFLOW_ENGINE_V0.md`
- Workflow live smoke test: `docs/operations/WORKFLOW_ENGINE_SMOKE_TEST.md`
- Development Slack reporting: `docs/operations/DEVELOPMENT_SLACK_REPORTING.md`
- Observability architecture: `docs/architecture/OBSERVABILITY_CONSOLE_V0.md`
- Observability setup: `docs/operations/OBSERVABILITY_CONSOLE_SETUP.md`
- Observability access: `docs/operations/OBSERVABILITY_CONSOLE_ACCESS.md`
- Internal environment reports: `docs/internal/`
- HWPX POC architecture: `docs/architecture/HWPX_POC_V0.md`
- HWPX reference creation: `docs/operations/HWPX_REFERENCE_TEMPLATE_CREATION.md`
- HWPX format references: `docs/references/HWPX_FORMAT_REFERENCES.md`
- Manual Intake architecture: `docs/architecture/MANUAL_CONTENT_INTAKE_V0.md`
- Content Pack architecture: `docs/architecture/CONTENT_PACK_V0.md`
- Content Pack authoring: `docs/operations/CONTENT_PACK_AUTHORING.md`
- Content Pack release: `docs/operations/CONTENT_PACK_RELEASE.md`
- Operations and rollback: `docs/operations/`
- Compose operations: `infra/compose/README.md`
