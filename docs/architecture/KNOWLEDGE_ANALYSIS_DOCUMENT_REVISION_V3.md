# Knowledge Analysis Document Revision V3

Status: implementation design
Date: 2026-08-25 (UTC)
Scope: bounded Knowledge Analysis over immutable Educational Document Revisions

## Decision

Knowledge Analysis V3 adds one source family, `DOCUMENT_REVISION`, without changing any V1 or V2
schema bytes. The canonical source identity remains the original PDF member pinned by an approved
`EducationalDocumentRevision`. A worker never receives that entire PDF. It receives a bounded,
hash-verified selection of canonical Markdown page members from the same revision's analysis
Artifact:

```text
EducationalDocumentRevision
  -> original PDF Artifact member                 # provenance and graph-anchor authority
  -> canonical analysis-bundle manifest
       -> selected Markdown page members          # temporary worker materialization only
  -> source-bound rights attestation

Knowledge Analysis Request V3
  -> exact Document + Document Revision IDs
  -> exact original PDF pointer/hash
  -> exact analysis manifest pointer/hash
  -> exact rights pointer/hash
  -> ordered page-range selection (at most 32 pages and 2 MiB)
  -> optional ordered EOM curriculum-unit keys
```

The resulting proposal, accepted result, Graph Snapshot, and Evidence Bundle pin the immutable
Document Revision and original PDF Artifact Revision. Derived Markdown is materialization evidence,
not a replacement source identity.

## 1. Responsibility and boundary

The Catalog application service resolves Document Revision eligibility and constructs the closed V3
source pointer. The Orchestrator resolves an immutable execution plan, retains the original PDF,
bundle-manifest, and rights pointers as provenance, authorizes only the selected Markdown Artifact
Revision for materialization, materializes selected members into a fresh worker workspace, validates
the worker result, and alone commits proposal Artifacts to NAS. Workers neither resolve current
pointers nor write NAS.

Graph publication accepts an analysis only after its accepted result, proposal receipt, original
source, selected derivative members, and Document Revision all re-resolve exactly. Retrieval reads
only a published immutable Graph Snapshot and never consults a mutable latest document revision for
historical evidence.

## 2. Canonical source and revision model

The canonical source is:

```text
document_id
+ document_revision_id
+ original artifact_id
+ original artifact_revision_id
+ member_path
+ source SHA-256
+ PDF page count
```

New requests require an `ACTIVE` logical document whose `current_revision_id` is the selected
`APPROVED` revision. This prevents new analysis from silently using a superseded or withdrawn
revision. Once created, a request and every resulting snapshot keep that exact revision even if the
logical document later advances.

The analysis-bundle and rights pointers are independently immutable dependencies. The resolver
verifies that the bundle's `canonical_source` equals the Document Revision's original PDF pointer
and that the rights attestation is source-SHA-bound, `CLEARED_LICENSED`, permits
`KNOWLEDGE_ANALYSIS` and `GRAPH_INDEXING`, and authorizes `DATA_ANALYST_WORKER`.

## 3. Bounded materialization contract

One V3 request selects a contiguous physical-page range:

- `first_physical_page >= 1`;
- `last_physical_page <= source_page_count`;
- at most 32 pages;
- exactly one canonical Markdown member for every selected page;
- ordered, gap-free physical page numbers;
- no duplicate member or destination path;
- aggregate selected Markdown bytes at most 2 MiB;
- optional curriculum-unit keys are sorted, unique, and must match bundle mappings overlapping the
  selected range.

The bundle index may be included as one additional small context member. It does not count as a
source page and cannot be cited as original evidence. Every selected member pins Artifact ID,
Artifact Revision ID, member path, SHA-256, byte count, media type, schema reference, destination
path, and physical page number.

Worker destinations are fixed below `source/document/` and created with exclusive, non-symlink,
group-private filesystem semantics. Total job-local bytes remain subject to the existing Knowledge
Analysis materialization ceiling. The original PDF is not copied into the workspace.

## 4. Anchor and result contract

Worker anchors always use:

- the original PDF Artifact Revision ID;
- the original PDF member path;
- locator `physical_page=<n>` or a bounded locator rooted in that page;
- an excerpt SHA-256 derived from selected canonical Markdown text.

An anchor page must fall within the request range. A worker cannot cite the bundle manifest, index,
or a Markdown member as the authoritative source. Proposal receipt V2 and accepted result V3 carry
the V3 source value. Historical receipt V1 and accepted result V2 remain V2-only.

## 5. Dominant access patterns and structures

| Access pattern | Structure or index |
|---|---|
| document lookup | primary/unique B-tree on document and revision IDs |
| eligible current revision | direct current-revision FK plus revision PK |
| ordered page selection | tuple sorted by physical page; page-number map for validation |
| member lookup | one manifest map keyed by `file_name` |
| duplicate detection | sets for pages, members, paths, and curriculum keys |
| run history | composite B-tree `(source_kind, source_revision_id, created_at DESC)` |
| document run lookup | partial B-tree on `educational_document_revision_id` |
| graph traversal | existing snapshot-local adjacency tables and indexes |
| immutable history | append-only revisions, runs, events, and graph snapshots |

At the initial scale of 10 documents and roughly 1,700 pages, resolving a request is
`O(manifest members + selected pages)`. Each member is hashed once at the materialization boundary,
so byte verification is `O(selected bytes)`. Lookup and history queries remain `O(log n)`. No
repeated list scan or N+1 Artifact lookup is required: manifests are indexed in memory once and the
small fixed set of Artifact rows is fetched by exact key.

## 6. Persistence and migration

An additive migration extends `knowledge_analysis_runs` with nullable
`educational_document_id`/`educational_document_revision_id` pointers and extends the source family
check to exactly three alternatives. A composite foreign key requires those two IDs to identify the
same immutable Document Revision; independent valid-but-mismatched IDs cannot be stored. Historical
rows remain valid. The migration applies the same pair invariant to Evidence Bundle entries and
widens the Graph Snapshot source-family check.

PostgreSQL stores no PDF or Markdown bytes. `canonical_request` remains a bounded pointer manifest;
the selected member descriptor list is limited to 33 entries. Large content stays in Artifact
storage.

## 7. Protocol families

New immutable contracts are:

- `knowledge-analysis-types/3.0`;
- `knowledge-analysis-request/3.0`;
- `knowledge-analysis-proposal-receipt/2.0`;
- `knowledge-analysis-result/3.0`;
- `catalog-application-request-v5` for document-selection creation;
- `workflow-role/1.5.0` with `knowledge-analysis-input-v2` and immutable
  `knowledge-analysis-proposal-result@2.0` (the worker proposal payload remains version 1.0);
- workflow definition `knowledge-analysis@2.0.0`;
- `resolved-execution-plan/4.0` for multi-member document materialization;
- additive Graph Snapshot/projection/Evidence Bundle readers where V3 sources are published.

All historical V2 resources, workflow definition `1.0.0`, role protocol `1.4.0`, and execution plan
`2.0` remain byte-pinned and readable. A V2 retry stays on V2 and its original workflow/preset
dependencies. A V3 retry stays on the same Document Revision and page range.

## 8. Transaction, concurrency, retry, and idempotency

Create uses the existing unique idempotency key and canonical submission hash. The source and
materialization descriptors are resolved in the same Catalog transaction that creates the run and
workflow. The plan pins every dependency before the command is queued.

Execution is at-most-one active Knowledge Analysis through the existing capacity policy. Worker
failure does not mutate the source or graph. Reconciliation is idempotent. A retry must name the
failed predecessor and exactly match its source kind, Document Revision, range, curriculum keys,
preset, and risk policy; it creates a new run but never changes the old run.

Graph publication is a separate operator-authorized idempotent transaction. It validates every
accepted run again, constructs one deterministic projection, writes immutable Artifacts, and then
atomically advances only the corpus current-snapshot pointer.

## 9. Dependency direction

```text
API / GUI / eomctl
  -> Catalog application command
     -> KnowledgeAnalysisApplicationService
        -> document/source resolver
        -> immutable workflow + execution-plan contracts
           -> Orchestrator materialization adapter
              -> fresh support worker
              -> proposal Artifact commit
     -> review/acceptance
     -> Graph publication
     -> bounded retrieval / Evidence Bundle
```

Contract packages import no service, SQLAlchemy, filesystem, or worker code. Domain validation does
not open files. Filesystem and NAS operations remain adapters owned by Catalog/Orchestrator.

## 10. Failure behavior

The boundary fails closed for missing/stale/retired/superseded Document Revisions, wrong source or
rights hashes, absent or non-canonical bundle manifests, page gaps, out-of-range pages, duplicate
members, materialization over budget, unsafe paths, symlinks, unexpected owner/mode, anchor pages
outside the selection, schema-family mismatch, and mixed V2/V3 receipt/result pointers.

No failure may fall back to a mutable current revision, a local staging path, the original PDF as an
oversized worker input, an unverified OCR file, general knowledge as attributed source evidence, or
a different publisher's page.

## 11. Simpler alternatives considered

**Raise the V2 100 MiB limit.** Rejected because it mutates historical semantics and places an
entire 289 MiB document in one worker context.

**Treat each Markdown page as an independent Content Intake source.** Rejected because it loses
logical edition/revision identity, rights inheritance, cross-page provenance, and current/superseded
document semantics.

**Anchor the graph to derived Markdown.** Rejected because Markdown is replaceable extraction;
original purchased PDF pages are the authoritative evidence.

**Analyze all 1,702 pages in one run.** Rejected because one-shot output/context bounds, failure
isolation, review quality, and cost are all worse. Bounded page-range runs can be independently
reviewed and accumulated in immutable snapshots.

## 12. Validation and rollout gates

Tests must cover old-schema byte hashes, JSON Schema/Pydantic parity, current/superseded revisions,
rights withdrawal/incompatibility, wrong Artifact family, page gaps and overflow, duplicate paths,
member hash drift, source-anchor range closure, multi-member authorization, non-symlink
materialization, idempotent replay, concurrent create, V2/V3 coexistence, graph publication,
Evidence Bundle resolution, index/constraint presence, migration cycle, absence of binary DB values,
package-resource parity, and clean-process imports.

Rollout is ordered:

1. ship dual-read schemas/models and additive migration;
2. install workflow definition `2.0.0` and a compatible immutable preset revision;
3. run one non-generating resolver/materialization smoke against a disposable page range;
4. request one separately authorized Knowledge Analysis run;
5. review and accept it;
6. publish one immutable pilot Graph Snapshot;
7. evaluate bounded retrieval before expanding page coverage.

No live Codex execution, graph publication, or repeated textbook analysis is authorized by the
source implementation itself.
