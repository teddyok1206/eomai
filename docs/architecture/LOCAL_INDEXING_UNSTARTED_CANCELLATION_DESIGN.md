# Unstarted indexing cancellation during a compatible deployment

2026-10-16 UTC. Additive owner-maintenance scope, not automatic runtime recovery.

## Observed need and simpler alternatives

Read-only operating evidence at10:25:24 UTC identifies the original INDEX request
`workflow_d9dfdd0ba988482892ce84d4b4d48e7c`: REQUESTED/LOCAL_EMBEDDING, one PENDING
START command, attempts/generation0, no lease, no steps and only its initial
WORKFLOW_REQUESTED event. It pins current service revision13/source2a4843c3.
The replacement fixed units/host configuration require a compatible owner successor;
its service identity must not pretend to be the predecessor source.

The existing preallocation-retirement1.0 operation intentionally requires an
expired PROCESSING lease and one RUNNING step, and records FAILED history. It
cannot truthfully accept this unstarted request. Do not fabricate a claim/step,
rewrite that schema, turn the request into a success, mutate rows manually, or
silently enqueue a new identity while the old request remains executable.
Generic role runners intentionally do not claim native work, and native claims
require the exact live source authority even for control commands. Reusing those
paths with a fabricated human/admin/service actor is not an alternative.

## Responsibility and canonical state

Add one narrow, optional **deployment-owner application** operation:
`cancel_unstarted_indexing_workflow`. It uses the existing Workflow models,
transition tables and append-only event history. It creates no queue, registry,
runtime grant, authentication capture, Job, Artifact or model execution.
Canonical state remains the original immutable request, original START command,
Identity service revision and Workflow events. A deployment caller separately
proves stopped units and a compatible installed successor; the application does
not run systemd or inspect the filesystem.

## Identity, pointers and authorization

Define JSON Schema2020-12 `local-indexing-unstarted-cancellation/1.0` before
Pydantic/application behavior. The small command pins workflow ID/request SHA,
original command ID, original service logical ID/revision/hash and the exact
successor source commit. The only reason is `NATIVE_RUNTIME_RELEASE_SUPERSEDED`.
It carries no credentials, source content, arbitrary path, worker permission or
force flag. Independently hash command and receipt canonical bytes.

First mutation requires the actual PostgreSQL owner principal for the existing
Workflow tables, a clean writable read-committed root, and the exact current
Identity metadata for the old service. The successor source must differ from
that identity's source. No worker, API runtime role or impersonated ADMIN may
use the operation. Historical exact receipt replay does not reactivate or grant
the old identity after it has been disabled/superseded.

## Access patterns and concurrency

Scale is occasional deployment maintenance, not corpus traversal. Operations are
PK workflow/command lookup, bounded uniqueness/membership checks, indexed
workflow-child lookup and append-only event replay. Reuse existing PKs and
workflow-ID/event-sequence indexes; no DB migration or derived cache.
Time is indexed lookup plus bounded related records, space is one small command
and receipt. Reject multiple commands or any step rather than scanning/repairing
ambiguous history. Lock workflow, command and step scope in the same order as
existing native claims/retirement; first mutation also fences the Identity head.
Use NOWAIT and existing stable BUSY handling instead of waiting indefinitely.
The workflow lock serializes against a concurrent native claim. Either cancellation
commits first and no claim can allocate, or claim wins and cancellation refuses.

## Exact lifecycle and replay

Accept only the released local-indexing service request and its validated original
START command: REQUESTED/LOCAL_EMBEDDING at encode_batch, PENDING, attempts0,
generation0, all lease fields absent, no processing/error/completion timestamps,
no steps, and exactly its initial request event. Never accept human QUERY work,
malformed native markers, active/expired claims, a prior step, alternate command,
different request hash/service pointer, or an already terminal unrelated state.

Use the existing transitions to cancel the command, stage and workflow. Record
the actual DB principal and UTC time, prior states, zero steps and terminal
CANCELLED states in the immutable cancellation receipt/event. Preserve request
bytes/hash, idempotency key, service reference and generation0. Exact replay
returns the original receipt with no new events. Conflicting replay fails.
Rollback leaves the original request fully unchanged. A timeout/unknown outcome
requires inspection and exact replay, never a fresh command identity.

## Layering, compatibility and validation

Contract packages remain pure. Application owns validation/transaction boundaries
and calls existing state transitions/Identity public reads. PostgreSQL owner
verification is one small shared adapter function for the two real maintenance
operations, not a generic framework. Existing retirement1.0 bytes/behavior and
all normal runtime admission/claim schemas remain unchanged. No new dependency.

Tests must cover strict JSON/schema/hash/UTC/nested-copy validation, owner/root
negatives, wrong source/hash/identity, every started/ambiguous history, immutable
request and zero Job/Artifact creation, rollback, replay after identity change,
conflicting replay, and real PostgreSQL cancellation-versus-claim/concurrent
cancellation lock races. Mutating tests run only in the existing guarded
disposable DB. Source PASS is not an operating cancellation receipt.

## Rollout boundary

The recovered QUERY service and ordinary API/Catalog need not change for this
optional leaf. First verify source/tests and an installed compatible owner pair.
Then prepare the exact owner command from the preserved operating request;
execute at most that supported cancellation and inspect its receipt/current rows
before publishing/selecting the INDEX identity/grant successor. Only the normal
missing-binding reconciliation can enqueue successor work. Preserve the old
cancelled request and every historical failed run. Never call this full-goal PASS.

## Source validation checkpoint

Implemented as an optional maintenance leaf; retirement1.0 bytes and normal runtime
admission remain unchanged. The application reuses the same package's existing
PostgreSQL-owner guard and native START identity resolver; it does not copy their
principal/hash/actor/key rules or create an additional execution framework.

Focused contract/old-retirement/QUERY regressions:106 PASS in12.53s. Strict mypy:
both new core modules PASS; Ruff format/lint and shell syntax PASS. The existing
guarded local-indexing-service test purpose now includes the new real PostgreSQL
tests:113 PASS plus19 policy-publication tests PASS in separate invocations.
They cover exact replay after an identity successor/disable, rollback, conflicting
replay, nonowner denial, simultaneous cancellation, both claim/cancellation orders,
and an actual held-row lock. No operating request has been cancelled by those tests.
Disposable database:`/tmp/eom-api-testdb-20261016103237_a4aad411`; actual operating
head remains0055, with no new migration. Installation and actual owner-maintenance
execution remain separate next gates.

The reviewed source candidate is`e6e9b926c5c6811478dd56d8d88c682d1312e3f3`.
Standard three-wheel build/RECORD verification PASS. Its protected owner pair was
actually installed **INACTIVE**, without replacing the b41b3cb4 numerical prefix
or recovered QUERY service. Platform raw:
`5b1a3cf7aaae8456daa9abd9447f07d3140c78d0710c4c12bd99d33c1dc99f8c`;
API-contracts raw:
`17e68bb26fe660b82124b3aec2c6b7ba50677db394d651ff8676a6a545d4768e`.
The disposable DB's guarded `--confirm` cleanup completed; no test rows remain in
that disposable database. Operating DB migration/head and ordinary services are
unchanged. The first cleanup invocation omitted the required confirmation flag
and made no changes; only the guarded exact disposable target was then removed.

An exact operating cancellation command was prepared using that installed public
contract, but **not executed**: original workflow/request/command/service13 remain
unchanged. Command semantic:
`d5d4c26675855aec66c7419cbc7be14def9f43ebf77dc36c00aa87efa7dab597`;
raw:`b8c8c3f68d883c7d833d5c69bb6de4d8c0f05c54fead9f78857ad912d3587c95`.
Root preparation evidence:
`/var/lib/eom-release-operator-stage.2857bf77-6g9mpdap/index-unstarted-e6e9b926`.
Next prepare/review the compatible INDEX identity14/runtime/grant selection before
applying this supported cancellation and normal reconciliation. Do not allocate a
synthetic lease, directly modify rows or treat this preparation as a receipt.
