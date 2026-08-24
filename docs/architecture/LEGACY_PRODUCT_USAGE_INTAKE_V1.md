# Legacy Product and Usage Intake V1

Status: Phase 11 implementation contract

Date: 2026-08-24 UTC

## Responsibility and system boundary

Content Intake owns the immutable source workbook and its exact Artifact Revision. Catalog owns
reviewed Product, Form, Assembly, Publication, and append-only Usage history. A spreadsheet reader
is an untrusted-input adapter: it may produce schema-valid proposals, but it cannot create a
canonical placement or Usage Record. The existing graph publisher consumes only committed ledger
pointers and produces a rebuildable projection; the graph never becomes usage authority.

No workbook bytes, Item content, or publication output bytes are stored in PostgreSQL. Workers do
not parse or commit legacy usage. The import application service is the only transaction owner.

## Canonical sources and revision model

The canonical chain is:

```text
Content Intake batch
  -> exact source_file_id
  -> source Artifact Revision + SHA-256 + XLSX member
  -> released Legacy Mapping Contract Revision + SHA-256
  -> immutable Import Run
  -> immutable Row Proposals
  -> reviewed RESOLVED rows
  -> Product Revision -> Form Revision -> Assembly Revision -> Placement
  -> Publication Revision -> append-only Usage Record V1 detail
  -> rebuildable product/usage graph projection
```

The mapping contract identifies one worksheet, one header row, and an explicit column name for
every accepted field. It never stores a host path. A new column meaning or normalization rule gets
a new mapping-contract revision. Historical imports pin the exact revision and never resolve a
mutable current mapping.

## Pointer and proposal contract

Each import request pins intake batch, source file, Artifact logical/revision IDs, member path,
schema reference, media type, workbook SHA-256, mapping-contract revision ID, and mapping hash.
Resolution validates
all of them before opening the workbook. The source must be an approved regular non-symlink member
at `<artifact-root>/<logical-id>/<revision-id>` and must match the stored source-file row
byte-for-byte.

Each normalized row has a stable source row key and a canonical row SHA-256. It contains reviewed
machine keys plus complete immutable revision pointers. Exact Product, Product Revision, Form,
Form Revision, Item, and Item Revision pointers must agree. An omitted revision is never replaced
with a current/latest revision.

Proposal states are `RESOLVED`, `UNRESOLVED`, `CONFLICT`, and `REJECTED`. Only `RESOLVED` plus an
explicit `APPROVE` decision can be committed. All other states are quarantine. Candidate pointers
are bounded and informative only; they are never selected automatically. Reason codes are closed
machine values, not copied spreadsheet text.

## XLSX adapter and limits

The V1 adapter reads only Office Open XML `.xlsx` packages with the Python standard library. It
rejects encrypted, macro-enabled, external-link, traversal, duplicate-entry, oversized, excessive
sheet/string/cell, formula, error, merged-identity, and unsupported cell payloads. It never executes
formulas and never follows external relationships. Shared strings, inline strings, booleans, and
plain numeric cells are decoded under explicit byte/cell limits. Formula cells are quarantined
rather than evaluated.

The adapter emits only small normalized strings and integers. Original workbook bytes stay in the
Artifact store. This avoids a new spreadsheet dependency and its transitive parser surface. If
future files require broader Excel semantics, that requires a separately reviewed dependency and
sandboxed adapter.

## Access patterns and data structures

- mapping lookup: unique `(mapping_contract_id, revision_number)` and revision ID, O(log n);
- import replay: unique `(source_file_id, source_artifact_revision_id,
  mapping_contract_revision_id)`, O(log n);
- row replay: unique `(import_id, source_row_number)`, O(log n);
- duplicate-key conflict lookup: non-unique B-tree `(import_id, source_row_key)`, O(log n + k);
- ordered Form/Assembly iteration: B-tree on owner plus ordinal/position, O(log n + k);
- exact placement lookup: unique Assembly Revision plus section/position, O(log n);
- reverse usage: B-tree on exact Item Revision, Product/Form/Publication revisions, O(log n + k);
- workbook columns: one bounded map from normalized header to index, O(1) per field;
- duplicate row/placement detection: sets and database unique constraints, O(1) expected;
- graph projection: adjacency tuples sorted once, O(n log n), with canonical rows as input.

Expected initial scale is hundreds of workbooks, at most 100,000 rows per workbook, hundreds of
thousands of placements, and millions of immutable usage records. PostgreSQL stores only bounded
documents, pointers, states, hashes, and relationships. No N+1 pointer resolution is permitted;
commit validates each referenced entity set with batched indexed queries.

## Persistence and immutable usage detail

Historical V0 `deliverables`, `deliverable_revisions`, and `usage_records` remain unchanged. Their
V0 placement uniqueness omits Form identity, so it cannot represent twelve forms that each contain
question 1. V1 therefore adds Form/Assembly/Publication tables and a separate append-only
`usage_records_v1` table rather than corrupting V0 `section` values or weakening its historical
constraint. V1 pins Product, Form, Assembly, Placement, Publication, Item Revision, points, usage
role, source kind/key/hash, and contract version. Read projections may union the two explicitly;
they never fabricate V1 pointers for V0 rows. The placement snapshot must equal the referenced
immutable Assembly placement.

Proposal and review rows are append-only after creation/decision. The import header alone is a
versioned state-machine row so it can move `PROPOSED -> REVIEWED -> COMMITTED` while its pinned
source, mapping, request hash, and counters remain unchanged. Corrections create a new import
against a new source or mapping revision. Canonical Form, Assembly, Publication, placement, and V1
Usage rows are immutable after release. Graph rows are derived and may be rebuilt from these
records.

## Transaction, concurrency, retry, and idempotency

Proposal creation resolves and hashes the workbook outside the canonical commit transaction, then
inserts one import plus all proposal rows atomically. The import identity is a digest of the pinned
source revision and mapping revision. Same identity/same request hash returns the prior import;
same identity/different hash fails with `LEGACY_USAGE_IMPORT_IDEMPOTENCY_CONFLICT`.

Review locks one proposal row and records one immutable decision. Same decision replay is
idempotent; a different decision fails. Commit locks the import and all approved rows, validates
their exact pointer chains in batches, creates or verifies deterministic Assembly, Publication,
and Usage identities, and commits everything in one transaction. A placement conflict rolls back
the whole reconciliation group. It never partially publishes a product form.

## Graph projection

The V1 product/usage projection contains pointer-only nodes for Product Revision, Form Revision,
Assembly Revision, Publication Revision, Item Revision, and Usage Record, and edges for containment,
placement, publication, and actual use. Every edge pins its source Usage/Placement identity and
hash. The projection is deterministic and can be attached to a new graph snapshot only by the
existing graph publication boundary. Import does not mutate a published snapshot.

## Failure behavior

Malformed ZIP/XML, formulas, external links, unknown columns, missing exact revisions, stale or
hash-mismatched pointers, ambiguous candidates, duplicate positions, mixed ownership chains,
changed source-row hashes, non-approved decisions, and graph/ledger disagreement fail closed with
stable codes. Quarantine creates no canonical Assembly, Publication, Usage, or graph edge.

## Dependency direction and simpler alternative

JSON Schema and frozen value contracts live in `catalog_contracts`. Catalog services own parsing
adapters, proposal/review application services, SQLAlchemy records, and transactions. API/CLI/GUI
may submit typed commands and render bounded projections; they do not parse spreadsheets or
calculate placements.

Direct Excel-to-Usage insertion is simpler but insufficient: it loses immutable source identity,
silently guesses revisions, makes retry ambiguous, bypasses review, and cannot explain conflicts.
Encoding form/position in free text or treating graph edges as the ledger also destroys ordering
and historical replay. The two-stage proposal plus immutable pointer chain is the smallest design
that preserves the required audit and quarantine boundary.

## Phase boundary

Phase 11 source work may add immutable contracts, additive migration 0015, parser/proposal/review
services, deterministic projection, and disposable-database tests. It does not authorize importing
a production workbook, publishing a production graph, running Codex, building HWPX, or mutating a
canonical production Product/Item. Those remain Phase 12 rollout gates.
