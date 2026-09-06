# Past-exam page media and visual knowledge analysis V1

## Responsibility and boundary

The assessment-learning surface exposes the exact rendered page images that already back a
reviewed past-exam bundle. The Application API authenticates and audits the request. The Catalog
application resolves metadata and bytes. Workers never read NAS and never write canonical media.
The orchestrator alone materializes validated page images into an isolated worker workspace.

## Canonical source and revision model

The canonical image remains the existing NAS `ArtifactRevision` member. PostgreSQL stores only
the assessment bundle, immutable layout-observation pointer, and Artifact/ArtifactRevision
metadata. A page identity is:

```text
assessment occurrence revision
  -> assessment source bundle revision
  -> immutable layout observation
  -> page_input_id + source_role + physical_page
  -> artifact_id + artifact_revision_id + member_path + sha256
```

No PNG bytes are copied into PostgreSQL. A browser preview and a Codex image input resolve the same
pinned member; a worker workspace copy is temporary materialization, not a second canonical source.

## Required pointers and resolution checks

Every page pointer carries the logical Artifact ID, immutable Artifact Revision ID, member path,
media type, SHA-256, dimensions, and physical page. Resolution verifies batch membership, exact
occurrence and bundle revision, layout self-hash, Artifact lifecycle/approval, manifest membership,
media type, byte bound, filesystem containment, regular-file identity, and content hash. Missing,
stale, dangling, duplicate, or mismatched pointers fail explicitly.

Past-exam knowledge analysis uses a new request/source protocol version. It pins the canonical Item
JSON plus the exact problem/answer page-image members recovered from that Item's immutable legacy
extraction provenance. OCR and normalized text remain auxiliary evidence; image observation is
required and every selected page is passed to Codex through the orchestrator image manifest.

The Graph snapshot manifest stores the smallest immutable Item Revision source pointer. Its paired
accepted-result Artifact retains the complete visual-source closure, while each projected node or
edge source pointer records the exact Item JSON or PNG Artifact Revision, member path, and hash that
its anchor cited. Retrieval re-resolves the accepted V9 request and validates the projected pointer
against that closed member set; it never substitutes the source PDF or a newer page render.

## Access patterns and data structures

- Exam lookup: indexed batch work-unit membership followed by the indexed bundle revision.
- Item-in-exam lookup: current Graph snapshot plus the occurrence metadata composite index, with an
  optional exact occurrence-revision and item-number predicate. The returned placement includes the
  parent exam identity/label and sorted curriculum unit IDs, so `exam -> item -> unit` and
  `unit -> exam/item` traversal share the same immutable placement row.
  API projection `assessment-item-occurrence-view/2.0` preserves the Graph's existing 32-hex node
  identity; V1 remains immutable because its wider node pattern never matched persisted Graph IDs.
- Page lookup: one layout observation followed by an ordered tuple keyed by `page_input_id`.
- Single image lookup: a map from page ID to the unique page pointer, then one Artifact Revision PK
  lookup.
- Worker materialization: a set of authorized Artifact Revision IDs and ordered immutable page
  tuple; no repeated list membership scan.
- Replacement analysis selection: append-only predecessor links with a latest accepted successor
  chosen per Item Revision; historical results are retained but only the current eligible result is
  published.

For the current archive the expected scale is hundreds of Items and at most 64 selected page images
per extraction request. Listing or materializing one exam is `O(p)` time and `O(p)` metadata space,
where `p` is its page count. Artifact lookup and identity checks are indexed `O(log n)` database
operations (or PK lookup); no binary data is held in a DB row.

## Transaction and concurrency boundary

Media reads are read-only and pin immutable revisions. Knowledge-analysis request creation and
successor selection occur in the existing Catalog transaction and use existing idempotency and
analysis-run constraints. NAS commit remains orchestrator-only. Graph publication reads accepted
immutable results and chooses one non-superseded result per Item Revision.

## Dependency direction and ownership

Web UI -> Application API/BFF -> Catalog private media protocol -> Catalog artifact adapter.
Knowledge-analysis application service -> source resolver -> domain contracts; orchestrator
resolver/materializer implements filesystem and worker boundaries. Domain contracts import no DB,
filesystem, HTTP, or service modules.

## Failure, retry, and idempotency

A media failure returns a stable missing/stale/hash error and never substitutes a newer revision.
Analysis failures retain immutable evidence. Corrected visual analyses are new successor runs with
new idempotency keys; no failed or accepted historical row is rewritten. Graph publication excludes
an accepted predecessor once a validated successor exists. Automatic work remains single-claim and
bounded by the existing batch policy.

## Simpler alternative considered

Teaching the old approved-item request to discover images transitively from Item JSON was rejected.
It would silently change historical request semantics, would not guarantee page images for
text-only Items, and would omit the extraction provenance required for reproducibility. Copying PNG
bytes into PostgreSQL was also rejected because it duplicates canonical artifacts, bloats backups,
and bypasses the existing immutable NAS boundary.

## Verification

Tests cover JSON Schema/Pydantic parity, missing or stale layout and image pointers, hash mismatch,
duplicate page IDs, deterministic ordering, authorized media streaming, exact worker image
materialization, required image observations, idempotent successor creation, and exclusion of
superseded analyses from Graph publication. Persistence tests assert that no PNG payload is stored
in PostgreSQL.
