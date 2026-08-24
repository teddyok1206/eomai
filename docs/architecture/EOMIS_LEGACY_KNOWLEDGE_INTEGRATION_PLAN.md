# EOMIS Legacy Knowledge Integration Plan

Status: `PHASE_2_SOURCE_COMPLETE`; read-only baseline mapping, additive contracts, and the synthetic
scanner/dry-run implementation are complete. The separately reviewed real-root dry run remains
pending. No EOMIS file,
production database row, Artifact, Graph Snapshot, worker prompt, or runtime service was changed by
this plan.

Date: 2026-08-24 UTC

Related EOM decisions:

- [Codex and Education Knowledge Control Plane Implementation Plan](CODEX_KNOWLEDGE_CONTROL_PLANE_IMPLEMENTATION_PLAN.md)
- [Knowledge Analysis Intake and Workflow V1](KNOWLEDGE_ANALYSIS_INTAKE_WORKFLOW_V1.md)
- [Education Graph Snapshot Persistence V1](EDUCATION_GRAPH_SNAPSHOT_PERSISTENCE_V1.md)
- [Education Retrieval and Evidence Bundle V2](EDUCATION_RETRIEVAL_EVIDENCE_BUNDLE_V2.md)
- [Education Knowledge and Item GraphRAG](EDUCATION_KNOWLEDGE_ITEM_GRAPHRAG.md)
- [Item Origin and Assessment Occurrence V1](ITEM_ORIGIN_OCCURRENCE_V1_DESIGN.md)
- [Legacy Product and Usage Intake V1](LEGACY_PRODUCT_USAGE_INTAKE_V1.md)

## 1. Outcome and scope

This plan integrates useful legacy educational sources from EOMIS and the old EOM AI Server into
the existing EOM control plane. It does not import the old runtime as a second platform. It does not
allow a worker to browse EOMIS, NAS, PostgreSQL, or a mutable vector database directly.

The desired flow is:

```text
read-only legacy source inventory
  -> reviewed selection of original source files
  -> Content Intake
  -> immutable source Artifact Revision
  -> fresh one-shot Knowledge Analysis through the Orchestrator
  -> normalized Markdown + source anchors + graph proposal
  -> deterministic validation and human/risk review
  -> accepted analysis Artifact Revision
  -> reviewed curriculum structure binding
  -> immutable Education Graph Snapshot
  -> bounded Evidence Bundle
  -> existing fresh item workflow / review / Item Registry / HWPX boundaries
```

The following are explicitly outside this document:

- writing or tuning the data-analyst prompt;
- writing item-authoring, review, image, or registration prompts;
- defining how a particular question should be authored;
- deciding which question should be placed in which product/form/position;
- importing a production workbook or creating Product/Usage rows;
- executing a live Codex job or publishing a production Graph Snapshot;
- integrating the old OpenAI/ChatGPT API runtime;
- training or deploying the EOMIS local Qwen/LoRA model stack.

This document defines data ownership, contracts, pointers, selection, staging, normalization,
validation, publication, retrieval, security, testing, rollout, and rollback only.

## 2. Corrected source-of-truth decision

The decisive clarification is that the textbook and reference-book originals are PDFs. The
SQLite databases, page summaries, normalized JSON, chunks, registries, Qdrant collections, page
observations, and related files were produced by earlier Codex/AI processing.

Therefore:

1. An original textbook/reference-book PDF is eligible to become an EOM canonical source Artifact
   Revision after Content Intake and rights review.
2. Existing EOMIS AI-produced outputs are not independent source evidence.
3. An EOMIS `doc_id`, `segment_id`, `chunk_id`, `concept_id`, vector point ID, local path, or SQLite
   row ID is a legacy locator only. It is never an EOM logical ID or immutable revision ID.
4. Existing derived outputs may be used as migration hints, discrepancy inputs, and evaluation
   baselines, but cannot supply canonical graph facts or source anchors by themselves.
5. A new EOM Knowledge Analysis begins from the exact original PDF Artifact Revision. Its accepted
   Markdown, anchors, nodes, edges, claims, and observations are new immutable derived Artifacts.
6. A rendered page PNG is a derived materialization identified by the source PDF revision, page
   number, rendering policy/version, and output hash. It is not the textbook source of truth.
7. Physical Qdrant or SQLite indexes are rebuildable caches. EOM does not migrate them into its
   canonical store.

For the textbook/reference-book corpora specifically, the original-source class contains PDFs
only. Adjacent JSON, Markdown, SQLite, chunks, concept registries, page observations, indexes, and
rendered page images are presumed Codex-derived unless independent provenance proves otherwise.
This rule does not reclassify separately inventoried original assessment files such as HWP/HWPX.

This prevents provenance laundering in which one model-produced summary is later cited as if it
were the original textbook.

## 3. Read-only inventory findings

The inventory below is a point-in-time observation, not a committed import manifest. A future
scanner must reproduce it with hashes and exclusions under a versioned contract.

### 3.1 EOMIS source items

Observed under the legacy source-item area:

| Kind | Count | Approximate bytes | Interpretation |
| --- | ---: | ---: | --- |
| normalized item JSON | 841 | 10 MB | prior derived representation; proposal/evaluation input only |
| HWP source files | 837 | 399 MB | potential original item sources, subject to provenance and rights review |
| PDF append-set files | 2 | 4.9 MB | potential original assessment/solution sources, subject to review |
| total files | 1,684 | 414 MB | too large for one unreviewed all-or-nothing batch |

Filename-stem inspection found 812 JSON/HWP matches, 29 JSON files without a same-stem HWP, and 25
HWP files without a same-stem JSON. No importer may assume a one-to-one pair based only on the
filename. The relation must be proposed, hash-pinned, and reviewed.

The legacy normalized item model contains useful observations such as subject, unit, subunit,
difficulty, question-shell type, reasoning types, asset types, achievement-standard candidates,
choices, answer, solution, and source traces. These values remain untrusted proposals until they
map to the EOM `AssessmentItemContent`, origin, occurrence, and rights contracts.

### 3.2 EOMIS knowledge workspace

Observed under the legacy knowledge workspace:

| Kind | Count/size | Interpretation |
| --- | --- | --- |
| JSON files | 660 / about 65 MB | mostly AI-derived normalized documents, chunks, registries, and observations |
| local vector SQLite files | 3 / about 57 MB | Qdrant physical cache; never canonical import input |
| PDF files | 2 / about 3.2 MB | potential original source candidates after provenance review |
| curriculum corpus | 2 raw, 3 normalized, 3 chunk files | original/derived files must be classified separately |
| textbook corpus | 10 raw, 11 normalized, 11 chunk files | existing derived corpus, not textbook originals |
| official-guidance corpus | currently empty | no production source should be invented |

One observed curriculum normalized document has 303 segments. Its metadata and segment fields are
valuable as a cross-check, but its paths and AI-derived classification are not authoritative.

### 3.3 EOMIS models and experiments

The model area is about 28.5 GB and includes checkpoints, safetensors, training exports, reports,
and caches. These are excluded from knowledge ingestion. A future local-model qualification project
may inventory them under a separate model-registry design, but they are not educational source
documents and must not consume Content Intake or knowledge-analysis capacity.

### 3.4 Old EOM AI Server bundle

The old server bundle contains four uploaded PDFs totaling about 486 MB. Two exceed the current
Content Intake per-file maximum of 100 MiB. Their filenames are content-hash shaped, but the importer
must recompute the bytes' SHA-256 and must not trust a filename as evidence.

The local checkout's SQLite index is empty and its cache directory contains no page files. The old
runtime code expects a mutable SQLite/FTS index, page images, page summaries, concepts, normalized
terms, and optional embeddings. Those are derived runtime state, not canonical data.

The bundle also contains external-API application code and a protected `.env` file. The `.env` was
not inspected and is permanently excluded. The application code, request-scoped API headers,
prompts, and external OpenAI execution paths are not part of this integration.

### 3.5 Existing EOM capabilities to reuse

EOM already provides the main production boundaries:

- bounded Content Intake with path normalization, symlink/hard-link rejection, hashing, secret
  scanning, immutable Artifact commit, review, and event history;
- `knowledge-analysis-request/2.0` over an exact Content Intake file or approved Item Revision;
- a fresh, one-shot support worker through the Orchestrator with no DB/NAS/network authority;
- `knowledge-analysis-worker-proposal/1.0` for Markdown, anchors, nodes, edges, claims, component
  observations, and ambiguities;
- immutable proposal and accepted-result Artifact Revisions;
- closed graph node/edge ontology, deterministic projection, source pointers, curriculum closure,
  and immutable Graph Snapshot publication;
- closed retrieval requests, access-policy revisions, answer-bearing controls, and immutable
  Evidence Bundles;
- Item Registry, Item Element bindings, human approval, HWPX, secure download, origin/usage design,
  and the implemented legacy usage ledger.

The integration should extend these owners. It must not create an EOMIS-specific orchestrator,
graph database, item registry, vector store, or worker-to-worker protocol.

## 4. Canonical and derived data classes

Every discovered file receives exactly one preliminary class. The class is an inventory decision,
not an automatic publication decision.

### 4.1 Class A — original source candidate

Eligible for reviewed Content Intake:

- original curriculum PDFs;
- original textbook and reference-book PDFs;
- original official guidance PDFs or office documents;
- original HWP/HWPX/PDF assessment files when provenance can be established;
- original source images only when they exist independently of PDF rendering;
- reviewed legacy usage workbooks under the existing Phase 11 contract.

Class A still requires rights, ownership, media, size, malware/active-content, hash, and lifecycle
checks. “Original” does not mean “approved.”

### 4.2 Class B — derived migration evidence

Preserved only as optional comparison/evaluation material:

- normalized curriculum/textbook JSON;
- OCR text, page summaries, page chunks, page observations, concept registries, curriculum spine,
  study packs, and error memory;
- normalized item JSON and its legacy metadata;
- generated page PNGs;
- FTS rows, embedding JSON, and retrieval benchmark reports;
- AI-produced review, generation trace, and experiment reports.

Class B cannot create a source anchor that lacks a Class A pointer. If attached to a migration
review, it must say which exact original source revision it claims to derive from. Unresolved
relations remain quarantined.

### 4.3 Class C — excluded runtime or sensitive state

Never selected by the knowledge importer:

- `.env`, credentials, tokens, SSH/Codex auth, API headers, and secret-bearing logs;
- `.git`, caches, temporary files, backups, lock files, WAL/SHM files copied out of context, and
  runtime status databases;
- Qdrant physical collection files and mutable FTS indexes;
- model weights, LoRA adapters, checkpoints, optimizer state, and training caches;
- external-API server code and prompt files in this prompt-excluded project;
- generated HWPX/PNG/PDF outputs that are not reviewed source documents;
- infrastructure audits and unrelated projects.

The scanner uses an allowlist of Class A roots and explicit Class B comparison roots. It never
implements “scan everything except known bad names.”

## 5. Responsibility and dependency boundaries

```text
operator CLI / later ADMIN GUI
  -> Legacy Source Inventory application service
      -> read-only legacy filesystem adapter
      -> typed inventory Artifact (no canonical source publication)
  -> operator selection/review
  -> existing Content Intake application service
      -> Artifact adapter commits selected original bytes
  -> existing Knowledge Analysis application service
      -> Orchestrator materializes one pinned source
      -> support worker returns schema-valid proposal
      -> Orchestrator commits proposal Artifact
  -> Catalog review/acceptance
  -> Graph publication and retrieval services
```

Ownership rules:

| Concern | Owner |
| --- | --- |
| inventory/selection JSON Schema and frozen values | `packages/catalog_contracts` |
| root alias resolution and read-only file inspection | Catalog infrastructure adapter |
| source selection, idempotency, and intake command | Catalog application service |
| source bytes and derived large files | immutable Artifact Revisions |
| source lifecycle and review | Content Intake / Catalog |
| model execution | existing Orchestrator only |
| accepted Markdown/anchors/graph proposal | Knowledge Analysis Artifact Revision |
| graph publication/retrieval | existing Catalog graph services |
| operator interaction | `eomctl`, later ADMIN GUI calling same use case |
| original item lifecycle | Item Registry after reviewed conversion |
| product placement/use | existing Assembly/Publication/Usage ledger |

The inventory adapter may read configured legacy roots as an operator-owned process. A worker may
not. After Content Intake, all worker access uses job-local materialization from an approved
Artifact Revision.

## 6. Identity and pointer model

### 6.1 Root aliases

Absolute host paths are not identity and must not enter worker messages or public API responses.
Protected operator configuration maps a bounded alias to a read-only root, for example:

```text
EOMIS_LEGACY_SOURCE -> configured EOMIS source root
EOM_AI_SERVER_LEGACY_SOURCE -> configured old server data root
```

An inventory entry records the root alias and normalized relative path. It does not store a bearer
token, database URL, NAS mount credential, or arbitrary path supplied by a browser.

### 6.2 Required identity chain

```text
legacy root alias + relative locator        (discovery only)
  -> inventory snapshot revision + entry key
  -> Content Intake batch + source_file_id
  -> Artifact logical ID
  -> immutable Artifact Revision ID
  -> exact member path + media/schema + SHA-256
  -> Knowledge Analysis run and accepted-result Artifact Revision
  -> Graph Snapshot Revision
  -> Evidence Bundle Revision
```

Every layer keeps its logical ID, revision ID, Artifact ID, Artifact Revision ID, and content hash
separate. A changed file at the same legacy path creates a new inventory entry revision and new
source Artifact Revision; it never overwrites history.

### 6.3 Derived-output relation

A Class B value may point to a Class A source only through a reviewed relation:

```text
DERIVED_FROM
  original Artifact Revision + member + SHA
  derived Artifact Revision/member or inventory entry + SHA
  transformation kind
  transformation implementation/version when known
  source page/range when known
  confidence and review state
```

Unknown transformation provenance is explicit. It is never reconstructed from matching filenames
alone.

## 7. Protocol-first additions

The existing V1/V2 schema bytes remain immutable. New work begins with Draft 2020-12 JSON Schema,
then frozen Pydantic models, canonical serializers, and negative tests.

### 7.1 `legacy-source-inventory/1.0`

One immutable scan snapshot. Required fields:

- inventory ID and UTC timestamp;
- scanner implementation version and policy revision/hash;
- root alias and a hash of the allowed-root configuration identity, not its secret/path content;
- sorted entries;
- total file/byte counts by preliminary class;
- excluded counts by closed reason code;
- inventory content hash.

`legacy-source-inventory/1.0` is retained byte-for-byte for historical compatibility. Phase 2 adds
`legacy-source-inventory/2.0` because V1 included `observed_at` in its self-hash and therefore could
not satisfy repeated-observation idempotency. V2 adds an explicit stable `source_set_sha256`,
derives the inventory identity from it, and excludes observation time from the stable domain hash.
The eventual Artifact manifest hash still protects the complete serialized bytes, including the
UTC observation time.

Each entry contains:

- deterministic inventory-entry key;
- normalized relative path;
- regular-file/non-symlink/non-hardlink observation;
- byte count, media type detected from bounded signature inspection, and SHA-256;
- preliminary source family (`CURRICULUM`, `TEXTBOOK`, `REFERENCE_BOOK`, `GUIDANCE`, `ITEM`,
  `USAGE_WORKBOOK`, `DERIVED_EVIDENCE`, `EXCLUDED`);
- canonicality candidate (`ORIGINAL`, `DERIVED`, `UNKNOWN`);
- rights state (`UNREVIEWED`, `CLEARED_INTERNAL`, `CLEARED_LICENSED`, `RESTRICTED`, `REJECTED`);
- relation-group proposal key when a PDF/HWP and legacy output may be related;
- closed exclusion/uncertainty codes.

Modification time and inode may be recorded only as scan diagnostics. They are never identity and
never replace hashing at the intake boundary.

### 7.2 `legacy-source-selection/1.0`

One reviewed selection pins:

- exact inventory ID/hash;
- selected entry keys and hashes;
- reviewed source class and declared Content Intake role;
- source owner and rights-review pointer;
- intended corpus key;
- whether Class B comparison evidence is attached;
- approver, UTC time, selection hash, and idempotency key.

The selection cannot name an entry absent from the inventory. Class C cannot be selected. A Class B
entry cannot be marked original.

Phase 3 adds `legacy-source-selection/2.0` and `legacy-source-rights-review/2.0` additively. V1 bytes
remain immutable for historical decoding, but new intake uses only V2. The V2 rights review pins the
exact inventory ID/hash, entry key, and content hash it reviewed; this prevents one owner-level
rights document from being reused for a different source. V2 selection IDs are derived from their
canonical identity payload, and conflicting replays fail closed.

### 7.3 `legacy-source-relation-manifest/1.0`

This small Artifact-backed manifest records reviewed relationships between originals and legacy
derived values. It is not a graph snapshot and contains no large payload. It pins both sides by
inventory entry or Artifact Revision and exact hash. It supports at least:

- `DERIVED_FROM`;
- `RENDERS_PAGE_FROM`;
- `EXTRACTS_TEXT_FROM`;
- `NORMALIZES_FROM`;
- `LEGACY_ITEM_REPRESENTATION_OF`;
- `EVALUATION_BASELINE_FOR`.

### 7.4 `legacy-source-rights-review/1.0`

A source-level immutable review records owner/document type, reviewed rights state, exact evidence
pointers, allowed internal processing, model-role exposure, excerpt/page-image materialization,
item-grounding permission, answer-bearing status, retention policy, withdrawal behavior, reviewer,
UTC time, and canonical hash. Rejected sources cannot retain any use permission. Model exposure must
name an allowed worker role, and item grounding requires model exposure.

This source-level evidence closes the selection pointer. It does not replace the later corpus-level
retrieval access-policy aggregate or legal policy.

### 7.5 No immediate change to Knowledge Analysis V2

The first pilot uses the existing `CONTENT_INTAKE_FILE` source variant and analyzes one original PDF
at a time. The request pins the exact source file, Artifact Revision, member path, media type, size,
and hash. Existing V2 proposal limits and review rules remain unchanged.

If deterministic PDF text/page extraction is needed before the worker, it must be an Orchestrator-
owned materialization adapter. It may create a job-local derivative but may not replace the pinned
PDF identity. The accepted anchor still records a locator that resolves to the original PDF page or
section and an excerpt hash derived under the reviewed extraction policy.

### 7.6 Conditional future Document Revision

Do not add a generic Document aggregate merely to start the pilot. Add it only when at least two
real recurring cases require logical edition/revision history or multi-member source resolution,
such as:

- successive editions of the same textbook/reference book;
- one source revision that must pin the original PDF plus independently reviewed source media;
- a rights policy that changes by document revision;
- cross-corpus reuse of the same source revision.

If that gate is met, add an immutable `educational-document-revision-manifest/1.0` and an additive
Knowledge Analysis V3 `DOCUMENT_REVISION` source variant. Never widen or reinterpret V2.

## 8. Field-level crosswalk

### 8.1 Knowledge documents

| EOMIS observation | EOM treatment |
| --- | --- |
| `doc_id` | namespaced legacy key only; never an EOM logical ID |
| `source_type=curriculum` | candidate `CURRICULUM`, reviewed at selection |
| `source_type=textbook` | candidate `TEXTBOOK`, only original PDF is canonical |
| `source_type=official_guidance` | candidate `INTERNAL_GUIDE` until a new source class is justified |
| `title`, `publisher`, `issuing_body`, `grade_level`, `volume` | bounded metadata proposals; rights/organization review remains separate |
| `subject`, `unit`, `subunit` | labels/aliases only; graph IDs come from reviewed curriculum structure |
| `achievement_standard_id` | candidate exact standard key; must resolve in reviewed framework revision |
| `concept_tags` | candidate aliases; never direct stable graph keys |
| `allowed_scope`, `restricted_scope` | policy proposals; never automatically become effective access rights |
| `source_path`, `sidecar_path`, `image_path` | legacy locators only; replaced by Artifact member pointers or discarded |
| `text_extraction_status`, `ocr_required`, `text_source` | transformation/quality observations |
| `quality_flags`, `quality_score` | migration comparison data; EOM recomputes its own quality result |

### 8.2 Segments and anchors

| EOMIS observation | EOM treatment |
| --- | --- |
| `segment_id`, `chunk_id` | legacy local keys; not graph identities |
| `page_no` | PDF `PAGE` anchor locator candidate |
| `heading`, `section_title` | `SECTION` anchor locator and normalized Markdown heading candidate |
| segment text | compared with fresh extraction; accepted text receives an excerpt SHA |
| `figure_caption`, `table_explanation` | candidate component observation anchored to original PDF page |
| `has_question`, `has_table_graph` | weak discovery hint only, not a canonical item/table fact |

Anchor IDs are deterministic only inside one analysis proposal. Graph source pointers ultimately
pin source Artifact Revision, original PDF member, locator, and excerpt hash. A page summary cannot
cite its own generated text as the textbook source.

### 8.3 Curriculum hierarchy

EOMIS `unit`, `subunit`, curriculum spine, and neighbor links are proposals. The reviewed EOM tree
is exactly:

```text
Curriculum Framework Revision
  -> MAJOR
      -> MIDDLE
          -> MINOR
              -> ACHIEVEMENT_STANDARD
```

For the first Integrated Science framework, the user-confirmed editorial semantics of those levels
are fixed in [EOM Integrated Science Editorial Outline V1](EOM_INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_V1.md):
`MAJOR=I권/II권`, `MIDDLE=대단원`, and `MINOR=중단원`. The outline has two volumes, six large units,
and 35 ordered middle units. It is company editorial authority, while official curriculum-course
and achievement-standard identities remain separate reviewed source mappings.

The current graph contract validates this shape, sibling ordinals, parent levels, cycles, and
closure. However, the current persistence layer does not yet own a separate resolvable
`CurriculumFrameworkRevision` record; `framework_revision_id` is currently carried inside the
reviewed structure manifest and snapshot-local rows.

Before the first production curriculum graph is declared authoritative, implement one of these two
reviewed options:

1. preferred: a small logical Curriculum Framework + immutable Framework Revision aggregate whose
   revision pins a canonical structure-manifest Artifact and hash; or
2. transitional: explicitly define the immutable structure-manifest Artifact Revision as the sole
   framework-revision authority and add a resolver that proves that identity everywhere.

The preferred option is clearer for the 2022 curriculum and future revisions. It needs a short
protocol/persistence design, additive tables, exact indexes, and a migration. It must not copy the
full curriculum text into PostgreSQL.

Stable graph keys must be reviewed machine keys such as a curriculum edition/code path. Korean
labels remain labels. Unreviewed EOMIS concept IDs or normalized Korean strings cannot silently
merge nodes.

### 8.4 Legacy assessment items

EOMIS `NormalizedItem` is not the EOM canonical Item schema. Conversion produces a proposal only.

| EOMIS value | EOM target |
| --- | --- |
| legacy `item_id` | namespaced legacy source key and mapping evidence |
| `stem`, `material_text`, `gnd_block` | candidate typed content blocks |
| choices/answer | candidate interaction and solution pointers |
| solution sections | candidate EOM solution text and statement explanations |
| assets/path fields | must resolve to separately ingested original or approved media Artifacts |
| difficulty/reasoning/shell | taxonomy proposals, not free-form canonical facts |
| `human_authored`, `authoring_origin` | origin-profile observations requiring review |
| `training_eligible` | legacy observation only; never EOM training or retrieval approval |
| source/review/generation trace | provenance evidence, not canonical workflow history |

The converter must reject missing assets, ambiguous HWP/JSON relationships, non-resolving choice
answers, duplicate IDs, unsupported block shapes, and inconsistent solutions. Only RegistryService
may allocate an EOM Item/Item Revision and commit validated `AssessmentItemContent`.

Past-exam status is not inferred from a filename. It requires the future/implemented origin path:
reviewed Organization, Assessment Occurrence, rights policy, and exact source evidence. Until then,
the source remains quarantined or restricted `PAST_EXAM` intake evidence and cannot masquerade as
an approved EOM Item.

### 8.5 Page images

For a PDF source, page PNG identity is:

```text
source PDF Artifact Revision
  + page number
  + renderer implementation/version
  + rendering options hash
  -> derived PNG Artifact member + SHA-256
```

The original PDF remains canonical. A legacy generated PNG may be used only to compare rendering or
page alignment. Workers receive a bounded job-local page image when visual inspection is required;
they never receive the legacy cache root.

### 8.6 Product and usage history

No item placement is inferred in this project. If legacy Excel workbooks are later supplied, use
the already implemented Phase 11 chain:

```text
workbook Content Intake
  -> released mapping contract
  -> row proposals
  -> explicit row review
  -> Product/Form/Assembly/Publication/Usage V1
  -> rebuildable graph projection
```

The graph remains a projection. Usage ledger rows remain authority.

## 9. Read-only scanner design

### 9.1 Access patterns

Dominant operations are ordered tree traversal, exact relative-path lookup, content hashing,
membership/exclusion, duplicate-hash detection, and incremental change detection.

- iterate files once in normalized relative-path order: `O(n)`;
- hash eligible bytes once: `O(total selected bytes)`;
- detect duplicate bytes with a hash map/set: expected `O(n)`;
- look up prior inventory entries by `(root_alias, relative_path)`: indexed/map `O(1)` expected or
  DB `O(log n)`;
- group possible source/derived relations by an explicit relation key, never repeated filename
  scans;
- serialize sorted immutable entries once: `O(n log n)` for stable order.

At the observed scale, an Artifact-backed inventory manifest is sufficient. Do not add inventory DB
tables until recurring scans require indexed pagination or concurrent review. If they are later
added, use unique `(inventory_revision_id, entry_key)`, indexes on class/state/SHA, and no file
bytes in rows.

### 9.2 Filesystem safety

The scanner must:

- open only configured root aliases;
- reject root, directory, or file symlinks and path escapes;
- record and reject hard-linked candidates at the canonical intake boundary;
- use `lstat`, directory-relative operations, and `O_NOFOLLOW`/fd-based reads where practical;
- bound file count, per-file bytes, total bytes, nesting depth, and name length;
- normalize Unicode and casefold collision keys exactly as Content Intake does;
- detect media by signature plus reviewed suffix policy;
- scan the bounded initial bytes for secrets, active content, and unsupported archive types;
- never source a legacy `.env` or import/execute legacy Python;
- never open mutable SQLite in write mode;
- never follow database-stored absolute file paths;
- emit only safe metadata, never document content, to logs or Slack.

### 9.3 Incremental scans

Size/mtime/inode may avoid unnecessary rehashing only when a prior protected cache is exact and the
root identity is unchanged. Every selected file is re-opened and rehashed at Content Intake. Cache
hits cannot authorize ingestion.

Same path plus changed bytes becomes a new inventory revision. Same bytes at multiple paths remain
separate observations until a reviewer decides whether they represent aliases, duplicates, or
different rights/provenance contexts.

## 10. Large PDF strategy

Current Content Intake and Knowledge Analysis cap one source member at 100 MiB. Two observed old
server PDFs exceed that limit. Do not weaken the global limit merely to accept them.

Use this order:

1. verify whether the PDF is an original, rights-cleared source;
2. keep the complete original in a protected quarantine/inventory state until a reviewed large-
   document boundary exists;
3. deterministically split by PDF page ranges in a trusted adapter without modifying the source;
4. record a split manifest pinning original SHA, each inclusive page range, tool/version/options,
   child Artifact member hash, and complete non-overlapping page coverage;
5. ingest/analyze bounded child members while preserving the original parent pointer;
6. reject encrypted, malformed, active, over-page-limit, or inconsistent PDFs;
7. prove reassembly/page coverage and deterministic hashes in tests.

This requires an additive `pdf-page-range-materialization-manifest/1.0` if used. A child range is a
materialization of the original revision, not a new textbook identity.

## 11. Knowledge Analysis integration

### 11.1 Request creation

For each reviewed original source:

1. resolve the exact Content Intake batch/source file;
2. prove the source Artifact logical/revision pair, approved lifecycle, member path, media type,
   bytes, and SHA;
3. map source family to the existing closed source class;
4. pin one released Knowledge Analysis Execution Preset Revision and risk policy;
5. create one `knowledge-analysis-request/2.0` with a unique idempotency key;
6. admit it under the existing `KNOWLEDGE_ANALYSIS` capacity of one;
7. make no automatic retry. A later retry is a new run with an explicit predecessor.

Source-class mapping for the initial rollout:

| Reviewed family | Existing class |
| --- | --- |
| official curriculum | `CURRICULUM` |
| textbook/reference book | `TEXTBOOK` |
| institutional original assessment | `PAST_EXAM` only after origin/rights review |
| internal/official guide | `INTERNAL_GUIDE` |
| approved EOM Item Revision | `APPROVED_ITEM` through the existing source variant |

Reference books share `TEXTBOOK` initially only if the retrieval policy treats both identically.
If materially different rights or ranking behavior is required, introduce an additive source-class
contract version rather than encoding the distinction in a label.

### 11.2 Worker boundary

The worker receives only:

- one staged exact original source or one bounded page-range materialization;
- immutable request and execution-plan values;
- reviewed instruction/reference material selected by the existing preset system;
- its output JSON Schema.

It receives no EOMIS root, old SQLite/Qdrant index, NAS path, DB credentials, external API key,
previous Codex session, or peer-worker output outside explicit Orchestrator pointers.

Prompt content is intentionally deferred. This plan only fixes the message contract and allowed
materialization.

### 11.3 Proposal validation

The existing proposal boundary already requires closed unique anchors/nodes/edges/claims,
resolving edge endpoints, no self-edges, bounded collection sizes, exact request identity, and
general-knowledge provenance flags.

Add integration-specific deterministic checks outside the model:

- every anchor locator is valid for the selected source media;
- PDF page locators are within the parsed page count;
- every excerpt hash matches text produced by the pinned extraction policy;
- source-like instructions are treated as data;
- no anchor points to Class B derived text unless its original relation is explicitly pinned;
- proposed stable keys use reviewed namespaces and do not collide by case/alias;
- unit/standard claims resolve to the reviewed curriculum framework or remain ambiguous;
- component observations do not claim a media Artifact that was not staged/resolved;
- `general_knowledge_used` never produces a citation/source anchor.

### 11.4 Review and acceptance

Auto-accept should remain disabled for the first corpus rollout. Human review checks:

- source identity and rights;
- extraction/page-anchor correctness;
- curriculum hierarchy and achievement-standard mapping;
- concept alias merge/split decisions;
- contradictions and unsupported claims;
- table/figure/equation observation accuracy;
- whether legacy Class B output agrees or disagrees, without treating agreement as proof;
- unresolved ambiguities and blocking quality flags.

Only the existing Knowledge Analysis acceptance service publishes an accepted-result Artifact.
Rejecting a proposal creates no graph delta.

## 12. Graph publication design

### 12.1 Initial corpus split

Use separate logical corpora so rights and quality can be controlled independently:

- reviewed integrated-science curriculum;
- rights-cleared textbooks/reference books;
- reviewed official/internal guidance;
- approved/reviewed assessment items.

Do not publish one mixed “all EOMIS” corpus.

### 12.2 Stable keys and merging

The graph publisher merges nodes by `stable_key` and rejects conflicting type/label pairs. Therefore
stable keys must come from a reviewed normalization registry, not from free Korean text or legacy
concept IDs.

Recommended namespaces:

- curriculum framework/unit/standard: official edition and controlled code path;
- concept/process/formula: reviewed science taxonomy key;
- source sections: immutable source revision plus bounded local key;
- item elements: exact Item Revision and existing stable element ID.

Aliases remain separate reviewed values. Zero or multiple candidate matches remain unresolved.

### 12.3 Snapshot transaction

One publication command pins:

- corpus and expected current snapshot;
- sorted accepted analysis run IDs;
- exact accepted-result Artifact pointers/hashes;
- reviewed curriculum/item structure manifest;
- publisher and ontology versions;
- idempotency key and request hash.

Publication builds deterministic JSONL/Markdown projections, adjacency, lexical terms, curriculum
closure, source pointers, and counts before the short DB transaction. The transaction rechecks all
pointers, inserts the immutable revision, and moves only the corpus current pointer atomically.
Prior snapshots remain unchanged.

### 12.4 No physical index migration

EOMIS Qdrant, old SQLite FTS, and embedding JSON are not copied. After a graph snapshot exists,
evaluate EOM's existing lexical/hierarchy/adjacency baseline first. A vector adapter is introduced
only if a fixed benchmark proves retrieval benefit and remains a rebuildable snapshot-derived
adapter.

## 13. Retrieval and Evidence Bundle integration

The first retrieval evaluation uses the three existing closed query kinds only. No browser or
worker supplies arbitrary graph queries or paths.

The service must:

- pin one exact graph snapshot and access-policy revision;
- enforce source-class and requester-role policy;
- use indexed curriculum closure, stable/lexical keys, and bounded adjacency;
- deduplicate by immutable source/revision/member/use pointer;
- mark answer-bearing approved-item/past-exam evidence `AVOID_COPY`;
- refuse answer-bearing evidence for worker roles under the standard policy;
- emit a bounded `evidence/context.md` and pointer-only manifest;
- record document/item/node/claim/token counts and hashes;
- materialize only the bundle member needed by the fresh worker.

The Evidence Bundle references the new EOM accepted analysis and source pointers, never EOMIS
paths or Qdrant IDs.

## 14. Rights, provenance, and access policy

Rights are the main gate before textbook/reference-book rollout. Content ownership and model
availability are independent.

At minimum, each selected source needs a reviewed decision for:

- owning/licensing organization;
- document type and edition;
- allowed internal processing;
- allowed model exposure;
- allowed human roles;
- whether excerpts or page images may appear in Evidence Bundles;
- whether the source may ground generated items;
- whether answer-bearing material is present;
- retention and withdrawal behavior.

The current retrieval access policy controls query kinds, roles, source classes, budgets, and
answer-bearing access, but it does not by itself prove document-level copyright permission. Until
the Phase 6 rights-policy aggregate is implemented, textbook/reference-book sources should use a
restricted pilot corpus visible only to explicitly approved administrator/reviewer acceptance
flows. Broad production grounding is blocked.

A withdrawal never deletes immutable history. It retires the source for new retrieval and publishes
a new graph snapshot excluding it. Historical workflows retain their pinned evidence and audit
records subject to legal retention policy.

## 15. Security and threat model

| Risk | Required control |
| --- | --- |
| prompt injection in PDF/HWP/OCR text | treat all source text as data; fixed worker instructions; no executable fields |
| secret in legacy tree | allowlist roots, bounded secret scan, `.env`/auth/config exclusion, fail closed |
| path traversal/symlink/hard link | fd-safe root containment and current Content Intake checks |
| malicious PDF/archive | signature validation, size/page limits, sandboxed deterministic extraction, no active content |
| stale path or changed file | rehash at intake; pin Artifact Revision; never resolve latest by path |
| provenance laundering | only Class A originals are sources; Class B is comparison evidence |
| filename-based false pairing | typed reviewed relation manifest and hash pointers |
| answer leakage/copying | answer-bearing graph flag, `AVOID_COPY`, role policy, separate reviewer access |
| copyright overreach | per-source rights review and restricted corpus before broad retrieval |
| external API leakage | do not execute/import old API code; no network; no API keys in EOM |
| worker persistence access | existing one-shot sandbox; no DB/NAS/peer-worker access |
| graph poisoning | closed ontology, anchor closure, confidence/review, conflict rejection |
| duplicate storage | one source Artifact; workspace copies are temporary materializations |
| Slack leakage | milestone/stable-code only; no source text, paths, prompts, results, or secrets |

## 16. Transaction, concurrency, retry, and idempotency

### 16.1 Inventory

- same root alias + scanner policy + identical sorted entries returns the prior inventory hash;
- changed bytes create a new immutable inventory revision;
- concurrent identical scans may produce duplicate temporary work but converge on one Artifact by
  idempotency/content hash;
- scanning creates no Content Intake or graph row.

### 16.2 Intake

- selection pins one inventory revision and exact entries;
- the adapter copies/materializes only selected files at the intake boundary;
- existing source fingerprint/idempotency returns the same batch for identical bytes;
- a conflicting replay fails rather than substituting another file;
- no batch exceeds 500 files, 2 GiB, or 100 MiB per member.

### 16.3 Analysis

- one active knowledge-analysis process maximum;
- one attempt per workflow, zero hidden rework cycles;
- a retry is a new analysis run with explicit predecessor and identical dependencies;
- failure commits no accepted result and no graph delta.

### 16.4 Publication

- publication locks the expected corpus/current pointer;
- source set and request hash are immutable;
- same key/same request returns the existing snapshot;
- same key/different request fails;
- transaction conflict publishes no partial DB graph state;
- immutable orphan Artifacts use the existing reviewed reclamation policy, never ad hoc deletion.

## 17. Detailed implementation phases

### Phase 0 — freeze the baseline

Work:

1. record clean EOM HEAD, deployed source provenance, schema hashes, and migrations;
2. record EOMIS/old-server roots as read-only aliases without changing their repositories;
3. capture safe aggregate counts only;
4. confirm no legacy secrets are in Git or scan output;
5. define the explicit allowlist/exclusion policy revision.

Exit gate: reproducible read-only inventory dry run produces no source, DB, NAS, worker, or runtime
mutation.

### Phase 1 — protocol contracts

Work:

1. add Draft 2020-12 schemas for inventory, selection, relation manifest, source rights review, and
   PDF page-range materialization;
2. add frozen Pydantic models and canonical hashing;
3. package schema resources and pin historical schema bytes;
4. define stable error codes;
5. add source-family and exclusion enums without changing existing knowledge V2 enums.

Likely files:

- `schemas/legacy-knowledge/*.schema.json`;
- `packages/catalog_contracts/eom_catalog_contracts/legacy_knowledge.py`;
- `packages/catalog_contracts/eom_catalog_contracts/__init__.py`;
- contract/resource parity tests.

Exit gate: schema/model parity, canonical serialization, invalid path/class/hash/relation negatives,
and historical hash pins pass.

### Phase 2 — read-only inventory adapter

Source status: complete against synthetic untrusted fixtures. A protected operator-only policy was
also used for one successful read-only dry run of each reviewed real root on 2026-08-24; the
resulting V2 source-set identities and semantic pilot findings are recorded in
[EOMIS Legacy Curriculum Semantic Pilot Review](EOMIS_LEGACY_CURRICULUM_SEMANTIC_PILOT.md). The
checked-in policy remains an example only and does not assert real host prefixes. No inventory
Artifact has been committed.

Work:

1. implement root-alias configuration and allowlist resolver;
2. implement ordered fd-safe scanner with bounded hashing and signature detection;
3. emit immutable inventory manifest and summary;
4. add `eomctl knowledge legacy inventory` dry-run/commit commands;
5. ensure Slack receives only milestone counts and stable codes.

Likely files:

- a narrowly named Catalog adapter such as `legacy_source_inventory.py`;
- a Catalog application service such as `legacy_knowledge_intake_service.py`;
- `apps/eomctl` command adapter;
- unit fixtures containing synthetic untrusted files only.

No worker and no DB migration are needed for the first Artifact-backed inventory implementation.

### Phase 3 — reviewed selection and Content Intake bridge

Work:

1. review inventory entries and rights state;
2. create a typed selection that pins exact entries;
3. materialize only selected originals into a protected staging directory;
4. call the existing Content Intake service rather than committing directly;
5. attach relation manifests only as evidence;
6. verify Artifact/member/pointer/hash identity and state transitions;
7. expose bounded inspect/list commands.

Initial batch sizes:

- one curriculum PDF batch;
- one textbook/reference PDF per batch;
- at most 10 legacy item source pairs in the item pilot;
- no model/checkpoint/index directory.

Exit gate: same selection replay is idempotent, mismatched hash/path fails, original bytes exist once
in canonical Artifact storage, and PostgreSQL contains no large payload.

### Phase 4 — curriculum analysis pilot

Work:

1. analyze one reviewed original curriculum PDF through existing Knowledge Analysis V2;
2. require human review;
3. compare accepted output against EOMIS normalized/segment/spine values as non-authoritative
   evaluation evidence;
4. measure page-anchor precision, hierarchy coverage, achievement-standard resolution, ambiguity
   rate, deterministic serialization, runtime, and context/output sizes;
5. publish no graph yet if the Curriculum Framework authority decision is unresolved.

Exit gate: one accepted result points only to the original PDF Artifact Revision; every graph
proposal fact has at least one resolving source anchor; no Class B path appears as canonical
provenance.

### Phase 5 — curriculum framework authority and first graph

Work:

1. finalize preferred Framework/Revision aggregate or transitional manifest authority;
2. produce a reviewed MAJOR/MIDDLE/MINOR/ACHIEVEMENT_STANDARD structure manifest;
3. validate sibling ordering, parent levels, cycles, aliases, and exact source anchors;
4. publish one small immutable curriculum Graph Snapshot;
5. run indexed curriculum subtree and exact-standard acceptance queries;
6. retain prior/current pointer semantics and rollback evidence.

Exit gate: every `framework_revision_id` resolves to immutable reviewed authority; closure and
source-pointer queries pass; no implicit latest framework is used.

### Phase 6 — textbook/reference-book pilot

Work:

1. select one rights-cleared original PDF under 100 MiB;
2. analyze it from its original Artifact Revision;
3. create page materializations only through a pinned deterministic renderer when needed;
4. compare old summaries/chunks/page observations only as baseline evidence;
5. review section, concept, table, figure, equation, and curriculum-alignment proposals;
6. publish a separate restricted textbook corpus snapshot;
7. evaluate retrieval without enabling item production.

Exit gate: source citations resolve to original PDF pages; legacy generated values are absent from
canonical source pointers; document-level rights gate passes.

### Phase 7 — oversized PDF path

Work:

1. implement and validate the page-range materialization contract;
2. prove complete ordered coverage and deterministic child hashes;
3. analyze bounded child ranges;
4. aggregate only through reviewed parent/child pointers;
5. compare whole-document retrieval to section/range retrieval.

Exit gate: the 100 MiB source limit remains unchanged; no range loses parent PDF identity.

### Phase 8 — legacy item pilot

Work:

1. inventory a small representative HWP + normalized JSON set;
2. establish original/derived relationships explicitly;
3. convert derived JSON to a typed Item proposal without trusting legacy IDs/paths;
4. resolve all media as Artifacts;
5. validate canonical `AssessmentItemContent` and origin evidence;
6. require human review before Registry commit;
7. bind approved Item Elements to a later graph snapshot;
8. verify HWPX remains an output boundary, not an import identity.

Exit gate: ambiguous/missing pairs remain quarantined; only approved Registry revisions become
`APPROVED_ITEM` graph sources.

### Phase 9 — old EOM AI Server PDF pilot

Work:

1. treat only the four original PDF candidates as potential sources;
2. exclude `.env`, external-API code, prompts, empty index, and runtime paths;
3. establish ownership/rights and document identity;
4. ingest the two bounded PDFs directly and the oversized PDFs only after Phase 7;
5. compare any recoverable old index result only as a retrieval baseline.

Exit gate: zero external API/network calls, zero legacy secret reads, and zero dependency on the old
server process.

### Phase 10 — retrieval evaluation and controlled activation

Work:

1. publish fixed acceptance queries for curriculum, textbook, table/figure, and cross-source
   grounding;
2. measure provenance precision, source/page recall, duplicate rate, ambiguity rate, latency,
   context tokens, and rights-filter behavior;
3. compare EOM lexical/hierarchy/adjacency to legacy Qdrant/FTS results without importing those
   physical indexes;
4. add a replaceable semantic adapter only if measured benefit justifies it;
5. activate a knowledge-backed preset only under a separate reviewed rollout.

Prompt content and item-generation policy remain separate work.

### Phase 11 — operations and recurring sync

Work:

1. define scheduled inventory as observation only, never auto-ingest;
2. show new/changed/missing/rejected counts to an administrator;
3. require a new selection for changed sources;
4. publish new analysis/snapshot revisions rather than editing old ones;
5. monitor worker capacity, graph size, query plans, Artifact growth, and rights expirations;
6. retain redacted milestone reporting and operator audit events.

Exit gate: recurring scans cannot mutate canonical state without explicit review/command.

## 18. Required tests

### Contract and compatibility

- Draft 2020-12 schema and frozen-model parity;
- canonical/package resource byte equality;
- historical Knowledge Analysis V1/V2 and graph schema hashes unchanged;
- canonical serialization and exact content hashes;
- unknown fields, enums, root aliases, and relation kinds rejected.

### Inventory and files

- symlink, hard link, traversal, Unicode/casefold collision, device/FIFO/socket rejection;
- oversized file, too many files, too many bytes, excessive nesting, malformed signature;
- `.env`, key/token patterns, Git/auth/model/index paths excluded;
- same path changed, same hash different path, duplicate relations, missing original;
- read-only behavior proven with immutable fixture permissions;
- scanner never imports or executes legacy Python.

### Pointer and intake

- missing/stale/unapproved logical/revision pointers;
- member path/media/size/schema/hash mismatch;
- same selection replay and conflicting idempotency replay;
- no large bytes in PostgreSQL;
- selected byte committed once and workspace copy treated as temporary.

### Analysis

- exact request ID pinned in nested proposal schema;
- PDF page locator bounds and excerpt hashes;
- source prompt injection remains inert;
- Class B output cannot become a source citation;
- duplicate node/stable keys, dangling anchors/endpoints, illegal edges, self-edges;
- general knowledge cannot create anchors;
- failed/rejected analysis creates no accepted result or graph delta;
- concurrent capacity remains at most one.

### Curriculum and graph

- framework revision resolution;
- MAJOR/MIDDLE/MINOR/STANDARD parent and ordinal rules;
- cycles, missing parents, alias collisions, mixed framework revisions;
- deterministic nodes/edges/closure/lexical projection;
- old snapshot replay after current pointer changes;
- B-tree/index-backed subtree and adjacency query plans.

### Retrieval and rights

- exact snapshot/policy/permission-set pins;
- restricted source omitted for unauthorized role;
- answer-bearing source requires `AVOID_COPY` and allowed role;
- dedup by immutable pointer, not text/filename;
- budget and token limits;
- no arbitrary SQL/Cypher/path input;
- deterministic Evidence Bundle hashes.

### Legacy item conversion

- missing/ambiguous HWP/JSON pair;
- bad answer pointer, duplicate choices/statements, incomplete explanations;
- stale/missing media Artifact;
- legacy item ID never accepted as EOM Item ID;
- origin/occurrence/rights unresolved state blocks Registry approval;
- successful conversion preserves exact source provenance.

### Dependency and security

- domain/contracts import no infrastructure;
- workers have no DB, NAS, network, sudo, Docker, `eom` group, or peer access;
- no runtime Git/source dependency;
- no external OpenAI/ChatGPT API call;
- Slack output contains no content, paths, prompt/result, or secret;
- default tests do not run live Codex or consume usage.

## 19. Measured acceptance criteria

The first rollout is successful only when:

- 100% of accepted facts have at least one resolving original-source anchor;
- 0 accepted anchors point only to EOMIS/old-server AI-derived output;
- repeated deterministic serialization produces identical bytes and hashes;
- no source, Markdown, image, PDF, HWP/HWPX, node collection, or embedding is stored as a large DB
  value;
- all changed/missing source pointers fail explicitly;
- curriculum hierarchy review has zero dangling/cyclic units;
- answer-bearing and restricted rights tests have zero unauthorized disclosures;
- one rejected/malformed analysis publishes no graph state;
- one historical snapshot and Evidence Bundle replay after a new publication;
- retrieval benchmark records provenance precision, source/page recall, duplicate rate, latency,
  and context-token cost against the legacy baseline;
- EOMIS and old server repositories remain byte-unmodified by the importer.

Thresholds for retrieval recall or educational quality should be fixed only after the first reviewed
fixture set exists. They must not be invented from the current small corpus.

## 20. Release and deployment order

Each boundary requires its own reviewed authorization:

1. schemas/models/tests only;
2. source scanner and dry-run inventory only;
3. deployment of scanner/CLI with no content import;
4. one reviewed Content Intake source;
5. one one-shot Knowledge Analysis run;
6. human acceptance;
7. curriculum authority/structure publication;
8. one small Graph Snapshot;
9. read-only retrieval/Evidence Bundle acceptance;
10. separate knowledge-backed item rollout.

Use the repository-owned API/Catalog/GUI release paths and explicit Conda environments. Apply only
additive migrations after backup/restore proof. Restart only services that import changed packages.
Do not restart HWPX, workers, Observability, Caddy, PostgreSQL, or port 8000 unless a separately
reviewed change actually owns that boundary.

No phase implies authorization for the next phase.

## 21. Rollback and correction

- Inventory dry run: discard only its disposable output.
- Imported immutable source: do not edit/delete; reject, supersede, or retire through lifecycle.
- Analysis proposal: reject it; publish no accepted result.
- Accepted analysis found wrong before graph publication: exclude it from publication and create a
  corrected new run.
- Published graph found wrong: disable retrieval or move current through a reviewed replacement;
  never mutate/delete the old snapshot.
- Retrieval policy found too broad: publish a stricter new policy and disable affected preset;
  historical audit remains pinned.
- Item conversion found wrong: do not register; after registration, correct through a new Item
  Revision under existing rules.
- Legacy source disappears: retain its canonical Artifact Revision; mark the legacy observation
  missing in a new inventory revision.

Rollback never writes to EOMIS, deletes historical source evidence, rewrites Usage, or restores an
old database over newer accepted Item/HWPX/workflow state.

## 22. Open decisions requiring human evidence

These decisions cannot be safely inferred from files:

1. ownership and allowed use of each textbook/reference-book PDF;
2. which PDFs are originals versus exports or duplicates;
3. the official curriculum framework identity and edition boundaries;
4. organization/assessment occurrence for legacy HWP items;
5. which legacy normalized item fields were human-reviewed versus model-produced;
6. whether reference books need a distinct source class/ranking/rights policy from textbooks;
7. the first representative curriculum, textbook, and item acceptance fixtures;
8. whether recurring document editions justify a Document Revision aggregate;
9. acceptable retrieval thresholds after the benchmark fixture exists.

Prompt wording, item-authoring behavior, and product placement policy remain intentionally deferred.

## 23. Recommended first executable slice

The smallest safe slice is:

1. implement the inventory/selection/relation contracts;
2. run a read-only scanner against an allowlisted curriculum source root;
3. review and intake one original curriculum PDF;
4. execute one separately authorized Knowledge Analysis V2 run;
5. review page anchors and hierarchy against the PDF and use EOMIS output only as a discrepancy
   report;
6. decide and implement Curriculum Framework Revision authority;
7. publish one small curriculum-only Graph Snapshot;
8. run read-only retrieval/Evidence Bundle acceptance;
9. stop before prompt or item-production changes.

This slice exercises the new legacy bridge while reusing the strongest existing EOM boundaries. It
also exposes extraction, hierarchy, provenance, rights, capacity, and retrieval defects before a
large textbook or 841-item migration can amplify them.
