# Legacy Assessment Item Corpus Ingestion V1

Status: design for protocol-first implementation; no live inventory commit, Content Intake,
worker execution, Item registration, or Graph publication is authorized by this document.

Last reviewed: 2026-09-01 UTC

Related decisions and designs:

- [Manual Content Intake ADR](../adr/0014-manual-content-intake.md)
- [Item and Revision Separation ADR](../adr/0017-item-and-revision-separation.md)
- [Item Component Pointers ADR](../adr/0018-item-component-pointers.md)
- [Item Origin and Assessment Occurrence ADR](../adr/0038-item-origin-and-assessment-occurrence.md)
- [Legacy Source Inventory Phase 2](LEGACY_SOURCE_INVENTORY_PHASE2_DESIGN.md)
- [Legacy Source Selection to Content Intake](LEGACY_SOURCE_SELECTION_CONTENT_INTAKE_BRIDGE_V1.md)
- [Item Origin, Organization, and Assessment Occurrence V1](ITEM_ORIGIN_OCCURRENCE_V1_DESIGN.md)
- [Education Knowledge and Item GraphRAG](EDUCATION_KNOWLEDGE_ITEM_GRAPHRAG.md)
- [Role Guidance and Graph Integration](ROLE_GUIDANCE_AND_GRAPH_INTEGRATION_V1.md)

## 1. Purpose and current corpus observation

The corpus under the protected NAS root currently materialized as
`/mnt/nas/0613appenddataset` is the first substantial legacy assessment-item source available to
EOM. It complements the textbook corpus: textbooks provide reviewed scientific source knowledge,
whereas this corpus provides actual assessment occurrences, item structures, answer keys,
explanations, internal curriculum labels, difficulty observations, and historical authoring or
digitization evidence.

The path is a storage location, not an identity. It must never be embedded in worker contracts,
PostgreSQL rows, Graph nodes, or public APIs. The protected root configuration maps it to a closed
root alias.

A read-only metadata observation on 2026-09-01 found:

| Observation | Value |
| --- | ---: |
| total bytes | 965,307,504 |
| regular files | 551 |
| directories including root | 152 |
| first-level directories | 54 |
| PDF | 276 |
| HWP | 137 |
| XLSX | 112 |
| HWPX | 25 |
| CSV | 1 |

Common source bundles contain a problem PDF, answer/explanation PDF, HWP or HWPX reconstruction,
and an XLSX classification workbook. Sample workbooks contain item number, internal difficulty,
inquiry flag, large/middle curriculum labels, volume, science domain, source-exam subject, display
name, and legacy numeric identifiers. These values are useful observations, not trusted canonical
facts.

The corpus is structurally irregular. Observed examples include copied files, sample files, a June
folder below a March chemistry folder, a July bundle below a March earth-science folder, a 2022
source inside a directory named for 2021, and workbooks whose sheet names differ from their parent
directory. Therefore neither directory name nor filename is sufficient evidence for identity or
pairing.

## 2. Responsibility and system boundary

This feature converts untrusted legacy assessment sources into reviewable, provenance-complete
proposals. It does not allow a worker to register Items, publish Graph data, modify NAS, or infer
canonical examination identity from filenames.

```text
protected legacy root
  -> read-only inventory observation
  -> reviewed source relations and rights
  -> immutable Content Intake source Artifact Revisions
  -> deterministic assessment-bundle proposal
  -> reviewed bundle and occurrence identity
  -> deterministic page/image/worksheet materialization
  -> orchestrated one-shot legacy-item analyst jobs
  -> schema-valid extraction proposals
  -> deterministic coverage and cross-source validation
  -> human review for conflicts/uncertainty
  -> approved Item Revision + origin/occurrence pointers
  -> optional immutable Graph Snapshot projection
```

Catalog owns source selection, reviewed bundle identity, occurrence resolution, Item import, and
Graph projection. The Orchestrator owns worker plans, staging, validation, and Artifact commit.
Workers read only exact staged inputs and return local schema-constrained results. Workers never
read the NAS mount directly and never communicate with each other.

## 3. Canonical sources and identities

The design keeps the following identities separate:

```text
legacy inventory observation
  -> reviewed selected source files
  -> Content Intake source Artifact Revisions
  -> Assessment Source Bundle Revision
  -> Assessment Occurrence Revision
  -> pilot Workflow / Step Run / Job / Result Artifact Revision
  -> later Extraction Batch / Work Unit / Result Revision
  -> Item / immutable Item Revision
  -> Item Origin Profile
  -> optional Graph Snapshot Revision
```

### 3.1 Raw file

Every raw file is preserved as an immutable source Artifact Revision after reviewed Content Intake.
Exact duplicate bytes may reuse one canonical Artifact Revision, but every observed legacy path
remains a separate inventory/source observation so provenance is not lost. A path alias never
becomes the Artifact identity.

### 3.2 Assessment Source Bundle

An `AssessmentSourceBundle` is a logical collection of exact source revisions believed to describe
one assessment occurrence and subject/form. Its immutable revision classifies members by reviewed
role:

- `PROBLEM_DOCUMENT`;
- `ANSWER_EXPLANATION_DOCUMENT`;
- `STRUCTURED_RECONSTRUCTION` for HWP/HWPX;
- `ITEM_CLASSIFICATION_WORKBOOK`;
- `TYPE_CODE_REFERENCE`;
- `OTHER_REVIEWED_EVIDENCE`.

Bundle membership never implies that two files are byte-equivalent. Every member pins Artifact,
Artifact Revision, SHA-256, media type, schema or format profile, and source inventory pointer.
Changing membership, role, or occurrence resolution creates a new bundle revision.

### 3.3 Assessment Occurrence

The occurrence is the real examination event, not the folder. It pins a reviewed Organization
Revision, exam family, administration year/date, session, subject, form/region when applicable,
source evidence, and rights revision. Filename-derived labels remain proposals until resolved.

### 3.4 Item

The Item Registry remains canonical. One source occurrence item number normally produces one Item
Revision, regardless of whether the same content appears in PDF, HWP/HWPX, and XLSX members. Those
members become source evidence for the same proposal; they do not create duplicate Items.

An imported historical item is not forced to pretend that every source item is an EOM-generated
item. The generic `AssessmentItemContent` contract supports variable paragraphs, tables, images,
equations, statement sets, choices, constructed responses, solutions, and scores.

The intended EOM-generated question template is broader than the currently deployed validator:

- the ordered `ㄱ`, `ㄴ`, `ㄷ` statement set is required;
- five statement-combination choices remain required;
- stimulus composition is variable and may be table-only, image-only, multiple images, or a
  table-and-image combination;
- equations are optional and may accompany any of those compositions;
- the renderer must preserve the ordered body composition rather than require one table, one image,
  and one equation.

The current `eom-question-template-v1` validator's exact six-block/one-table/one-image/one-equation
rule is therefore an implementation limitation, not the product template definition. It must be
preserved for historical builds and replaced by an additive successor profile and renderer
contract. Source extraction records all observed item forms. Generation retrieval can then select
the source-grounded patterns with `uses_statement_set=true` and a compatible visual composition
without misclassifying non-ㄱㄴㄷ historical items.

## 4. Source authority and conflict precedence

No source type is globally trusted. A reviewed bundle records the intended precedence for each
field. The initial default is:

1. problem PDF: visual appearance, item order, item number, visible stem/data/choices;
2. answer/explanation PDF: official answer and explanation observation;
3. HWP/HWPX reconstruction: structured text, equations, tables, and recoverable media comparison;
4. XLSX/CSV: internal curriculum, difficulty, inquiry, legacy ID, and operational classification
   observations.

This precedence does not silently resolve disagreement. A mismatch between problem PDF, answer
document, reconstruction, and workbook becomes a typed conflict. The source-specific observations
are retained with exact anchors until a reviewer decides which value becomes canonical.

### 4.1 Initial visual audit observations

A bounded visual review of all four pages from one 2018 and one 2024 Integrated Science problem
paper confirmed that the extraction ontology must represent, at minimum:

- image-only items with one or several labelled panels;
- table-only items;
- a table and diagram in one stimulus;
- graphs, timelines, flow diagrams, particle models, apparatus drawings, maps/cross-sections,
  photographs, cartoons, article excerpts, and text-only stimuli;
- inset labels, legends, arrows, blank symbols, callouts, and question-specific panel order;
- both `ㄱ`/`ㄴ`/`ㄷ` combination interactions and ordinary five-choice interactions.

The worker therefore records one visual observation per meaningful representation and an optional
composite observation spanning multiple representations. It does not flatten a table into an image
or merge several panels into one opaque description.

## 5. Protocols to add

Existing immutable inventory, selection, rights-review, source-relation, Content Intake, Item,
Artifact, and Graph schemas should be reused unchanged. The following additive Draft 2020-12
contracts are required before worker behavior:

### 5.1 `assessment-source-bundle-proposal/1.0`

Contains deterministic candidate key, exact source pointers, proposed member roles, parsed
occurrence observations, pairing evidence, conflicts, and proposal hash. It cannot claim reviewed
organization or occurrence identity.

### 5.2 `assessment-source-bundle/1.0`

Contains logical bundle ID, immutable revision ID/number, previous revision, exact reviewed member
pointers, exact Assessment Occurrence Revision pointer, rights pointer, review evidence, lifecycle,
and canonical manifest hash.

### 5.3 `assessment-layout-observation/1.0`

Describes every problem and answer page, visible item-number observations, normalized integer
bounding boxes, reading order, cross-page continuation, and source anchors. Coordinates use a
closed integer space such as 0..10,000 relative to the exact page-image revision; floating-point
pixel inference is not persisted.

### 5.4 `legacy-item-extraction-request/1.0`

Pins the exact bundle revision, occurrence revision, work-unit ordinal, expected item numbers,
page-image pointers, bounded source excerpts, workbook-row observations, HWP/HWPX comparison
members, rights, schema versions, preset revision, and output limits. It contains no NAS path.

### 5.5 `legacy-item-extraction-result/1.0`

Returns a tuple of item proposals. Each proposal contains:

- occurrence item number and proposed stable source key;
- generic `AssessmentItemContent` candidate;
- per-block, per-choice, per-answer, and per-solution source anchors;
- exact image/table/equation observations and derived-media proposals;
- curriculum and difficulty observations with source kind;
- origin/organization/occurrence observations;
- conflicts and unresolved ambiguities;
- page and item coverage evidence;
- canonical result hash.

The worker returns neither database IDs it is not given nor arbitrary relationship names.

### 5.6 `legacy-item-extraction-acceptance/1.0`

Records deterministic validator results, reviewer decisions, accepted/rejected fields, corrections,
coverage status, and exact worker-result pointer. It is the only bridge from a proposal to Item
import.

### 5.7 `legacy-item-corpus-coverage/1.0`

Pins the inventory, bundle revisions, all expected occurrence/item positions, accepted result
pointers, gaps, conflicts, rejected records, and a deterministic coverage hash. `COMPLETE` requires
zero missing expected item positions. A batch completing its queue is not automatically complete
coverage.

## 6. Deterministic intake and bundle discovery

Bundle discovery must not begin with a model. The deterministic adapter performs:

1. fd-relative, no-follow inventory and SHA-256 observation under the protected root alias;
2. signature/media validation independent of suffix;
3. exact-byte duplicate indexing by SHA-256;
4. bounded filename/path token observations for date, subject, session, and document role;
5. safe PDF metadata/page count observation;
6. safe XLSX archive inspection without formula execution, macros, external links, or recalculation;
7. safe HWPX ZIP validation with entry-count, expanded-size, path, relationship, and media limits;
8. HWP classification without executing or loading embedded macros;
9. candidate bundle edges with reason codes and confidence classes;
10. a review queue for ambiguous or conflicting components.

Maps keyed by SHA-256, inventory entry key, and normalized occurrence candidate provide expected
O(1) lookup. Candidate relations use a sparse adjacency list. Union-find may combine only
high-confidence, non-conflicting exact relations; fuzzy filename similarity can only create review
edges and never auto-merge a bundle.

The current 551-file corpus exceeds the existing Content Intake limit of 500 files for one batch.
It must be split by reviewed source bundle or a small bounded group of related occurrences, not by
raising the limit for convenience.

## 7. Safe materialization and deterministic preprocessing

Original files remain immutable. Derived inputs are explicit temporary or Artifact-backed
materializations:

- PDF pages become pinned page images only when the rights revision permits page-image
  materialization;
- extracted PDF text is auxiliary OCR/search evidence and never substitutes for page images;
- HWP/HWPX text, tables, equations, and media are extracted in a no-network, no-macro sandbox;
- XLSX values are read as stored data; formulas are never calculated or executed;
- item crops retain the source page-image pointer, exact normalized bounding box, transform
  version, dimensions, and output SHA-256;
- no worker receives a directory-wide mount or unbounded workbook/archive.

Page images and crops are canonical Artifact Revisions only when later audit or Item component
resolution requires them. Otherwise they remain disposable workspace materializations. PostgreSQL
stores pointers and metadata, never PDF, HWP, HWPX, XLSX, PNG, or Markdown bytes.

## 8. Analyst workflow assigned to one Codex slot

Create a successor `legacy-item-analysis` Execution Preset for the existing `support` worker role.
Do not repurpose the textbook `knowledge-analysis` preset and do not edit a released preset. Use a
dedicated eligible support slot while other long-running analysis owns another slot.

The initial reviewed policy should use:

- fresh one-shot Codex context for every work unit;
- an exact released model/effort pair selected through capability evidence, initially the same
  `gpt-5.6-terra` / `xhigh` class already validated for multimodal analysis;
- a bounded maximum execution time, initially 7,200 seconds;
- read-only sandbox and disabled network;
- all required page PNGs through the image-input boundary;
- exact schema output and result-size bounds;
- one active legacy-item analysis work unit for the pilot;
- `CONTINUE_AND_COLLECT` aggregate behavior;
- no automatic retry and no session resume.

The job-local materialization is conceptually:

```text
workspace/
  AGENTS.md
  instructions/platform.md
  instructions/legacy-item-analysis.md
  references/guidance/index.md
  references/guidance/integrated-science-single-item-authoring.md
  references/evidence/curriculum-scope.md
  source/manifest.json
  source/problem/page-*.png
  source/answer/page-*.png
  source/item-crops/*
  source/reconstruction/*
  source/workbook/observations.json
```

All reference/source bytes are untrusted data. They never become instructions and cannot override
`AGENTS.md`, JSON Schema, or the fixed sandbox.

## 9. Work-unit sizing

One 20-item examination should not automatically become one giant worker result. The pipeline uses
two levels:

1. **layout observation**: inspect every exact problem/answer page and propose item boundaries,
   item numbers, continuations, and answer positions;
2. **item extraction work units**: process a deterministic ordered subset, initially at most four
   items, with their full source page plus item crop and exact answer/reconstruction/workbook
   evidence.

The four-item default is a pilot value, not a permanent constant. Measure worker duration, output
bytes, validation rate, and reviewer correction rate for one-, four-, and eight-item units before
changing it. Work-unit identity pins the exact bundle revision and ordered item-number tuple, so a
different partition never reuses an old result accidentally.

## 10. Coverage and failure behavior

This corpus must not repeat the earlier failure mode where one malformed result stopped hundreds of
independent ranges. Per-result validation remains strict, but aggregate scheduling continues.

```text
PENDING -> STAGED -> RUNNING -> PROPOSED -> VALIDATING
                                      -> ACCEPTED
                                      -> NEEDS_REVIEW
                                      -> FAILED
```

One terminal work-unit failure is recorded and does not block unrelated pending units. When the
queue is exhausted:

- zero gaps/conflicts: `SUCCEEDED`;
- at least one failed or unresolved unit: `COMPLETED_WITH_GAPS` or the existing externally mapped
  blocked state with an exact gap manifest;
- a later explicit continuation batch uses `REUSE_ACCEPTED` pointers and executes only missing or
  corrected work units.

Accepted artifacts are never copied into the continuation. They are referenced by exact result
revision and hash. Final publication requires a coverage manifest proving every reviewed bundle,
page, expected item number, answer position, and extraction unit exactly once, with no gaps,
overlaps, or duplicate accepted pointers.

## 11. Deterministic acceptance checks

Before an extraction result can become accepted, validators require:

1. every supplied page image has exactly one ordered observation;
2. every expected item number appears exactly once in the work unit;
3. every body block, statement, choice, answer, explanation, table, equation, and image proposal has
   at least one exact source anchor or an explicit uncertainty;
4. every source anchor resolves to a supplied immutable source/page revision and valid bounds;
5. all item reference invariants pass `AssessmentItemContent` typed validation;
6. choice count, correct answer, and answer-document mapping are coherent;
7. problem, answer, HWP/HWPX, and workbook disagreements are retained as conflicts;
8. curriculum codes resolve only through the reviewed EOM editorial outline; labels do not invent
   stable keys;
9. legacy numeric IDs remain source observations and are not adopted as EOM IDs;
10. proposed media are regular, non-symlink, bounded, hash-matching derived artifacts;
11. occurrence and organization values are reviewed pointers or explicit unresolved observations;
12. no answer-bearing data enters a student-safe or authoring retrieval projection without an
    explicitly permitted use case;
13. no source or derived binary is stored in a PostgreSQL row;
14. result and acceptance hashes use canonical serialization.

The expected item-number set is itself reviewed. It is reconciled from visible problem numbers,
answer numbers, and workbook rows; no single source silently defines completeness.

## 12. Duplicate and similarity policy

Three different meanings must remain separate:

- **duplicate source bytes**: exact same SHA-256; reuse canonical Artifact bytes while preserving
  every source observation;
- **multiple representations of one occurrence item**: PDF/HWP/HWPX/XLSX evidence merged into one
  extraction proposal keyed by reviewed occurrence revision plus item number;
- **similar or reused item content across occurrences**: never auto-merge Items. Create a scored
  similarity candidate for review and later project `SIMILAR_TO_ITEM`, `DERIVED_FROM`, or a shared
  assessment-pattern relation only after evidence supports it.

Candidate similarity may use normalized text hashes, equation/table signatures, perceptual image
features, and curriculum/structure filters. These are caches or observations, not canonical item
identity. Exact Item/Revision pointers remain authoritative.

## 13. Canonical outputs and derived views

One accepted extraction can produce several projections without duplicating authority:

| Output | Authority |
| --- | --- |
| raw PDF/HWP/HWPX/XLSX | immutable source Artifact Revisions |
| structured item JSON | canonical `AssessmentItemContent` Artifact Revision |
| Item/Item Revision | canonical Catalog identity and lifecycle |
| item images | canonical media Artifact Revisions with derivation anchors |
| Markdown item view | deterministic derived projection for human/worker reference |
| origin/occurrence | canonical reviewed Catalog pointers |
| curriculum/knowledge/item Graph | rebuildable immutable Graph Snapshot projection |
| historical workbook fields | immutable source observations or reviewed metadata snapshot |

Markdown must not become a second canonical Item. It should be regenerated from the exact Item
Revision and include bounded front matter containing only typed identities, revisions, hashes,
classification observations, and source-anchor summaries. Large images and files remain pointers.

## 14. Graph integration

After Item and origin/occurrence registration, Graph publication may add pointers and edges for:

- Item Revision and stable item elements;
- assessed and required concepts;
- represented concepts in tables, figures, equations, and statements;
- curriculum alignment;
- Organization and Assessment Occurrence observation;
- source-document/page evidence;
- reusable assessment patterns;
- reviewed similarity or derivation;
- later product/form placement history through the existing legacy-usage contracts.

The graph never copies complete item content, answer text, source documents, or media. Answer-bearing
edges and solution evidence require role-aware retrieval policies. An item-analysis result cannot
publish directly; only accepted Catalog pointers enter a Graph Snapshot proposal.

## 15. Access patterns, structures, indexes, and scale

| Access pattern | Structure/index | Expected behavior |
| --- | --- | --- |
| exact source lookup | map/B-tree by inventory key, Artifact Revision, SHA-256 | `O(log n)` persistent, expected `O(1)` in-memory |
| exact duplicate detection | hash map/index by SHA-256 | expected `O(1)` candidate lookup |
| bundle candidate grouping | sparse adjacency list; reviewed high-confidence union-find | `O(n + e)` after ordered scan |
| occurrence item lookup | unique `(occurrence_revision_id, item_number, form_key)` | conflict-safe `O(log n)` |
| work scheduling | indexed `(batch_id, state, ordinal)` plus slot lease constraints | bounded claim with no duplicate run |
| coverage | ordered range/item-position rows and sets | `O(r)` deterministic audit |
| source anchors | indexed exact source revision/page/item position | `O(log n + k)` |
| similarity candidates | bounded feature index scoped by subject/curriculum | candidate generation only |
| Graph traversal | existing indexed adjacency and curriculum closure | bounded by retrieval policy |

The observed corpus is small enough for deterministic inventory in memory, but the persistent model
should assume hundreds of thousands of Item Revisions and millions of source anchors. PostgreSQL
stores one anchor row or compact typed value per meaningful relationship, not page pixels or full
worker JSON blobs. GIN is appropriate only for reviewed queryable JSON metadata; core identity and
state predicates use B-tree/unique/partial indexes.

## 16. Transactions, idempotency, and concurrency

The first bounded one-item pilot deliberately uses the existing Workflow Instance, Step Run,
platform Job, resolved execution plan, and immutable result Artifact Revision as its authoritative
execution record. The pilot does not add a parallel run table or copy worker result JSON into
PostgreSQL. Its operator request is body-hash-bound to one idempotency key, the workflow permits one
step attempt, and the result receipt pins the exact request/result identities and Artifact Revision.

Bulk corpus execution remains a separate additive phase. Before more than the reviewed pilot is
submitted, it requires pointer-only extraction batch/work-unit/event records with an indexed FIFO
claim boundary and a unique `(bundle_revision_id, work_unit_ordinal,
expected_item_numbers_sha256)` identity. Those records will point to the existing workflow, plan,
job, and result Artifact; they will not duplicate the canonical request or result payload. This
keeps the minimal pilot simple without weakening the later gap-free coverage requirement.

- inventory is idempotent by root configuration, policy revision, sorted entries, and hashes;
- source selection and Content Intake pin exact inventory and rights revisions;
- bundle creation is unique by reviewed deterministic bundle key and request hash;
- work-unit creation is unique by batch, bundle revision, ordinal, and item-number tuple;
- one work unit permits one submission attempt; response-loss replay uses the same key/body;
- worker result staging and validation occur before Artifact commit;
- accepted result Artifact commit and acceptance record use existing idempotent Artifact semantics;
- Item import atomically creates Item Revision, components, provenance/origin data, event, and
  current pointer under optimistic locking;
- graph publication reads only approved immutable pointers and commits one snapshot transaction;
- workers have no transaction, DB, NAS, or cross-worker authority.

Concurrent bundle or item creation conflicts on unique logical keys rather than creating duplicates.
No operation silently resolves an omitted revision to current.

## 17. Security and rights

All corpus members are external untrusted input even when company-owned or previously processed.

- never execute HWP macros, spreadsheet formulas, PDF JavaScript, embedded executables, or external
  links;
- validate archive paths, compression ratios, expanded sizes, entry counts, media signatures, and
  symlinks before parsing;
- parse complex formats in a no-network, read-only, resource-bounded adapter sandbox;
- pin a rights-review revision before model exposure, page-image materialization, item grounding,
  or excerpt retention;
- mark answer-bearing sources and prevent their accidental inclusion in student-safe contexts;
- never place source content, worker output, credentials, absolute paths, or answers in Slack logs;
- keep root aliases and exact pointers in protocols; protected absolute paths stay operator config;
- preserve withdrawal behavior so future retrieval/publication can exclude withdrawn sources
  without corrupting historical evidence.

The V1 implementation bridges the existing immutable `legacy-source-rights-review/2.0` Artifact
to the independent `RightsPolicyPointer` boundary with a deterministic one-to-one ID projection.
The bridge loads and validates the exact Artifact, requires an assessment-item review, a cleared
state, internal processing, page-image materialization, model exposure, and the reviewed
data-analyst role. It never accepts a bare operator boolean. A later dedicated Rights Policy
registry can replace this adapter without changing Organization, Occurrence, or Bundle contracts.

## 18. Implementation phases

### Phase A — frozen inventory and corpus report

1. Use the existing immutable `EOM_AI_SERVER_LEGACY_SOURCE` domain alias with a new protected
   root-configuration revision that maps the currently mounted AI-server corpus location; the
   absolute mount path remains operator configuration, not protocol identity.
2. Run the existing V2 inventory adapter read-only.
3. Produce exact extension/signature/size/hash/duplicate/path-anomaly counts.
4. Commit only the small inventory Artifact and safe summary; do not copy source bytes yet.

### Phase B — protocols and deterministic adapters

1. Add the seven additive schemas in section 5 and frozen Pydantic models.
2. Implement safe PDF/XLSX/HWPX metadata adapters and an isolated HWP adapter interface.
3. Implement candidate bundle grouping and a review projection.
4. Implement Organization/Assessment Occurrence/Item Origin contracts and persistence from the
   already accepted V1 design before canonical bulk Item registration.

### Phase C — three-bundle pilot

Choose three reviewed bundles that cover distinct shapes:

- older integrated-science PDF problem + answer + HWP;
- recent integrated-science HWP + multi-sheet XLSX;
- science-elective PDF + answer + HWP/HWPX + XLSX.

For each pilot, review bundle identity and expected item numbers before worker submission. Compare
one-, four-, and eight-item work-unit size on completeness, duration, output bytes, and correction
rate. No Graph publication occurs in the pilot.

### Phase D — corpus extraction

1. Freeze all reviewed bundle revisions and a complete work-unit manifest.
2. Run one dedicated support slot with continue-and-collect scheduling.
3. Monitor bounded counts and stable failures, not source content.
4. Create explicit continuation batches for gaps; reuse accepted exact pointers.
5. Stop only when the coverage manifest proves every intended bundle/item position.

### Phase E — registration and Graph projection

1. Review conflicts and low-confidence fields.
2. Import accepted Items with origin, occurrence, source, rights, and component pointers.
3. Generate Markdown views as derived projections.
4. Publish a new Graph Snapshot only after item/source/curriculum coverage gates pass.
5. Connect product/form placement only through the existing legacy-usage ingestion boundary.

## 19. Pilot acceptance gates

- original NAS tree remains byte- and metadata-unmodified;
- inventory count/hash/topology is reproducible;
- no folder or filename alone establishes a bundle or occurrence;
- all staged sources resolve through approved Artifact Revisions and rights;
- every supplied page is visually observed by the worker;
- every reviewed expected item number is accepted, unresolved, or explicitly failed—never absent;
- PDF/HWP/HWPX/XLSX disagreements remain visible;
- generic item contract validation passes without forcing the fixed HWPX profile;
- exact duplicates do not duplicate canonical bytes or Items;
- continuation reuses accepted pointers and executes only gaps;
- no worker reads NAS, writes NAS/DB, contacts another worker, or accesses the network;
- no large binary or full source document is stored in PostgreSQL;
- no Graph node is created from an unaccepted proposal;
- historical textbook analysis, standard-item production, HWPX, and existing Graph snapshots remain
  unchanged during source-only development and the isolated pilot.

## 20. Simpler alternatives rejected

**Convert every file to Markdown and let one Codex sort it out.** This loses layout, image, table,
equation, answer, occurrence, and cross-file provenance; it also creates a second pseudo-canonical
corpus and oversized prompts.

**Use one folder as one exam.** Observed misplaced and cross-year files make that incorrect.

**Use only HWP/HWPX because it is structured.** Those files are often internal reconstructions and
cannot replace the visual problem/answer evidence without reviewed equivalence.

**Use only PDFs.** This discards valuable internal curriculum, difficulty, legacy-ID, and structured
reconstruction observations.

**Register every extracted record automatically.** Model output and legacy labels remain untrusted;
strict typed validation and conflict review are required before canonical Item/occurrence records.

**Reuse textbook Knowledge Analysis output.** Textbook knowledge proposals and historical item
extraction have different source topology, answers, occurrence identity, coverage, and target
contracts. They should share Orchestrator/slot/Artifact infrastructure, not one result schema.

**Stop the whole corpus at the first malformed item.** This wastes independent work and hides total
coverage. Continue-and-collect with strict per-unit validation preserves safety while making gaps
explicit and recoverable.
