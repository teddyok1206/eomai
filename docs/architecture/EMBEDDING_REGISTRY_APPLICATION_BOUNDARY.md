# Catalog embedding registration application boundary

2026-10-12 UTC. Source-only boundary over the committed 0052 contracts/tables;
no new migration, runtime composition, service authority or activation.

Catalog owns the one metadata transaction. An owner-injected authenticated caller
context and trusted verification port compose the official Graph/source/report
resolver and committed Artifact reader. No worker/model role, boolean approval,
FK existence, DRAFT Item or REQUESTED analysis constitutes eligibility. The port
has no default implementation; absent composition fails explicitly before writes.

Canonical bytes remain the committed index/shard members and original source/
accepted report. Temporary verified captures may materialize bounded profiles and
view text once; only scalar projections and immutable pointers enter the DB.
Existing pure index/source-binding validators remain the semantic authorities.
Application checks additionally bind one exact caller/command, corpus, Graph,
policy, namespace, ordered source/binding set hashes and coverage denominator.

Dominant operations are B-tree operation/encoding key lookup, bounded association
membership, immutable insertion and head CAS. Use maps/sets over at most 1,024
sources/bindings and a bounded VALUES + NOT EXISTS anti-join; no timestamp discovery,
unbounded corpus scan, new queue or persistent eligibility cache is added.

Registration/replay run inside the caller's Catalog transaction and a nested
savepoint so failed CAS/constraint checks leave no partial encoding/binding/revision
rows. Lock the exact head and recheck the immutable operation key after acquiring
it. A first-head uniqueness race rereads only the same identity; differing namespace
or index identity is conflict, never latest substitution. Encoding/binding inserts
use exact unique identities and compare immutable projections on replay. The same
binding may retain its first canonical origin member instead of replacing its
pointer whenever a successor index repeats that value.

Each successful head advance publishes exactly the next immutable revision number
and one lock generation. Historical replay returns the original registration time,
predecessor and registered generation plus the locked current head; it never rewinds
the pointer. Reauthorize the original exact sources and resolve all retained
encoding/binding origin pointers even on replay/lookup. Distinct pointer mismatch,
revocation, unavailable verification, conflicting operation and stale CAS are
stable redacted errors. No encoder/publisher retry is performed here.

The bounded missing-binding leaf accepts owner-verified exact candidates; it is
not source discovery, paging, a public API or background service admission. Current
1.0 source limits remain explicit. Production official-owner composition and the
1.1 service-authority/paged-index successors are still pending.

SQL infrastructure implements projection/membership/locking only; the application
owns contract validation and transaction orchestration. Contracts/domain import
neither SQL nor Catalog infrastructure. Complexity is O(B) expected map/set work
plus indexed DB lookups and O(B log B) deterministic ordering, with O(B) temporary
metadata space. Original source/Artifact validation cost is separately bounded by
the verification owner. No new dependency is needed. A batch-only current path or
direct insertion would lose exact replay/authorization/atomicity; a generic registry
framework is unnecessary for these two fixed use cases.

## Bounded source-binding batch validation

The additive public batch validator is a pure contract boundary, not a verification
owner or grant. It keeps the released JSON Schemas and scalar validator semantics
unchanged. Canonical source remains exact approved profile/source material and the
committed shard member; no derived eligibility or validation status is persisted.
Logical source/revision, Artifact/revision, raw-member SHA and semantic hashes stay
separate. Each entry, binding and pinned shard is revalidated from JSON-mode data;
the exact member schema/media/path, hash, row, profile, evidence, Graph and view text
checks remain one shared semantic leaf with the scalar validator.

Dominant operations are source-revision and exact-pointer key lookup plus ordered
binding iteration. Bounded dictionaries reject duplicate source revisions, bindings
and shard pointers; they are temporary captures, not a new registry. For B bindings,
E entries and R total rows across unique shards, work/temporary metadata is O(B+E+R)
apart from deterministic canonical serialization. The existing index-reference
validator may separately revalidate each unique shard once; this is still linear.
The batch limit is 1,024, not an unlimited/paged contract.

This pure operation changes no transaction, lock, caller authority or adapter
ownership. Missing/stale/changed pointers and unavailable text fail explicitly;
there is no latest fallback, retry or caller-provided "already validated" switch.
Contracts do not import SQL/application infrastructure. A parse/hash operation-count
test uses 1,024 synthetic bindings in one shared shard without vector inference or
binary materialization. Repeating the scalar validator for every row would be the
simpler call site but repeatedly parses/hashes all R rows, giving O(B*R) work; a
second copied semantic rule or unchecked frozen-instance bypass is insufficient.

## Guarded metadata query-plan evidence

The disposable integration fixture observed a nested-loop anti-join with
`ix_embedding_binding_encoding`: `encoding_sha256` is the indexed equality and
the other nine exact association fields remain equality filters. No sequential
scan was present. This is an indexed exact-key lookup, not evidence that the
composite unique index was used. The test verifies the chosen installed index's
table, B-tree method, validity and key columns against the source model, and checks
all ten equality predicates. It separately verifies the installed unique B-tree
`uq_embedding_binding_association` and its exact ten ordered columns.

The tiny fixture uses `SET LOCAL enable_seqscan=off` to establish an available
indexed path, not a production planner preference or high-fanout benchmark. An
encoding may have many Graph/profile bindings; production fanout/selectivity and
planner choice still require representative measurements. Earlier guarded runs
passed replay, savepoint rollback and both independent-process races but failed
the test's guessed composite-index-name assertion; that was a test expectation
defect, not evidence of lost association predicates or a registry mutation defect.

## Immutable first-origin ledger resolution

2026-10-18 UTC; separate source-only INDEX throughput cohort. Existing released
contracts, database schema, numerical defaults and authority boundaries are unchanged.

1. **Responsibility:** Catalog's existing reference verifier reconstructs current
   source bindings and checks their original committed member; it does not register
   data, choose a head, or grant source access.
2. **Canonical source:** committed index/shard bytes remain canonical values. The
   scalar registration ledger records membership established by full index/source/
   numerical validation before insertion. Migration 0052 rejects UPDATE/DELETE on
   binding, encoding and index-revision rows; activation requires the actual trigger
   gate, not merely a model declaration or an unverified database head.
3. **Identity:** source logical/revision identity, complete binding SHA, first-origin
   Artifact/revision/raw SHA and encoding/row identity stay separate. Historical
   replay never rewrites the first origin to the current cumulative index.
4. **Resolution:** rebuild the exact binding from fresh admitted source/profile/
   report/Graph/policy/recipe plus its registered numerical row, using the same pure
   constructor as index assembly. Batch-read the immutable ledger and compare every
   scalar projection and the complete first-origin pointer. Each distinct origin
   still passes existing member-set/schema/media/size/path/raw-SHA checks and current
   Artifact/revision approval and terminal producer checks. Only its redundant full
   historical index DTO interpretation is omitted.
5. **Access patterns:** bounded binding-SHA key lookup, deduplication of exact origin
   pointers and shard pointers, and deterministic ordered binding iteration; at most
   1,024 current bindings.
6. **Structures/indexes:** temporary dictionaries keyed by binding SHA, encoding SHA
   and immutable pointer; one existing primary-key batch query over binding SHAs.
   No persistent validation cache, new table, schema, receipt family or index.
7. **Complexity:** binding reconstruction/DTO validation becomes O(B), plus ordering,
   rather than parsing every cumulative prefix (batch 4 gives 40/544/8,320 binding
   visits at B=16/64/256). Unique-origin physical read/hash counts stay unchanged;
   cumulative raw-byte I/O is not claimed linear. Historical DTO graphs are no longer
   retained together. Bounded fixture timings/memory are diagnostic, not live
   throughput or memory-pressure attribution.
8. **Transactions/concurrency:** retain the existing caller-owned root, current
   source/IAM/runtime fences, registration savepoints, immutable insertion and head
   CAS. Fresh scalar ledger reads cannot inherit stale ORM values. Absence and
   mismatch fail closed even for rows inserted earlier in the same registration
   transaction; no previous index-revision FK is invented before its insertion.
9. **Dependency direction:** pure binding construction remains in the existing
   assembly module; shared ledger projection and indexed reads remain in the
   existing Catalog repository; the verifier owns physical Artifact resolution.
   Protocol/domain packages gain no SQL/filesystem imports or new dependencies.
10. **Failure/replay:** forged ledger fields/origin pointers, missing members,
    stale raw hashes, withdrawn producers/approval and revoked current sources stay
    errors. There is no weaker parser fallback, latest substitution, mutation,
    automatic retry or schema-less receipt. Selected-index and predecessor parsing,
    finite/L2 numerical checks and protected-runtime pre/post scans remain intact.
11. **Simpler alternative:** merely trusting a digest would omit ledger equality and
    current eligibility; retaining historical full DTOs repeats all cumulative
    bindings. Native batch input/results prove encoding rows, not the complete
    source/profile/Graph/policy association, and are not a universal origin proof.
    The existing immutable registration fact plus exact current reconstruction and
    unchanged origin bytes is sufficient without per-binding receipts.

### Verification of the bounded optimization

Root's merged-source gate passed257 tests in31.27s (eight focused suites); strict
mypy5 modules and Ruff/format9 Python files passed. Agent's separate executed
16/64/256 diagnostic controls retain identical origin read/hash counts and exact
bindings. For256 bindings/two captures, the old origin-only control used128.029s
and208.18MB traced peak versus6.168s/53.51MB for full optimized verification.
Those scopes differ: this is a synthetic repeated-DTO diagnostic, not an actual
INDEX throughput claim or a reason to remove cumulative raw-byte validation.

The official `testdb_run.sh embedding-tests` passed **122/122, no skips**, in
277.05s on disposable PostgreSQL. This includes actual SQLSTATE23514 rejection of
UPDATE/DELETE for encoding/binding/revision history, current scalar/origin refresh
from a poisoned identity map, registration/replay, native completion and private
QUERY compatibility. Evidence `/tmp/eom-index-ledger-db.Cbcjez2P/TEST.xml`, raw
`9e7927a1087dcba7231cca064c6a0ad1ec03f3031a132872d5a934e8bebf2d74`.
The guarded test database and roles were removed successfully; no production DB
was a test target. Before actual private INDEX activation, attest the current
target's unchanged0052 enabled triggers and exact function bodies using a bounded
read-only metadata check. Source tests do not attest the operating installation.
