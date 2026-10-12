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
