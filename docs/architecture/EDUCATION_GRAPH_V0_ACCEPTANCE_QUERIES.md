# Education Graph V0 Acceptance Queries and Legacy Mapping Scenarios

Status: Accepted Phase 0 acceptance design; fixtures are synthetic and schema implementation is
deferred to Phase 1.

Last reviewed: 2026-08-23 UTC

## 1. Purpose

These scenarios define the first GraphRAG use cases before choosing graph infrastructure or adding
an ontology. Each result must return canonical supporting pointers, not only prose or similarity
scores.

## 2. Fixture Families

Future test fixtures use synthetic identifiers and small Markdown/JSON members. They represent:

- one immutable curriculum framework with one major unit, two middle units, and bounded minor units;
- approved textbook/source revisions with paragraph, table, figure, and equation members;
- approved EOM, external-human, and institutional past-exam Item Revisions;
- stable Item block, statement, and choice IDs;
- one Product Revision “00모의고사” with forms 1 through 12;
- Item A at form 1 question 12 and Item B at form 5 question 7;
- one exact Item Revision reused in a second publication;
- one derived Item with a different identity and explicit source lineage;
- one redacted synthetic legacy workbook mapping source.

Large/binary source bytes are not committed to Git. Synthetic tabular fixtures stay small; any
realistic binary fixture is an approved test Artifact with a manifest and hash.

## 3. Query Q1 — Curriculum Subtree Table Evidence

Request intent:

> Find all approved table-shaped evidence beneath one pinned curriculum middle unit.

Required input pointers:

- Graph Snapshot Revision;
- Curriculum Framework Revision;
- stable middle-unit ID;
- allowed source classes and rights policy;
- `include_descendants=true`;
- bounded result/evidence budget.

Acceptance:

- return only tables aligned to the middle unit or its descendant minor units;
- distinguish source `TableRef` from Item `TableBlockRef`;
- include exact Document/Item/Artifact Revisions, member/element ID, schema/media, hash, and source
  anchor;
- deterministic ordering and deduplication by immutable pointer;
- exclude sibling-unit, unapproved, unauthorized, stale, and hash-mismatched material;
- query plan uses the revision-scoped curriculum closure and indexed element type, not repeated
  Markdown or Item JSON scans.

## 4. Query Q2 — Structured Prior Items

Request intent:

> Find approved items under the same curriculum scope that contain both a table and a ㄱ/ㄴ/ㄷ
> statement set, then provide grounded prior-pattern and negative-similarity evidence.

Acceptance:

- require exact membership of both element kinds using indexed Item Element refs;
- return the pinned Item Revision and exact block/statement IDs;
- filter origin dimensions independently from interaction type;
- institutional past-exam filtering requires an Organization and Assessment Occurrence Revision;
- EOM human/AI items remain distinguishable without changing `item_type_key`;
- answer-bearing edges are available only to an authorized author/reviewer projection;
- similarity is a scored derived observation, never a canonical identity or duplicate fact;
- Evidence Bundle remains within item/node/claim/token budgets.

## 5. Query Q3 — Product/Form/Question Usage History

Request intent:

> Where was this exact Item Revision published, and at which Product, Form, section, and question
> position?

Acceptance:

- start from exact Item Revision, not mutable Item current revision;
- return canonical Usage Record, Product/Deliverable Revision, Form Revision, Assembly Revision, and
  Publication Revision pointers;
- prove Item A appears at “00모의고사” form 1 question 12;
- prove Item B appears at form 5 question 7;
- distinguish reuse of the same Item Revision, use of another revision of the same logical Item,
  and a derived/similar Item;
- distinguish Usage Plan, assembled placement, published Usage Record, and Distribution Event;
- preserve historical results after a product current pointer or Item current pointer advances;
- reject duplicate positions and graph/ledger disagreement.

## 6. Origin Acceptance Matrix

| Scenario | Source domain | Creation method | Required supporting pointer |
| --- | --- | --- | --- |
| human new item | external individual or reviewed internal author domain | human authored | source/workflow provenance; no occurrence |
| institutional past item | external institution | known or explicit unknown | Organization + Assessment Occurrence + source evidence |
| EOM item | internal EOM | human, AI assisted, or AI generated | exact workflow/manual provenance |
| EOM adaptation | internal EOM | adapted | exact source Item/Document Revision derivation |

A verified-institution query excludes unresolved legacy organization text. A past-exam query
excludes items that have no exact occurrence even if their tags or filename contain “기출”.

## 7. Legacy Workbook Mapping Scenario

The synthetic workbook represents common columns such as product title/edition, form number,
section, question number, legacy Item key, points, usage role, and optional publication date.

The mapping proposal must include:

- source intake batch, source file, Artifact Revision, SHA, sheet, and stable source row identity;
- mapping-contract revision and normalized row hash;
- resolved Product/Form/Item logical and revision pointers;
- proposed section, positive position, points, and usage role;
- resolution state `RESOLVED`, `UNRESOLVED`, `CONFLICT`, or `REJECTED`;
- reviewed reason/evidence for every non-exact match.

Acceptance rules:

- exact replay is idempotent;
- the same product/form/position cannot map to two Items;
- duplicate workbook rows deduplicate by source row identity and normalized hash;
- conflicting rows remain quarantined and create no Usage Record or graph edge;
- a missing revision never resolves to `Item.current_revision_id` silently;
- imported Usage Records pin exact approved or historically approved/superseded Item Revisions;
- source and committed counts reconcile deterministically;
- student names, accounts, answers, scores, and attempts are absent.

## 8. Performance and Quality Baselines

For the synthetic fixture, exact pointer and ordering correctness is mandatory. Before a larger
backend choice, measure on representative approved data:

- indexed result count and query latency for Q1–Q3;
- retrieval recall against a human-reviewed gold set;
- provenance precision and unsupported-edge count;
- deterministic Evidence Bundle hash and token estimate;
- PostgreSQL query plans showing indexed hierarchy, element, and reverse-usage lookup;
- simple lexical/vector baseline versus graph/hybrid result quality.

No dedicated graph database, embedding model, or GraphRAG global/community mode is accepted from
these small fixtures alone.
