# Current encoding reservation and Artifact composition

2026-10-13 UTC. Extends the approved incremental-index goal after actual CPU
numerical/replay acceptance. This note neither activates indexing nor grants authority.

1. Responsibility: the current authenticated Runner owner supplies command/source
   admission to the existing Orchestrator encoding reservation API. Catalog reads
   committed owned input/result members. Native workers still have no DB/NAS access.
2. Canonical sources: exact saved Workflow request, source plan/policy Artifacts,
   current Identity/Catalog rows, original encoding events and committed file sets.
3. Identities: current command lease is separate from original launch audit; native
   launch Job, per-encoding Jobs and file-set producer Jobs retain distinct IDs.
4. Resolution: current operator/source/command checks precede launch/existence reads.
   Owned input is a canonical single-member Artifact; result/shard/binary are one
   canonical three-member Artifact. Verify approved producer/lifecycle, exact schema,
   primary/member set, raw/semantic hashes, shape/finite/L2 and request closure.
5. Access: keyed Workflow/step/command/Job lookups; bounded selected source maps;
   exact member reads; per-operation encoding maps and immutable ordered tuples.
6. Structures: reuse existing indexed records and file-set reader, no new queue or
   registry. Native launch identity is one exact Workflow/step/request key. The
   original all-demand request stays canonical; owned input is a separate subset.
7. Scale: at most1024 sources/encodings; O(N+B+Nd) validation and O(B+Nd) bounded
   materialization. Capture demanded entries with source validation instead of
   fetching the full corpus again. Never cache current authority across roots.
8. Transactions: acquire Workflow then current command and retain Identity/source
   locks through each root. Reservations use separate short roots; model execution
   occurs outside SQL. Read reauthorizes the caller's explicit requested scope,
   not the winner's historical command or full original source plan.
9. Dependencies: Runner composition may use official Identity/Catalog/Orchestrator
   APIs. Catalog owns numeric/member validation. Domains import no infrastructure.
   No new third-party dependency, DB schema or released protocol bytes are needed.
10. Failure/replay: missing/revoked/stale/hash/mixed producer failures are explicit.
    Uncertain exact unit preserves its handle and ownership. A persisted launch
    audit is not a new lease or permission; current linked command remains required.
    Reuse validated existing results rather than generating a new computation.
11. Alternative: saved actor/plan or a pass-through admission callback cannot prove
    actual current authorization; copying bytes or creating another job queue would
    duplicate existing ownership. Compose the supported owners instead.

Native launch Job metadata uses the original validated Workflow request1.1 and
the existing encoding execution/event family, not a Codex JobRequest/worker role.
Its task type and deterministic Workflow/step/request key must be checked by its
Orchestrator owner. Protocol family and the embedded request's schema are distinct.
Allocation is implemented through the existing structured Job owner: one hashed
Workflow/step/request key fits the existing128-character column, and one immutable
intent event preserves original command audit across reentry. It requires an active
non-savepoint caller root and the registered encoding protocol. Current command
authority remains the caller's independently fenced root, never that audit event.
Start/completion and full Runner executor composition are subsequent connections;
source adapters or synthetic tests do not establish live activation.

## Source and disposable verification

`CatalogLocalEmbeddingOwnerAdmission.resolve_sources` returns demanded entries
from the same official capture that rebuilt the plan. `resolve_mutation_sources`
retains current Identity/source/command fencing and returns only those root-local
values. Existing submission/fence APIs delegate without a cached authority result.

The concrete encoding port locks Workflow then actual command/step, checks original
Job/request/key/intent and exact step input pointers before reservation/launch/
completion. Read authorizes the caller's explicit current encoding set. Shared
completed rows require no historical command lease or winner input. File-set reads
are grouped; schema/lifecycle/producer/hash/result/shard/binary/row checks use one
authoritative leaf. Pending ownership inspects actual current command and protected
exact units without starting; expiry preserves uncertainty. Late Identity checks
follow Artifact/OS reads. This port is implemented but not installed/composed yet.

Actual disposable PostgreSQL: Identity/session writer competition19 PASS and
encoding reservation/coordinator9 PASS; guarded migration/reconcile/cleanup PASS.
Source tests include real test-local file-set publication/read, immutable original
intent replay, wrong producer/lifecycle/binary/ordinal, duplicate/empty rows,
foreign scopes, late denial and step-pointer mismatch. Mock owner/OS seams in unit
tests remain synthetic, not production authentication. No model/GPU/corpus run,
production migration or operating service restart occurred in this phase.
Final same-tree focused11 suites336 PASS, strict mypy5 modules, Ruff/format/diff
PASS. PostgreSQL mutation coverage is the guarded disposable28 tests above;
the new native coordinator's allocation/replay/key bound ran in PostgreSQL.
Remaining full native executor/registry/real source and consumer gates are open.
