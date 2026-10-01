# ADR 0166: Flow-to-HWPX pinned Item Revision handoff

## Status

Accepted for implementation on 2026-10-01.

## Context

Scientific Studio can already create an HWPX delivery from an exact registered Item Revision.
However, the Workflow view only copies the registration Revision ID into a separate HWPX form.
The user must discover the HWPX tab and reason about an internal identifier, and selecting another
non-terminal Workflow can leave the previous Revision in that form.  This is inconvenient and can
select stale work when several one-Item Workflows complete asynchronously.

The change must not make a generation Workflow own HWPX persistence, create one HWPX per Item in a
mock-exam cohort, or compete with the Assessment Assembly HWPX application.  A generation Workflow
and an HWPX build have separate lifecycle and idempotency boundaries.

## Decision

### Responsibility and boundary

The browser derives one transient delivery target from an already validated Workflow detail or Item
Preview projection.  A completed Workflow with an exact `item_registration` exposes an explicit
“HWPX 제작으로 계속” action in Flow.  The action selects the immutable `item_revision_id` and
navigates to the existing HWPX application screen.  It does not submit a build automatically.

The HWPX screen keeps the existing build command, eligibility resolver, idempotency, validation,
Artifact commit, download, and post-registration approval behavior.  Exact-ID entry remains an
administrator recovery tool under technical details instead of the primary user flow.

### Canonical source and pointer model

The canonical chain remains:

```text
Workflow detail.item_registration
  -> logical Item
  -> pinned immutable Item Revision
  -> existing HWPX build application
  -> immutable HWPX Artifact Revision/hash
```

The browser target is a small immutable value object containing source kind, Item ID when known,
the pinned Item Revision ID, and Workflow ID when known.  It is navigation state, not persisted
truth.  Loading a non-completed Workflow clears its Flow handoff.  Changing the selected Revision
clears any HWPX build selection for another Revision rather than silently reusing it.

### Access patterns and data structures

The dominant operation is one keyed Workflow detail lookup followed by constant-time extraction of
its registration pointer.  The browser stores one selected target, so selection and equality checks
are `O(1)` time and space.  No corpus scan, list deduplication, cache, table, index, migration, or new
wire schema is required.

### Single-Item and bulk production

This handoff is deliberately presentation-only for one registered Item Revision.  Concurrent
Workflows continue through the existing orchestrator queue/claim/lease boundaries and may each
expose their own terminal pointer.  The explicit user selection determines which one is handed to
the single-Item HWPX command.

Mock-exam production continues to pin ordered approved Item Revisions in an Assessment Assembly and
uses the existing Assembly HWPX command.  This change does not create 25 individual HWPX builds,
alter production checkpoints, or add an automatic per-Item subscriber.  A future delivery policy
may call the same application services, but must define its own typed successor contract rather than
turn this browser action into orchestration.

### Failure, retry, and rollback

Missing registration, non-terminal Workflow state, malformed Revision identity, or a mismatched
selected build fails closed in the browser and causes no server mutation.  Build submission retains
the existing server idempotency boundary.  Rollback removes the presentation handoff; registered
Items and HWPX builds remain unchanged.

## Alternatives rejected

1. **Automatically build HWPX when every Workflow completes.** This spends resources without an
   explicit delivery request and conflicts with Assembly-level production semantics.
2. **Add HWPX as another worker step.** HWPX is an application delivery from a canonical registered
   Revision, not worker-to-worker communication or a generation Artifact.
3. **Keep exact Item Revision ID as the primary UI.** This exposes internal identity and permits a
   stale target when users move among concurrent Workflows.
4. **Create a second Flow-specific HWPX API.** The existing application command already owns
   eligibility, idempotency, validation, and persistence; a parallel endpoint would duplicate the
   invariant.

## Required verification

- completed Workflow plus registration yields one immutable target;
- pending/failed/missing-registration Workflow yields no target;
- malformed Item Revision identity is rejected;
- Flow action selects the exact registration Revision and then opens HWPX;
- selecting another target clears a mismatched prior build selection;
- Item Preview uses the same target selector;
- direct ID recovery remains available only as a secondary technical control;
- frontend/backend route alignment and installed static-file inventory remain exact;
- no Workflow, HWPX, Item, mock-exam, schema, or database contract changes.
