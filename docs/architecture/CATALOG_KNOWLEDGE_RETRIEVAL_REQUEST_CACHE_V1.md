# Catalog knowledge retrieval request cache V1

## 1. Responsibility and system boundary

`KnowledgeRetrievalApplicationService` owns one closed Evidence Bundle retrieval. This change
removes repeated immutable-source work inside that single application request. It does not add a
cross-request cache, change the Catalog application protocol, change worker behavior, or move a
NAS commit boundary. Authorization still completes before candidate lookup begins.

## 2. Canonical source

The canonical sources remain the pinned published Graph Snapshot, its
`knowledge_snapshot_analyses` associations, accepted `knowledge_analysis_runs`, registered source
revisions, Artifact Revisions and manifests, and immutable NAS members. Cache entries are derived
only after the existing resolver has checked those canonical records and bytes; the cache itself is
never canonical or persisted.

## 3. Logical entity and revision model

Graph Snapshot identity, Analysis Run identity, source logical identity, source revision identity,
Artifact logical identity, Artifact Revision identity, and member SHA-256 remain separate. A
request-local source result is reusable only for the same pinned Analysis Run. A Graph member is
reusable only for the full immutable source-member key, and artifact bytes or verification results
are reusable only for the full Artifact member validation key.

## 4. Required pointers and resolution checks

The Graph source-member key contains Graph Snapshot Revision ID, Analysis Run ID, source Revision
ID, source class, Artifact ID, Artifact Revision ID, SHA-256, and member path. The filesystem
validation key contains Artifact ID, Artifact Revision ID, member path, SHA-256, media type, schema
reference, and maximum-byte boundary. Association existence, accepted Analysis Run state, JSON
Schema/Pydantic source parsing, source lifecycle, canonical source equality, and exact member
membership remain mandatory. Only a successful full check populates a cache; failures are never
cached. Repeated members of one accepted run reuse its already validated source contract, but every
distinct Graph member key is independently checked against that contract.

## 5. Primary access patterns

The dominant operations are lookup and deduplication, not ordered scanning:

- preload all accepted-snapshot associations for the candidate Analysis Run ID set;
- preload all Analysis Runs for that same set;
- look up association and run by Analysis Run ID;
- look up a validated source by immutable Analysis Run ID;
- look up a validated Graph member or Artifact member by its complete immutable key.

A read-only production-shaped sample contained 193 candidate source groups, 140 Analysis Runs, 68
source revisions, 608 Artifact reads with 104 distinct validation keys, and 444 Artifact verifies
with 74 distinct validation keys. Per-candidate association and run lookup was therefore an N+1
pattern, while Artifact validation repeated identical work many times.

## 6. Chosen data structures and indexes

Request-local dictionaries provide source, association, run, and immutable-member lookup; a set
records successful verification keys. Association and run preload use two bounded `IN` queries.
Existing uniqueness on `(graph_snapshot_revision_id, analysis_run_id)`, the Analysis Run primary
key, and the existing Graph source-pointer indexes support those queries, so no migration or new
index is required. Candidate grouping uses the complete source-member key while retaining the
legacy deterministic ordering fields before any added tie-breakers.

## 7. Expected time, space, scale, and evidence

For `R` distinct Analysis Runs and `P` candidate Graph pointers, association/run database work is
`O(R)` materialization with exactly two SQL queries, replacing `O(P)` round trips. Cache lookup is
expected `O(1)` and candidate ordering remains `O(P log P)`. Artifact byte caching is capped at 64
MiB per request; keys and typed source objects are bounded by the existing 256-candidate limit and
are released when candidate resolution returns.

The benchmark was a direct single-process invocation of `_candidates` against one existing
production-shaped request, inside `SET TRANSACTION READ ONLY`. It was rerun after the unrelated
legacy automation loop was disabled, so the result does not depend on that loop's CPU load.

| Measure | installed before | workspace after | change |
| --- | ---: | ---: | ---: |
| elapsed | 21.800 s | 10.275 s | -52.9% (2.12x) |
| SQL statements | 5,152 | 1,634 | -68.3% |
| delegated Artifact reads | 608 | 104 | -82.9% |
| delegated Artifact verifies | 444 | 74 | -83.3% |
| resolved candidates | 193 | 193 | unchanged |

The resulting 42 Evidence entries exactly matched the already-published records, and the rendered
context SHA-256 exactly matched the already-published context Artifact.

## 8. Transaction and concurrency boundary

All caches are constructed inside `_candidates` after authorization and live only for its current
database session and application request. They are not service globals and are not shared between
operators, requests, processes, or transactions. The first resolution performs the canonical DB,
manifest, filesystem, and hash checks. Later lookup returns only immutable in-memory bytes or typed
values from that same request. Concurrent publication cannot rebase the pinned Snapshot Revision,
and no mutable current-revision lookup is introduced.

## 9. Dependency direction and adapter ownership

The Catalog application service owns orchestration and the request-local cache. The existing
`CatalogArtifactService` remains the sole filesystem/NAS adapter and performs the first exact
member validation. Source resolvers remain the authoritative source-lifecycle and schema boundary.
No domain model imports infrastructure, no worker gains storage access, and no dependency is added.

## 10. Failure, retry, and idempotency behavior

Missing associations, absent or unaccepted runs, invalid Pydantic payloads, stale lifecycle state,
unsafe paths, schema/media/hash mismatches, and invalid bytes retain their stable errors. A failed
read, verification, or source resolution does not populate any cache. A replay is a new request and
therefore reauthorizes and revalidates its immutable dependencies once again. Evidence Bundle
idempotency and publication transaction boundaries are unchanged.

## 11. Simpler alternative and why it is insufficient

Increasing the 30-second Catalog client timeout would preserve the 5,152-query and repeated-hash
path, making a 25-call production merely wait longer. Caching only by path, Analysis Run, or
Artifact Revision would omit hash/schema/member identity and could conflate distinct immutable
pointers. A process-global cache would weaken authorization/lifecycle freshness and cross-operator
isolation. The bounded request-local maps plus two bulk queries are the smallest change that removes
the measured duplication while preserving all canonical checks and published output.
