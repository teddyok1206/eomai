# Education Retrieval and Evidence Bundle V2

Status: Phase 9 implementation design

Last reviewed: 2026-08-24 UTC

## 1. Responsibility and boundary

Catalog owns deterministic retrieval over one exact published Education Graph Snapshot and owns
publication of the resulting immutable Evidence Bundle. The Application API authenticates the
Operator, derives the effective permission set, and submits a typed command over the private
Catalog Unix socket. Workers never query PostgreSQL, traverse the graph, read NAS, or choose an
access policy.

The first implementation supports the two Phase 0 graph-grounding query families plus the bounded
item-preparation composition used by Phase 10:

- `CURRICULUM_COMPONENTS`;
- `APPROVED_ITEM_STRUCTURE`;
- `ITEM_PREPARATION`.

Phase 0 Q3 (`PRODUCT_USAGE_HISTORY`) remains intentionally unavailable until Phase 11 establishes
the canonical Product/Form/Assembly/Publication/Usage ledger and its legacy mapping contract. It
will be introduced additively under a new immutable request/schema identity; V2 is never widened or
reinterpreted in place.

It does not accept arbitrary Cypher, SQL, graph paths, embedding prompts, or filesystem paths.

## 2. Canonical source and revision model

```text
published KnowledgeGraphSnapshotRevision
  + immutable RetrievalAccessPolicyRevision
  + authenticated caller permission snapshot
  + typed retrieval intent
  -> immutable EducationRetrievalRequest V2
  -> deterministic ranked pointer selection
  -> immutable Evidence context Artifact Revision
  -> immutable Evidence manifest Artifact Revision
  -> EvidenceBundle logical ID / immutable revision
```

The graph snapshot remains the source of derived adjacency. Source Document, Content Intake, and
Item Registry Artifact Revisions remain the source of evidence bytes and identity. An Evidence
Bundle stores only exact pointers, scores, bounded derived Markdown, counts, hashes, and provenance;
it is never a second canonical copy of a textbook, Item, image, table, equation, or answer.

## 3. Pointer and policy resolution

Before retrieval, Catalog re-resolves:

- the exact `PUBLISHED` Graph Snapshot Revision and its manifest Artifact Revision;
- the exact `RELEASED` retrieval-policy revision and canonical content hash;
- the authenticated Operator identity, normalized requester role, sorted effective permission keys,
  and permission-set hash;
- every selected source logical/revision identity, Artifact logical/revision identity, lifecycle,
  manifest member, media type, schema reference, byte count, and SHA-256;
- every selected graph node, edge, curriculum-closure row, and Item Element against the requested
  snapshot revision.

The request never resolves an implicit current snapshot. A stale, missing, unapproved,
schema-mismatched, hash-mismatched, or unauthorized pointer is a typed failure. Historical requests
continue to pin their exact snapshot and policy revisions after current pointers advance.

## 4. Dominant access patterns and data structures

The dominant operations are exact key lookup, set membership, bounded curriculum subtree lookup,
two-hop adjacency traversal, exact stable-key/term lookup, grouped Item-element membership,
deterministic deduplication, and idempotent publication.

- B-tree primary/unique indexes serve snapshot, request, policy, idempotency, and source pointers.
- Curriculum closure uses `(snapshot, framework, ancestor, depth, descendant)` and its inverse.
- Sparse adjacency uses the Phase 8 outbound and inbound composite indexes.
- Immutable lexical terms use `(snapshot, term, node)` plus reverse node lookup. Terms are a derived
  snapshot-local cache populated at publication; no mutable invalidation path exists.
- Item structure uses `(snapshot, item_revision, element_kind)` and grouped `HAVING` membership.
- Evidence entries use one row per deduplicated immutable source/use pair. Bounded node and anchor ID
  tuples are stored as PostgreSQL arrays with GIN indexes for reverse inspection.
- In-memory ranking uses maps for node/source lookup, sets for visited/deduplication, and a sorted
  tuple for deterministic output. No repeated list membership or unbounded traversal is permitted.

Indexed lookup is expected to cost `O(log n + k)`. Two-hop traversal is `O(V_b + E_b)` within the
request's hard node bound. Ranking is `O(k log k)` with `k <= 256`; manifest serialization is linear
in at most 128 entries. Initial scale is up to millions of immutable graph nodes but only hundreds
of selected candidates per request.

## 5. Ranking, budgets, and materialization

Ranking is deterministic and explainable: exact stable/topic matches, curriculum distance,
required Item-element coverage, graph hop distance, source class, and immutable identity are the
only inputs. No model or embedding call is made. A vector adapter remains optional and disabled
until it demonstrates measured recall/latency benefit against this baseline.

Selection is bounded independently by documents, Item Revisions, graph nodes, claims, entries, and
estimated context tokens. Token estimation is deterministic and conservative for UTF-8 Korean
Markdown. The publisher stops before exceeding any bound; it never truncates a source pointer or
silently widens the query.

The context Artifact contains one generated `evidence/context.md`. The manifest Artifact contains
the V2 manifest and points to that exact context member. Job-local materialization in Phase 10
copies only the validated bounded context member; it does not expose NAS paths or graph access.
`manifest_sha256` is the manifest's canonical self-hash with that field omitted; the manifest
Artifact member pointer separately carries the SHA-256 of the complete serialized bytes. Those
hashes are intentionally distinct and both are verified when the pointer is resolved.

## 6. Answer-bearing and rights policy

The immutable access policy defines allowed query kinds, requester roles, source classes, maximum
budgets, and roles allowed to receive answer-bearing graph nodes. Catalog intersects the command's
source classes and budget with the policy. `WORKER` never receives answer-bearing entries in the
standard policy. A public caller cannot self-assert role or permission keys: the API derives both
from the authenticated session before crossing the private socket.

Even for an allowed reviewer/admin, answer-bearing evidence is marked `AVOID_COPY`; it remains
distinct from grounding. Student identity, answers, scores, attempts, and distribution data are
outside this graph and Evidence Bundle contract.

## 7. Transaction, concurrency, retry, and idempotency

The service validates and selects from one immutable snapshot, writes deterministic context and
manifest Artifacts through the existing Catalog Artifact adapter, then enters one short database
transaction. The transaction rechecks snapshot/policy identity, locks the idempotency row, inserts
the immutable request/bundle/entry records, and returns the committed revision. Same key plus same
canonical submission hash returns the same bundle; same key plus different input fails closed.

Concurrent identical creation converges on one bundle. A transaction race never creates two
canonical revisions. Artifact commits that lose the final transaction are safe immutable orphans
and may be reclaimed only by the separately reviewed Artifact garbage-collection policy.

## 8. Failure contract

Stable failures distinguish invalid request, unknown/stale snapshot, unknown/stale policy,
unauthorized query/source/answer-bearing access, missing curriculum scope, insufficient evidence,
source pointer mismatch, budget exhaustion, artifact commit failure, idempotency conflict, and
concurrent publication conflict. A graph miss creates no Codex job and no workflow.

## 9. Dependency direction and simpler alternative

JSON Schema and frozen Pydantic contracts live in `catalog_contracts`. Catalog application services
own database queries, ranking, policy, Artifact commits, and idempotency. The private Unix-socket
adapter exposes typed operations; the API owns authentication and presentation only. Phase 10's
workflow use case consumes an immutable Evidence Bundle pointer and never imports Catalog
infrastructure.

Scanning projection JSONL for every request was rejected because it repeats parsing and yields
`O(n)` lookups. Copying source Markdown into PostgreSQL was rejected as canonical duplication. An
external graph database or embedding service was rejected because the three accepted query classes
fit indexed PostgreSQL adjacency/closure and there is no measured benefit yet.
