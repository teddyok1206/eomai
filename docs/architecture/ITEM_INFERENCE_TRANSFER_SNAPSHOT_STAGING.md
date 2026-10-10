# Authorized snapshot to staged experiment

Status: **SOURCE_PROPOSAL**. This note authorizes no installation, production
read, model invocation or Artifact publication. It composes the existing
snapshot and experiment contracts without changing their bytes or meanings.

1. **Responsibility/boundary.** A small Orchestrator application use case asks
   an injected supported Catalog snapshot read port to prepare/read the exact
   population and assembles the existing experiment request. A separate call
   reauthorizes that exact assembly immediately before an authorized commit.
   The caller supplies its actual authenticated operator context; workers never
   receive DB, NAS or transport authority. This is not another search engine.
2. **Canonical source.** Catalog's current authorization and exact accepted
   source/report/profile values are authoritative. A local assembly, hash,
   producer-admission label or cached authorization reply is not a credential.
3. **Identity/revision.** Retain the prepared header, complete index, exact
   Graph/policy/projection/view and model pins, immutable experiment IDs, request
   SHA and independent source/profile/entry/baseline hashes. Never follow latest.
4. **Resolution checks.** Reparse every request/reply through the released
   schema/model validators. Check phase, actual actor, full index membership,
   complete record coverage, duplicate records, profile/source/count/hash
   closure and exact query/baseline closure before assembling the experiment.
   Reauthorize the full entry and baseline sets, not just selected queries.
5. **Access patterns.** Stable ordered chunk iteration and keyed exact lookup,
   complete-set membership/deduplication, one deterministic assembly and final
   authorization. Missing-report sources stay in the denominator; they cannot
   be selected as an encodable query.
6. **Structures/indexes.** Reuse existing immutable tuple/index contracts and
   map/set lookups. No DB table, queue, snapshot cache, new index or raw-vector
   persistence. Keep the pure use case independent of filesystem/SQL/HTTP.
7. **Scale/complexity.** At most 1,024 sources, 16 queries and existing 64 MiB
   input limit. Track accumulated encoded bytes while receiving chunks and
   validate final canonical request bytes before any materialization. Chunk
   count/bytes retain their existing limits. Owner reconstruction remains
   O(chunks × population), explicitly unoptimized pending a real measurement;
   local merge is O(N log N) for canonical ordering and O(N) space.
8. **Transaction/concurrency.** Each read is independent current authorization
   plus frozen-header equality, not a distributed transaction. This use case
   performs no DB mutation, file write, model launch or Artifact commit. The
   existing owner performs protected local staging and validated commit later.
9. **Dependency/ownership.** Orchestrator application code depends on existing
   public Catalog contracts and an injected read protocol, not Catalog private
   adapters or Application API internals. Filesystem, transport, authentication,
   model execution and Artifact publication stay in their existing owners.
10. **Failure/retry/idempotency.** Do not accept partial/duplicate/out-of-order
    coverage, missing query reports, mismatched pins or malformed replies. Only
    an explicit read-only chunk-budget error may split that same selected chunk;
    a one-record overflow fails without truncation. Authorization, revocation,
    transport and unknown errors are not retried with another actor/policy/key.
    A pre-execution authorization reply must not substitute for post-execution
    reauthorization. Preserve historical evidence and never call a partial
    subset the full corpus.
11. **Simpler alternative.** Manually copying JSON is shorter but cannot protect
    full-index/chunk closure or mandatory final authorization consistently. A
    single pure assembly use case over the supported read port closes that gap
    without another maintenance API, authentication framework or registry.

Source tests use fake owner ports only: exact complete assembly, missing-report
denominator, query absence, duplicate/foreign chunks, changed actor/header,
current revocation, wrong phase/hash, bounded budget splitting, one-entry
overflow, no implicit retry and final reauthorization. These tests do not prove
that an operator is authenticated, a live snapshot is accessible, the model is
installed or that a committed result has passed human transfer review.

## Source implementation evidence

The approved pure boundary is implemented in
`services/orchestrator/eom_orchestrator/inference_transfer_snapshot_staging.py`.
Its frozen actor context is a caller-captured value, **not a credential**. The
injected supported owner adapter retains actual authentication and maps stable
failures to the application-owned `SnapshotReadFailure`; arbitrary exception
text cannot authorize chunk splitting.

`stage_snapshot_experiment` performs exact PREPARE and ordered complete READ
assembly only. It does not cache an AUTHORIZE reply. The separate
`reauthorize_staged_experiment` call always asks the current owner again after
model execution and before publication. A result labelled
`AUTHORIZED_CURRENT_READ` remains a current-read observation, not a durable ACL
or a commit token. The later commit owner must retain its own transaction fence.

Accumulated canonical reply bytes and final canonical experiment bytes both
respect the selected existing input budget (at most 64 MiB). The complete compact
index and all sources retain missing-report denominator entries. The local merge
is O(N log N); reusing the existing full-index validator on each chunk also costs
O(chunks × N), in addition to the owner's independent reconstruction. No new
cache or optimized authorization shortcut was introduced.

Source verification: 38 focused fake-owner tests PASS; together with the existing
snapshot, binding and experiment contracts, 141 tests PASS. Explicit `eom-core`
strict mypy, Ruff and formatter checks PASS. No production snapshot, model run,
filesystem staging, installation, activation or Artifact commit was performed.
