# Creative cohort: three actual report-writing slots

Status: design for the user's current goal; NOT installed or accepted.
Date: 2026-10-30 UTC.

## Decision and existing boundary

The user requested three continuously productive solution-report slots, then the slot usage
refresh bug fix, then actual DB similarity integration and operating deployment. Three queued
jobs, an active service, or three available slot indicators do not satisfy the first condition.

The admitted creative cohort currently pins a slot05-only support pool. The fixed inventory
has only two default SUPPORT identities (05/06), and global Knowledge Analysis concurrency
is two. Raising only a runner loop setting cannot make three actual workers. The old bounded
parallel design deliberately reserved the other physical roles; do not silently change that
history or loosen its schema. This new user request needs an explicit successor.

## Canonical inputs, revisions and pointers

Retain the original immutable cohort and exact ordered source target-set hash. A successor
execution scope references the original cohort and its preceding continuation through
validated Artifact/member/revision/hash pointers, not a copied target list. It pins released
extraction and analysis presets, the new reviewed capacity revision, the exact workflow and
Pack, original operator, source commit and max-in-flight=3. Define additive JSON Schema
2020-12 and a frozen Pydantic model before implementing this execution scope.

Existing registered Items and accepted reports use their original lineage, analysis identity,
pinned plan and source authority. They are not resubmitted with a different preset to evade
idempotency validation. An interrupted existing Workflow remains its original request; use
the existing supported recovery boundary. Only a genuinely unsubmitted target uses the new
capacity/preset. Report warnings remain readable, not blockers to recording the source.

## Bounded scheduling and data structures

Use the existing creative execution application and one process fence for the original
cohort. A bounded three-entry window advances different source targets through the same
existing Workflow queue/command/Job/lease owners. A target-key map/set enforces membership
and deduplication; target order stays in the immutable cohort. The cursor/window is ephemeral
and reconstructed from validated canonical state on restart, never trusted from status JSON.
Per-tick scheduling is O(3); initial indexed source reconstruction is O(N), not pairwise scans.
Do not add another queue, DB tracker, model daemon, distributed scheduler or worker chat.

Independent workers may finish out of order. The single local driver invokes the existing
Graph publication owner serially; the corpus CAS/advisory lock remains the cross-owner guard.
Existing unique registration/analysis/Workflow keys and held-slot constraints remain the
race-safe boundaries. The embedding owner discovers committed publications asynchronously.

## Three physical workers without role or privilege bypass

Implement one explicit fixed-host capacity successor for this bounded purpose. Review a
purpose-limited SUPPORT grant on physical slot04 in addition to 05/06, retaining slot04's
default item-management identity and authentication. Do not rewrite WorkerSlotRecord.role,
copy auth, broaden Linux privileges or remove the old equality check globally. The exact
released capacity/pool/purpose must authorize the extra eligibility; all other requests retain
their original fixed-role rules. A fixed slot04 analysis unit may be required to match the
existing analysis timeout and sandbox; pin and verify its template like other fixed units.

The host Codex ceiling remains three and per-slot ceiling one across all policy revisions.
The new analysis ceiling is explicitly three for the successor, not a reinterpretation of old
policy bytes. Actual IAM, account assignment, model capability, quota, claim and lease checks
remain mandatory. Reuse existing queue priority so interactive work is not indefinitely
starved by new background claims. Existing jobs are not preempted or killed to free a slot.

## Ownership, validation and rollback

Catalog owns the cohort window and original source authorization. Orchestrator owns released
capacity/preset resolution, model invocation, claim/lease and unit lifecycle. Contracts/domain
do not import infrastructure. The protected release installs the exact compatible owner,
policy, runner and fixed unit at a lease-safe point; do not mutate a running GPU bundle.
No new DB table/index is expected: use existing indexed commands, target lookup, revision
records, publication and append-only history. Add a migration only if inspection proves a
missing persistent invariant, not for an ephemeral three-entry window.

Before activation test schema mirrors, immutable predecessor replay, exact source/preset
resolution, three distinct claims, cross-policy global ceiling, per-slot exclusivity,
interruption/retransmission, serial Graph CAS, and report/source hash preservation. Mutating
concurrency tests run only in a guarded disposable PostgreSQL database. Models and GPU are
opt-in. Operating acceptance requires actual three-slot claims on different admitted targets,
report completions, refill onto later targets and Graph progress, with no duplicate successor.

Stop on a real source/hash/permission mismatch without rewriting history. Rollback stops new
window submissions, waits for existing workers, and restores the preceding owner for future
work; canonical Items/reports/Graphs and failed history stay intact. An exact retry reuses the
same original request and identity. A new execution scope is not authorization to retry a
terminal failure under a different identity.

## Alternatives

Three separate cohort scanners would race and duplicate scheduling. Three processes in one
worker identity break isolation. Simply widening pool size cannot pass fixed-role eligibility
or the analysis ceiling. Rewriting all old cohort/preset pins breaks reproducibility. A seventh
new worker account adds provisioning/authentication without needing a new physical slot.
The bounded existing-owner continuation is the smallest change that can produce three actual
workers while retaining current source, queue, Graph and operating ownership.
