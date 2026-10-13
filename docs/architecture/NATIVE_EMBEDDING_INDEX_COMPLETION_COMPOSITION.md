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
