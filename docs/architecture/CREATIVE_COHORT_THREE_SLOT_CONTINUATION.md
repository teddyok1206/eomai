# Creative cohort: three actual report-writing slots

Status: capacity, continuation and bounded driver source verified; three-slot operating activation pending.
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
Pack, original operator and source commit. Bound the pipeline to six source states: three
report workers plus at most three sources in one Graph publication batch. Define additive JSON Schema
2020-12 and a frozen Pydantic model before implementing this execution scope.

Existing registered Items and accepted reports use their original lineage, analysis identity,
pinned plan and source authority. They are not resubmitted with a different preset to evade
idempotency validation. An interrupted existing Workflow remains its original request; use
the existing supported recovery boundary. Only a genuinely unsubmitted target uses the new
capacity/preset. Report warnings remain readable, not blockers to recording the source.

## Bounded scheduling and data structures

Use the existing creative execution application and one process fence for the original
cohort. A bounded six-entry window advances different source targets through the same
existing Workflow queue/command/Job/lease owners. A target-key map/set enforces membership
and deduplication; target order stays in the immutable cohort. The cursor/window is ephemeral
and reconstructed from validated canonical state on restart, never trusted from status JSON.
Per-tick scheduling is O(6); initial indexed source reconstruction is O(N), not pairwise scans.
Do not add another queue, DB tracker, model daemon, distributed scheduler or worker chat.

Independent workers may finish out of order. The single local driver invokes the existing
Graph publication owner serially in batches of at most three. A single bounded background
publication future lets other report jobs proceed; it is not another queue or source of
completion authority. The corpus CAS/advisory lock remains the cross-owner guard.
Existing unique registration/analysis/Workflow keys and held-slot constraints remain the
race-safe boundaries. The embedding owner discovers committed publications asynchronously.

## Three physical workers without role or privilege bypass

Implement one explicit capacity successor for this bounded purpose, under a separate logical
capacity key so the current `fixed-host` policy pointer remains unchanged. Review a
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
missing persistent invariant, not for an ephemeral source window.

Extraction keeps Workflow 2.0.0, role/result 1.34/2.0, resolved plan 28 and the exact
instruction bundle. Graph analysis also keeps its existing released task/plan family.
Both use the existing `support` pool name under a **separate**, purpose-limited capacity
revision. The draft capacity 1.4 candidate originally used a new pool name; inspection
proved that would unnecessarily require two additional plan families with identical task
semantics. No capacity 1.4 has been operating-activated, so the candidate was simplified
before release; original released 1.0–1.3 bytes/meaning remain unchanged.
The fixed profile maps the explicit parallel preset key to the same source task, not an
arbitrary caller-selected pool or preset. Existing
predecessor Workflows are found first by their original indexed idempotency keys and retain
their original execution plan. New targets alone use the separate parallel presets.

Inspection found that the existing DB CHECK caps Knowledge Analysis at two, and Orchestrator
correctly classifies both EXTERNAL_ITEM_LEARNING and knowledge analysis as that workload.
Migration `0064` therefore admits a ceiling of three only for explicit capacity schema `1.4`;
old schema rows retain their original upper bound. It adds no table, queue, role column or
index. Downgrade refuses once three-report capacity history exists. The protected release
operator needs an additive exact `0064` context/callback, not a direct production SQL change.

The new schema carries an explicit immutable `slot04/item_management → support` delegation,
limited to the `support` pool of this exact purpose/capacity. The same mapping owns prepublication model options
and actual lease eligibility. SQL eligibility additionally excludes a tampered slot04 default
role. Existing host advisory lock and held-slot unique constraint remain authoritative.

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

## Capacity component source checkpoint

New capacity, exact role-purpose delegation, old control contracts, fixed unit, polkit
allow/deny cases and release context/callback tests: 268 PASS (overlapping groups, not summed
with earlier checks). Guarded disposable PostgreSQL: 15 PASS covering actual three distinct
claims, same-request concurrent replay, original role preservation/tamper rejection, shared
host ceiling with old policies, old knowledge/GPU limits, downgrade history protection and
the changed capacity table metadata. Empty-state 0064 upgrade/downgrade/re-upgrade also PASS.
Ten affected core modules passed mypy; affected Ruff/format and shell syntax checks PASS.

The separate complete metadata audit still reports 14 pre-existing differences; these were
confirmed identical against the unchanged installed 54b39f7f baseline. Its assertion was not
weakened. See the operating record. No capacity policy, migration, worker template or new
three-slot execution scope has been activated in production at this checkpoint.

## Source pipeline checkpoint, 19:13 UTC

The continuation reader/admission, bounded source window, serial Graph batches and exact
predecessor reuse are now implemented. Source/analysis presets clone the original released
instructions, models, reasoning and isolation; only separate logical preset/capacity
identities change. Existing registered reports/analyses select their original source plan,
not the new capacity. An explicit failed-source recovery also retains its original purpose.

Related source tests (old families, new continuation/window/history, capacity and operator):
688 PASS. A fresh disposable PostgreSQL database at head 0064: 24 PASS covering actual
control Artifact/lifecycle publication and concurrent replay, source preparation/command
creation/recovery, three distinct physical claims and shared capacity limits. Fifteen core
modules passed mypy; affected Ruff/format and shell syntax checks PASS. These remain source
and disposable evidence, not three live worker completions.

Concurrent control release initially exposed an advisory/FK lock inversion. The candidate
now acquires the lifecycle fence before evaluation insertion; the real concurrency test
passes without catch-and-retry or history edits. A separate fixture failed to find a
definition already imported under its real ID; it now uses the existing unique family /
version index and asserts the same canonical definition. Initial failure logs are retained.

Candidate capacity schema 1.4 SHA is
`sha256:e739d0d4085146919a4dc6eea678b4e6e06ec801cebcfd0796fc2793e530eb04`.
The earlier unactivated candidate pool name was simplified before operating release; no
new resolved plan 29 or another analysis plan family is introduced. Both root launcher and
developer boundary now test exact parity with the closed 0064 callback enum.

## Restart scheduling: unfinished sources first, not historical re-verification first

Operating evidence showed the new owner spending minutes materializing already-published
reports while no fresh worker could start (only nine historical sources checked after
roughly two minutes). Full-cohort scheduling therefore uses one existing Graph-owner
snapshot resolution and one indexed Item/accepted-analysis/snapshot-membership join as a
**priority hint**. A set and stable O(N) partition put unfinished targets first. The original
cohort tuple, target-set hash, seed, source pointers and order within each partition remain
unchanged. Short canaries retain their original target order and count.

This projection cannot mark a source complete, skip a target, grant access, trust status
JSON or create a new request. All targets still pass the same source/Workflow/report/Graph
and official report-read checks before VERIFIED. A stale/false-positive hint only delays
that target; authoritative validation remains at execution. The projection is ephemeral,
not a cache/table/queue, and is recomputed from one pinned Graph on restart. This removes
the O(completed × Graph materialization) delay **before** the first unfinished worker
submission; historical acceptance remains verifiable rather than being reinterpreted.

## Three queue consumers for three bounded physical workers

Operating observation found one synchronous Workflow command consumer waiting for a
long-running worker while other admitted source commands could not be submitted. Capacity
three alone is not parallel execution. Extend the existing fixed runner scale-out manager
to at most two accelerator units (three consumers including the canonical runner), not a
threaded executor or another queue. Both consume the same indexed command claims; existing
command lease, Job idempotency and physical worker lease uniqueness remain authoritative.

Each runtime unit retains the exact canonical fragment and only its reviewed optional
similarity-read drop-in. No credentials, user, sandbox, worker protocol, DB schema or capacity
ceiling changes. The manager verifies the closed two-name set, exact root-owned files,
distinct healthy PIDs and inherited configuration. Deployment rejects either staged
accelerator, including an inactive orphan. Stop removes only exact reviewed runtime files;
durable Jobs/history survive. Complexity and memory are bounded to two additional consumers.
One consumer plus a larger capacity cannot remove the blocking command call, while a new
executor framework would duplicate the already tested cross-process claim mechanism.
