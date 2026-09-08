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
   adapter requires systemd `ActiveState=inactive`, `SubState=dead`, and
   `UnitFileState=masked-runtime`; execution re-observes it immediately before its write
   transaction. A read-only DB preflight first resolves all 25 Workflows and validates creator,
   production-occurrence, call, and start-command ownership; only then may the application ask the
   existing Codex capacity controller to reconcile expired leases whose `workflow_id` belongs to
   the proven cohort. That controller inspects each
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

## Deployment hold and safe sequence

The shared release installer normally restarts every platform consumer. For this exceptional
recovery, `--install-preserve-workflow-runner-inactive` first requires the runner to be inactive,
adds a runtime systemd mask, and verifies the mask before wheel replacement and after all other
consumer restarts. The mask is deliberately retained on failure and success.

Run the sequence without a runnable gap:

1. stop the Workflow runner and verify exact `inactive/dead/MainPID=0` state;
2. install with `scripts/api/deploy_release.sh --install-preserve-workflow-runner-inactive`;
3. run installed `eom-api mock-exam-production retire-items <execution-id>` with the owning fresh
   operator session; this first reconciles any expired exact-cohort lease through the capacity
   controller and retains the self-hashed 25-outcome receipt;
4. verify the receipt contains 24 `CANCEL_QUEUED` outcomes and the known failed Workflow as
   `UNSUCCESSFUL_TERMINAL_PRESERVED` (or the live state-equivalent exact totals);
5. unmask the runtime unit, start the Workflow runner, and verify every old active Workflow reaches
   `CANCELLED` before initializing the corrected production request;
6. run the normal release verifier only after the runner is active again.

Because all prior START/ADVANCE commands become `CANCELLED` in the same transaction that creates
the replacement cancel commands, the first runnable command for every nonterminal member is a
cancellation. No old authoring/review/image worker can be scheduled between installation and the
retirement fence.
