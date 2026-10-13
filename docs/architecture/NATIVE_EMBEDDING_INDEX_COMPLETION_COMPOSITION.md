# Native batch to index and completion composition

2026-10-13 UTC. Part of the existing incremental-index goal; no runtime activation.

1. Responsibility: Runner composes current source owner, existing encoding
   reservations, fixed native launcher, Orchestrator Artifact owner and Catalog
   registration. No alternative queue, search or worker communication is added.
2. Canonical sources: original Workflow/source plan, owned input and committed
   numerical result; registered immutable index and its exact registration receipt.
3. Identity: native coordinator, reserved encoding Jobs and Artifact-producing
   Jobs stay separate. Completion's producer must be the actual receipt publisher.
4. Resolution: current source/command fencing surrounds short mutations; exact
   input/result/shard/binary/index/receipt pointers, producer and hashes are checked.
5. Access: unique encoding maps, one coordinator-key lookup, append-only small
   checkpoints, grouped file-set reads and index-head CAS.
6. Structures: reuse existing Job/event and pointer-only registry. Input/result
   bytes materialize only at owned workspace, validation and publication boundaries.
7. Scale: at most1024 source/encoding rows; linear maps plus stable ordering and
   O(Nd) bounded numerical checks. No vector bytes or whole source plan in DB events.
8. Transactions: no SQL through model inference; source/Identity/command fences
   apply to each root. Cross-owner commit/register is resumable, not distributed
   atomicity. Exact immutable checkpoints preserve operation IDs and timestamps.
9. Dependencies: current public owner APIs only; no domain infrastructure imports,
   new DB migration, queue framework or third-party dependency.
10. Failure/replay: after model completion reuse local/committed bytes; after index
    commit reuse its exact pointer; CAS conflict is explicit. Completion replay
    verifies historical registration without advancing or rewinding the head.
11. Alternatives: a saved actor is not authority; recomputing after a timeout or
    silently substituting current/latest would destroy reproducibility.

## Release inspection includes the non-Codex definition

The first independent wheel build after the executor connection rejected its
own admission inventory: the existing release inspector inferred every protocol
from an AgentStep and omitted the admitted application-only embedding definition.
Materialize `config/workflows/local-embedding-index.v1.yaml` in that same installed
simulation and use the authoritative `definition_execution_protocol` calculation
for both Codex and native definitions. The fixed two-step schema remains unchanged;
this file does not activate a runner or select an execution policy. Reinforce the
same check in the inventory test. Three existing transfer contract modules missing
from the explicit wheel inventory are also required, not waived or deleted.
The rejected build installed nothing and changed no service, DB or frozen CPU
runtime. Its local build candidate remains distinct from a passed release.

## Two closure corrections required by actual bounded production

An operation's source-plan subset is not the entire authorized corpus. Catalog
registration intentionally reports the whole eligible denominator and may retain
bindings from prior batches. Native receipt validation therefore needs an explicit
resolved full-index/population value for bounded plans, proving that every selected
source/demand occurs exactly in the index. Legacy whole-plan validation remains
unchanged when that value is absent. Never fake missing profiles or shrink corpus
coverage to make a one-source operation appear complete.

Receipt1.0 contains its producer Job ID. The existing file-set publisher normally
allocates that ID after content serialization. Support a separately named typed
identified-publication entrypoint: trusted composition fixes Job/Artifact/revision
IDs before forming these bytes and persists that choice in its coordinator event.
The same owner still creates/commits the file set; its old entrypoint/request bytes
are unchanged. Existing-key or identity conflicts are errors, never overwritten
allocations. Identity values themselves grant no permission. This avoids changing
released receipt schemas or forging a producer ID in a completion carrier.

## Implemented source connections

- Catalog's `prepare_index_basis` captures the complete currently authorized
  source/report population once, derives exact encoding keys, validates reusable
  canonical shard/result/binary rows, and selects one explicit namespace predecessor
  and its CAS version. A final current permission check follows file reads. This
  is an owner-local value, not a saved permission or an automatic latest selector.
- The namespace selection uses its existing unique B-tree identity, then pinned
  PK/FK metadata reads. It takes no current-head write lock. Competing successors
  remain subject to registration CAS; preparation never allocates/advances a head.
- `assemble_embedding_index_revision` constructs current source bindings from
  that full plan and the exact available numeric rows. Missing reports/vectors
  remain partial coverage; previously revoked sources are never copied from the
  predecessor. Graph-only changes rebuild associations without changing vectors.
- `verify_embedding_index_registration_observation` independently checks current
  authority, official source/report and numeric resolution, and persisted immutable
  operation/revision/components. It does not register, advance/rewind a head, or
  rewrite the historical result's original current/replayed flags.
- The existing file-set publisher now accepts a strictly typed preselected identity
  for self-identifying content. Its old publication request/protocol/entrypoint and
  idempotency key remain unchanged. Allocation conflicts are explicit errors.
- Native completion uses that owner to commit one receipt and build its exact
  pointer carrier. Catalog's canonical reader exposes the actual validated producer
  ID and resolves the receipt's commit/lifecycle/schema/member/raw/semantic hashes.
  A forged producer in otherwise genuinely committed bytes is still rejected.

These are supported source use cases, not production activation. The complete
native executor still needs to compose them with durable coordinator checkpoints,
current command recovery, registration/publication and same-session completion
verification. No source/mock/disposable gate activates that executor or admits a
service identity. No new schema bytes, migration, queue or dependency is introduced.

## Verification — 2026-10-13 19:42 UTC

Final same-tree focused16 suites: **379 PASS**,73.84s. Strict mypy9 source modules,
Ruff/format and diff checks PASS. Earlier regex fixtures, a test-only authorization
Literal/enum mistake and the new union revalidation invocation were corrected;
the final full gate was rerun. Failed invocations were not treated as PASS.

Final guarded disposable PostgreSQL **22 PASS**,32.54s, includes real concurrent
identified publication, NAS-commit-before-DB interruption recovery, identity conflict,
actual committed receipt resolution, current namespace predecessor lookup and
historical registration observation with no INSERT/UPDATE/DELETE. Metadata source/IAM
ports remain synthetic; these tests do not assert production user/source activation.
Official prepare/marker/owner/schema/migration/reconcile/cleanup PASS; state
`/tmp/eom-api-testdb-20261013193855_984afd97` is removed. Earlier same-phase22 PASS
is retained separately and not summed. Logs are outside Git in
`/tmp/eom-native-completion.4XmEw88C/` and `/tmp/eom-native-completion.fmUAGbk9/`.

No model/GPU inference, CPU reinstall/probe/seal, production DB migration or
operating service restart occurred. API/Web/runner/chat/chat-worker remain active.
No production index seed/delta or consumer activation is established by this phase.
The full goal remains ACTIVE; next is actual executor/checkpoint/registration and
same-session completion composition, then bounded real seed/delta/reuse/query and
the originally planned consumers/GPU comparison. Do not reopen sealed CPU proof.

## Actual executor and durable continuation

The implemented source composition uses four fixed, schema-first coordinator events in the existing
Job history: ALLOCATION → INDEX_PREPARED → REGISTERED → COMPLETED. Each carries the
exact original native Job/intent hash and bounded typed metadata, never text or vectors.
ALLOCATION fixes separate index/receipt producer identities and one input publication
timestamp and original publication code provenance. INDEX_PREPARED fixes the exact registration command and local index bytes'
hash before publication. REGISTERED records the actual immutable Catalog observation
inside its transaction; COMPLETED links the actual committed receipt carrier.

Primary operations are keyed Job lookup, append-only ordered events, canonical member
reads, and existing registry CAS. Native Job locking serializes the four records; each
record is immutable/idempotent and missing/skipped/conflicting history is an error.
No new table, generic checkpoint framework, queue or dependency is added. The new
coordinator schema is separate from all released worker/receipt/schema inventories.

Only the concrete current operator/source owner may drive the CPU executor. Readiness
checks installed CPU configuration without IAM writes/model start. Every short mutation
root fences actual current Workflow/command/step and source; no SQL root spans inference.
NAS publication occurs with current authority retained, through the existing owner.
Numeric reservation APIs own their own roots rather than opening a competing transaction
under the Runner's Workflow lock. Original intent audit is never the current lease.

Resume reads the same allocation, association and exact systemd handle. Completed
encoding rows bypass computation. BUSY/UNCERTAIN is pending, not permission to recreate
a handle. The staged index is durable owner-local materialization and is read by exact
hash on resume; after commit the canonical index is preferred. Lost local bytes plus an
uncommitted canonical member is explicitly unavailable, not permission to rebuild from
latest. Registration replay verifies history without rewriting the index head.

Claim continuation is allowed only by fresh current authority and the exact existing
native Workflow/step/coordinator history. It is not an authentication extension or
reopening failed history. Step/command completion resolves the same genuine carrier,
original launch/input/shared results and registered numeric/source pointers in its root.
Automatic service identity and CUDA/default activation remain distinct later gates.

Responsibilities are split into the CPU executor (reservation/input/unit/result),
index completion (publication/registration/receipt), shared current execution-source
fence and immutable original publication-provenance composition. The latter preserves
the same Artifact request even if owner code is upgraded during continuation.

An expired claim may rejoin only an exact non-failed allocated coordinator/step
under fresh actual Identity/source authority. Missing allocation, vanished execution,
wrong step or failed history remains unavailable. No prior audit extends a session
or provides the new command token/generation. Protocol hash, contiguous order and
each producer identity are checked on read/replay. First-use coordinator protocol
registration uses PostgreSQL unique-key conflict handling across concurrent Jobs.

Optional canonical index resolution returns uncommitted only when BOTH exact
metadata identities are absent. Partial metadata, foreign identity, corrupt hash,
revoked source and unapproved producer remain errors; no local/latest fallback.
The local proposed index is separately resolved against current official sources
and canonical numeric rows before NAS publication and actual registration.

## Executor verification — 2026-10-13 20:55 UTC

Final same-tree20 focused suites **642 PASS**,69.94s; strict mypy15 source modules,
Ruff/format/bash/diff PASS. Separate owner-only schema/resource/mirror and frozen
Pydantic checkpoint values are implemented without changing released predecessors.
Schema raw SHA is
`sha256:796268d09fb8004b3f1ce17e16c8d44e19e151d3434c5288324bf1292707fd08`.

Final guarded disposable PostgreSQL **28 PASS**,77.01s. The six new actual DB cases
include concurrent first-use checkpoint roots, complete Workflow→encoding→Artifact→
index→receipt→terminal flow, Graph-only delta with no extra numerical forward,
interruption after numeric publication/before encoding completion, interruption
inside registration and after receipt publication, and owner release code changes
between receipt publication and continuation. Source/IAM and numerical backend are
EXPLICITLY SYNTHETIC. Canonical numeric bytes/file sets and DB transactions are real;
these cases do not prove real model performance, user authentication or live activation.

One source gate failed its stdlib-only boundary inventory after adding `functools`
to bind a typed identity; the inventory was precisely extended and the whole642
gate rerun. Earlier DB runs exposed test-only UID/protocol setup, request replay
expectation and synthetic Graph revision/pointer fixture mistakes. The production
UID/authorization/schema/unique/FK checks were not weakened to accommodate fixtures.
Those failed logs and overlapping25/27 PASS results are retained and not summed.

Official prepare/migration/reconcile/guarded cleanup PASS. Final state
`/tmp/eom-api-testdb-20261013205041_11f2118d` is removed; logs are retained outside Git
at `/tmp/eom-native-executor.XoUy2uka/`. Earlier same-phase evidence is retained in
the other `/tmp/eom-native-executor.*` task directories. No production DB test,
model/GPU run, CPU reinstall/probe/seal or operating service restart occurred.
API/Web/runner/chat/chat-worker5 services remain active. Same sudo pane was reused.

Source executor is implemented; it is not installed/activated as the current runner.
Next: protected owner connection and actual authenticated compatible composition,
bounded real seed/delta/reuse/query, automatic service-identity reconciliation,
planned consumer connections and the original CPU/GPU comparison/default gate.
Full goal stays ACTIVE; this checkpoint is not a smaller substitute completion.
