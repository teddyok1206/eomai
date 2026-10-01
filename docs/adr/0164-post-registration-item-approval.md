# ADR 0164: Post-registration Item approval with review HWPX evidence

## Status

Accepted for implementation on 2026-10-01.

## Context

Released `generic-item-development` definitions place the human gate before the registration
worker.  Consequently no Item Revision exists while a reviewer is deciding, and the HWPX Manager
correctly refuses to build from anything other than a registered approved revision.  A reviewer
must therefore approve an intermediate worker result before seeing the registered Item and its
editable HWPX output.  The gate also prevents a multi-Item producer from observing creation as
complete until a human resolves every Workflow.

Changing the order in an existing definition, registering the revision as already approved, or
letting the HWPX Manager accept arbitrary draft content would break immutable history and collapse
production, review, and publication eligibility into one state.

## Decision

### Responsibility and boundary

A successor one-Item Workflow performs authoring, optional image work, automated review, and
registration, then completes without a Workflow human gate.  The registration application creates
one current immutable Item Revision in `IN_REVIEW`.  Human approval is a separate Item Registry
application command.  Released Workflow definitions and already registered revisions retain their
historical meaning.

Any number of these successor Workflows may run concurrently through the existing queue/claim
boundary; none waits for a human before registration and terminal completion.  Immutable mock-exam
production plans V1-V5 continue to pin their released Workflow families and are not silently
retargeted.  Moving the dedicated 25-Item coordinator to this lifecycle requires its own successor
plan/execution contract because its existing checkpoint model binds Workflow human approval before
registration.

The runner derives the post-review transition from the compiled successor step rather than a
Workflow version or step-name convention.  A review whose successor is the `item_management` agent
atomically enters Workflow/state stage `REGISTERING`; a review whose successor is a human gate keeps
the released pre-registration approval behavior.  This keeps the transition table truthful and
allows the registration terminal to enter `COMPLETED` without synthesizing a human decision.

The Application API accepts an approval only for an exact current `IN_REVIEW` revision and an exact
validated HWPX build.  It sends a typed command through the Catalog application boundary.  The
Application API owns the HWPX application-record lookup and binds its terminal `SUCCEEDED/PASS`
output pointers into that command.  The Catalog application owns the approval transaction and
independently revalidates the Item, manifest, output Artifact Revision, and content hash before
changing state.  Catalog deliberately does not import or query the HWPX infrastructure model.

### Canonical sources and revision model

The canonical content remains:

```text
logical Item -> immutable Item Revision -> component Artifact Revisions -> content hashes
```

Registration does not alter component bytes after review.  It creates an immutable Revision with a
V2 registration manifest declaring `IN_REVIEW` and post-registration human approval.  Approval
changes only lifecycle metadata on that exact Revision and appends an immutable typed approval
receipt to Item history.  It never rewrites the registration manifest or component Artifacts.

The approval receipt binds:

- Item and exact Item Revision plus registration-manifest Artifact Revision/hash;
- source Workflow and completed registration pointer;
- successful HWPX build and exact output Artifact Revision/hash;
- human operator, decision time, reason hash, and receipt self-hash.

`APPROVED`, `SUPERSEDED`, and `RETIRED` retain their existing publication semantics.  `IN_REVIEW`
is visible to authorized Item/Preview/HWPX-review queries but is excluded from Item Bank production,
Graph publication, assembly creation, and ordinary usage.

### Access patterns and data structures

Primary operations are indexed key lookup by Item Revision ID, HWPX build ID, Artifact Revision ID,
and Workflow ID; current-revision compare-and-swap; append-only Item-event insertion; and paginated
Item listing.  Existing primary keys, `item_revisions.revision_state`, current revision pointer,
HWPX history index, and append-only Item event sequence match these operations.  No new table or
large JSON/Binary value is required.

Approval resolution performs a constant number of indexed lookups, `O(1)` time and space with
respect to corpus size.  Item list queries join the current revision in one query rather than
issuing an approval lookup per row.  Approval projection is a frozen value derived from revision
state and the optional approval receipt; it is not a second mutable source of truth.

### Transaction and concurrency

The Catalog approval transaction locks the exact Item and Revision rows, checks the caller's
expected Revision resource version, confirms that the Revision is current and `IN_REVIEW`, and
revalidates the HWPX output Artifact pointers supplied by the API-owned build lookup.  It then
transitions the Revision to `APPROVED`, records
the actor/time, increments lock versions, and appends one `ITEM_REVISION_APPROVED` event containing
the typed receipt.  The Item remains `ACTIVE` and continues to point at the same Revision.

The command is idempotent by `(item_revision_id, approval idempotency key)` and canonical submission
hash.  A byte-identical replay returns the recorded receipt.  Reuse with another Revision, build,
actor, reason, or expected version fails closed.  Concurrent approval is serialized by row locks;
only one receipt can win.  HWPX build success is immutable and may precede approval.

### HWPX review eligibility

Ordinary HWPX publication still requires the current `APPROVED` Revision.  The single-Item review
build path additionally accepts the current `IN_REVIEW` Revision only when all of the following are
true:

- it was registered by the successor post-registration-review Workflow family;
- its registration manifest declares the same review policy and manifest hash;
- the source components and Artifact Revisions resolve exactly;
- the build request uses the authenticated Item-review application endpoint.

The Registry owns this eligibility decision.  Before the HWPX Manager accepts the `IN_REVIEW`
exception, the Registry safe-resolves the V2 manifest bytes and matches the exact Item/Revision,
revision number, Workflow definition, Content Pack release, metadata snapshot, and ordered component
pointers.  Approval repeats the same check and additionally safe-resolves the committed HWPX member
bytes.  The HWPX Manager does not reimplement Catalog persistence rules.

The output is a normal immutable HWPX Artifact.  Approval requires a terminal `SUCCEEDED` build with
validation `PASS`; requested, running, failed, stale, or differently pinned builds are rejected.

### Read contracts and UI

Core Item, Item Revision, Workflow-registration, and Preview projections expose an explicit approval
projection.  `IN_REVIEW` is presented as `PENDING`; `APPROVED` as `APPROVED`; rejected and historical
states remain distinct.  The UI enables human approval only after the selected registered Revision
has a validated HWPX build, and it links the exact build used by the decision.  Legacy Workflow
approval UI remains available only for legacy Workflows that still own a human gate.

For a human-reviewed `APPROVED`, `SUPERSEDED`, or `RETIRED` Revision, the projection is valid only
when the typed approval receipt is present and exactly matches the Revision, manifest, Workflow,
actor, time, and HWPX build.  `PENDING` carries no approval evidence.  Missing, malformed, duplicate,
or mismatched approval events fail the read projection instead of manufacturing a partial approval.

### Failure, retry, and rollback

Pointer absence, stale current Revision, hash mismatch, non-terminal HWPX, permission failure, or
version conflict returns a stable error and changes no Item state.  A failed approval is replayed
with the same idempotency key only after its outcome is known.  A rejected or abandoned review is
not reinterpreted as approval; successor content requires a new immutable Revision.

Rollout is additive: successor schemas, Workflow definition, Content Pack compatibility, API route,
and UI capability are deployed before activation.  Rollback stops selecting the successor; existing
`IN_REVIEW` revisions and HWPX outputs remain inspectable and are never mass-promoted or deleted.

## Alternatives considered

1. **Move the existing human gate after registration while keeping Workflow approval.** This keeps
   generation Workflows non-terminal and couples Item publication state to a runner command.  It
   also requires a distributed side effect between Workflow approval and Registry approval.
2. **Register as approved and add a display-only review flag.** This permits unreviewed content into
   Graph, assemblies, and usage and creates two contradictory approval sources.
3. **Build HWPX from worker workspace before registration.** This bypasses canonical Item pointers,
   repeats large files, and makes the reviewed document irreproducible.
4. **Add a new approval table immediately.** Existing Revision lifecycle fields and append-only Item
   events already support the required state and receipt.  A new aggregate would duplicate truth
   without a demonstrated access need.

## Required verification

- JSON Schema 2020-12 and Pydantic parity for the V2 registration manifest, approval command, and
  approval receipt, including canonical self-hash.
- Legacy registration still creates `APPROVED`; successor registration creates `IN_REVIEW`.
- Missing/stale Revision, wrong manifest, wrong Workflow, wrong HWPX build/output, failed build,
  permission failure, and hash mismatch all fail before mutation.
- Byte-identical replay returns one receipt; different-input replay and concurrent approval fail
  closed without duplicate events.
- `IN_REVIEW` remains absent from production candidates, Graph publication, assembly, and usage.
- Item list/detail/revision/Preview show the same approval status without N+1 queries.
- Review HWPX embeds package-internal media and passes existing renderer/output validation.
- Existing Workflow, Pack, manifest V1, approved Item, and HWPX contract bytes remain unchanged.
