# ADR 0099: Orchestrator-mediated bounded item rework

## Status

Accepted for successor-workflow implementation. Released workflow `1.11.0`, Content Pack
`1.17.0`, role results `@11.0`, and their immutable Artifacts remain unchanged.

## Responsibility and boundary

An independent review may identify a correctable item-quality problem without making the Workflow
or its evidence corrupt. The Workflow Runner owns the bounded state transition, while Catalog owns
resolution of the exact authoring/review Artifact revisions and deterministic classification of the
review finding. Workers never communicate directly. The Orchestrator remains the only component
that commits worker Artifacts to NAS; the Runner stores only a bounded typed rework decision in the
Workflow history and supplies exact Artifact pointers to the next authoring attempt.

The successor permits the initial authoring/review pair plus at most three review-driven authoring
rework cycles. Human approval remains mandatory after a clean review. Exhaustion does not publish,
fail, or silently approve the item; it opens the human gate with the exact history available for an
operator decision.

## Canonical source and revision model

The canonical inputs to one rework decision are:

- the immutable Workflow request and pinned Workflow definition;
- the exact authoring Artifact logical ID, revision ID, result schema, and content hash;
- the exact review Artifact logical ID, revision ID, result schema, and content hash; and
- the current Workflow rework-cycle count and definition-owned maximum.

`workflow-review-rework-directive/1.0` is a small self-hashed value object. It does not copy the
draft, review report, or finding messages. It separates verified repairable finding codes,
human-judgment codes, and disregarded false-positive codes. The next authoring materialization
resolves the pinned prior authoring/review revisions and renders their validated JSON only at the
prompt boundary. Superseded attempts and their Artifacts remain immutable append-only history.

## Finding taxonomy

Only verified content-quality findings may schedule authoring rework. Schema, permission, hash,
evidence-pointer, lifecycle, and Artifact-resolution failures remain hard pre-commit failures and
are never converted into model dialogue. Unknown blocking finding codes and findings that require
new evidence or human policy judgment go to the human gate.

Catalog independently rejects false positives before deciding. In particular, a standalone V4
Brief uses `material_requirement` as the authoritative student-visible form. A review finding that
requires `task_type == material_requirement.form` without a `mock_exam_slot` is disregarded when
the canonical draft already satisfies the material requirement. This prevents repeated generation
from trying to repair a conforming draft.

## Access patterns and data structures

The frequent operations are keyed step-attempt lookup, bounded code-set classification, ordered
attempt history, and exact pointer resolution. Finding codes use sets for O(1) membership and are
serialized as sorted unique tuples. Rework history is an append-only tuple bounded to four review
decisions (initial review plus three cycles). Step attempts use the existing indexed
`(workflow_id, step_key, attempt)` relation and immutable Artifact pointers.

With at most 20 findings and four review decisions, classification is O(F), pointer resolution is
O(1) per bounded pointer, and temporary space is O(F). No database migration, new queue, cache,
binary column, or unbounded JSON value is introduced.

The complete bounded history is validated whenever a decision is appended and whenever feedback is
materialized for another role. Observed cycle numbers must be contiguous from zero, decision hashes
and review revisions must be unique, review attempts must advance, and an unchanged authoring
attempt must retain the same immutable pointer. Validation is O(H), where `H <= 4`; a separate
mutable index or cached summary would add invalidation risk without improving this scale.

## Transaction, concurrency, retry, and idempotency

The review worker Artifact commits before classification. Under the existing fenced Workflow
command transaction, the Runner records the exact directive, supersedes active authoring/image/
review step attempts, creates exactly one successor authoring attempt, increments the Workflow
rework counter, and returns the stage to `AUTHORING`. The new authoring job idempotency key already
contains Workflow ID, step key, attempt, and definition hash.

A lost response replays the same review job and directive. Directive self-hash and source pointers
must match the previously recorded decision; a different revision or code set conflicts rather
than replacing history. The rework limit bounds feedback to three cycles, while the separate
ten-attempt step ceiling leaves room for proven pre-commit infrastructure retries without creating
additional review decisions. Command lease fencing and existing unique constraints continue to
serialize concurrent advancement.

Different Items have different Workflow IDs and therefore different command rows, step-attempt
keys, runtime histories, and job idempotency keys. Multiple Runners may advance different Items in
parallel through the shared indexed queue. They do not share a process-global feedback collection;
each exact directive and Artifact pointer pair remains scoped to the claimed Workflow transaction.

## Dependency direction and adapters

The Workflow Runner depends on a narrow Catalog application port returning the typed directive.
Catalog resolves and validates Artifacts through its existing Artifact adapter. Prompt rendering
materializes prior result JSON through the existing Content Pack boundary. Domain contracts do not
import SQLAlchemy, filesystem, HTTP, or NAS implementations.

## Failure and rollback

- A repairable verified finding with remaining capacity schedules authoring rework.
- No verified blocking finding opens normal human approval.
- An unknown or judgment-required finding opens human approval with a hold recommendation.
- Rework-limit exhaustion opens human approval and records the exhausted decision.
- Pointer, schema, hash, evidence, permission, or lifecycle failure remains fail-closed.

Rollback selects workflow `1.11.0` and Content Pack `1.17.0` for new requests. Existing successor
attempts, decisions, events, and Artifacts are not rewritten or deleted.

## Simpler alternative and why it is insufficient

Keeping the existing human `REQUEST_REWORK` command alone is insufficient: it stores a free-text
reason on the approval row but the replacement authoring worker does not receive the exact review
Artifact or prior draft. Prompt-only retry is also insufficient because false blockers and rework
limits would remain unenforced by the application. Direct author/reviewer chat is rejected because
it bypasses immutable pointers, validation, orchestration, and audit history.

## Verification

Tests cover JSON Schema 2020-12/Pydantic parity, self-hash and sorted-code invariants, false material
profile findings, repairable/human/unknown classification, exact prior pointers, three-cycle
exhaustion, append-only supersession, idempotent replay, concurrent command fencing, prompt
materialization, historical workflow/Pack byte immutability, and absence of large payloads in DB
rows.
