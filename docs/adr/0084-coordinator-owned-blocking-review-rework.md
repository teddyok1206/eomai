# 0084. Let the production coordinator request bounded review rework

## Status

Accepted

## Responsibility and boundary

The mock-exam production coordinator owns every mutation of a Workflow that carries a production
occurrence. Public approval, rework, and cancellation routes remain forbidden for those Workflows.
When a trusted-RAG review reaches the human gate with actual blocking quality findings, the same
coordinator may request one ordinary Workflow rework to the released `authoring` target. It never
approves a blocked review and never weakens review, evidence, or registration validation.

This decision extends only the trusted-RAG review family used by
`generic-item-development@1.10.0`. Historical production contracts keep their fail-closed behavior.
The released Workflow definition remains authoritative for execution and enforces its three-cycle
limit. The coordinator mirrors that exact pinned limit only to stop submitting commands once the
released boundary is exhausted; a future Workflow version with a different limit requires an
explicit successor decision.

## Canonical source and pointers

The Workflow service is the canonical append-only history for rework commands, approval resolution,
superseded step attempts, and replacement attempts. The production checkpoint remains a small
reconciliation snapshot and does not copy a blocking review result or its findings. Before requesting
rework, the coordinator resolves and validates:

- the exact Workflow and monotonically observed resource version;
- its pinned generation resolution and knowledge provenance;
- the official Catalog review-eligibility observation;
- the pending approval request ID and approval resource version;
- the blocking review Artifact revision and trusted evidence-receipt pair; and
- the current Workflow rework-cycle count.

The command uses the existing typed `WorkflowActionRequest` and approval expectation. Its
idempotency key includes the Workflow/call identities, pending approval revision, blocking review
Artifact revision, and current rework cycle. A lost response therefore replays the same command;
a replacement review or approval necessarily produces a different key. No Artifact bytes, worker
result, finding text, or prompt is copied into the checkpoint.

## Access patterns and data structures

One observation pass keeps two sets keyed by `workflow_call_id`: approval-ready calls and
rework-ready calls. Membership and deduplication are `O(1)`. If any call needs rework, one second
ordered pass submits only those commands and no approvals. Otherwise, approval retains the existing
all-25 barrier. With fixed `n = 25`, time and temporary space are `O(n)` and plan order is stable.

The map from workflow-call ID to immutable plan call remains the authoritative lookup. No new table,
index, cache, binary column, or derived persistent value is introduced.

## Transactions, concurrency, retry, and failure

Workflow command enqueueing and Workflow engine execution keep their existing transaction
boundaries. Checkpoint compare-and-swap serializes coordinator observations. Successful enqueueing
returns the row to `WORKFLOW_ACTIVE`; subsequent passes observe `REWORK_REQUESTED`/`RUNNING`, the
new review, and eventually the same cohort-wide approval barrier. A crash before checkpoint commit
is safe because the same deterministic command key is replayed.

Only an exact trusted-RAG observation with `PENDING` approval and at least one blocking finding is
automatically reworked. Stale pointers, provenance or receipt failures, unavailable review evidence,
terminal Workflow failures, and eligibility inconsistencies remain fail-closed and are never turned
into rework. Exhausting three released cycles produces the stable non-retryable
`WORKFLOW_REWORK_LIMIT_EXHAUSTED` checkpoint failure for operator intervention.

## Dependency direction and rejected alternative

The application coordinator depends on the existing narrow Workflow operations port. Its concrete
adapter invokes the public command contract internally; it does not read Workflow tables or bypass
the engine. The Workflow engine continues to own target validation, authorization, superseding old
attempts, cycle increments, and append-only audit events.

Allowing the public rework endpoint for production occurrences was rejected because it would split
mutation authority and race the immutable production checkpoint. Automatically approving the row
was rejected because it defeats the quality gate. Abandoning all 25 Workflows for one correctable
formatting finding was also rejected because the existing bounded rework state machine already
preserves exact attempt history and safely repairs only the affected occurrence.
