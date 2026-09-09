# Mock-exam production retirement v1

## Decision

Retire a superseded mock-exam production occurrence through one operator-authorized application
use case while the Workflow runner is held inactive. The use case prepares a typed CAS snapshot,
then atomically fences all older commands and cancellable platform jobs for the exact 25-Workflow
cohort. It queues the existing `CANCEL_WORKFLOW` command for every active Workflow and appends a
same-state retirement audit event for every member. It never executes a worker and never reads or
writes NAS.

The protocol is JSON Schema 2020-12
`mock-exam-production-retirement-v1.schema.json`, mirrored by frozen Pydantic command and receipt
models. The receipt remains pointer-only and can be replayed from Workflow audit events.
The canonical schema and packaged mirror are byte-identical and are admitted by the exact API-wheel
schema inventory. Retirement is intentionally an authenticated local operator CLI recovery action,
not a public HTTP action, so it adds no OpenAPI operation; public production Workflow mutations
remain blocked at the HTTP boundary.

## Required design procedure

1. **Responsibility and boundary.** The mock-exam application authorizes the owner and supplies its
   validated historical checkpoint. Retirement deliberately does not compare that old plan pointer
   with the newly released current plan; it revalidates the checkpoint's own revision/content hash
   instead. The Workflow-runner retirement application service owns the shared DB transaction and
   delegates platform-job transitions to the orchestrator-owned service. The Workflow runner later
   executes only the already-queued standard cancellations. Workers have no retirement behavior.
2. **Canonical source.** The immutable production checkpoint identifies the occurrence and exact
   cohort. Workflow rows, command history, step/job pointers, worker leases, and Workflow events are
   the canonical runtime state. The returned receipt is a projection of the appended audit events.
3. **Entity and revision model.** `production_request_id` and `execution_id` name logical
   occurrences. `execution_revision_id` and `checkpoint_sha256` pin the immutable checkpoint.
   `workflow_id`, its observed `lock_version`, and `workflow_call_id` remain separate.
4. **Pointers and resolution.** All 25 Workflow IDs and start-command IDs must exist. Each stored
   request must carry the expected production request and call IDs, and its creator must be the
   checkpoint operator. Every step-to-job edge resolves a typed `RoleWorkerInput` whose job,
   Workflow, step-run, attempt, role, protocol, artifact, revision, task type, and canonical request
   hash match both endpoint rows. Missing, stale, completed, foreign, or malformed targets fail
   explicitly before any affected Job transition.
5. **Access patterns.** Operations are 25 keyed Workflow lookups, bounded adjacency queries for
   commands/events/steps, membership checks, and deterministic ordered result assembly. Maps and
   sets provide O(1) membership after indexed DB reads; no item content or binary is loaded.
6. **Structures and indexes.** Workflow primary keys, command/event `workflow_id` indexes, step
   `workflow_id` and `platform_job_id` indexes, job primary keys, and worker-lease `workflow_id`
   indexes serve the bounded queries. Ordered tuples preserve positions 1–25; maps validate exact
   membership and sets reject duplicates.
7. **Scale and complexity.** The cohort is fixed at 25. Reads, validation, and writes are O(25 + C +
   J), where C and J are commands and jobs adjacent to those Workflows. Space is O(25 + C + J).
8. **Transaction and concurrency.** Before any DB session is opened, a read-only infrastructure
   adapter requires systemd `loaded/inactive/dead/MainPID=0`, an empty systemd job, the exact local
   base fragment, `UnitFileState=enabled`, and the exact root-owned persistent hold drop-in by path,
   mode, SHA-256, loaded drop-in set, `RefuseManualStart=yes`, and `NeedDaemonReload=no`. Execution
   re-observes it immediately before its write transaction. A read-only DB preflight first resolves
   all 25 Workflows and validates creator, production-occurrence, call, and start-command ownership;
   only then may the application ask the existing Codex capacity controller to reconcile expired
   leases whose `workflow_id` belongs to the proven cohort. That controller inspects each
   exact fixed worker unit and appends `ACTIVE -> RECONCILING -> EXPIRED` only for proven `ABSENT`;
   `RUNNING`, `UNKNOWN`, and unexpired leases remain held and block retirement. Preparation then
   observes exact Workflow resource versions. Execution locks Workflows in ID order and requires
   exact version/state matches. The single retirement DB transaction locks and terminalizes older
   commands/jobs before inserting cancellations and audit events. Unexpired command leases, held
   worker leases, or jobs at validation/commit fail closed.
9. **Dependency direction.** CLI calls application, application calls the runner facade, and the
   runner facade calls the Workflow-runner retirement service. That service owns Workflow command
   and event transitions and delegates job/lease rules to the orchestrator application service;
   neither the CLI nor the generic mock-exam application mutates their tables. Contracts contain
   only identifiers, versions, states, timestamps, and hashes. Domain workers and Catalog remain
   uninvolved.
10. **Failure, retry, and idempotency.** Any first-pass error rolls back the whole cohort. A
    deterministic retirement ID and per-call command idempotency keys prevent duplicate action.
    Exactly 25 matching audit events reconstruct the same self-hashed receipt and re-resolve every
    exact cancellation and typed step/job provenance edge; partial, conflicting, or tampered audit
    evidence is an explicit error. Expired-lease reconciliation is itself idempotent: a proven
    absent process reaches terminal `EXPIRED`, while a still-running or unknown process remains
    `RECONCILING` for another exact observation. Existing rows and artifacts are never deleted.
11. **Simpler alternative.** Enqueuing 25 ordinary cancellations independently is insufficient:
    older START commands win FIFO ordering, a mid-loop failure leaves a partially retired cohort,
    and stale processing commands/jobs can resume. Direct DB updates would bypass state machines and
    erase application-level ownership, CAS, and audit guarantees.

## Runtime database privilege boundary

The installed local retirement command connects as `eom_api_runtime`, so its cross-service write
surface is part of the reviewed design rather than an incidental deployment grant. This amendment
applies the required design procedure specifically to that privilege boundary:

1. **Responsibility and boundary.** Only the authenticated local Application API retirement use case
   invokes these existing orchestrator and Workflow-runner application services; no HTTP route
   exposes it, and application authorization limits invocation. Workers, direct SQL recovery, NAS
   access, and general orchestration remain outside the use case.
2. **Canonical source.** `eom_api.runtime_privileges` is the canonical required-grant matrix;
   `bootstrap_runtime_role.sh` first revokes drift, then reconstructs and verifies that matrix.
3. **Entity and revision model.** The change adds no entity or revision. Identity, request,
   provenance, revision, and hash columns remain outside every new UPDATE grant.
4. **Pointers and resolution.** Existing Workflow, step-run, Job, lease, command, and event pointer
   validation runs before a transition. Column grants cannot rewrite any of those pointers.
5. **Access patterns.** Retirement performs bounded indexed reads, append-only event insertion, and
   row-locked state transitions for the exact 25-member cohort. Event sequence allocation requires
   read access to existing Job and lease events.
6. **Structures and indexes.** Ordered immutable tuples define the allowed table and column sets.
   Existing primary-key, foreign-key, Workflow adjacency, and lease indexes serve the operation; no
   schema or index change is required.
7. **Scale and complexity.** Runtime work remains O(25 + C + J + L) with bounded adjacent commands,
   Jobs, and leases. Deployment reconciliation scans schema metadata once; its cost is proportional
   to the table/column catalog, not production row count.
8. **Transaction and concurrency.** PostgreSQL row locks require UPDATE authority. It is granted
   only on `jobs(completed_at,status,updated_at)`,
   `worker_leases(release_reason,released_at,state)`, and
   `workflow_commands(processed_at,state)`. The owning Workflow rows retain their pre-existing
   table UPDATE grant. Step-to-Job edges remain SELECT-only: the verified persistent runner hold,
   owning Workflow locks, and no-held-lease check freeze their sole valid writer, so
   `workflow_step_runs` does not need `FOR UPDATE` or UPDATE privilege.
9. **Dependency direction.** The API infrastructure matrix and privileged bootstrap express the DB
   adapter boundary. Retirement still delegates lease and Job rules to orchestrator services and
   Workflow command/event rules to the Workflow-runner service; no domain layer imports API or SQL
   infrastructure.
10. **Failure, retry, and idempotency.** Missing scoped columns or accidental table-wide UPDATE make
    readiness fail. Bootstrap is revoke-then-grant idempotent and verifies effective privileges per
    table and column. Any runtime denial rolls back the enclosing transition; deterministic command
    and retirement identities make the retry safe.
11. **Simpler alternative and trade-off.** Table-wide UPDATE on Jobs, leases, commands, events, or
    step runs is operationally simpler but permits unrelated provenance/history mutation and is
    rejected. A permanent second DB role would add credential and deployment surfaces for one
    tightly bounded local use case without narrowing the three required state transitions further.

The resulting event permissions are deliberately append-only:

| Table | SELECT | INSERT | UPDATE | Retirement reason |
| --- | --- | --- | --- | --- |
| `job_events` | yes | yes | none | allocate the next sequence and append Job cancellation |
| `worker_lease_events` | yes | yes | none | inspect and append lease reconciliation history |
| `jobs` | yes | none | three columns above | lock and terminalize cancellable Jobs |
| `worker_leases` | yes | none | three columns above | lock and reconcile only expired cohort leases |
| `workflow_commands` | yes | yes | two columns above | fence old commands and enqueue cancellation |
| `workflow_events` | yes | yes | none | append the complete retirement audit payload once |
| `workflow_step_runs` | yes | none | none | validate the pinned step-to-Job edge |

`workflow_instances` continues to use its already-reviewed table UPDATE grant because ordinary API
Workflow actions also lock and advance its resource version. The retirement audit now calculates
that next locked version before insertion, so it never updates an event after append.

## Deployment hold and safe sequence

The shared release installer normally restarts every platform consumer. For this exceptional
recovery, `--install-preserve-workflow-runner-inactive` first requires the runner to be inactive,
installs the persistent systemd drop-in, and verifies its exact identity before wheel replacement
and after all other consumer restarts. The hold is deliberately retained on failure and success.

Run the sequence without a runnable gap:

1. stop the Workflow runner and verify exact `inactive/dead/MainPID=0` state;
2. install with `scripts/api/deploy_release.sh --install-preserve-workflow-runner-inactive`;
3. run the installed `eom-api mock-exam-production retire-items <execution-id>` as the `eom-api`
   service identity, using its fresh owning operator token and canonical checkpoint root; atomically
   publish the successful stdout envelope to the fixed eom-api-owned mode-0600 receipt path;
4. independently review the immutable execution/revision/checkpoint/request/plan/operator pins and
   verify all 25 outcomes use the disposition derived from their command-hashed prior Workflow
   states: active states are `CANCEL_QUEUED`, while `FAILED` or `CANCELLED` states are
   `UNSUCCESSFUL_TERMINAL_PRESERVED`; do not supply or assume a fixed aggregate;
5. run the fully pinned `scripts/api/deploy_release.sh --release-workflow-runner-hold RECEIPT_FILE
   EXECUTION_ID EXECUTION_REVISION_ID CHECKPOINT_SHA256 PRODUCTION_REQUEST_ID PRODUCTION_PLAN_ID
   PRODUCTION_PLAN_SHA256 OPERATOR_ID RECEIPT_SHA256` action documented in the privileged deployment
   runbook; then explicitly enable and start the Workflow runner and verify every old active
   Workflow reaches `CANCELLED` before initializing the corrected production request;
6. run the normal release verifier only after the runner is active again.

Because all prior START/ADVANCE commands become `CANCELLED` in the same transaction that creates
the replacement cancel commands, the first runnable command for every nonterminal member is a
cancellation. No old authoring/review/image worker can be scheduled between installation and the
retirement fence.
