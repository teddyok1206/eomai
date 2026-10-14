# System RAG similarity context implementation boundary

Written: 2026-10-12 UTC. Inspected Git base: `550a239cac74b8255bf33467b78671b6d37f811f`.
Status: **DESIGN + CONTRACT / PINNED-READ / COMPOSER / DELIVERY SOURCE CHECKPOINTS; NOT ACTIVATED**.
The separately approved source steps are recorded in sections 8–19. Source observations are not
installed-runtime, production permission, performance, or educational-quality evidence.
This note implements no authority, provider, schema, API, worker, database, model, or release.
The root implementer must read this complete note before changing the common-context boundary.

This is the consumer-side boundary for
[the agreed design](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md), not a replacement
for it. Persistent vector execution, host/runtime closure, actual Identity fences, service IAM,
claim/lease, CPU/CUDA benchmarks, and default-device activation have separate owners. The only
file created during the initial design review was this note; section 8 records later contract work.
Other owners' worktree changes were not altered or staged.

## 1. Decision and truthful first vertical

Start with **one approved reference Item anchor**, first in 1:1 past-exam variation. Reuse the
current official Catalog source/report resolver, actual operator, pinned released policy, Graph,
and the existing Orchestrator Evidence Bundle/materialization boundary. Deliver a small typed
similarity context **beside**, never inside or as a replacement for, existing Graph Evidence and
evidence-usage receipts. This is a real reusable first vertical for the five required consumers;
it is not completion of all five integrations.

The approved anchor is the reference being searched, not the requested private draft or proposed
new Item. Returned context must say this explicitly. For variation, it describes reference-to-
candidate conditions, reasoning, differences, and limitations; it does not claim that the new
draft already preserves that reasoning. Draft-to-candidate comparison requires its own query
successor. No fallback fabricates a V10 report, approval, source membership, or indexed profile.

Do not add a generic search framework, separate search engine, ANN/vector database, candidate
authority, or worker corpus access. Extend the existing Catalog/Orchestrator owners. A registry
row, configured numerical runtime, or validated pointer is not a permission grant.

## 2. Verified source boundaries and gaps

This table records the initial design inventory. Sections 8–10 record subsequent approved
SOURCE implementations; they do not establish installation or operational activation.

| Existing file / symbol | Actual supported meaning | Consequence |
|---|---|---|
| `services/catalog_service/eom_catalog_service/inference_transfer_service.py`: `InferenceTransferSearchCommand`, `InferenceTransferApplicationService.search` | Actual actor plus Graph/policy pins; query is `query_item_revision_id` in the same admitted approved-Item population. Candidate maximum 1,024, `top_k` 1–64. Missing query profile returns `NOT_INDEXED`. | There is no arbitrary-text, RequestDraft, authoring-result, or natural-chat query basis. Query class must currently be admitted alongside candidate classes. |
| `inference_transfer_ports.py`: `InferenceTransferCandidateRanker`, `ScoredInferenceTransferProfile`, `EmbeddingRankerProvenance` | Bounded approved profiles; one cosine per profile; provenance pins a model or identifies `TEST_ONLY`. | Existing result cannot express three independently pinned view indexes, query execution, or per-view coverage. Preserve it; add a compatible context successor. |
| `inference_transfer_catalog_adapter.py`: `CatalogInferenceTransferSourceAdapter._scope`, `_resolve_profile_inputs`, `load`, `authorize_pair`, `reauthorize` | Checks the actual active operator, effective permissions and eligible existing roles against exact released policy; official accepted V10 solution resolution creates deterministic profiles. Reauthorization covers the full population, including unranked/no-report members. | Reuse this authority. Never accept model-supplied ADMIN/WORKER or broaden policy. Counts/hash can leak population and require the same full-population reauthorization. |
| `knowledge_retrieval_service.py`: `ReadOnlyCandidatePoolScope`, `admit_read_only_candidate_pool`, `retrieve_read_only` | Approved Item candidate admission has no lexical-overlap requirement; Graph/lexical retrieval is a separate bounded channel. Admission validates exact source/lifecycle/occurrence/answer-bearing scope. | Vector pool is **not** Graph top64. All vector rows still belong to that actual actor's eligible, pinned Graph/source population. |
| `inference_transfer_snapshot_catalog_adapter.py`: `CatalogInferenceTransferSnapshotSourceAdapter.capture_in_session`, `_materialize_entries` | Same official source boundary with in-session capture/fence seam and bounded, deduplicated canonical Item/report materialization. | Reuse supported capture and reader interfaces. Do not reach into these private methods from a new consumer. Current capture can materialize the entire bounded population; do not advertise vector-only reads as implemented. |
| `embedding_registry_application.py`: `register_embedding_index`, `lookup_missing_embedding_bindings`; `embedding_registry_ports.py`: `EmbeddingRegistryLookup` | Exact registration/replay/CAS and authorized missing-binding/reusable-row lookup. Lookup is internal and is explicitly not corpus discovery or a public wire contract. | There is **no pinned read-index/candidate application use case** yet. Missing-binding API is not a search API and must not be exposed as one. |
| `embedding_registry_repository.py`: `EmbeddingRegistryRepository.revision`, `encodings`, `bindings`, `missing_bindings`, `head` | Scalar/pointer persistence and indexed anti-join; `head` takes a write lock for registration. | Add the smallest owner-local read lookup for an exact immutable revision. Do not lock or dereference mutable `head` as search identity. |
| `embedding_registry_catalog_adapter.py`: `CatalogEmbeddingRegistryVerifier`, `EmbeddingRegistryOwnerConfiguration` | Concrete official source/member composition; `identity_fence` is mandatory, absent fence fails closed. Configured space is DOCUMENT. No controller/transport/background admission is activated here. | Reuse its **public** verification boundary or add an explicit read method there; no second source-authority provider and no claim of installed IAM. Stale docstrings elsewhere do not supersede this concrete source fact. |
| `packages/catalog_contracts/eom_catalog_contracts/inference_transfer_embedding.py`: `IncrementalEmbeddingInput.exact_input_rows`, `IncrementalEmbeddingResult`, `EmbeddingSpace` | Incremental corpus input is **DOCUMENT only**, despite `EmbeddingSpace` representing QUERY or DOCUMENT. Native result is an exact source-neutral input/shard closure. | Do not pass QUERY into index input or relabel a DOCUMENT vector as a query. Production QUERY execution needs an explicit successor. |
| `local_embedding_adapter.py`: `ExactLocalEmbeddingRanker.rank`, `LocalTextEmbeddingBackend.encode`; `inference_transfer_vectors.py`: `rank_normalized_vectors` | Existing optional ranker encodes query with QUERY prefix and all candidates with DOCUMENT prefix for CONCRETE_FACETS, then exact cosine. | This is the compatibility route, not persistent-vector reuse. Do not re-encode every document in the new persistent read path. |
| `packages/catalog_contracts/eom_catalog_contracts/embedding_device_benchmark.py`: `BenchmarkPurposeSpaces.genuine_purposes`, `BenchmarkWorkerInvocation`; native benchmark execution | Benchmark enforces distinct genuine QUERY/DOCUMENT spaces of one model/runtime. | Benchmark QUERY is measurement-only, **not an admitted production query API**. Never replay benchmark worker invocations as a consumer operation. |

All paths in the middle rows are under `services/catalog_service/eom_catalog_service/` unless a
package path is given. These observations were checked by reading source, not by live calls.

Current source classes remain `PAST_EXAM` and `APPROVED_ITEM` with accepted V10 reports. Textbook
EducationalDocument chunks, private uploads, and Chat histories are not Item profiles or this
index's corpus. Textbook evidence retains its existing GraphRAG route; private uploads and Chat
histories remain excluded from public corpus enrollment. Approved Item without accepted report
is missing report/partial coverage, not synthetic CONTENT_ONLY success.

## 3. Query basis by consumer — all five remain required

| Consumer / actual entrypoint | Minimal reference-anchor connection | Explicit remaining query / consumer change |
|---|---|---|
| **1:1 past-exam variation**: `PastExamVariationRequest` and `EducationalRetrievalRequirementV2` in `packages/catalog_contracts/eom_catalog_contracts/knowledge.py`; `WorkflowCatalogService.source_material_requirement`, `_past_exam_variation_source`; `resolve_evidence_materials` in `services/orchestrator/eom_orchestrator/execution_materializer.py` | Use exact `past_exam_variation.source_item_revision_id`, source Artifact, Graph and policy captured in the grounded execution plan. Keep exact original source and variation intent. Candidate pool is separate from the one-source variation Evidence selection. | First actual vertical. A successor plan pins auxiliary context/materials separately; current plan cannot receive new untyped keys. No alteration of source-copy policy, approval, or original Evidence receipt. Missing anchor report explicitly disables vector context. |
| **New authoring**: `WorkflowRequest.item_brief`, `educational_retrieval`; `WorkflowCatalogService.prepare_prompt`, `_prompt_context`; `KnowledgeRetrievalApplicationService.create_item_production` | An official Graph-selected approved reference may be searched as an **explicit reference anchor**. The resulting context describes that reference, not semantic search of the new brief. Anchor selection is deterministic, pinned and purpose-authorized; no hidden model-chosen source. | Searching the actual objective requires a `PRIVATE_AUTHORING_INTENT` query basis that pins validated brief/request identity and hash, a released text recipe, and admitted production QUERY execution. No accepted-report/profile claim. If no reference is available, ordinary Graph path continues with explicit auxiliary unavailability. |
| **Review / re-review**: `WorkflowCatalogService.classify_review_rework`, `_prompt_context`; `WorkflowRunner` in `services/workflow_runner/eom_workflow_runner/engine.py` review correction/rework transitions; `ContentTeamAuthoringRoleResultV12`, `ContentTeamReviewRoleResultV12` | Review may reuse the same pinned authoring reference context and compare it only as a reference observation. Reauthorize for the current actual operator and exact review purpose. | Searching the candidate draft requires `PRIVATE_AUTHORING_RESULT` basis pinning workflow/step/attempt and exact result Artifact revision/hash/schema, plus a question-only projection recipe. It is not an approved Item, V10 report, or corpus insertion. Comparison to approved candidates requires a distinct draft-comparison contract, not `authorize_pair` with a fabricated approved left profile. Preserve existing maximum-three-pass/escalation/correction behavior. |
| **General → ChatGPT**: `ChatRagResolutionService.resolve`, `_resolve`, `_authority`, `_authorize_context`; `ChatRagToolBroker.execute`; `NativeRagChatTools.call` | After an existing read tool materializes an approved Item reference, explicitly offered related-reference context can use that exact authorized anchor. Textbook `retrieve_eom_knowledge` keeps its EducationalDocument evidence. Existing tools remain the only offered tools until a compatible release activates a successor. | Natural-language query needs `PRIVATE_CHAT_QUERY` basis from the exact owned turn/message revision/hash or its existing durable immutable execution pointer, explicit bounded text recipe, and production QUERY admission. `ChatRagArguments.terms` is Graph term lookup, not this semantic query contract. Read-only policy may deny answer-bearing approved profiles; denial is not grounds to borrow authoring authority. Follow-ups pin and reauthorize context/index/Graph/policy/source, never latest. |
| **25-Item assembly**: `MockExamAssemblyService.preview`, `create_planned`; `MockExamCandidateRepository.resolve`; `build_mock_exam_assembly_plan` in `packages/catalog_contracts/eom_catalog_contracts/mock_exam_planner.py` | Use exact selected/cohort approved Item revision anchors to obtain independent bounded observations. Shared pool resolution and row reads are batched/deduplicated; no per-screen query implementation. | Accepted V10 may be absent even for approved/rated cohort members. Report partial coverage. Pair/repetition observations are a separate sidecar pinned to exact plan/cohort hash; they do not change deterministic slot selection, rating, approval, publishing or regeneration. A compatible preview/result successor exposes them; current closed plan/manifest has no such field. No new 25-Item or HWPX generation is required for this gate. |

Anchor mode is a narrow capability available to multiple consumers, not a silent substitute for
their actual intent. Every consumer records which basis it used and whether its target mode is
`NOT_IMPLEMENTED`, `NOT_OFFERED`, unavailable, source-tested, or live-verified. The full five-
consumer target remains open until its requested basis, delivery, prompts and activation are
implemented and verified; a matrix of planned adapters is not a completion claim.

## 4. Protocol-first minimum source changes

The following names/versions are **proposed**, not existing registered schemas. Root review must
approve the exact schema boundary before behavior. Do not edit released predecessor bytes.

1. New closed JSON Schema 2020-12
   `schemas/knowledge/system-rag-similarity-context-v1.schema.json`, mirrored to
   `packages/catalog_contracts/eom_catalog_contracts/resources/knowledge/`, registered by the
   existing offline registry in `validation.py` with exact raw SHA. New frozen Pydantic models
   in `packages/catalog_contracts/eom_catalog_contracts/similarity_context.py`; export the public
   parsers/models via existing `__init__.py`. No infrastructure/ML imports.
2. First request/result carry `APPROVED_REFERENCE_ITEM` **only**. Do not initially add a generic
   union of unimplemented private query types. Concrete later successors add the three private
   bases above once ownership and execution are real. A first contract for all existing views
   may report an unavailable view; it must not declare that view ready without verified rows.
3. Separate minimal production QUERY input/result schema, proposed
   `schemas/knowledge/embedding-reference-query-v1.schema.json` and frozen
   `embedding_reference_query.py`, before a native behavior successor. This task does not assign
   a new compute purpose, provider, IAM, lease, installed runtime or API activation. The existing
   execution owner must supply supported production admission, or vectors remain unavailable.
4. A compatible grounded item-plan successor pins the auxiliary context Artifact member and
   hash separately from Evidence Bundle fields. New materialization manifest/workspace member
   meaning is schema-first. Existing plan V19/V20, role schemas, pack versions and replay bytes
   remain unchanged. Do not choose a version number by assuming other branches are absent.

### 4.1 First common request and context shape

- Request: consumer purpose enum (`PAST_EXAM_VARIATION`, `ITEM_AUTHORING`, `ITEM_REVIEW`,
  `GENERAL_CHAT_READ`, `MOCK_EXAM_OBSERVATION`), approved reference source/profile/report pointers,
  exact Graph and released policy revision/hash, explicit index revision/member pointer per
  requested view, query/document space pins, recipe pin, canonical source classes/topic/unit
  scope and bounded budgets. The authenticated actual actor is an application value injected
  by the owner, not worker-controlled authority. No paths, arbitrary metadata dictionary, roles,
  permission claims, approved flags, or source text in the cross-component request.
- Pinned index selection happens at an existing trusted initial request/plan preparation
  boundary; result and history retain the selected immutable revision. If no exact index is
  available, return an explicit status. Retry/follow-up cannot resolve current/latest instead.
- Result is a discriminated closed `READY`, `PARTIAL`, `EMPTY`, `UNAVAILABLE` or `FAILED` union.
  Vector mode is explicitly `OPTIONAL` or `REQUIRED`, with per-view coverage/status and stable
  limitations. `FAILED` carries no candidates/population metadata. Ready does not mean full
  corpus coverage, accepted transfer, or educational quality. Schema rejects contradictory
  candidate/status/count combinations and arbitrary extra fields.
- Candidate key is exact source logical ID/revision plus profile revision/hash. Reuse
  `ApprovedItemKnowledgeSourceV2` or the actual approved past-exam source subtype,
  `InferenceTransferProfilePointer`, `KnowledgeSolutionEvidencePointer`,
  `KnowledgeGraphSnapshotPointer`, `ArtifactMemberPointer`, `EmbeddingVectorRowRef` and
  `EmbeddingIndexManifest` pointer semantics. Preserve full official subtype lineage when it is
  required; never downcast away occurrence/page authority. Candidate has no complete Item,
  profile claims, report, vector, PDF/PNG bytes, or large JSON blob.
- Provenance is a bounded tuple of **separate** channel observations: `GRAPH_LEXICAL` graph
  milli-score and rank; `VECTOR` view, exact index/query/document space/recipe/execution pins,
  rank and approximate cosine display. The same source may have several observations without
  appearing several times. Do not mix three view scores, cosine and Graph scores into a single
  confidence, probability, threshold, approval or physics judgement.
- Canonical hashed JSON does not accept float arrays or relax the existing serializer. Proposed
  wire scalar is signed integer `cosine_millionths` in `[-1000000, 1000000]`, **display only**.
  Exact ranking uses existing finite float64 cosine semantics and exact reference tie keys
  before rounding; pins allow replay of the underlying rows/recipe. Rounded values cannot
  determine ties, candidate inclusion or a new quality threshold. No percentage rendering.
- Population envelope retains distinct authorized source count/set hash, accepted-profile
  count/set hash, requested-view available binding count/set hash, actually scored count, missing
  report/view counts, and explicit truncation. Do not call these values the same denominator or
  expose global/unauthorized registry counts. If an exact authorized source population exceeds
  the first 1,024 bound, expose bounded/truncated scope, never full-corpus coverage. Existing
  520/1,560 observations are not constants in the new contract.
- Existing Graph Evidence pointer/receipt is a separate optional field/reference, not copied
  entries. Similarity observations are not `evidence_id`s and must never satisfy current
  `SCIENTIFIC_VALIDATION`, `CURRICULUM_SCOPE`, or evidence-usage approval gates.
- Explanation is an optional exact comparison request/result Artifact pointer and explicit
  `MODEL_INFERENCE` label; never synthetic source Evidence. Approved-anchor/candidate pairs may
  reuse the supported V1/V1.1 comparison contracts and `authorize_pair` only when both approved
  profiles/purpose/control pins are valid. `INSUFFICIENT` remains explicit. Scores alone cannot
  manufacture conditions, a decisive inference, additional reasoning, or a comparison result.

### 4.2 QUERY execution closure

Reference query preparation resolves the approved source/profile/report first, then renders only
the requested view with `experiment_view_text` and the exact released `ExperimentViewRecipe`.
One bounded local materialization contains 1–3 query text rows and exact input hashes. It is not
registered as public corpus data. Missing metadata/content or overflow is per-view unavailable;
never truncate numbers, units, conditions or tail negation.

The proposed input/result must pin job/request/input-set hash and purpose QUERY; the source owner
retains source authority and the numerical worker receives only staged bounded text/encoding
identity. Reuse the binary codec and Artifact publication boundary without relaxing
`IncrementalEmbeddingInput` DOCUMENT invariant or reinterpreting legacy incremental results.
Query vectors remain distinct QUERY-space artifacts/pointers. Their document counterpart must
have equal exact model spec and numerical runtime/precision/normalization recipe, complementary
purpose and distinct space hash, as `BenchmarkPurposeSpaces` demonstrates **for the benchmark
only**. A small pure production compatibility validator can express this same invariant; it is
not imported from a benchmark framework and does not confer compute admission.

CPU vs CUDA spaces are distinct; no query CPU/document CUDA pairing, alternate view, alternate
recipe, alternate storage partition, or latest-index fallback. A compatible released device
selection may pick a new complete pair before preparation, and pins both. Once prepared, retry
must retain that pair. GPU failure cannot be hidden by another space. There is currently no
admitted persistent query cache; do not add a global registry/cache for private query text.

## 5. Required 11-item design note

1. **Responsibility / boundary:** Catalog owns candidate admission, exact index/binding closure,
   bounded context composition and reauthorization. Orchestrator owns job/staging, validated
   Artifact commit and consumer execution delivery. UI/CLI only construct/render typed requests;
   workers neither search DB/NAS nor coordinate with other workers.
2. **Canonical source:** Existing immutable Item/source/report/Graph/policy Artifacts are the
   canonical evidence. Vector shards/indexes and similarity contexts are reproducible auxiliary
   derivations, not a second corpus or authority. Comparison text is model inference.
3. **Entity / revision model:** Keep source Item logical ID, Item revision, profile ID/revision,
   analysis runs, index ID/revision, Artifact ID/revision and content hashes separate. Context
   request/result hashes pin derivation, not source identity. Historical requests never resolve
   mutable heads. No new durable context registry is needed for the first vertical: one existing
   committed Artifact plus its typed pointer is enough.
4. **Pointers / resolution:** Resolve existence, approved lifecycle, actual purpose permission,
   Graph membership, report acceptance/lineage, schema/version, media/size, committed file set,
   exact raw/semantic hashes, row index, dimensions/finite/unit norm, storage partition, view,
   recipe and QUERY/DOCUMENT pair. Reuse `PinnedArtifactReadContext` and public official verifier
   seams. Dangling/stale/revoked/hash mismatch fails; no latest substitution or claimed repair.
5. **Access patterns:** Exact immutable key lookup; eligible-population membership; binding join;
   shard deduplication; ordered per-channel exact top-k; small union; bounded batched evidence
   reads; reproducible append-only history. Index reads are not registration/missing-work scans.
6. **Structures / indexes:** Maps keyed by exact source/profile and encoding; sets for union and
   unique shard/member identities; immutable tuples for ordered observations. Reuse registry
   PK/revision/FK and association unique/indexed columns. Add only an exact immutable revision
   read/namespace check and batched binding/row lookup if current repository lacks it. Review
   B-tree PK/composite indexes and query plans; no new GIN/ANN index without a measured need.
7. **Complexity / scale:** First source scope at most 1,024; up to three real views and 64 returned
   candidates, smaller policy/materialization budgets prevail. Exact cosine O(VNd), sorting
   O(VN log N) with stable full-reference ties, union O(Vk), metadata O(N + Vk), vector bytes
   O(VNd). Read each unique immutable shard/member once per authorized request; stream rows if
   needed within memory bounds. Source/report projection and neural encode have separate cost;
   do not call them O(Nd). Twenty-five reference queries batch population/rows once; do not
   repeatedly scan/hash/parse the corpus. A bounded 25×24 repetition observation is explicit,
   not an unbounded all-corpus pair graph.
8. **Transaction / concurrency:** Capture exact authority/population/index closure in the
   Catalog read/authorization transaction, release it before slow encode/optional Codex work,
   then reauthorize the same full returned population immediately before disclosure/commit.
   Context metadata commit uses the official owner's appropriate retained fence/transaction;
   no long encoder under source locks. Immutable index reads need no current-pointer CAS.
   Concurrent source/policy revocation, report change, or population change blocks the pending
   result including counts/hash. Actual fence semantics belong to Identity/source owners.
9. **Layers / adapters:** Contract/pure view/ranking logic imports contracts only. Catalog
   application coordinates supported source and index read interfaces. Existing infrastructure
   owns SQL, NAS/member bytes and numerical execution adapters. Consumers call the common
   application boundary, never repository/private resolver methods. New source-only modules may
   be cohesive functions, not a DI framework, singleton registry or catch-all manager.
10. **Failure / retry / idempotency:** Ordinary optional absence/not-prepared/runtime-not-offered
    produces explicit vector `UNAVAILABLE` while the existing valid GraphRAG output continues.
    Required-vector requests return explicit unavailable, not Graph-only success. Permission,
    pointer, schema/hash/lifecycle or authority integrity failures fail closed; they are not
    optional model absence. Same command/key and pinned context/index/query execution replay is
    deterministic and reauthorized; timeout is not proof of unprocessed work. Do not retry with
    another space or regenerate accepted reports. Partial coverage never becomes COMPLETE.
11. **Simpler alternative:** Repeating Graph searches in each screen loses unified pins,
    reauthorization, provenance and duplication semantics. Wrapping the existing transfer result
    alone cannot read persistent per-view rows or represent private intent; recomputing all
    candidates wastes the new index. The minimal extension is one approved-anchor context schema,
    exact read-index application function, production QUERY successor and one consumer adapter.
    Generic multi-basis search, query cache, standalone candidate provider, ANN and automatic
    educational judgements are unnecessary for this first boundary.

## 6. Concrete implementation order and source gates

1. **Contract-only change:** Add proposed context/reference-query closed schemas, packaged mirrors,
   registry metadata/raw hashes and frozen models. Preserve old registry resource bytes and
   fixtures, including `schemas/knowledge/item-inference-transfer-v1.schema.json`,
   `item-inference-transfer-embedding-v1.schema.json`, `embedding-registry-v1.schema.json`,
   `schemas/general-chat/general-chat-rag.schema.json`, existing plan/role/pack files. Freeze raw
   predecessor SHA snapshots in tests before any runtime behavior; do not overwrite approved
   `ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md` or original content-team instructions.
2. **Exact pinned index read:** Extend the existing registry owner with proposed public
   `read_pinned_embedding_index` application use case and small typed resolved read value, not
   a second provider. Extend its verifier's public read intent explicitly and add read-only
   repository revision/batched lookup if required. Reuse official capture, `PinnedArtifactReadContext`,
   binary validator and existing binding validation. Fakes demonstrate SOURCE_PASS only.
3. **Context compose:** Add proposed `services/catalog_service/eom_catalog_service/similarity_context_service.py`
   and cohesive application-owned ports only where real adapter substitution needs them. Reuse
   existing `InferenceTransferApplicationService` behavior/tests for Graph/union semantics;
   extend common owner behavior rather than copy its authority into this module. New read path
   uses verified persisted document rows and one actual approved-anchor QUERY execution; no
   per-candidate encoding. First tests use one source beyond Graph baseline and all three view
   pins, with no cross-view score arithmetic.
4. **Production reference-query execution:** Execution owner adds only supported native QUERY
   successor/materializer/admission as required by section 4.2. Until then context's vector leg
   is explicitly unavailable, never declared functional because benchmark QUERY ran. Source
   contract tests do not activate runtime. Persistent query/artifact tests use the existing
   Orchestrator publisher; workers write local results only.
5. **Variation delivery:** Add a compatible grounded plan/materialization successor and a minimal
   immutable `generated-knowledge-item` pack/profile successor. Pin auxiliary context pointer in
   prompt/execution provenance and stage only bounded candidate evidence needed by authoring/review.
   Existing Artifact members `evidence/context.md`, `evidence/manifest.json`, workspace members
   `references/evidence/context.md`, `references/evidence/manifest.json`,
   `references/variation/request.json`, `references/variation/source-item.json`, and Evidence usage
   fields are unchanged. Do not smuggle context into old additionalProperties-
   false input/request/plan values. Claim live variation only after its actual successor release,
   activation and one existing authorized-source canary pass.
6. **Remaining four consumers:** Add each concrete private-query successor/adapter and explicit
   prompt/output/receipt compatibility where needed, in the agreed order (authoring/review,
   chat, assembly). A reference-only connection is labeled as such. New context/tool fields use
   compatible schema successors and real offered-tool activation, not mutations of old chat
   transcript bytes. Assembly uses a separate observation sidecar, not a score-driven planner.

No new dependency is proposed. Core formatting/linting/strict typing and focused tests use the
repository's explicit Conda environments. Disposable DB tests remain opt-in; production DB,
external LLMs, model downloads, new full 25-Item generation, HWPX generation and human quality
evaluation are not prerequisites for the source-only context gate.

## 7. Fixtures and required regressions

Reuse these exact fixtures/tests; extend their supported public seams, not unrelated runtime WIP:

- `tests/unit/inference_transfer_fixtures.py: profile`; `test_inference_transfer_service.py:
  exact_profile`, `Sources`, `corpus`, `command`: nonlexical vector candidate, Graph union,
  out-of-scope/duplicate rejection, no-report/unindexed query and unranked/no-report revocation
  blocking returned population counts/hash.
- `tests/unit/inference_transfer_embedding_fixtures.py`: `embedding_entry`, `source_binding`,
  `vector_shard`, `index_manifest`, `index_pointer`, `shard_pointer`, `seal`;
  `embedding_registry_application_fixtures.py`: `capture_pair`, `MemorySession`, `MemoryRepository`;
  `test_embedding_registry_catalog_adapter.py`: `OwnerSession`, committed synthetic file sets.
  Cover missing/stale revision, forged namespace/view/recipe/partition, revoked source/report,
  hash/schema/media/row mismatch, immutable historical read and each unique shard read once.
- `test_inference_transfer_embedding_contracts.py`: predecessor raw-hash and resource freeze,
  DOCUMENT-only input, distinct CPU/CUDA/purpose space, exact result/reference closure and
  forbidden infrastructure/ML imports. `test_embedding_native_stdio.py`: invalid/corrupt input
  never constructs backend or re-encodes; existing index behavior remains unchanged.
- `test_past_exam_variation_mode.py`, `test_execution_materializer.py: _past_exam_variation_fixture`,
  `test_knowledge_backed_execution.py`, `test_review_evidence_binding_pack_successor.py`,
  `test_variation_review_grounding_pack_successor.py`, `test_bounded_review_rework.py`,
  `test_review_correction.py`: original source/intent, compatible minimal successor, exact Evidence
  usage validation, source-copy restriction and maximum-three-pass behavior remain unchanged.
- `tests/unit/general_chat_rag_fixtures.py`, `test_chat_rag_resolution.py`,
  `test_general_chat_rag_owner.py`, `test_general_chat_rag_contract.py`,
  `test_general_chat_grounding_contract.py`: actual actor/policy, pinned history, optional absence
  vs invalid pin, no unoffered tool, read-only/answer-bearing restrictions, no pixel claim from
  text-only evidence and no Item casting of textbook/private chat sources.
- `test_mock_exam_assembly_contracts.py`, `test_mock_exam_candidate_repository.py`: exact approved
  cohort after Item head advancement, missing rating/report, deterministic unchanged placement
  selection, bounded indexed queries and hash-pinned observation sidecar without publication.

Add source-only focused tests proposed as `test_similarity_context_contracts.py`,
`test_similarity_context_service.py`, `test_embedding_reference_query_contracts.py`,
`test_embedding_registry_read.py` and `test_similarity_context_consumer_boundaries.py`:

1. Closed Draft 2020-12 validation precedes behavior; frozen models revalidate nested copied/
   constructed values, reject authority/paths/extra keys and incorrect supplied hashes rather
   than silently deriving/repairing them. Canonical serialization is float-free and deterministic.
2. Approved-anchor mode rejects private RequestDraft/new authoring/chat text and fabricated V10;
   actual consumer basis is visible. No source authority from row/FK/test fake/model claim.
3. Vector candidate absent from Graph top64 remains searchable within admitted pool; outside-pool
   canary never appears or affects result counts/hash. Source classes, policy/answer-bearing and
   purpose restrictions precede row access. Entire exposed population is reauthorized.
4. Separate view/provenance score/rank, stable full-reference ties before rounding, deduplicated
   source union, bounded context/materialization and explicit missing report/metadata/content.
   High similarity changes neither approval nor physics/transfer/probability decisions.
5. OPTIONAL unavailable keeps original valid Graph output and receipt unchanged; REQUIRED
   unavailable is explicit; permission/hash/stale failures never pass as optional absence.
   No alternate device/space/view/latest fallback. Query/document same runtime compatibility
   rejects CPU/CUDA or recipe mismatch and DOCUMENT-as-QUERY relabeling.
6. Revision-pinned repeat/follow-up, revoke-between-rank-and-result, model/runtime drift, no partial
   disclosure on failure, query Artifact commit/replay without duplicate encoding, and no worker
   DB/NAS/network/peer access. Large binaries and full source/report data stay out of DB/context.
7. Synthetic 1,024-row/three-view measurement or query-plan/read-count test demonstrates batched
   registry lookup and unique-shard resolution. Twenty-five anchors do not cause 25 full corpus
   captures/parses/hashes or N+1 row reads. Include missing/stale/hash/lifecycle/duplicate cases.

Record `SOURCE_PASS / DISPOSABLE_DB_PASS / INSTALLED / ACTIVE / LIVE_VERIFIED / NOT_IMPLEMENTED /
NOT_EVALUATED` separately. Context/schema source pass, persistent index coverage, production QUERY
admission, CPU/CUDA performance/default activation, each consumer delivery, and human educational
quality have different evidence and denominators. This note alone satisfies none of those gates.

## 8. Contract-only source checkpoint — 2026-10-13 UTC

The approved first boundary now has two additive closed Draft 2020-12 schemas and their exact
packaged mirrors: `system-rag-similarity-context-v1.schema.json` and
`embedding-reference-query-v1.schema.json`. Existing Catalog `validation.py` registers their raw
hashes; public models/parsers are exported through the existing package interface. Released
predecessor schema bytes and the original 296-entry inventory hash remain unchanged. Its existing
freeze test excludes exactly the two new resource names, not a wildcard or a revised denominator.

`similarity_context.py` carries approved reference anchors only, purpose-specific request metadata,
three independent view selections, immutable index/space/recipe pins, scoped coverage, five closed
result statuses and separate Graph/vector observations. Signed `cosine_millionths` is explicitly
display-only. Optional absence can retain Graph observations; required vectors cannot be replaced
by Graph-only success. Missing anchor reports disable reference QUERY explicitly. Full official
past-exam page lineage is retained. FAILED exposes no candidates, population, query or Graph
Evidence. Neither candidates nor comparison explanations satisfy existing Evidence receipts.

`embedding_reference_query.py` is a distinct source-neutral QUERY input/result and execution
pointer contract. QUERY/DOCUMENT must have complementary purposes and identical exact model,
runtime, device, precision and normalization. One bounded query has 1–3 exact view/text/encoding
rows; existing f32 shard metadata is reused without changing DOCUMENT-only incremental inputs.
Pure supplied-index and supplied-query closure helpers reject mismatched revision/view/recipe,
space, execution and row references. Actual target existence, raw member bytes/hash, source/report
lineage, current permission, lifecycle and compute admission remain the owners' required checks.

Models preserve raw copied/constructed extras, booleans and scalars before schema/Pydantic
validation, reject incorrect hashes rather than repairing them, and retain float-free canonical
serialization. Bounded nesting rejects cycles. No new dependency was added. Explicit API Conda
source gates: strict typing, Ruff lint and formatting PASS for seven Python files; the focused
new-contract plus predecessor suite passed 170 tests (5.06 seconds). The final broader
eleven-suite contract/consumer regression passed 377 tests (16.66 seconds). Overlapping suites
are not additive counts. Initial local test/typing failures were corrected and rerun; no failed
runtime or historical product record was rewritten.

**SOURCE_ONLY / NOT_ACTIVE.** No Catalog read/provider behavior, protocol transport, DB/IAM,
Runner, runtime, benchmark admission, consumer/prompt/plan, installation or operational query was
changed. No model/GPU invocation or new consumer tool was activated. All five consumer connections
and genuine production QUERY admission remain unimplemented at this checkpoint. A valid synthetic
contract fixture is not evidence that production QUERY exists.

Root independently read all twelve frozen contract files and checked every raw SHA. Its eleven-suite
contract/registry/source/consumer compatibility gate passed **411 tests in13.91s, skip0**, with
explicit strict mypy and Ruff/check-format **seven files PASS**. The root inventory also includes
`test_item_inference_transfer_contracts`, `test_inference_transfer_service`,
`test_embedding_registry_application` and `test_embedding_registry_catalog_adapter`; it differs
from the agent's377-test gate, so these overlapping counts are not summed. Protocol-only validation
does not establish current source permission, installed QUERY execution, or consumer activation.

## 9. Exact pinned index read delta — source implementation scope

This step extends only the existing registry application/ports/repository/Catalog verifier and
their focused tests. The owner-local read intent reuses `EmbeddingRegistryLookup` and frozen
`SimilarityViewSelection`; no new public wire/schema, authority provider, registry, migration or
consumer query is introduced. The exact index must be present. An absent Identity/source owner
remains `EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE`, never a permissive adapter default.

Read authorization reuses public `capture_in_session` with the actual caller's current Identity
fence, active operator/role, ITEM_READ, KNOWLEDGE_GRAPH_RETRIEVE, KNOWLEDGE_ANALYSIS_READ and
CONTENT_INTAKE_READ for past exams, plus the exact released answer-bearing policy. The existing
ITEM_PREPARATION scope is not a grant for a future Chat/private-intent operation. The existing
`knowledge_graph:publish` condition remains exclusively a registration/write check.

The application authorizes before an exact PK/revision + immutable namespace lookup, verifies
the committed canonical index through its existing owner, then batches selected encoding/binding
lookups and performs late authorization in the same caller-owned transaction. No head/current
pointer lookup, FOR UPDATE, write, flush, commit, implicit latest or historical count reuse occurs.
Current official source/report eligibility chooses the subset before numeric member reads.
Out-of-scope historical sources/rows and full index metadata remain internal to the verifier;
currently eligible stale source/report/hash pins fail explicitly rather than being rebound.
Historical binding-origin pointers are not dereferenced or exported as authority when the exact
requested committed index independently contains and validates the same immutable binding.

The read value contains only the requested index/namespace pointers, currently authorized source
and accepted-profile references, selected bindings, and owner-local selected numerical rows.
Full Item/report text, global historical counts and unselected numerical rows are not returned.
Numerical tuples exist only at this explicit local read/materialization boundary, never in DB or
wire DTOs. The existing private shard/result/binary validator is factored inside the same owner
to read/validate each selected unique member once; no parallel binary reader is added.

Maps/sets join exact source, profile, binding and encoding identities; existing indexed batch
queries and PK/FK/namespace indexes are reused. The work is O(N + R + Sd) for N authorized sources,
R selected bindings and S materialized shard rows, with O(N + R + Sd) bounded local memory.
Registration/missing-binding signatures and behavior remain unchanged. Retry reuses the exact
immutable selection and reauthorizes it; source revocation or missing/corrupt targets is not a
reason to select another index. Actual installation/IAM/API/QUERY/consumer activation remains
outside this source-only step.

### 9.1 Pinned-read source checkpoint — 2026-10-13 UTC

The seven approved source paths now implement the exact revision read and owner-local resolved
value. The application suppresses SQLAlchemy autoflush, checks the required read owner before
lookup, validates raw copied selection values with the existing closed 2020-12 view schema,
and reauthorizes after batched scalar binding/encoding checks. Wrong nested owner values fail
with a stable pointer error rather than an uncaught attribute error. Numeric finite/shape/hash
and unit-norm validation remains solely at the existing authoritative f32 codec; there is no
duplicate normalization or corruption repair.

The same owner-local generator verifies numerical shards for both registration and read.
Registration retains only the previous manifest result, not decoded corpus matrices. A read
retains only selected row tuples and one working shard matrix at a time. Tests cover two logical
sources sharing one numerical row with one read of each unique index/result/shard/binary member,
and a 1,024-binding synthetic case using one binding batch and one unique-encoding batch. These
are source complexity/read-count checks, not a live query plan, throughput benchmark, or IAM grant.

Explicit API Conda source gates: strict mypy, Ruff lint and format check **six Python files PASS**;
focused new-read plus old application/owner regression **81 tests PASS in 17.52s**; the eleven
suite read/registry/contracts/planner/codec/source-resolution regression **270 tests PASS in
24.25s**, skip zero. The inventories overlap and are not added. `git diff --check` passed for the
seven approved paths. No model, GPU, DB, installed-runtime or historical-product execution was
performed for this source step.

**SOURCE_ONLY / NOT_ACTIVE.** Context composition, genuine production QUERY admission and the
five consumer connections remain subsequent steps. This read is not a public search endpoint,
background grant, chat scope, or proof of operational installation. Missing actual owners stay
explicitly unavailable; synthetic source/authority fixtures never stand in for production grants.

Root independently reviewed all seven frozen paths, matched their raw SHA values, and reran the
eleven suites: **270 PASS in 24.75s, skip0**; strict mypy, Ruff lint and format **six files PASS**.
The first root invocation named two nonexistent test paths and executed no tests; after resolving
the actual repository filenames, the recorded gate above passed. This was an invocation correction,
not a runtime retry or a hidden product failure. The overlapping agent/root counts are not summed.

## 10. Approved C0 composer delta — source only

Approved paths: new `similarity_context_service.py`, `similarity_context_ports.py`,
`test_similarity_context_service.py`, `test_similarity_context_consumer_boundaries.py`; existing
`embedding_registry_catalog_adapter.py`, `inference_transfer_service.py`, their two test files,
and this note. No released schema, production QUERY runtime, Pack, CLI, DB, IAM or Git change is
part of C0. First concrete purpose is approved-reference past-exam variation; other consumers are
explicitly unoffered, not granted by the purpose enum. Non-empty topics/unit constraints are
rejected until the official owner supports them; they are never silently ignored.

1. **Responsibility:** The Catalog application composes independent candidate observations.
   The existing Catalog verifier owns actual source/index/member reads. A mandatory query-result
   verification seam owns an already committed genuine QUERY; C0 neither launches nor publishes it.
2. **Canonical source:** Official immutable Item, accepted report, Graph and released policy remain
   authority. Context and numerical rows are local auxiliary derivations, never Evidence receipts.
3. **Identity:** Request/context hashes, source/profile/report revisions, index/space/recipe and
   query execution/member identities stay separate. No new registry, query cache or mutable head.
4. **Resolution:** Reuse public official capture, pinned index application read, f32 codec and
   pure QUERY closure validators. Prepare exact anchor view texts only at the local preparation
   boundary; query hashes must correspond to them. Invalid/missing/revoked pointers fail closed.
5. **Access patterns:** Bounded population capture, exact view/revision lookup, profile/encoding
   joins, unique member reads, independent top-k and deduplicated union, final full reauthorization.
6. **Structures:** Frozen local tuples, maps and sets; reuse existing registry indexes. A small
   bounded channel-union function serves both the legacy service and new composer; no framework.
7. **Complexity:** At most 1,024 sources, three views and 64 results. Exact cosine O(VNd), sorting
   O(VN log N), source union O(Vk). Only selected rows escape owner materialization. Source decoding
   and numerical runtime have separate costs; fake read-count checks are not throughput evidence.
8. **Transactions:** Preparation and final read use separate caller-owner transactions around any
   slow QUERY. Inside one multi-view read, actual scope authorization is performed per view; the
   official full population is captured at start and end and compared with prepared exact pins.
   An owner-private window reuses decoded immutable members and captured inputs only inside the
   exact Session/root transaction/caller/Graph/policy/recipe window. READ COMMITTED or Session
   possession does not freeze source membership or grant permission. No current membership or
   permission is accepted from a cache; end capture detects change before any disclosure. The
   existing source owner's retained row/Identity fences remain required. No window crosses QUERY.
9. **Dependencies:** Application ports contain small local values and required verification methods;
   existing Catalog verifier implements source behavior. Core imports no SQL/filesystem/ML. Query
   verifier absence is explicit, never replaced with benchmark or a test-only runtime grant.
10. **Failure/replay:** OPTIONAL ordinary absence preserves valid Graph observations; REQUIRED
    absence is unavailable. Permission, source/hash/index/query corruption returns FAILED without
    candidates/counts/evidence. Same pins are reauthorized; no device/view/latest substitution,
    report fabrication, worker execution, or failure-history rewriting.
11. **Alternative:** The old on-demand ranker recomputes every DOCUMENT and cannot convey three
    pinned indexes. A standalone provider duplicates authority. Reuse the official source/index
    owners and committed-query verification seam instead. Missing C1/C2 dependencies keep vector
    delivery/consumer activation unoffered, not falsely complete.

### 10.1 C0 source checkpoint — 2026-10-13 UTC

The nine approved paths now implement a typed approved-reference composer plus the existing
owner's preparation, bounded multi-view read and fresh full-population reauthorization. The
source owner receives the actual requested `top_k`, so its existing released-policy budget check
is reused rather than silently using the old corpus-read default of one. Non-empty topic/unit
constraints and all four unconnected consumer purposes remain explicitly unavailable.

The legacy and new use cases share one bounded channel union. Three independent view ranks use
the existing exact cosine/full-reference tie rule before display rounding; no view/Graph score
arithmetic or quality threshold was added. Typed coverage distinguishes no report, missing view,
no prepared index, unoffered QUERY, overflow and an empty related pool. Final authority failure
removes every candidate, count, query pointer and Graph Evidence from the FAILED context.

The multi-view owner tests verify two full official captures and nine scope checks across three
views; a changed end population fails before returned rows/counts. That seam test substitutes
the registered/numeric application read and is not live DB/IAM admission. Existing concrete
single-index and application read tests cover its real pointer/binary closure. Each view uses a
different logical namespace/index identity in the synthetic composer fixture. The existing
snapshot capture currently supplies no Graph ranking rows; C0 does not invent them. Supplied
authorized Graph observations are preserved by the composer, while existing workflow Evidence
selection and receipts remain unchanged and unconnected until C2.

Explicit API Conda gates: strict mypy, Ruff lint and format check **eight Python files PASS**;
five-suite focused read/composer/owner/legacy regression **124 PASS in 17.01s**; the final
fourteen-suite composer/consumer/registry/contracts/planner/codec/source-resolution regression
**334 PASS in 29.29s**, skip zero. Overlapping counts are not added. Earlier local fixture/static
failures were corrected and rerun; no runtime/history record was rewritten.

Root independently read the nine-path change, matched all eight Python raw hashes and reran
the same fourteen suites: **334 PASS in 29.47s, skip0**; strict mypy, Ruff lint and format
**eight files PASS**. The earlier seven-path pinned-read result remains in section 9, not C0.

**SOURCE_ONLY / NOT_ACTIVE.** The mandatory committed genuine QUERY read interface exists but no
production implementation/admission/launcher/publisher was composed. Absence returns explicit
QUERY unavailability, never a benchmark replay or DOCUMENT relabeling. C1 production execution,
C2 variation Artifact/plan/Pack delivery and all five consumer activations remain incomplete.
No schema/DB/IAM/runtime/model/GPU/CLI/Pack/Git mutation occurred in this C0 source step.

## 11. C1 genuine reference QUERY — design-only delta, 2026-10-13 UTC

This section proposes the next bounded vertical path. It does not activate QUERY, amend released
DOCUMENT contracts, authorize DB/root/runtime actions, or claim that an installed owner exists.
The first connection remains an authorized approved-reference query for **past-exam variation**;
private drafts/chat queries and the other four consumers are not introduced here.

### 11.1 Protocol necessity before behavior

The frozen `EmbeddingReferenceQueryInput/1.0` limits both row count and `batch_size` to three.
The actual backend reports its configured numerical recipe, not the number of rows in a final
partial batch. An admitted QUERY/DOCUMENT pair configured with batch size four cannot be called
three, resized, padded with invented rows, or silently assigned a different runtime. A proposed
**input-only `/1.1` successor** keeps one to three genuine rows but permits the existing numerical
recipe bound of 1–16. It reuses `ReferenceQuerySpaces`, released view recipes, encoding pointers
and float-free canonical helpers. The frozen input `/1.0` parser and schema remain unchanged.

`EmbeddingReferenceQueryResult/1.0` contains no batch-size field: it pins the exact request hash,
spaces, recipe, input set and shard. A separate `/1.1` input/result-closure validator can therefore
retain that result and the existing context `/1.0` execution pointer without a context/result
successor. Additive public parsing accepts the two literal input versions only; it must not widen
the old parser or treat arbitrary schema names as an extension mechanism.

The fixed native index workflow, request `/1.1`, execution policy, encoding reservations and
receipts are **DOCUMENT-only**. QUERY needs its own small closed controller request/purpose and
fixed application operation, while reusing existing queue, Job, command-lease and Artifact owners.
The current DB check `ck_workflow_step_runs_local_embedding` allows only application result
`incremental-embedding-result@1.0` and `step_key='encode_batch'`. A real queued QUERY application
step consequently needs an additive conditional-check migration. Source tests cannot bypass
that check or relabel a QUERY result as the index result. Existing `LOCAL_EMBEDDING` stage can be
reused; no new queue, table, registry or indexing-service identity is justified by this path.

These are source-byte observations. Whether the currently installed registered DOCUMENT indexes
have batch size four, exact compatible model/runtime/view recipes, an admitted native QUERY
purpose, or a usable current-owner continuation remains **UNKNOWN** until actual preflight.
An input-only contract successor is not such preflight or a GPU approval.

### 11.2 Eleven required decisions

1. **Responsibility/boundary:** Catalog's existing verifier prepares the exact authorized anchor
   and candidate scope; Orchestrator's native owner executes one bounded QUERY and publishes it;
   Runner retains existing queue/claim/state-machine responsibilities. C0 consumes only an
   admitted committed result through its mandatory read port. No consumer gets a direct model,
   PostgreSQL or NAS capability. C1 ends at that read port, not at an activated authoring Pack.
2. **Canonical source:** Original approved Item revision, accepted profile/report pointers,
   pinned official Graph/policy and registered index revisions remain authoritative. Native QUERY
   text is the existing released recipe's bounded anchor projection, not a new accepted report,
   private draft or full copied Item. The published QUERY file set is canonical for that execution.
3. **Identity/revision:** Keep context request ID/hash, query request ID/hash, logical native Job,
   publication-owner Job, Artifact/revision/raw member hashes, index/namespace revision, paired
   spaces and numerical recipe separate. One query Job belongs to one exact context request;
   no global text/query cache, DOCUMENT encoding-key reservation or corpus binding is created.
4. **Pointers/resolution:** Controller request pins the exact context request and every selected
   registered index, namespace, Graph, policy, anchor/profile/report, runtime bundle and resource
   policy. Worker input carries only the bounded QUERY DTO. Actual current caller is outside the
   wire. Source owner checks existence, lifecycle, permission, exact schema/media/hash and query
   derivation before submission/claim and again after execution. An absent index is explicit
   unavailable; stale/mismatched or revoked references fail closed, never resolve `latest`.
5. **Access patterns:** Context-key reservation and Job/command ID lookups are indexed; exact
   immutable source/member lookups are batched; view selection and rows are ordered tuples;
   duplicate/index/member identity checks use maps/sets; events are append-only. Three views
   share one genuine query execution and may not mix model/runtime/device/partition/recipe.
6. **Structures/indexes:** Reuse existing `jobs_idempotency_key_key`, Workflow command queue and
   Job/event records. Public `submit_structured_job` supplies the reservation primitive, but its
   check-then-insert alone is not a concurrency guarantee: the owner needs the existing bounded
   unique-key/savepoint/re-read pattern and exact immutable-request comparison. Reserve one
   context-specific logical QUERY Job, not three independent per-view jobs or a cloned encoding
   reservation framework. No new DB index is proposed without an observed missing lookup plan.
7. **Scale/complexity:** One inference has 1–3 rows; exact document reads stay bounded by the
   existing 1,024-source limit and three views. Preparation/ranking remains O(P + V*P*d) with
   map/set deduplication and one read per unique shard member. Query binary is at most three
   float32 rows; no candidate is re-encoded and no vector/body is persisted in DB/wire context.
8. **Transactions/concurrency:** Short writable owner roots acquire the actual Identity/session
   fences before submission/claim/savepoints and recheck command owner/token/generation/expiry
   late before commit. No SQL root, source-permission cache or C0 preparation window survives
   slow inference. Renewals use their own fresh fenced root. Source population is independently
   reauthorized in fresh roots before computation and before publication/disclosure, including
   unranked/no-report rows. Expired user authority means explicit unavailable, not service/admin
   impersonation or a saved audit grant. CUDA acquires the shared GPU0 lease before model/CUDA
   initialization and retains it through synchronization, unit exit and cgroup cleanup. Busy is
   WAIT, not a second inference or automatic CPU fallback.
9. **Dependency/ownership:** Reuse the actual `AuthService.capture_access` transport and
   `AuthenticatedSessionFence.assert_current` in the controller, never in the worker. The existing
   Catalog public prepare/read/reauthorize methods remain the source authority. The native backend
   factory, fixed prefix/UID/RECORD admission, backend and codec are reused; purpose-specific launch
   is independently required. `ControlFileSetPublisher` remains the only NAS commit owner. Add
   cohesive QUERY functions to existing adapters instead of a plugin/provider framework.
10. **Failure/retry/idempotency:** Same context/request/key replays the same exact committed output
    with fresh current authority; it never reruns inference to repair unknown processing. Different
    request bytes conflict. Failed/partial/uncertain launch or teardown history is preserved;
    no automatic model retry or newly allocated key escapes it. Permissions, hashes, purpose,
    runtime and late revocation fail closed with no candidates/counts/evidence. Genuine optional
    runtime/index absence is explicit unavailability and preserves only authorized Graph evidence.
11. **Simpler alternative:** Reusing the benchmark QUERY would borrow a measurement admission;
    changing DOCUMENT to QUERY would corrupt purpose provenance; running the old on-demand ranker
    would re-encode the corpus. Instead, use one actual QUERY plus existing persisted DOCUMENT rows.
    The new fixed operation is the smallest truthful queue/Artifact extension. No ANN, query cache,
    generic multimode framework, corpus re-encoding, automatic policy grant or five-consumer rewrite.

### 11.3 Exact staged source candidates, not an edit authorization

Each stage requires root review and an explicit file freeze before the next. Existing numerical
implementation files (`embedding_offline_backend.py`, `inference_transfer_vectors.py` and
`embedding_vector_binary.py`) do not need changes: backend already accepts genuine `purpose=QUERY`.
Their exact bytes must remain paired with the registered DOCUMENT space. Physical native profiles
`CPU_INDEX_FP32`/`CUDA_INDEX_FP32` name existing fixed installations, not a QUERY permission. A new
QUERY entrypoint may reuse them only after separate actual purpose/unit admission, without adding
duplicate model installations or asserting that an INDEX runtime proof grants QUERY execution.

- **C1a — input-only contract first:** proposed new
  `schemas/knowledge/embedding-reference-query-input-v1_1.schema.json`, its packaged mirror under
  `packages/catalog_contracts/eom_catalog_contracts/resources/knowledge/`, and
  `packages/catalog_contracts/eom_catalog_contracts/embedding_reference_query_v11.py`; additive
  registry/export changes in the existing Catalog `validation.py` and `__init__.py`; new
  `tests/unit/test_embedding_reference_query_v11_contracts.py`. Only if required by the frozen
  inventory test, add this one literal resource to the existing exact exclusion in
  `tests/unit/test_inference_transfer_embedding_contracts.py`, preserving original 296/raw inventory
  SHA and every predecessor schema byte. Independently test the new resource's raw hash and mirror.
  C0's eight Python files remain unchanged in this first step.
- **C1b — pure genuine encoder/handoff:** existing
  `services/catalog_service/eom_catalog_service/embedding_encoder_adapter.py`,
  `embedding_execution_ports.py`, `embedding_native_stdio.py`, `embedding_native_entrypoint.py`;
  additive QUERY functions and a small frozen QUERY output value, with protected-FD primitives
  shared inside the existing owner. No request-supplied parser, executable, module, path or factory.
  Extend existing `test_embedding_incremental_encoding.py`, `test_embedding_native_stdio.py`,
  `test_embedding_native_entrypoint.py` for QUERY and complete DOCUMENT regressions; add
  `test_embedding_reference_query_encoding.py`. No native launch or installed-identity claim.
- **C1c — fixed queued control/receipt, only after its schema review:** proposed new
  `schemas/workflow/reference-query-execution-v1.schema.json` and packaged mirror;
  `packages/workflow/eom_workflow/reference_query_execution.py` for bounded owner request/policy/
  step-output/receipt and `reference_query_workflow.py` for one fixed operation/definition.
  Reuse `LocalEmbeddingResourceProfile` as a value, not its DOCUMENT policy/container. Add literal
  support to existing workflow `schemas.py`, `compiler.py`, `admission.py`,
  `definition_execution_protocol.py`, `__init__.py`. Runner candidates are the existing
  `repository.py`, `engine.py`, `models.py`, plus proposed cohesive `reference_query_execution.py`;
  factor the existing native step's mechanical lease/transaction checks only where both real
  operations use them. One newly allocated migration after the actual current head extends only
  the fixed-step CHECK and refuses destructive downgrade with QUERY history. Its exact filename
  cannot be safely chosen from this source snapshot. No table/grant/queue/framework is proposed.
- **C1d — actual owner, Artifact and C0 read seam:** proposed
  `services/orchestrator/eom_orchestrator/reference_query_owner.py` owns source/current-session/
  Job/unit scope; extend existing `embedding_artifact_store.py` with `publish_reference_query`
  and its exact query Artifact type, reusing protected local reads and `ControlFileSetPublisher`.
  Proposed `services/catalog_service/eom_catalog_service/reference_query_artifact_read.py`
  implements only the existing committed-query read port through supported owner reads, not a
  second source provider. Existing `similarity_context_ports.py` and `similarity_context_service.py`
  add literal input `/1.1` support after approval; result/context predecessors stay unchanged.
  Concrete installed owner/session/unit/claim/lease proof is a separate operational prerequisite;
  an injected fake, saved provider DTO or source protocol is not its implementation.

C1c/C1d are a proposed bounded vertical inventory, not permission to edit all those files now.
Before their approval, inspect the actual root owner's public launch/read composition and freeze
the smaller resulting exact set. If an essential public seam is absent, retain explicit unavailable
or propose a narrow owner extension; never call another owner's private persistence/launch code.

### 11.4 Actual forward path, authority-free worker input and source gates

The intended first path is: existing variation source resolution (`RegistryService`
public `resolve_past_exam_variation_content`, then `WorkflowCatalogService` preparation) supplies
an approved reference; existing Catalog owner independently prepares the exact request/scope and
literal registered index pins; actual current owner submits the fixed native QUERY; existing queue
claims it with real command lease; the worker runs `encode(..., purpose='QUERY')` over only anchor
rows; Orchestrator validates/publishes the exact file set; committed-query read returns the existing
typed result to C0; C0 reauthorizes and composes independent observations. The later C2 compatible
plan/Pack sidecar pins that context for authoring/review. C1 alone must not claim that the existing
variation worker already receives it. No authoring slot/parent SQL lease should be held waiting for
a separate native query; durable asynchronous handoff belongs to that later compatible plan step.

Current QUERY wire fields contain typed model/runtime/encoding/view values and bounded text, **not**
an actual actor, role, permission, source filesystem path or executable. Model member names are
validated relative identities resolved from protected fixed runtime roots, not arbitrary paths.
Worker descriptors are inherited local files only. Controller supplies actual authority outside
wire; any actor audit fields in its new closed request are derived from genuine capture and are
never a grant. `ParentRoleToken`, bearer/access/refresh tokens, provider captures, DB/NAS locations,
actual command lease token, runtime override flags and arbitrary source paths must not enter worker
input, result, Artifact manifest, logs, SQL JSON or Slack. QUERY row text proves neither source rights
nor scientific validity. Worker/result-supplied spaces are checked against actual admitted runtime.

SOURCE gates must cover input1.0 byte preservation + new1.1 raw/schema/mirror/canonical/hash/strict
scalar checks; same configured batch4 with one genuine partial row (not four invented rows);
actual QUERY prefix/purpose and row order; same exact QUERY/DOCUMENT runtime/model/normalization;
wrong purpose/device/batch/thread/recipe/row/hash/model-copy rejection; before/after backend drift;
protected FD alias/seek/symlink/change/partial-write cases; exact Job replay and unique-key race;
claim/heartbeat/late expiry and source/report/population revocation; GPU busy/uncertain cleanup;
query-only Artifact commit/receipt/member bytes and publication Job linkage; no registry/index
registration and no DOCUMENT re-encoding; committed-query current-authority read; optional absence
versus corruption fail-closed; original DOCUMENT/Runner regressions and forbidden-layer imports.
DB mutation tests are disposable only, installed/native/GPU tests explicitly opt-in. Static/fake
SOURCE_PASS cannot be reported as owner/native/QUERY/runtime READY. Actual provider/session scope,
registered numerical pair and installed purpose/unit admission remain mandatory UNKNOWNs until
the corresponding supported preflight is performed.

### 11.5 C1a source checkpoint — 2026-10-13 UTC

The approved eight paths add only the closed input `/1.1` schema (raw SHA
`sha256:03a2d1332fefef201d30baae59597dda49a46f5650c45bf1384cf20a1f08c81d`), its exact
package-resource mirror, frozen model/literal parser, small `/1.1`-input `/1.0`-result closure,
additive Catalog registry/exports and source contract tests. Canonical schema preceded model code.
The package mirror follows the existing actual `resources/knowledge/` owner, correcting the
earlier proposed `schemas/knowledge/` location; no alternate loader or packaging dependency.

Rows remain 1–3; configured batch remains 1–16 without pretending to observe actual installation.
Synthetic configured batch four with one partial row, all three views, canonical hashes, strict
scalars, authority/path/extra rejection, nested model-copy/constructed corruption and released
result member drift are covered. The legacy registry test excludes exactly the one new literal
resource separately, retaining **296** and its original inventory SHA. Original query input/parser/
validator/schema, result/context `/1.0`, all eight C0 Python paths and three numerical modules are
unchanged. Tests/verification do not assert source authority or native QUERY execution.

Explicit API Conda strict mypy, Ruff lint and format check **five Python files PASS**. The final
sixteen-suite contract/composer/owner/registry/planner/codec/source-resolution regression is
**494 PASS in 30.87s**, skip zero. Counts overlap prior C0 gates and are not summed. The first local
pytest invocation omitted source `PYTHONPATH` and collected zero tests from the old installed
package; the corrected explicit source path passed. Local fixture typing/format errors were fixed
and all affected static/test gates rerun; no operation/history record was changed.

**C1a SOURCE_ONLY / NOT_ACTIVE.** C1b encoder/handoff, C1c native queue/check/receipt, C1d actual
owner/installed purpose/unit admission/Artifact read and C2 variation plan/Pack delivery remain
unimplemented in this checkpoint. C0 does not consume input `/1.1` yet. No DB, IAM, runtime, model,
GPU, Git, root, API, worker, Pack or numerical implementation mutation occurred.

Root read the full C1 design and all eight C1a changes, matched their raw hashes, and independently
reran the same sixteen suites: **494 PASS in30.65s, skip0**; strict mypy, Ruff and format **five
Python files PASS**. Existing C0/numerical bytes and predecessor contracts remain unchanged.

### 11.6 C1b approved pure-source design delta

The eight approved Python paths add `encode_reference_query_batch`,
`run_native_reference_query_descriptors` and `run_native_embedding_reference_query`, with a small
frozen `EncodedReferenceQueryBatch` sibling. They parse only the literal `/1.1` input and produce
the existing `/1.0` result/shard/view-row closure after one genuine `purpose='QUERY'` call. The
same actual-backend model/runtime/dimension/batch/thread checks run before and after both real
operations; finite/scalar/norm/float32 validation remains only at the existing authoritative codec.
No numerical implementation bytes change and no extra normalization or corpus encoding occurs.

Inside the existing stdio owner, bounded JSON reading, descriptor/inode preparation, unchanged
input/empty output checks and binary-before-result fsync/write/epoch checks become shared private
primitives. Fixed DOCUMENT and QUERY functions select their own literal parser/encoder, not a
request-supplied callback, path, flags, plugin or public generic runner. Backend construction stays
no-argument and owner-supplied, after all input/FD validation. Index public names/error behavior
remain compatible. Entrypoint shares the existing quiet-FD/identity primitives and adds a fixed
QUERY leaf; it still has no main/CLI/default capture or permission grant. Output bytes are temporary
local materialization only. Invalid input skips construction; drift/partial writes/teardown failure
never retry or imply publication. Synthetic tests extend the real two-use-case seam plus complete
DOCUMENT regressions; actual model/GPU/unit admission, queue, DB, policy, Pack and C0 consumption
remain outside this step.

### 11.7 C1b source checkpoint — 2026-10-13 UTC

The approved nine paths now contain the fixed QUERY encoder, protected-descriptor leaf and
stdlib-first entrypoint plus frozen local-output sibling. Both actual use cases share private
backend mismatch and shard packing primitives; stdio shares bounded raw JSON/FD preparation,
unchanged-input/empty-output checks and validated binary-before-result writes/fsync/epoch checks.
The native QUERY leaf accepts only input `/1.1`, caps input before reading at 1 MiB, invokes the
backend once with `purpose='QUERY'`, and emits the existing result/shard/view-row contracts. The
DOC leaf retains input/result `/1.0`, configured batch/thread checks, 64 MiB bound and error codes.
No input-selected parser/factory/path/flags, generic execution mode or publication was added.

Synthetic tests cover configured batch four/one partial row, 1–3 ordered view rows, CPU/CUDA
metadata, before/after backend provenance/model/dimension/runtime/recipe drift, invalid finite/
scalar/norm output through the original codec, wrong literal input before construction, FD mode/
offset/access/link gates, corrupt binary, partial writes, local-input changes and uncertain scope exit.
Both fixed entrypoints use the real quiet-FD primitive in a CPU-only subprocess seam; native
identity is explicitly substituted, so this is not installed-purpose/unit admission. The synthetic
model has equal QUERY/DOCUMENT prefix strings; the test intentionally verifies the fixed actual
QUERY argument, not an invented prefix difference or permission to relabel DOCUMENT vectors.

Explicit API Conda strict mypy/Ruff lint/format check **eight Python files PASS**; focused six
suites **266 PASS in 6.68s**; the final thirty-suite native/backend/Artifact/Runner/contract/context/
registry regression **1,272 PASS in 91.99s**, skip zero. Counts overlap and are not summed. Initial
local test expectations for prefix inequality and wrong-schema exception type plus fixture type/
format errors were corrected; all affected gates passed afterward. No runtime retry/history change.
Original C0/C1a contract bytes and all three numerical implementation module hashes remain unchanged.

**C1b SOURCE_ONLY / NOT_ACTIVE.** No actual model/native/GPU inference was run here; the tests use
synthetic backends. The fixed runtime profile identity itself grants no QUERY purpose. Actual
owner/session/unit/runtime admission, queue/DB check/claim/receipt, Orchestrator commit/read and C2
variation delivery remain mandatory unimplemented boundaries. C0 query read remains unavailable
until those owners are composed. No DB/IAM/policy/API/Pack/Git/root/runtime mutation occurred.

Root independently read all nine frozen C1b paths and matched their raw hashes. The same
thirty-suite inventory passed **1,272 tests in91.68s, skip0**; strict mypy, Ruff and format passed
all eight Python files. This independent source gate does not admit an installed QUERY unit or
execute the actual model, and does not change C0/C1a or the numerical module hashes.

## 12. C1c fixed QUERY execution protocol — approved first boundary

This nine-path step defines contracts only. It does not change the compiler/admission/Runner,
apply the proposed migration, publish a policy/Artifact, launch a native unit or consume QUERY in
C0. Source `alembic heads` is the single `20261012_0053`; operating DB revision is not rechecked.
The QUERY native-step CHECK successor remains separately required before a real queue operation.

1. **Responsibility:** Two cohesive new domain modules define the fixed QUERY Workflow and its
   request/policy/launch/publication receipt/carrier. Existing schema owner adds one independent
   closed 2020-12 resource plus exact mirror/public exports. No generic operation/plugin/provider.
2. **Canonical source:** `SimilarityContextRequest/1.0` carries the immutable official anchor,
   Graph/policy and literal registered-index pins once. Policy remains a referenced immutable
   Artifact. Native input `/1.1` and result `/1.0` remain their canonical numerical contracts;
   source authority/runtime admission cannot be supplied by these value objects.
3. **Identity/revision:** Keep context/controller/native-request hashes, workflow/step/native Job,
   query-output publication Job, receipt publication Job and all Artifact revisions/raw member
   hashes separate. Definition schema `1.2`, fixed key `local-embedding-reference-query/1.0.0`,
   execution protocol `reference-query/1.0` and controller purpose `REFERENCE_QUERY` are distinct
   from native space purpose `QUERY` and the released DOCUMENT contracts. Those Job fields preserve
   distinct concepts, not an arbitrary requirement to allocate three unequal Job IDs.
4. **Pointers/checks:** Request contains only OPERATOR audit, one small typed context, definition
   SHA, runtime bundle/resource values and policy Artifact/hash. Pure closure checks policy,
   paired QUERY/DOCUMENT space/device/recipe, every selected index and exact context. Launch audit
   pins the allocated native Job and exact native request/input-set hashes; no stored lease token.
   Receipt closes the committed input/result/shard/binary members of one QUERY file set and its
   receipt carrier, with exact original request/launch/UTC provenance.
5. **Access patterns:** Keyed contract/resource lookup, ordered 1–3 view rows, set-based unique
   identities, canonical append-only audit/pointers. No corpus scan, query cache or DB vector/text
   storage. Missing source/index/actual owner remains an unavailable use-case, not a schema grant.
6. **Structures:** Reuse public paired-space/context/runtime-bundle/OPERATOR-audit/resource/ID/
   Artifact-member values. The new resource registers separately; old role/native resources and
   inventories/raw hashes are not expanded or rewritten. Small domain values remain frozen.
7. **Complexity/scale:** Each control/receipt is capped at 64 KiB, carrier 8 KiB; at most three
   index/view pins are checked with tuples/maps/sets. Domain checks are bounded O(V) excluding
   the existing canonical serialization, with no binary materialization, parsing loops or inference.
8. **Transactions:** None in contracts. The future actual owner must allocate/reserve the logical
   Job and reacquire actual current session/source/command fences in fresh roots; persisted audit
   and original command generation are not continuation. QUERY policy uses its own literal
   `OPERATOR_REQUEST_ONLY`, not DOCUMENT's `OPERATOR_SEED_ONLY`. Slow inference remains outside SQL.
9. **Dependencies:** Domain modules import public existing contracts/value objects and schema
   validators only. No SQLAlchemy/filesystem/network/native launcher/ML/GPU/root/Runtime imports.
   Schema resource loading remains with existing workflow schema owner and installed resources.
10. **Failure/replay:** Literal schemas, raw scalar/model-copy/extra preservation, immutable
    pointer/hash closure and UTC order fail explicitly before any behavior. Pure replay validation
    matches exact historical values; it does not retry, update status or assert current permission.
    No `approved/admitted` booleans, token/provider capture, source path, vectors or source text body.
11. **Simpler alternative:** DOCUMENT request/receipt describes corpus/index registration and
    cannot truthfully describe a QUERY publication. One fixed two-step definition and closed
    pointer-only QUERY receipt are necessary; a separate queue/table/registry/framework is not.

### 12.1 C1c protocol-only source checkpoint — 2026-10-13 UTC

The approved nine paths add the one closed resource/exact mirror (raw SHA
`sha256:68e741506fec708956096aa5af6199e7c03821219385775cf9623aea88246c9b`), two frozen domain
modules, independent workflow schema-owner registration/public exports and two new test modules.
Root read the complete draft schema/mirror and eleven decisions before model code; its QUERY
continuation correction to `OPERATOR_REQUEST_ONLY` leaves DOCUMENT's seed enum unchanged. Job
roles remain separate expected identities without arbitrary unequal-ID checks or actual allocation.

The literal definition has schema `1.2`, application `encode_reference_query` then `complete`,
attempt one/rework zero. Controller frames contain only bounded immutable metadata/pointers.
Cross-value checks close exact policy raw/semantic hashes, runtime bundle/model/numerical recipe,
source context/index/partition/view, native request/result hashes, launch audit and UTC ordering,
QUERY input/result/shard/binary same-file-set members and receipt/carrier raw/semantic hashes.
No-report/profile stays absent; topic/unit values are preserved, not ignored or silently cleared.
Required index absence is not a launchable control request. Current target existence, actual source
permission, numeric bytes and installed/native producer admission still belong to their real owners.

New tests cover grant/path/body/extra rejection, boolean/float/raw model-copy/construct revalidation,
stale expected context/policy/member/owner hashes, foreign Artifact revisions, malformed member
schema/media, UTC order, same publication-owner identities and no invented missing report. Missing/
corrupt new schema or required existing schema dependency is explicit SCHEMA_UNAVAILABLE, not bad
caller input. Public schema/registry mutation cannot alter parser-pinned resources. Released native
four-resource/two-receipt inventories, their schema/mirror bytes and DOCUMENT purpose remain intact.
The new definition is explicitly still unoffered to the current compiler and admission table.

Explicit API Conda strict mypy/Ruff lint/format **six Python files PASS**. The final thirty-six-suite
protocol/native/backend/Artifact/Runner/context/registry regression is **1,610 PASS in 99.87s**,
skip zero. Counts overlap previous gates and are not summed. Initial source fixtures used `+00:00`
instead of canonical `Z`, mixed default CUDA bundle with a CPU profile, and expected an unwrapped
Pydantic exception; those were corrected alongside precise content-free public parser errors. Static
typing/format corrections and all affected tests were rerun. No operational retry/history change.

**C1c FIRST_PROTOCOL_BOUNDARY SOURCE_ONLY / NOT_ACTIVE.** Compiler/protocol calculation/admission,
Runner/queue/claim/lease, migration/DB/IAM, actual owner/unit/model/GPU, Artifact commit/read and C2
consumer delivery remain unchanged and unconnected. C0/C1a/C1b and numerical module bytes are
preserved. No Git/root/API/worker/Pack/runtime/model execution occurred in this source step.

Root independently read all nine frozen paths and matched their raw hashes. The same
thirty-six-suite inventory passed **1610 tests in99.63s, skip0**; strict mypy, Ruff and format
passed all six Python files. This remains the first protocol-only boundary: no compiler,
queue, migration, real owner/native unit, Artifact publication or consumer activation follows.

## 13. C1c fixed QUERY compiler/read boundary — approved source delta

The seven approved paths extend the existing compiler, execution-protocol calculator and Runner
repository, add two focused test modules, update the prior QUERY contract test's compiler-stage
expectation, and record this delta. QUERY remains NOT_ADMITTED for new work. The admission table,
native executor, engine, persistent Workflow creation implementation, DB constraints/migrations,
QUERY schema/domain model bytes and numerical implementation remain unchanged.

1. **Responsibility:** Compiler/protocol owner recognizes the literal QUERY definition. Runner
   repository reads its exact inactive status and quarantines unsupported native history. This
   step adds no native execution, publication, owner authority or consumer delivery.
2. **Canonical source:** Reuse the committed closed `reference-query-execution/1.0` Schema and
   public `parse_reference_query_workflow_definition`; no YAML/config, loader or schema successor.
3. **Identity/revision:** Fixed key `local-embedding-reference-query`, definition version `1.0.0`,
   schema `1.2`, protocol `reference-query/1.0`, canonical bytes and SHA remain distinct values.
   Compiling or importing a valid inactive definition is not admission or runtime availability.
4. **Checks:** Raw QUERY parser revalidation preserves forged copied extras/booleans. Stored
   definitions must recompile to the same key, version, schema and canonical SHA before protocol
   status is returned. No latest substitution, repair or native result registration in role maps.
5. **Access patterns:** Fixed-purpose dispatch, keyed step projection, exact stored identity
   lookup, ordered admission-status reads and the existing indexed FIFO command header.
6. **Structures/indexes:** Keep existing ROLE/LOCAL_EMBEDDING queue families. Extend the existing
   total native routing predicate with literal QUERY markers; no new queue/table/registry/cache.
   Candidate native request remains DOCUMENT-only in this stage, so QUERY is explicitly absent.
7. **Complexity:** The QUERY definition has exactly two steps. Compiler checks are bounded and
   status iteration remains O(N); native routing preserves the existing SQL/PK/FIFO access plan.
   No model, source corpus, Artifact or vector materialization is introduced.
8. **Transactions:** Reject QUERY submission before generic serialization/fingerprint, lookup,
   savepoint or persistence. Reject native candidates lacking a supported exact request before
   root/row lookup or lease assignment. Valid DOCUMENT claim/lock/generation behavior is unchanged.
9. **Dependencies:** Compiler depends on public domain/schema contracts. Runner consumes those
   contracts in its existing owner module. No private cross-owner calls, framework or new ports.
   Existing engine native-but-not-DOCUMENT guard keeps QUERY unavailable after quarantine.
10. **Failure/replay:** Matching typed QUERY submission is explicitly unavailable using existing
    `LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE`; cross-purpose input uses `WORKFLOW_REQUEST_INVALID`.
    Unsupported native candidates use the same stable unavailable before mutation, never ROLE
    fallback. Inactive QUERY reads truthfully show its protocol and accepts-new-work false.
11. **Simpler alternative:** Adding admission alone reaches DOCUMENT-only serialization, claim,
    executor and DB CHECK paths. Compile/read support plus fail-closed quarantine is the smallest
    safe step before separately reviewed actual owner, queued QUERY execution and paired CHECK.

Source tests use synthetic definitions and read/session spies only. They must cover exact
canonical replay, raw copied corruption, inactive import/status, stale stored identity/hash,
cross-purpose submission, QUERY routing markers, unsupported direct claim and zero mutation.
Source migration head remains `20261012_0053`; no operational DB revision is inferred or queried.
The fixed QUERY native-step CHECK, actual owner/session/unit admission and C0/C2 delivery remain
mandatory subsequent boundaries, not requirements silently bypassed by this compiler extension.

### 13.1 C1c compiler/read source checkpoint — 2026-10-13 UTC

The seven approved paths now recognize only the fixed QUERY schema `1.2`, revalidate its raw
typed definition with the committed public parser and calculate `reference-query/1.0`. Canonical
replay and keyed fixed-step projection require no Codex role. Stored QUERY identity/schema/hash
is checked before protocol status; valid inactive history is no longer mislabeled invalid. Even
an active snapshot cannot offer new QUERY work while the unchanged admission policy excludes it.

QUERY submission is refused before generic request storage/fingerprint or any Session operation.
Cross-purpose requests use the existing invalid-request code; matching QUERY uses the existing
native-unavailable code. The total SQL predicate includes literal QUERY markers in the same
existing queue families, preventing ROLE fallback. Visible mixed QUERY/DOCUMENT metadata never
produces a DOCUMENT candidate request. Direct claims with no supported exact request stop before
root lookup, and a QUERY-only related definition stops after exact hash checks but before owner
calls or lease mutation. Non-object canonical JSONB is a stable invalid-definition error, not an
attribute exception. No broad catch, repair, additional family/flag/callback or new owner is added.

Focused six-suite source regression is **150 PASS in 11.96s**; final forty-three-suite gate is
**1,779 PASS in 115.09s**, skip zero. That inventory contains the complete previous C1c thirty-six
suites, both new modules and existing command-claim/runtime-admission/submission/runner-admission/
Workflow-definition suites. Counts overlap and are not summed. Explicit API Conda strict mypy,
Ruff lint and format check **six Python files PASS**. An initial unused test import was removed.
Independent read-only review found the mixed-purpose and non-object JSONB edges; both were given
targeted guards/tests, and the whole gate was rerun on the final bytes. The earlier 1,775-pass
collection precedes those four JSONB cases and is not the final freeze evidence.

The unchanged admission table, QUERY schema/domain modules, engine/native admission/executor/
step execution, models/migration and three numerical modules match all fourteen baseline raw
hashes. The existing `_persist_workflow_instance` body retains raw SHA
`26862954508e41bae72c54e446defc4dc4b4f6be7929ee2781cfc3396285a94d`.
SQL compilation/read spies are not real PostgreSQL concurrency or operational routing evidence.

**C1c COMPILER_READ SOURCE_ONLY / NOT_ACTIVE / QUERY_NOT_ADMITTED.** No DB, IAM, actual native
owner/Job/unit/model/GPU, publication or installed-runtime action occurred. The paired QUERY-step
CHECK, concrete current-owner continuation, queued QUERY executor, committed-query C0 reader and
C2 consumer delivery remain separate prerequisites. Existing DOCUMENT execution remains intact.

## 14. Protected regular namespace roots — approved source correction

Actual nonprivileged CPU-prefix observation, independently repeated by root, found four public
overlay wheel validations PASS, ten namespace roots and 965 expected members versus 964 walked
members. The only missing member is `lib/python3.12/site-packages/distutils-precedence.pth`;
extra count is zero. It is a protected root-owned single-link regular file. `os.walk(file)` yields
no member, although the existing verified-wheel namespace contract includes such top-level files.
Input SHA is `96f06fda4199bb614d19375dc569faffff15b1d7bad2ae46fd1e7aa0b8f857e5`, ending epochs
PASS. This is a confirmed observation defect, not a wheel byte/hash failure or runtime admission.

1. **Responsibility:** Existing runtime-file snapshot owner closes directory and regular-file
   namespace roots. Only that method, existing wheel tests and this note are approved to change.
2. **Canonical source:** Existing source-pinned wheel/RECORD and verified installed members;
   `.pth` content is checked as bytes, never executed or excluded from the expected inventory.
3. **Identity:** Retain archive/member SHA, protected file/ancestor epochs and exact member path.
   No schema, pin, installer, staged candidate or historical failure identity is rewritten.
4. **Checks:** Explicit root lstat type; regular files reuse protected-member identity checking
   for owner/mode/single link/ancestors and unchanged epochs. Missing/link/special roots fail.
5. **Access patterns:** Root membership, directory walk, exact expected/observed set equality and
   final epoch checks. No package import, model launch or input-selected executable.
6. **Structures:** Existing set/map/snapshots only; no skiplist, provider, registry or flags.
7. **Complexity:** O(files + roots); regular roots need identity only, not repeated hash/parse.
8. **Concurrency:** Preserve existing verified-byte epochs; root/member replacement or drift
   fails during observation or final checks. No permission transition or filesystem repair.
9. **Dependencies:** Stdlib snapshot owner remains shared by wheel/Conda/prefix callers. Reuse
   its public protected-member identity method, not a parallel verifier or external package.
10. **Failure:** Preserve exact missing/extra equality and existing fail-closed proof errors.
    Unexpected regular roots, links, writable/multilink/special/missing members are not tolerated.
11. **Alternative:** Removing `.pth` from expected would bypass closure. A small root-type branch
    is sufficient; whole-prefix activation, fresh actual audit and recovery remain root's work.

Source tests must include mixed/regular-only roots, actual wheel/RECORD association, unexpected
members, root protection/types and epoch drift without rehashing. Backend Phase B, the old staged
CPU candidate and failed history are outside this source correction and remain untouched.

### 14.1 Namespace source correction checkpoint — 2026-10-13 UTC

The three approved paths now handle protected regular namespace roots with the existing public
identity snapshot method, preserving any earlier byte SHA/epoch without a new hash or parse.
Directory roots retain protection and a root epoch even when a walk yields no rows. Missing,
symlink, special, writable, wrong-owner and multilink roots fail with stable proof errors; exact
expected/observed equality still rejects missing and unexpected members.

The complete focused wheel suite is **188 PASS in 2.99s**. Strict mypy, Ruff lint and format check
**two Python files PASS**. Tests include wheel/RECORD-associated `.pth`/top-level `.py`, mixed and
regular-only roots, no rehash, source byte-epoch preservation, missing/extra/protection and epoch
drift before/after namespace observation. Independent read-only review found no remaining blocker.
The first focused gate was 186 PASS/2 FAIL: its wrong-owner fixture expected a leaf error despite
the actual protected-open ancestor rejecting first, and directory recreation could reuse the old
inode. The expectations now preserve actual owner checks and keep the old inode alive for a
deterministic replacement. These diagnostic failures are preserved, not reclassified as PASS.

The common nineteen-suite and C1c forty-three-suite source regressions have separate overlapping
inventories; root performs the final shared gate after both the namespace and independently owned
backend Phase B scopes are frozen. No aggregate count is claimed here from a mutable worktree.
Actual fresh whole-prefix audit, new source publication and recovery remain root-owned pending
actions. This source correction does not repair the old staged candidate, change its history,
authorize an installed prefix/native identity or execute a model. **SOURCE_ONLY / NOT_ACTIVE.**

### 14.2 Root-review directory epoch correction

Root's production read found one narrower gap after the first source freeze: the walk's first
directory observation could replace the root epoch captured immediately before walking. A
same-snapshot repeated namespace call could likewise refresh it. Two tests kept the old empty
directory inode live while replacing it before the first walk yield or between calls. Both
reproduced the actual source defect: the expected namespace-change error did not occur.

The existing directory-epoch map now keeps its first observation with `setdefault` and requires
exact equality on every later root/walk observation. Unchanged repeated reads still pass; changed
identity is rejected rather than refreshed. This is one owner-local metadata rule, with no byte
hash/parse/scan, file repair, new framework or stronger authority claim. Regular member SHA/epochs
and all previously protected ownership/type/set checks remain unchanged. The two diagnostic
reproduction failures are retained as defect evidence, not overwritten as historical success.

After the targeted correction, the complete wheel suite is **191 PASS in 2.93s**; strict mypy,
Ruff lint/format **two Python files PASS**, and owned-three-path diff check PASS. No shared/actual
gate was repeated for this correction; root performs those gates on the new frozen source bytes.

## 15. Reference-query Artifact publication — approved source leaf

1. **Responsibility:** Extend the existing Orchestrator Artifact store with one fixed QUERY
   publication method. It validates supplied immutable contracts and local results; the actual
   owner still supplies current authorization, command/claim lease and genuine producer checks.
2. **Canonical source:** Exact canonical staged input 1.1, result 1.0 and validated f32 bytes.
   Reuse the existing ControlFileSetPublisher; only that owner commits the canonical Artifact.
3. **Identity:** Preserve controller/native request, launch association and publication Job IDs,
   Artifact ID/revision and raw member hashes as separate concepts. No arbitrary inequality of
   native/publication Job values is introduced and no QUERY receipt or runtime grant is minted.
4. **Checks:** Reparse closed contracts and validate launch/request/policy/bundle/input closure,
   actual QUERY purpose, recipe/runtime/resource pins, UTC ordering, canonical JSON and the
   existing authoritative numeric codec. Validate the returned real publication pointer frame.
5. **Access patterns:** Fixed four-member reads, create-once shard metadata and keyed immutable
   request replay. Source/report bodies, authority tokens and vector values are not put in DB.
6. **Structures:** One frozen pointer result and a fixed sorted tuple of input.json, result.json,
   shard.json and vectors.f32. Existing owner-local protected FD primitives remain shared.
7. **Complexity:** Bounded O(input + result + binary bytes), at most three QUERY rows; no corpus
   scan/re-encoding, repeated numeric normalization, registry or generic parser/provider layer.
8. **Concurrency:** Hold no-follow directory/member descriptors through publication and final
   epoch checks. Existing shard bytes must agree; the same immutable key cannot replace output.
9. **Dependencies:** Orchestrator leaf consumes public contracts/codec and the existing publisher.
   No Catalog private access, source lookup, native executor, queue, IAM or DB change is made.
10. **Failure:** Missing/unsafe/changed members, stale or mismatched immutable closure and invalid
    publisher receipts fail explicitly. A failure after publication does not assert no side effect
    occurred; retries remain the existing publisher's same-key immutable replay boundary.
11. **Alternative:** Relabeling DOCUMENT output or publishing unbound QUERY files bypasses the
    supplied closure. A fixed source leaf suffices; actual QUERY admission/execution and committed
    reader remain inactive prerequisites, not callbacks or boolean grants added here.

Approved paths are this note, existing embedding_artifact_store.py, a new focused QUERY Artifact
test, and the existing Artifact-store test only for its exact public-import boundary inventory.
Source fixtures do not prove native QUERY execution, current authority, lease ownership or NAS
publication. DOCUMENT/index signatures and behavior, released protocol bytes and numerical
modules stay unchanged. **SOURCE_ONLY / NOT_ACTIVE / QUERY_NOT_ADMITTED.**

### 15.1 QUERY Artifact source checkpoint — 2026-10-13 UTC

The existing store now reparses supplied typed QUERY values before serialization and validates
the fixed launch/controller/policy/bundle/input 1.1 closure before opening the workspace. Exact
canonical staged input/result bytes and the existing authoritative f32 codec are checked, without
input repair, padding or re-normalization. Protected member FDs remain held through the existing
publisher and final epoch checks. One create-once shard and exactly four ordered member pointers
share the publisher's Artifact/revision. The result is a small frozen pointer value, not an execution
receipt, authorization or producer proof. Native and publisher Job concepts need no arbitrary
inequality. Existing DOCUMENT/index method signatures and bodies remain unchanged.

Final ten-suite source regression is **494 PASS in 55.10s**, skip zero. Inventory:
`test_embedding_reference_query_artifact_store`, `test_embedding_artifact_store`,
`test_embedding_index_artifact_store`, `test_reference_query_execution_contracts`,
`test_embedding_reference_query_v11_contracts`, `test_embedding_reference_query_contracts`,
`test_embedding_reference_query_encoding`, `test_local_embedding_runner_execution`,
`test_local_embedding_workflow_receipt` and `test_control_file_set_publication`, all under
`tests/unit/`. Explicit API Conda strict mypy, Ruff lint and format check **three Python paths
PASS**; owned diff check PASS. No shared count is added to an earlier overlapping gate.

The first six-suite gate was **306 PASS / 4 FAIL in 16.93s**: public JSON Schema rejects bool,
extra and purpose drift with its exact ValidationError, which the new leaf initially did not
translate. Only that exception was added to the fixed QUERY boundary; no broad catch or released
contract changed. A following 310 PASS gate preceded independent review and is not the final
freeze. Read-only review then identified JSON-decoder RecursionError before raw-contract depth
validation. The new QUERY result block alone maps that precise exception and rejects deep JSON
with stable content-free error, publisher call count zero and original bytes preserved. An initial
strict test-dictionary inference issue and formatting failures were corrected before final gates.

Coverage includes canonical four-member/schema/hash closure, configured batch four with one real
row, typed/nested model-copy negatives, bool/extra/input-version/purpose/runtime/recipe/launch
drift, duplicate/noncanonical/deep JSON, codec hash/shape/nonfinite/nonunit checks, protected input
and output members, publication-time member/workspace replacement, immutable-key replay/output
conflict, malformed/null receipt, equal native/publication Job values and unknown-outcome no retry.
Fake owner metadata/replay tests are not PostgreSQL, NAS, current-session/command-lease or native
QUERY acceptance. Actual owner/native admission, source reauthorization, genuine producer binding,
committed-query reader and first consumer delivery remain separate prerequisites. No DB, migration,
IAM, runtime, model/GPU, queue, source lookup or installed activation occurred in this leaf.

### 15.2 Root-review three-view publication coverage

Root requested a three-row positive in addition to the earlier one-row/batch-four fixture. The
existing public contracts express three distinct CONTENT_ONLY/CONCRETE_FACETS/METADATA_ONLY
views. Test-only Case/reseal helpers close synthetic third-index metadata, controller/native/launch
hashes and sorted encoding rows; no index registration or source authority is invented. Three
different unit f32 rows are published without padding, while the configured numerical batch stays
four. Four negatives reject resealed view/row disagreement and declared binary hash/shape drift,
with publisher calls zero and original bytes preserved.

The precise limit remains explicit: permuting vectors and coherently changing all declared hashes
cannot establish or refute semantic encoding at this byte-publication leaf. The actual producer and
owner execution binding is still required. Unused Case receipt/output fixtures are not proof of the
new publication. Read-only review found no additional defect; production and existing DOCUMENT/
index test bytes remain unchanged from the preceding freeze.

The targeted five added tests are **5 PASS in 4.92s**. Final exact ten-suite regression, superseding
the prior source freeze in §15.1, is **499 PASS in 54.80s**, skip zero. Strict mypy, Ruff lint and
format check **the same three Python paths PASS**; gate start/end Python raw hashes agree. No
counts are added across overlapping runs. This is still **SOURCE_ONLY / NOT_ACTIVE /
QUERY_NOT_ADMITTED**, with no operational, migration, runtime, model or authority change.

## 16. C2 immutable context delivery — protocol-first publication boundary

2026-10-14 UTC. First consumer is still exact-source past-exam variation. Current
source already has the genuine QUERY owner/committed read; its finite live canary
is separate from this step. Do not reinterpret older dated NOT_ADMITTED checkpoints.

1. **Responsibility:** Define the small delivery value needed to pin the SAME
   validated common context in a later execution-plan/materialization successor.
   Orchestrator alone publishes its canonical JSON through the existing file-set
   owner. Catalog still owns compose/current source reauthorization; no new searcher.
2. **Canonical source:** One `context.json` member with the existing context1.0
   bytes. Source/report/Graph/policy/query/index pins remain inside that canonical
   value, not copied into another Item/report corpus. Similarity is not Evidence.
3. **Identity:** Delivery has an Artifact member pointer (including raw SHA), exact
   request SHA and semantic context SHA. It is a small frozen value without a new
   logical entity, revision, own hash, registry or independent lifecycle. Publisher
   Job/Artifact/revision and outer manifest hash remain separate local owner output.
4. **Resolution:** New closed `system-rag-similarity-delivery/1.0` schema precedes
   model/behavior. Pure association checks exact expected request, member schema/
   media/path/raw SHA and context semantic SHA. They do NOT prove target existence,
   committed lifecycle, current permission, raw storage integrity or native execution;
   actual owners must still resolve those before staging/disclosure.
5. **Access:** Exact small pointer lookup, bounded canonical serialization and
   same-key immutable file-set publication/replay. No corpus scan or vector compute.
6. **Structures:** Reuse public Artifact pointer, existing context/request parsers,
   frozen values and file-set publication. No DB/index/queue/cache or new framework.
7. **Cost:** Delivery≤8KiB; canonical context≤512KiB. O(context bytes) at the explicit
   local materialization/publication boundary, with no repeated Item/report copies.
8. **Transactions:** Caller retains actual current operator/source authorization
   across this bounded publication and late checks; no inference under a DB root.
   This low-level leaf cannot grant or capture that authority. The existing publisher
   owns create/replay/atomic commit and uncertain-publication recovery.
9. **Dependencies:** Pure Catalog contracts→public types/schema helpers only;
   Orchestrator adapter→contracts and existing `ControlFileSetPublisher`. No ML/API/
   Catalog private resolver imports, additional dependency or alternate NAS writer.
10. **Failure:** FAILED contexts never become a delivered fallback. OPTIONAL ordinary
    unavailability stays explicit; REQUIRED vector unavailability is not deliverable.
    Hash/pointer/request/source integrity failures fail closed. Same immutable key
    and first-observation UTC time replay without inventing dates, latest or retry.
    Publication receipt failure may follow a commit; preserve and reconcile it.
11. **Alternative:** Passing an untyped context dictionary into old plan19 or Evidence
    changes released meaning. A small pointer value is sufficient and reusable; no
    nested base-plan copy, embedded full context or independent delivery registry.

Keep all old plan/role/request/Pack schema bytes unchanged. Plans21/22 already belong
to inference-transfer comparison, so they must NOT be reused for variation. A new
grounded plan successor, source-owned preparation/current identity, worker workspace
aliases and prompt/Pack changes are the subsequent integration; this publication
leaf activates none of them. No consumer tool, production canary or new model run is
implied. Other consumers/private query bases and full goal completion remain open.

### 16.1 Delivery/publication source checkpoint — 2026-10-14 UTC

One new closed2020-12 resource/mirror is registered with raw SHA
`sha256:c403071c18e44cdad39d96ccb7e6c6454ac27fd76c83d7ac6e98e4b938c3fa65`.
The old296-resource inventory/count/hash and all released context/query/plan/Pack
bytes are preserved. The frozen public delivery model revalidates raw nested
copies/constructs before coercion/dump. Supplied hash/request mismatch is not repaired;
OPTIONAL absence remains explicit, FAILED and REQUIRED-vector absence are rejected.
Pure closure validation does not claim current source permission or target resolution.

The Orchestrator leaf publishes ONE `context.json` as
`control_system_rag_similarity_context` through the SAME file-set publisher and its
first actual UTC observation. No new NAS writer, time/identity source or DB aggregate.
The caller must derive/reuse its operation key from the actual actor and exact
request, hold current source/operator fences, and perform late checks; a wire request
or this leaf is not such authority. The returned local publication value separates
owner Job, delivery pin and outer manifest hash. Invalid returned type/identity/hash
is an explicit receipt error; it never means that the prior commit did not happen.

Final15-suite source regression: **347 PASS /77.98s**; strict mypy4, Ruff/format7
Python files and diff checks PASS. The publication fixtures use the actual existing
publisher, local SQLite, temporary Artifact bytes and official pinned reader. Same-key
replay retains one Job/revision and inode/mtime/bytes; conflicting content is refused,
Job requests omit full context/candidates/vectors, and seven post-commit receipt
failures preserve the original output for explicit same-key recovery. Current IAM,
source and genuine QUERY provenance are synthetic fixtures, NOT live acceptance.

Initial tests exposed the leaf's non-`control_` Artifact kind; only the new leaf was
corrected to the existing publisher's accepted kind, not by widening its guard.
Two fixture expectations were corrected: `model_construct` drops unknown fields,
so raw declared bool corruption is now tested; Job's actual field is `status`.
Those failures are retained in local logs, not rewritten as historical successes.
Evidence: `/tmp/eom-identity-provider-install.nAaycoDM/similarity-delivery-*.log`.

No operational DB/schema/role/unit/runtime/Pack/plan change, source grant, actual
corpus/model/GPU run or consumer activation occurred. PostgreSQL testing is not
claimed from the local SQLite fixture. The genuine QUERY handle remained untouched
and was verified alive at16:45 UTC awaiting its original single login. Next: a
separately versioned grounded plan, authorized materialization and prompt delivery;
actual variation and the other consumers remain unconnected at this checkpoint.

Candidate `07c25268af7a4d3f1aad8de77f647ab024fe404d` passed the complete existing
three-wheel/RECORD/application-contract build and a two-wheel-only transitive EOM
import/schema-reference check. The packaged resource raw hash, public exports,
copied-pin revalidation and authority-field rejection were checked with no checkout,
Application API wheel, prefix fallback or ML imports. Platform raw
`1f4e24d4ce380e7c1858a34e697ab13a0f30abbf64a01008bdec33bcf613ed91`;
API-contract raw `307b371555bd62320d400a73542b8a6453e2bfcaa222d6847addeec2ce1db850`.
Evidence: `similarity-delivery-{release-build,owner-pair-proof}.log` in the same local
directory. Candidate is NOT installed; current API75fdc265/owner5018ad2d are unchanged.

## 17. C2 grounded-plan and workspace binding

2026-10-14 UTC. Inspecting the existing inventory confirms23 is the next unused
plan version;21/22 remain comparison plans. Add plan23, not edits to plan19 bytes.

1. **Responsibility:** Extend the existing grounded post-registration plan with one
   typed similarity-delivery pin. Orchestrator materializes it only for authoring/
   review; current Catalog common-context composition remains the source authority.
2. **Canonical source:** The same context Artifact from§16. Existing original Item,
   Evidence Bundle, accepted report, Graph/policy and usage receipts stay unchanged.
3. **Identity:** New plan schema/resolver23, original workflow1.16 topology and Pack/
   instruction pins are separate. There is no new workflow graph merely for a file.
   A future compatible Pack/preset enables delivery; old pinned runs keep plan19.
4. **Resolution:** Schema-first parse, exact delivery/raw/context/request hashes and
   original variation source/Graph/policy agreement. Materialization uses the existing
   approved Artifact reader, exact allowlist and a mandatory current common-context
   reader; a stored permission hash or valid file alone is not current authority.
5. **Access:** Fixed plan/member key lookup, bounded JSON read and one fixed workspace
   alias `references/similarity/context.json`; no mutable head, model encode or search.
6. **Structures:** Frozen plan/pin, keyed source identity, existing file-set/Artifact
   records and exclusive workspace creation. No DB/index/queue/cache or new framework.
7. **Cost:** O(context bytes)≤512KiB at the explicit read/materialization boundary.
   Two common reads fence member IO; each retains the existing full-population
   authorization/decoding and bounded exact ranking cost (up to1,024 sources),
   not merely one selected candidate lookup. No DOCUMENT encoding, constant-time
   corpus-authorization claim, or authority cache is introduced. Already verified
   immutable bytes may be reused only inside the same existing reader root.
8. **Transactions:** Trusted caller keeps the actual current owner/session/source
   fences through bounded validation/staging. No inference in that transaction.
   Source/permission drift removes disclosure; partial workspace failure is not a
   new query, successful workflow or authorization to retry with a new identity.
9. **Dependencies:** New plan contract→public Catalog delivery/types; Orchestrator
   defines the small owner-local read port. The existing WorkflowRunner integration
   layer implements it through the current Catalog common application and pinned
   Artifact reader. Orchestrator does not import Catalog infrastructure. No worker
   DB/NAS, private resolver imports, external API or new dependency. Domain stays IO-free.
10. **Failure:** Missing current reader, wrong purpose/role/pointer/Graph/policy/source,
    stale context or revoked authority fails closed. OPTIONAL absence is only the
    explicit validated common result, not an exception swallowed as missing vectors.
    Same pinned plan/context are reused; no latest/device/recipe replacement.
11. **Alternative:** Adding free-form keys to plan19 or auto-authorizing its file
    list skips the new meaning. One compatible plan plus fixed validated staging is
    sufficient; no nested copy of a stored plan or fabricated Evidence receipt.

Plan23 keeps workflow1.16, maximum3-review behavior and approval-after-registration;
it does not activate a new graph or grant unsupported consumers/private intent.
Its pure construction accepts an UNPERSISTED base candidate only; existing stored
plans must never be rewritten/upgraded. Runtime preparation, current-reader binding,
Pack/prompt provenance, activation and actual variation remain separate required
integration, not implied by schema/materialization source tests.

The role-only sidecar is metadata, not the candidate's actual worked solution or
original-page pixels. C2 remains INCOMPLETE until bounded selected candidate
evidence/profile materialization, compatible Pack/instruction provenance, trusted
runtime preparation/reader composition, and actual variation execution are connected.
Do not claim that a worker used full candidate reasoning merely from this JSON file.

### 17.1 Source-only plan/materialization checkpoint — 2026-10-14 UTC

Plan23 canonical and packaged schema raw SHA is
`d0d41a79fee8d94c7815795081f55f46696e2802623670d09491559afefb02ad`.
Its schema-first public model preserves workflow1.16, original source, Evidence and
review escalation. The original296 Catalog resources/count/hash remain frozen.
Existing plan persistence dispatch retains dependency/Pack/preset/role and unique
workflow replay guards; the new fixture directly tests dependency refusal before
DB access, not a newly executed PostgreSQL persistence acceptance.

The Orchestrator application owns a narrow local read interface and checks exact
workflow/operator expectation, authoring/review role, request and returned bounded
raw SHA. The WorkflowRunner adapter holds the actual captured Catalog caller and
common reader, refusing a mismatched operator even when file/hash metadata is valid.
It checks current common context before/after pinned member IO, exact original Item
and content-member identity, singleton file set, schema/media/raw hash, approval and
successful producer. Image/registration roles get neither sidecar nor role guidance.
Primary/escalated review retain the same reference pin; missing or revoked authority
does not become OPTIONAL vector absence. A failed partial workspace is not a runnable
job; no auxiliary file or AGENTS document is created after the tested refusal.

Initial21-suite regression:437 PASS/1 FAIL. The existing dependency test detected
an Orchestrator import of Catalog infrastructure; the new adapter was relocated to
the WorkflowRunner integration layer and the test was NOT weakened. Earlier physical
fixtures also incorrectly assumed that a containing storage root is invalid and that
verified immutable bytes must be rehashed on every same-root read; those expectations
were corrected without weakening the shared Artifact reader. A late physical file
change cannot replace the already verified bytes, and a fresh reader rejects it.

Final22-suite source regression: **538 PASS**; strict mypy7, Ruff/format13 and diff
checks PASS. Actual local SQLite publisher/Artifact-reader tests are distinguished
from stubbed public workspace-wiring tests; current IAM/source/QUERY evidence is
synthetic in both. Logs: `/tmp/eom-identity-provider-install.nAaycoDM/` with prefix
`similarity-materialization-`, including original failure logs and final reruns.
No migration, production DB/role/unit/runtime/Pack change, real QUERY/model/GPU run,
candidate grant, corpus re-encoding or consumer activation is claimed here.

Candidate `cc369e193c472b6e718a30fc2f06a0421e2c8742` passed the existing complete
three-wheel/RECORD build and a strict two-wheel-only transitive import/resource/ref
proof for the new plan, Orchestrator port/materializer, WorkflowRunner Catalog
adapter and review parser. No checkout, API wheel, installed-prefix EOM fallback or
ML import was permitted. Platform raw
`ee6f0e9945e3403d7a5905304d59d3dbb4bab0d9e2064f8d7d128a6337a28d6b`;
API-contract raw `aef1b45d52d2810733d30fa6762e9f6e64990268ad2719a0e95b200990a48cd4`.
Evidence: `similarity-materialization-{release-build,owner-pair-proof}.log` in the
same local directory. This candidate is not installed; API75fdc265 and owner5018ad2d
remain the pinned runtime for the existing genuine QUERY canary.

## 18. Bounded selected-reference materialization

2026-10-14 UTC. Plan23 is still an unreleased source candidate with no production
plan/workspace history. Its pinned context already identifies each candidate's exact
Item/member, accepted-report pointer and profile hash; no additional source authority
or mutable lookup is needed. Previous candidate wheels/evidence remain immutable and
are not retrospectively called this new materialization acceptance.

1. **Responsibility:** Catalog's existing verifier resolves selected reference
   entries through its supported selected-source operation. The existing runtime
   adapter stages a closed derived JSON beside context, not inside Graph Evidence.
2. **Canonical source:** The original Item/member and accepted V10 report remain
   canonical. Reuse `StagedExperimentEntry` question-only text and concrete profile
   claims rather than copying entire Item/report/PDF/PNG files. Include the anchor's
   exact accepted profile when present, without duplicating its already staged Item.
3. **Identity:** One small frozen materials value pins request/context semantic hashes
   and its own canonical hash. Entries retain source/profile/report identities;
   no new registry, logical entity, Artifact lifecycle or DB aggregate is created.
4. **Resolution:** Compare every selected current source, profile, report and Graph
   against the exact context. Never substitute latest, add an unselected entry, or
   silently drop missing text/report/decisive reasoning. Existing entry limitations
   and explicit absent content survive; no inspected-pixel or quotation claim.
5. **Access:** One selected-source batch and map lookup, then context order iteration.
   Authoring/review accept at most8 context candidates plus the anchor profile and
   4MiB canonical materials;
   larger results explicitly fail this delivery budget, never truncate source text.
6. **Structures:** Existing source selector, tuple of entries, keyed membership map,
   canonical serializer and exclusive workspace creation. No new queue/cache/index.
7. **Cost:** Selection/closure O(N+K), material bytes O(B), K≤8. Existing official
   source eligibility retains its bounded full-population cost; it is not advertised
   as constant-time metadata access. No encoding or comparison-model invocation.
8. **Transactions:** Use the actual caller and the same root Session/identity/source
   fences as the existing read adapter. Before/after common authorization remains;
   no long model execution occurs inside this transaction or the source commit.
9. **Dependencies:** Contract-only model/schema reuse existing entry types. Catalog
   verifier implements its public material-read seam; WorkflowRunner implements the
   Orchestrator application port. No infrastructure dependency moves into contracts
   or Orchestrator; no worker DB/NAS or new dependency.
10. **Failure/replay:** Mismatched/missing/duplicate/oversized entries fail before
    runnable workspace completion. Same pinned context and deterministic entry
    projection reproduce bytes; missing decisive claims remain limitations, not a
    positive transfer verdict. Retry does not pick a new index/source/recipe.
11. **Alternative:** Pointers/scores alone cannot let a worker inspect the candidate's
    actual conditions or accepted-report-derived reasoning. A bounded existing entry
    projection is sufficient; copying the full corpus/reports or a new material store
    would duplicate canonical data unnecessarily.

Define the closed `system-rag-similarity-materials/1.0` JSON Schema2020-12 and frozen
model before behavior. Workspace alias is `references/similarity/materials.json`;
it is explicit temporary materialization, not a second canonical Artifact. The
returned local port value carries the two workspace payloads only at this boundary;
neither payload is stored in DB or added as arbitrary keys to existing role messages.
Compatible Pack/instruction provenance and actual trusted runtime composition remain
mandatory before plan23's first operational activation.

### 18.1 Source-only selected-material checkpoint — 2026-10-14 UTC

Closed materials schema raw SHA:
`a81f556811c74a93faf8635e492ec92a5791948428f9995179b27dea77bc640b`.
The schema/frozen model reuses existing exact Item-text/profile/metadata contracts,
checks canonical byte/semantic hash bounds, rejects duplicate/extra/foreign/altered
references, and preserves absent text/anchor report or decisive claims without
inventing content. Source/model-inference provenance is retained in each profile;
these projections are not original-page quotations, pixels or Evidence-usage receipts.

The existing Catalog verifier now exposes one selected-reference read using its
supported selected-source batch, actual caller fence, exact Graph/policy and existing
source/report projection. Hash-map closure checks restore context order regardless
of capture order. Missing, duplicate, changed or truncated capture is not partial
success. Empty material still performs official current capture. The WorkflowRunner
adapter validates these references before its late common read and pinned producer
check. Orchestrator validates exactly two bounded canonical payloads and writes them
only at the established temporary workspace boundary; no new Artifact writer/store.
Authoring and primary/escalated review retain original Evidence/variation files and
add both sidecars; image/registration receive neither. Existing plan23 schema bytes,
workflow/role schemas, released Packs and original296 Catalog metadata/bytes remain
unchanged. Plan23 has no operational history and is still not activated.

Final25-suite regression: **651 PASS /49.68s**, strict mypy6 and Ruff/format14 PASS.
The prior run649 PASS/2 FAIL is retained: the DB Session-shaped projection port was
moved from DB-independent common-context ports to the existing registry integration
ports, and empty-capture registry errors now use the same closed mapping as nonempty
selection. Neither boundary test nor authority refusal was weakened. Earlier fixture
failures exposed the candidate's old synthetic Graph pin; fixture profile/context
pins were corrected together, not the actual mismatch guard. Contract-only116,
focused81 and Catalog83 were overlapping intermediate gates, not additive totals.

Physical context reads use local SQLite/temporary Artifact bytes; selected-source
and IAM fixtures are synthetic, and public workspace tests explicitly stub the read
adapter. No production DB/role/unit/identity change, real QUERY/model/GPU run, corpus
re-encoding or consumer activation is claimed. Evidence prefix:
`/tmp/eom-identity-provider-install.nAaycoDM/similarity-reference-materials-`.
The existing genuine QUERY root/owner handles remained alive at17:50 UTC awaiting
their original login; no restart or second query was submitted. Next required C2
work is compatible Pack/instruction provenance, trusted runtime composition and an
actual bounded variation after the genuine QUERY acceptance; the full goal remains open.

Candidate `3c5e835e70bfa3625d68e1d0fa3588b4ddde4a27` passed the complete existing
three-wheel/RECORD build and strict two-wheel-only imports including the actual
Catalog selected-material owner, new public contracts, runtime adapter and workspace
value. Packaged schema raw SHA/offline refs, copied extra-field refusal and absence
of checkout/API-wheel/prefix fallback or ML imports passed. Public exports/registry
were additionally type-checked: strict mypy **8 source files PASS** (overlaps the6).
Platform raw `a26feedbcc825794ef2a95ee8136642ebf7aed2eb5ec889dd2445fe4a1c42b8f`;
API-contract raw `b143635b59fa95163d17217dd24033943006904a95e9af6a77273f8bd2ec4f9c`.
Evidence: `similarity-reference-materials-{release-build,owner-pair-proof,mypy-public-exports}.log`.
Candidate is not installed; the existing API/owner pair and waiting QUERY are unchanged.

Next integration inventory: Pack1.20.16 already exists as an inactive evidence-binding
clarification successor (`f019a060`), so do not overwrite it or assume1.20.16 is free.
Plan resolution/replay in `execution_resolver.py`, the real Orchestrator materializer
callback and evidence/result validation still need compatible plan23 wiring. In
particular, evidence validation also calls the shared allowlist without a similarity
context; do not activate the new plan after testing only the workspace leaf. Preserve
current actor/source fences, original evidence usage and late review validation while
closing that actual end-to-end path.

## 19. Plan23 preparation, replay and Evidence-result compatibility

2026-10-14 UTC. Keep existing wire schemas and workflow1.16. Source candidate
plan23 is not activated until the actual runtime/Pack path and canary are closed.

1. **Responsibility:** Extend existing grounded plan resolution/replay and its actual
   response/receipt/registration readers. No second workflow or result-validation path.
2. **Canonical source:** Existing plan/control records, pinned context delivery, Item,
   original Evidence Bundle and role result remain authoritative in their own scope.
3. **Identity:** The new plan is constructed only before first persistence; exact
   replay returns the original stored version/hash. A caller cannot upgrade plan19
   or change a stored plan23's context by supplying different preparation inputs.
4. **Pointers:** One frozen local preparation value pairs the checked context and
   delivery; it is not a source grant. Current producer/source/operator fences still
   belong to the real owner. All plan19/23 readers use one explicit family selector.
5. **Access:** Indexed workflow/plan key lookup, one exact schema selection, existing
   instruction/reference bundle lookups and bounded Evidence re-resolution.
6. **Structures:** Two-member frozen schema set, typed parser/preparation value and
   existing revision references/unique workflow constraint. No DB/schema/index/cache.
7. **Cost:** O(plan+bundle members) and existing bounded Evidence validation; no model
   run, native query or candidate material read during result receipt verification.
8. **Transactions:** Existing plan record/unique-workflow boundary is retained. The
   execution materializer continues requiring its actual current similarity reader.
9. **Dependencies:** Workflow contract helper is IO-free. Orchestrator owns the scoped
   Evidence-only allowlist query and shared bundle checks; runtime adapters remain
   outside it. No new dependency or Catalog infrastructure import into Orchestrator.
10. **Failure/replay:** Evidence verification never obtains the auxiliary sidecar
    allowlist or substitutes it for a Graph receipt. Missing current execution reader
    still prevents materialization; bad plan/hash/step/bundle/Evidence fails explicitly.
    Historical plan19 replay and all released schemas/Pack bytes are preserved.
11. **Alternative:** Passing a synthetic similarity-authority context to an Evidence
    receipt check would conflate unrelated permissions. A narrow Evidence-only query
    with the same shared bundle validation suffices; do not add bypass flags to the
    execution allowlist or weaken its current reader requirement.

### 19.1 Source plan/receipt compatibility checkpoint — 2026-10-14 UTC

The shared explicit plan19/23 selector is now used by resolution/replay, worker
response constraints, materialization, review escalation, Evidence-result validation
and variation registration. Existing V19 parsing is unchanged; malformed plan23
normalizes to an explicit invalid-plan error rather than an ungrounded result.
`PreparedSimilarityPlan` is a local frozen pair of already validated context/delivery
values, not a publication, permission or Pack-compatibility grant.

The existing grounded resolver can bind this pair to its UNPERSISTED V19 candidate
before the one normal plan-record call. It never records19 then upgrades it. Stored
V23 checks row ID/workflow/hash and reuses its exact context without current preset
lookups; a different Artifact pin or adding context to an old stored plan conflicts.
Without preparation, existing new-plan19 behavior and historical replay are preserved.

The Evidence-only query resolves the exact plan/step and the SAME shared released
instruction/reference-bundle checks but obtains no auxiliary context member grant.
Execution still requires its real current reader. New source tests exercise both
authoring and full V12 review receipt creation, exact plan23 SHA and original Evidence,
then the registration source pointer. They use synthetic source/publication/control
fixtures, not production IAM, PostgreSQL plan persistence, a model or actual worker.
The initial review test correctly rejected an APPROVED_ITEM-only verification target
against its PAST_EXAM fixture; the target fixture was corrected, not the source-class
validator. That failure is retained in the initial focused log.

Final30-suite regression: **764 PASS /51.71s**; strict mypy7, Ruff/format8 and diff
checks PASS. The new13 source cases include first persistence, immutable replay,
changed-pointer conflict, stale row headers, malformed response plans, restricted
Evidence-only scope, bundle/step refusal, both receipts and registration linkage.
Overlapping earlier101/11 gates are not additive. Evidence prefix:
`/tmp/eom-identity-provider-install.nAaycoDM/similarity-plan-runtime-`.
Read-only disposable guard inspection separately passed: current head0055 and zero
other connections. No new plan23 PostgreSQL mutation test is claimed from that check.

No production schema/DB/service/policy/Pack activation or actual model/query execution.
The existing QUERY handles were both verified S+ at18:19:32 UTC, still awaiting the
original login; no restart/retry/second submit. API75fdc265/owner5018ad2d remain pinned.
Still required: compatible Pack/instructions, actual API preparation/publication and
current-reader composition into the Orchestrator worker callback, genuine QUERY and
bounded variation acceptance. This is not a completed or active C2 consumer path.

Candidate `3038bdf20a011e6ca8207b6c3303982598990fe6` passed the complete existing
three-wheel/RECORD build and strict two-wheel-only transitive imports for the shared
plan selector/preparation, actual resolver, scoped Evidence query, receipt validator,
review and registration readers. No checkout/API wheel/prefix fallback or ML import
was admitted, and no model/DB/source/publication method was invoked by this proof.
Platform raw `befdbe92ca1aabc1ffdb14caff9d1d9709033d232c3db8a56da7cce4feff73f0`;
API-contract raw `bf6d3ea7e2aa78772348aabeebe8ef7e8e4787d01f46694026998deaf1e25436`.
Evidence: `similarity-plan-runtime-{release-build,owner-pair-proof}.log`. Source
candidate is not installed; actual API preparation and role callback remain unwired.

## 20. Compatible reference-aware Pack and trusted prompt mode

2026-10-14 UTC. This is a source successor, not an activation or a new workflow.

1. **Responsibility:** Pack1.20.17 extends only authoring/review guidance. Catalog
   derives its small render-context mode from the exact stored execution plan;
   workers cannot choose availability or authority through a brief or model output.
2. **Canonical source:** Existing plan, published Pack/instruction bytes, original
   Graph Evidence, original variation source and the two validated similarity
   workspace projections keep their separate ownership and meanings.
3. **Identity:** Preserve Pack1.20.16 and earlier bytes. Deterministically derive17
   from16; only Pack metadata, two role profiles and two prompts change. Workflow1.16,
   role1.24/results12, original guidance files and image/registration inputs stay fixed.
4. **Pointers:** Render mode `PINNED_REFERENCE_CONTEXT` requires an exact plan23
   row/header/hash, workflow, preset, role and Pack release binding. It does not
   authorize source access. The real materializer must still reauthorize and stage
   both `references/similarity/context.json` and `materials.json` from pinned inputs.
5. **Access:** One primary-key plan lookup for each new-Pack authoring/review prompt;
   no corpus scan, native model execution or similarity search while rendering.
6. **Structures:** Existing four-field plan pin, frozen typed plan and a two-value
   literal render mode. No new table, queue, wire/result field, cache or dependency.
7. **Cost:** O(bounded plan bytes) time/space, one indexed lookup. Only new Pack17
   roles use this context; historical prompt bytes/context hashes remain unchanged.
8. **Transactions:** Read the already committed plan at the existing Catalog prompt
   boundary. Missing/stale/mixed binding fails before prompt publication. Do not
   persist19 then upgrade to23 or run a model within the API admission transaction.
9. **Dependencies:** Catalog owns the DB adapter; Workflow plan parsers remain pure.
   The deterministic Pack generator embeds one versioned guidance source with its
   SHA. No new unstaged worker file is assumed and no business rule is copied to UI.
10. **Failure/replay:** Valid19/20 use `NOT_OFFERED`; missing/corrupt/unknown plans
    fail explicitly rather than masquerading as absence. Mode is not a source grant.
    Existing pinned-prompt replay remains byte-exact. New-Pack context hashing also
    includes plan ID/SHA, and exact replay rechecks that same row without rendering
    or publishing another prompt. Thus changing the delivery while keeping the same
    mode cannot reuse a previous prompt. Historical replay keeps its prior behavior.
    Auxiliary coverage absence
    alone is not an originality failure; real Evidence sufficiency remains enforced.
11. **Alternative:** Requiring auxiliary files in every prompt would break ordinary
    workflows; guessing from file presence or user text would lose provenance.
    Two explicit modes suffice; do not add a generic prompt framework or new workflow.

The appended rules compare concrete conditions, intermediate relations, decisive
inference, asked judgements and misconceptions, not generic solution-stage slogans.
Ranks remain independent observations and scores are not correctness, approval,
probability or originality thresholds. Profiles are not new Evidence IDs. Preserve
the exact existing citation union, original-source requirement, copy policy, student
layout/material constraints and maximum-three-pass repair loop.

The inherited image profile/prompt/policy must remain byte-identical and exact
Pack bundle hashes must retain the existing SVG label-layout gate. This includes
inactive16, whose previous membership omission is a source defect, not permission
to change an installed/historical Pack. Validate deterministic bundles before
adding explicit successor hashes; never use a semver range or latest fallback.

### 20.1 Source-compatible Pack checkpoint — 2026-10-14 UTC

Pack1.20.17 is deterministically derived from16 with exactly five changed source
files: Pack metadata, authoring/review profiles12.3.0 and their prompts. One embedded
guidance source, including its raw SHA, defines the two explicit modes and concrete
five-facet comparison. Original content-team guidance, image/registration prompts,
workflow topology, role/results schemas and existing Evidence rules are unchanged.
The generator refuses overwriting a target and verifies exact regenerated tree bytes.

Actual Catalog rendering now derives its mode from the persisted19/20/23 plan,
checking its row header, workflow/definition, preset, Pack release/hash and exact role
in one indexed lookup. Neither user text nor a similarly named runtime dictionary
selects the mode. The small frozen context contains mode plus plan ID/SHA, so pinned
prompt replay rejects changed delivery even if its mode has not changed. Old-Pack
context hashes and byte-only replay retain their prior behavior. This is metadata
binding, NOT current source authorization or proof of runtime materialization.

Both inactive16 and17 retain exact deterministic SVG layout-gate bundle pins;
16's missing membership was fixed without editing that Pack. New17 does not silently
lose image policy when gaining reference guidance. A stale test that treated16 as
an unknown future release now uses99.0.0; released brief rejection remains enforced.

Final27-suite regression **511 PASS /61.37s**, strict mypy4, Ruff/format6 and diff
checks PASS. Tests use synthetic plan/source authority and temporary Pack/workspace
files, not production IAM, a new PostgreSQL plan persistence run or a model. The new
39 cases include both roles/modes, exact compilation/reproduction, image gate hashes,
binding refusal, bounded malformed plans, actual Catalog context wiring, unchanged
old-role contexts and immutable prompt replay. Earlier overlapping63/56/505/509
gates are not additive totals. Initial preset and changed-member negative fixtures
accidentally supplied the original ID; they were corrected to guaranteed-different
IDs, not by weakening refusal. Failed logs are retained. Evidence prefix:
`/tmp/eom-identity-provider-install.nAaycoDM/similarity-reference-pack-`.

No production DB/migration/service/Pack/policy change, model/GPU execution, corpus
re-encoding or consumer activation in this checkpoint. The same QUERY handles were
alive at18:30 UTC awaiting the original Studio login; no restart or second submit.
Still required: published compatible Pack/instruction provenance, actual API native
QUERY preparation/context publication and trusted reader composition into the real
Orchestrator callback, then bounded variation acceptance. Other goal consumers and
actual CPU/GPU measurement/default selection also remain open.

Candidate `ae75dd83e1729ca45a55097188d919050e539f8d` passed the complete existing
three-wheel/RECORD build and strict two-wheel-only imports, now including actual
Catalog prompt-mode/replay wiring, frozen context value and exact16/17 SVG layout
pins. No checkout/API-wheel/prefix fallback or ML import was allowed. This proof
did not call DB/source/publication/model operations. Platform raw
`8c6b6a21d8f88e5d549f81fe26f9e21a471f4dfd11b4e0f7e6b035f777050043`;
API-contract raw `7fba99f40a256224adb2a78fe836608031e15bbbeef706bb80017355b4f1ed91`.
Evidence: `similarity-reference-pack-{release-build,owner-pair-proof}.log`.
Candidate is not installed; runtime activation and actual consumer acceptance remain open.

## 21. Trusted role execution composition into the real Orchestrator callback

2026-10-14 UTC. Connect the existing two-file materializer to the actual executor,
not a second worker path. Existing plan23/delivery/materials schemas are the wire
contract; the added port/context is owner-local, not a new worker protocol.

1. **Responsibility:** WorkflowRunner prepares the current role's trusted context;
   Orchestrator passes it to its existing allowlist and materialization callback.
2. **Canonical source:** Attached stored Workflow/step, immutable plan23 and the
   existing exact completed QUERY reader. No caller dictionary grants authority.
3. **Identity:** Reuse Workflow/step/plan/query identities. No new request tracker,
   persistent registry or re-created native query. The immutable creator, not the
   command processor or worker role, selects the actual operator.
4. **Pointers:** Validate exact stored request, running step/attempt, plan pin and
   compatible Pack17 before constructing the small local context. Its request must
   be the exact completed QUERY context, never a latest or DOCUMENT substitute.
5. **Access:** Indexed Workflow/step/plan lookups at the command-fenced root. Existing
   materializer performs current full source/Evidence/Artifact checks at staging.
6. **Structures:** A narrow preparation port and existing frozen context; explicit
   production composition injection. No mutable global map or parallel queue.
7. **Cost:** Bounded plan/request validation, no model, source scan or binary read
   at preparation. Existing full source reauthorization remains at materialization.
8. **Transactions:** Re-read attached rows under the existing command lease fence.
   Preserve Job/step binding, failure receipts, capacity and actual worker launch.
9. **Dependencies:** Runner owns the port/concrete Catalog adapter; Orchestrator
   receives only its own local materialization context and never imports Catalog.
10. **Failure/replay:** Missing composition remains unavailable, not a source grant.
    Actor mismatch, expired actual session, changed request/step/plan or withdrawn
    source fails explicitly. The existing captured owner/session is reused without
    extending its TTL. Historical role execution with no context remains unchanged.
11. **Alternative:** Letting worker input carry operator/policy or copying Catalog
    IO into Orchestrator would break authority/dependency boundaries. Explicit
    owner-local composition suffices; do not add global identity impersonation.

First composition binds one trusted completed QUERY reader/current captured owner
to a bounded runtime. Another operator/request cannot borrow it. This does NOT yet
activate shared API preparation or supply a durable multi-user owner-session
selection; that remaining production boundary must use official current captures,
not saved grants, background service impersonation or a relaxed session fence.

### 21.1 Retained Identity fence and caller-owned read root

Integration inspection exposed an unnecessary cross-root dependency: selected
materials are resolved in the materializer's root and retain its current Identity
fence, but its late common-context read opened another root. Inspection of the
actual Identity implementation confirms shared read locks (`FOR SHARE`), so two
ordinary readers alone do NOT prove a self-deadlock. A queued writer or bounded
connection pool can make separate roots matter, but no production deadlock was
observed/reproduced here. Treat this as root ownership/connection-pressure hardening,
not a confirmed live incident or a measured performance improvement. Synthetic IAM
fixtures do not demonstrate live lock safety.

Use one caller-owned root for first/late common composition, completed QUERY reads,
canonical context bytes and selected materials. Extend the existing completed QUERY
reader with an explicit root-local entrypoint; its ordinary entrypoint still opens
one root and delegates. A Runner-owned session adapter supplies Catalog's existing
in-session source/view methods to the SAME pure common application. No source fence,
full-population late check, QUERY provenance or session expiry is removed. The pure
application/Orchestrator do not import this infrastructure or acquire another DB
connection. Tests must reject missing/nested roots and prove no inner session opens;
this source/root-identity evidence is not a new production PostgreSQL acceptance.

### 21.2 Role composition/root-local read checkpoint — 2026-10-14 UTC

The actual `PlatformRoleJobExecutor` now prepares a context through a narrow
explicitly injected port and passes it to `Orchestrator.submit_workflow_role`.
The existing Orchestrator callback gives that SAME value to both its allowlist and
workspace materializer. It still owns Job creation/binding, capacity, worker launch,
failure evidence and Artifact commit; no parallel execution path was introduced.
Default composition has no provider and does not activate plan23 or invent authority.

The concrete provider re-reads attached Workflow/step/definition/plan at the existing
command-fenced root, checks running role/attempt, exact definition and stored request
business fingerprint, Pack17/hash and plan pins, then uses the immutable creator's
actual current captured owner. A command processor, saved operator ID, other user's
QUERY or changed context cannot substitute. Preparation does not run QUERY, scan
the corpus or read vector/image bytes. The captured session's original expiry stays
enforced, and default/legacy execution still uses its original path.

Root-local common composition supplies the existing pure application with bounded
Catalog in-session source/view adapters and the existing completed QUERY reader's
new in-session entrypoint. Ordinary completed reads still open one root and delegate.
First/late current checks, QUERY checkpoints/bytes and selected materials retain
one caller root without opening inner sessions. No current source fence or full
population late check was replaced by cached authority. The source uses small
per-read adapter values, not a global registry, long-lived Session or new dependency.

Final38-suite source regression: **801 PASS /211.81s**; strict mypy8 and Ruff/format12
PASS. Actual callback tests materialize both auxiliary files plus the original
variation/Evidence files in temporary workspaces before a synthetic worker stops;
no real model/process/result publication is claimed. They also verify missing or
foreign context refusal. Other tests cover current actor/session denial before Job
submission, roles/review tiers, original binding, exact request/plan failure, explicit
production injection, same-root identical ranking and late-source withdrawal.
The completed-reader same-root test uses actual temporary SQLite Artifact/Job bytes
and synthetic IAM; it forbids opening another root. This is NOT live IAM acceptance.

Separately, the guarded existing disposable PostgreSQL native-stage suite passed
**68 tests /45.61s** across its six existing files. Before/after inspections confirm
head0055, correct disposable identity and zero other connections. This is regression
for native persistence/submission/reconciliation, NOT a new plan23 PostgreSQL or C2
runtime acceptance. No production DB/migration/role/policy/Pack change was made.
Initial fixture failures (missing preset/header, and a negative image-mode test
that reused the original value) and the nullable-result-schema type-check failure
are retained in logs; fixtures and explicit narrowing were fixed without weakening
the underlying validators. Overlapping50/127 gates are not additive totals.
Evidence prefix: `/tmp/eom-identity-provider-install.nAaycoDM/similarity-role-composition-`.

The same genuine QUERY root/owner handles were verified S+ at19:00 UTC, still waiting
on the original Studio login; no restart, new capture, model/GPU run or corpus
re-encoding occurred. Still required: actual compatible Pack/instruction publication,
API/native QUERY preparation/context publication and durable multi-user selection
of an official current owner, then installed bounded variation acceptance. The new
bounded runtime injection is not represented as that completed shared API path.
Remaining consumers and actual CPU/GPU comparison/default selection stay in the goal.

Candidate `99d42aa59da478a048747d82855ee9798880176d` passed the existing complete
three-wheel/RECORD build and strict platform+contracts-only transitive import proof.
Actual executor/Orchestrator/composition signatures, current-capture provider,
root-local common/QUERY reader and existing materialization/receipt dependencies
resolve from those two archives alone. No checkout/API-wheel/prefix fallback or ML
import was allowed; the import proof made no DB/source/publication/model call.
Platform raw `0e2f174f353f10657d133ac9eb0f89794f2e815f3999eee86f0f4df7434fe139`;
API-contract raw `e05a96a8aedd99bd095a132ab29f93975f976325a510e645f28dc5823ad2a4b4`.
Evidence: `similarity-role-composition-{release-build,owner-pair-proof}.log`.
Candidate is not installed; this is not shared API or actual variation activation.

## 22. Owner-held item-reference preparation before API plan persistence

2026-10-14 UTC. API inventory confirms `start_workflow` resolves Evidence outside its
write transaction, then creates one plan and START command. The API cannot acquire
the protected native-owner DB identity, launch native units or commit NAS Artifacts.
Do not turn an injected Python callback into an API privilege expansion. Automatic
native execution needs an owner RPC/queued handoff; it is not implemented by merely
adding a constructor argument to the API.

1. **Responsibility:** First close the real owner use case: an exact completed QUERY
   read scope → current common context → Orchestrator-owned canonical publication
   → prepared plan value. This is a callable production component, not a mock port.
2. **Canonical source:** Actual captured owner/current Catalog sources and the
   original immutable QUERY, Evidence result, preset and expected resolution.
   Context publication does not replace any of these or create Evidence IDs.
3. **Identity:** No new lifecycle/registry/schema family for local checked values.
   Preserve separate owner Job, Artifact/revision, raw and semantic context hashes.
4. **Pointers:** Before publication, revalidate existing typed input contracts and
   exact original/Graph/policy/preset/Pack17 pins. Resolve canonical context bytes
   after publication, then repeat the full current common read in the same root.
5. **Access:** Indexed current control/Artifact resolution and existing bounded
   source/QUERY/vector reads; no native execution, HTTP login or corpus re-encoding.
6. **Structures:** One small frozen result and existing publisher/reader interfaces.
   Publication key derives from actual operator, exact native QUERY Workflow and
   context-request SHA, not a changed result or HTTP transport key. Multiple Item
   workflows reusing that same query reference one canonical context. No map/cache.
7. **Cost:** Existing O(bounded source/view rows) common composition and bounded
   canonical member IO. No constant-time claim or measured performance improvement.
8. **Transactions:** Retain the current source/Identity read root across publication
   and late checks. The Orchestrator publisher owns its independent commit. A late
   failure may leave a valid committed Artifact but MUST NOT return a prepared plan
   or promote a Workflow. Preserve/reconcile the original query-owned key, not
   delete/relabel it. API transport idempotency remains the existing API's concern.
9. **Dependencies:** Runner application coordinates the existing Catalog session
   reader and Orchestrator publisher. The API still receives no NAS/native/secret
   capability. No domain import of DB/filesystem and no new dependency.
10. **Failure/replay:** Invalid inputs/current capture fail before publication.
    Same-key exact retry reuses immutable bytes/time; changed context/provenance
    conflicts explicitly. Raw-byte/hash/lifecycle or late source mismatch refuses
    handoff. Native failures/history, session expiry and original query pins remain.
11. **Alternative:** Performing model computation in the API write transaction or
    constructing the privileged native owner inside API breaks latency/isolation.
    Use the concrete owner preparation component behind a later protocol-first
    challenge/owner-command adapter; do not present this local use case as the
    completed asynchronous multi-user API path.

Follow-up API work must preserve immediate asynchronous submission, existing
transport replay/accepted-resolution pins and one plan-before-first-authoring.
Native QUERY must run through its existing admitted Workflow/command/lease owner,
not a model call inside HTTP/DB transactions. A restart must recover exact owner
work/keys, not store bearer tokens/passwords or reinterpret saved IDs as grants.

API model inspection also confirms `WorkflowRequest.expected_resolution` is paired
with `production_occurrence`; it is NOT a normal single-item option. Pass the same
existing typed resolution value explicitly from trusted preflight to preparation,
without inserting either production field into an ordinary request. If a production
request already pins it, the two values must match. Return that small exact resolution
alongside local preparation metadata so a later API transaction can reject drift.

### 22.1 Explicit late provenance refresh without re-reading immutable payloads

The new preparation test used a separate SQLite connection to withdraw a canonical
Artifact approval after its first read. A second `read_pinned` reused captured ORM
metadata and did not see that external update; earlier same-Session mutation tests
did not cover this. Fix the owning reader, not each caller with ad hoc SQL.

1. Responsibility: existing `PinnedArtifactReadContext` owns a late provenance check.
2. Canonical source: current Artifact/revision approvals and producing Job rows.
3. Identity: same exact captured IDs/revisions, no current/latest substitution.
4. Pointers: compare lineage/type/status/hash metadata with the captured values.
5. Access: three indexed scalar batch queries; no per-member lazy/N+1 reads.
6. Structures: bounded identity sets/maps over at most4096 captured revisions.
7. Complexity: O(n) metadata time/space; no manifest/blob reload, decode or file rehash.
8. Transaction: same active root, no autoflush/write or new row-lock privilege;
   pending Artifact/Job mutations are refused. This is a late point-in-time check,
   not a transferable permission receipt or a distributed atomicity claim.
9. Dependencies: infrastructure reader only; no new domain/DB schema/dependency.
10. Failure: missing/changed/withdrawn provenance fails; canonical bytes/history stay.
11. Alternative: clearing immutable byte caches or refreshing every member would
    add repeated IO and N+1 work. One explicit handoff-boundary check suffices.

Both new owner preparation and existing C2 workspace delivery call this check after
their late current source read. Other immutable payload reuse and actual current
IAM/source fences retain their existing ownership. Source tests prove separate-root
withdrawal and batch bounds; they do not claim a new production PostgreSQL acceptance.

### 22.2 Concrete preparation and late-provenance source checkpoint — 2026-10-14 UTC

`CatalogItemSimilarityPreparation` now implements the owner use case above. The
existing closed schemas are validated before behavior; no new wire/DB schema,
dependency, privilege, migration or worker protocol was introduced. A frozen local
result retains the exact Workflow-request/Evidence/preset hashes and trusted
preflight resolution, alongside the one canonical publication and plan value.

Final42-suite source regression: **863 PASS /216.23s**. Strict mypy6 and Ruff/format6
PASS. The focused73-test result overlaps this regression and is not an additional
total. New preparation tests use the real publisher, temporary SQLite and actual
canonical member bytes; Identity/source/QUERY observations remain synthetic. They
cover same-query replay, distinct private briefs sharing the same publication,
raw-model copy rejection, original/Pack/preset/Graph/source-class pins, expired or
foreign authority, late denial with preserved committed history, canonical approval
withdrawal, and binding the real published delivery to plan23 before a single record
call. The last record call is captured, not PostgreSQL persistence acceptance.

New provenance tests use separate temporary SQLite Sessions to change approval,
producer state, manifest hash, path or existence. One or four captured revisions
still use exactly three scalar `IN` queries over primary-key columns; file/content
hash calls are forbidden during this check. Pending writes are refused without
flushing, and the original active root is required. Existing C2 materialization now
also refuses externally withdrawn target approval before returning workspace bytes.

Initial failures are retained: an incorrectly paired production fixture, a fixture
preset that did not allow its own auxiliary source classes, the real stale-ORM
provenance defect, and a misplaced test assertion. The input contracts/source-class
guard were not loosened; fixtures and the owning late-read boundary were corrected.
Evidence prefix: `/tmp/eom-identity-provider-install.nAaycoDM/similarity-item-preparation-`.

This is source acceptance only. No production rows/Artifact, installed runtime,
active Pack/policy, model invocation, native QUERY or corpus encoding changed.
The earlier68-test disposable native-stage PASS remains historical regression, not
a new plan23 persistence result. Owner RPC/queue and actual session-scoped shared API
selection, compatible publication/activation and installed bounded Item acceptance
remain open. Chat/exam consumers and actual CPU/GPU measurements/default-device
decision also remain in the active goal; this checkpoint does not close them.

Candidate `c8090f748c971dec77be339e025b0f115519b699` passed the existing full
three-wheel/RECORD build and strict platform+contracts-only import proof. The actual
preparation component/frozen result and late reader method resolve from those two
archives with no checkout, API-wheel, installed-prefix or ML fallback. This proof
does not call a DB/source capture/publication/model. Platform raw wheel SHA:
`c320a2fd44532fc19369d73c55922763bb97084076339d8e16e6eb37d4b0c489`;
contracts raw SHA: `d826b3062d2598deddf7dd98901228a9e96b1981f4d09eb839099205d7194050`.
Evidence: `similarity-item-preparation-{release-build,owner-pair-proof}.log` in the
same prefix directory. The candidate is not installed or activated.

## 23. Authenticated API request → owner preparation handoff

2026-10-14 UTC. The existing API→Catalog Unix socket is the transport owner; do
not add a daemon, generic RPC framework, API NAS access or an API model executor.
The current API `AccessAuthentication` is a presentation projection, not an opaque
Identity capture. Reconstructing authority from its operator/session IDs, reading
private capture fields, or sharing a process-global captured user is prohibited.

The immediate required seam is one real HMAC authentication that returns both the
existing projection and its genuine opaque capture. Identity owns that pair, which
is a small frozen operation-local value, not a wire schema/receipt or a durable grant.
The existing capture-only entrypoints delegate to the same implementation. Normal
non-owner API requests keep their existing path. For `workflow_start`, the dependency
retains the pair in the current RequestContext only; no bearer/password is retained
and no token/session TTL or permission rule changes. Rate limiting, forced-password
change and audit still use the original projection. No new DB/registry/index is
needed: existing token-selector/session/Operator lookups are unchanged in count and
lock order, and auth commits before command or Catalog side effects.

Only Identity's HMAC path creates the capture. The API does not construct/import it
from an HTTP body. A missing/mismatched request capture is an explicit unavailable
owner boundary, not permission to fall back to a saved actor. Context display/audit
must not serialize or reveal the opaque pair. A failed authentication yields neither
component, and supported logout/rotation/current-session fences still revoke access.
Returning the pair does not export it to Catalog or enable a new operation.

Next, the existing fixed-peer Catalog transport needs a bounded challenge/response
that independently observes the actual admitted API peer/provider before importing
the existing closed capture values. No parsed DTO is authority by itself. Reuse the
installed provider/current-session checks and original expiry; installation/privilege
admission is separate. The recipient constructs an owner for that request/session,
not an unbounded cache of users. No capture, verifier digest or bearer enters the DB,
NAS, logs, Slack or a worker workspace.

Automatic native QUERY must remain asynchronous through its supported admitted
Workflow/START/claim/lease path. HTTP timeout is not proof of no submission. Preserve
the existing transport replay identity and pin controls before the first authoring
plan; do not wait for model work inside an API transaction, persist plan19 and later
mutate it to23, or add fake production fields to a single Item. A protocol-first
pending preparation/continuation must account for crash/replay and current-owner
reauthorization before the shared API feature can be activated. The auth seam alone
is not that completed asynchronous integration or evidence of live activation.

### 23.1 Single-auth request seam verification — 2026-10-14 UTC

`SessionTokenService.authenticate_and_capture_access` and its transactional
`AuthService` use case return one `AuthenticatedAccess` local value. Both existing
capture-only entrypoints delegate to the same verified path. API `workflow_start`
retains that pair only in its current RequestContext; other operations keep their
ordinary authentication path. Its owner accessor refuses an absent, swapped,
fake or other-operator capture and never reconstructs authority from actor IDs.
No transport/export/worker execution has been added by this seam.

Final18-suite source regression: **349 PASS /14.19s**; strict mypy4 and Ruff/format7
PASS. Real source HMAC with synthetic DB rows proves permission dependency and
endpoint share one verification/root, the genuine capture passes the existing
current owner fence, ordinary requests do not capture, repeated requests obtain
distinct operation-local captures without extending the access-token lifetime,
and expiry/revocation/password/permission/rate guards stop owner work. Responses
and context repr do not expose bearer/verifier values; no auth material is logged.

The expanded regression initially found four old Graph-miss fixtures missing a
definition key required by the existing admission check. They now use an actual
transient `WorkflowDefinitionRecord`; no guard/admission/source code was weakened.
A forced-password test also showed that opaque capture rejection happened before
the friendly API guard: the combined use case now rejects that known condition
with existing Identity `AUTH_PASSWORD_CHANGE_REQUIRED`/403 before creating a capture.

The supported marker-guarded disposable PostgreSQL `authenticated-session-tests`
passed **20 tests /8.52s**, including the new real combined-auth/session/fence test
and existing supported-writer concurrency negatives. The prior19-test run overlaps
and is not additive. The new test proves one actual HMAC authentication, the same
API session/access expiry and successful current-root fencing with no second HMAC.
Environment: `/tmp/eom-api-testdb-20261007114938_c6970ffc`, head0055; before/after
identity PASS and zero other connections. Only synthetic disposable fixtures changed;
no production DB/schema/policy/role or migration changed. This is session-fence acceptance,
not new plan23 persistence, private RPC peer admission or shared API Item acceptance.
Evidence prefix: `/tmp/eom-identity-provider-install.nAaycoDM/similarity-api-owner-auth-`.
The existing held genuine QUERY/captured-provider release stays unchanged; no new
capture/login or model was executed in production during this source checkpoint.

Candidate `657951b7b124545b147dddfb060c9c2d2c85b33a` passed full three-wheel/RECORD
build and two isolated import proofs: owner code from platform+contracts only, and
actual API dependency/RequestContext from the explicitly selected three archives.
No checkout, undeclared wheel, installed EOM-prefix fallback or ML import was allowed;
the proofs made no DB/capture/publication/model call. A negative request-local accessor
also refuses missing authentication rather than deriving it from IDs. No installed
runtime or active policy changed; new API+new platform are one compatible candidate,
not authorization to replace the provider held by the pending genuine QUERY.

Raw wheel SHA: platform `aea6f8df227450e0dfd8c58b80bc37e978d766b703fe83910dc3dd40c3074e35`;
contracts `f41f922eae8a82576010e5993531bdb41e0541fec0b5be00fc48581c77ae46f3`;
API `a46cdbc7665f0d21242093875b9c893a29111b9c6bf3ea9d157b9ef66122ce84`.
Evidence: `similarity-api-owner-auth-{release-build,owner-pair-proof,three-wheel-proof-final}.log`.

## 24. Current installed API peer → Catalog owner capture

2026-10-14 UTC. This is the receiving half of §23, not asynchronous QUERY submission.

1. Responsibility: Identity's existing installed-provider adapter imports a capture
   only from a held Catalog-side Unix connection to the exact admitted API process.
2. Canonical source: actual API HMAC export and current protected process/config/code
   observation, followed by the existing current-session SQL fence in the owner.
3. Identity: preserve the same opaque capture and operator/session/token identities;
   no new persistent entity, session renewal, user registry or permission receipt.
4. Pointers: retain the installed provider's existing held process/files and exact
   release/config hashes. Check API request dependency/context code too. A different
   PID, UID, provider epoch, connection or closed descriptor fails explicitly.
5. Access: bounded fixed peer/config checks and small closed auth values; no model,
   corpus scan, NAS, worker auth, password or API hash-key read by the recipient.
6. Structures: extend the existing one-use transport observation with a private
   fixed epoch reader for each of its two real transport directions. Do not duplicate
   capture minting/expiry/replay logic in a parallel transport framework.
7. Cost: constant-size peer metadata and existing bounded provider file checks,
   independent of corpus size. No measured latency improvement is claimed.
8. Concurrency: observation/import stay in the same handler thread, under the
   original10-second transport deadline and original session/access expiries. The
   same held Unix FD and `SO_PEERCRED` PID/UID/GID are rechecked; multi-worker API
   process topologies are not implicitly admitted by a shared UID.
9. Dependencies: Identity infrastructure only; no Catalog/API/Orchestrator backimport,
   new package or DB schema. Existing TCP provider entrypoint remains unchanged.
10. Failure/replay: use the original canonical request/response1.1 schemas, restricted
    here to `REFERENCE_QUERY`. Reject seed/benchmark/unknown purposes and mismatched
    nonce/request hash before import. No DTO-only mint, reusable observation, changed
    clock/peer, retry, deadline extension or token persistence. Keep failures safe.
11. Alternative: trusting only the API Unix UID or an actor/session DTO cannot bind
    the actual loaded provider. Replacing the existing TCP observation globally or
    copying its security logic adds risk; share its original one-use/expiry owner.

The existing JSON Schema2020-12 capture1.1 family precedes this adapter and remains
byte-for-byte unchanged. A later closed Item-preparation RPC must create a fresh
challenge tied to that held command/connection and consume the reply before any
owner side effect. Its first-frame schema, exact Catalog server binding, loaded API
client code and installed receiver privilege admission still need validation before
activation. This leaf does not grant arbitrary sockets or parsed payloads access,
turn a schema into installed admission, or replace current SQL source/session checks.

### 24.1 Receiving peer source checkpoint — 2026-10-14 UTC

`ProtectedInstalledIdentityProviderAdmission.capture_catalog_request` now consumes
only the exact `REFERENCE_QUERY` exchange from a held Unix peer matching the admitted
API PID/UID/GID. The original public TCP observer keeps its signature and fixed TCP
epoch. Both use one private observation/expiry/one-use implementation, not separate
capture minting. Installed code inventory now independently pins the API authentication
dependency and request-local context as well as the prior nine members. No shared UID
fallback, model-controlled observer, token store, new dependency or schema migration
was added. Current provider checking remains once per shared observation fence; the
private physical-peer check does not rehash all provider files a second time.

Final26-suite regression: **587 PASS /160.47s**; strict mypy2 and Ruff/format4 PASS.
New tests exchange actual bytes over temporary Unix sockets and use real held FDs,
including an actual `dup2` descriptor replacement. The API PID/UID, installed unit
and protected ownership observations are explicitly synthetic; successful source
import is NOT installed private-IPC acceptance. Tests cover different PID with same
UID, changed UID/GID, provider restart/configured process mismatch, purpose/version/
hash/canonical-frame rejection, transport time bounds, closed/changed FD, wrong
thread, boolean-grant callback refusal, same SQL-source values and one-use import.
Legacy TCP/provider tests remain included. No production provider or credential was
read by these fixtures. Existing DB20 evidence is separate and does not prove this
new live peer boundary. Earlier99/586 test results overlap and are not additive.

Initial lint/collection failures (test wrapping and pytest's reserved `request`
parameter) were corrected. The prior inventory assertion expected nine files;
it now independently asserts the complete closed eleven-member set, rather than
weakening current provider checks. Evidence prefix:
`/tmp/eom-identity-provider-install.nAaycoDM/similarity-catalog-owner-peer-`.

At20:02:41 UTC the original genuine QUERY root4163147/owner4163164 were confirmed
S+, with the same live tmux pane, still at the original Studio input boundary.
Its preflight remains the last event: no source capture/model forward has happened.
No restart, replacement prompt, expiry extension, production mutation or installed
API/owner/Pack/Graph change was made here. Next remains the closed Item preparation
RPC/client/server handshake plus asynchronous native QUERY/continuation, current
multi-user scope and actual installed Item acceptance. Other consumers, persistent
coverage and actual CPU/GPU/default-device gates remain in the full active goal.

Candidate `5f9444a3b6c0a9af24c871001c805e3f2bafd4d8` passed full three-wheel/RECORD
build and isolated owner-pair/explicit-three-wheel import proofs, including the actual
receiver method and independent eleven-member code inventory. No checkout, undeclared
wheel, installed EOM-prefix fallback or ML import was admitted; no DB/provider capture,
publication or model was called by these proofs. Raw SHA: platform
`4198403601526e8389f95d9d007e1c86cfef99f3e562e3fba774d14c593fe6a5`;
contracts `9a6576b3c1c41bebb1661db6a1f2722834a061bc21d72acce6b849675a496041`;
API `ad8bcf9920992f208ee2f7e99c5d8f7e091eb9b3396b4a29cb29dea18f1533b7`.
Evidence: `similarity-catalog-owner-peer-{release-build,owner-pair-proof,three-wheel-proof}.log`.
The candidate is not installed or activated.

### 24.2 Deployment ownership discovery before RPC composition

Read-only actual unit inventory at20:15–20:17 UTC confirms:

- Catalog application is active as `eom-catalog-manager:eom-api`, with its fixed
  fragment and no drop-ins. Its installer selects `eom_catalog_manager_runtime`.
- The separate installed index owner is inactive as `eom-workflow-runner:eom`, with
  its fixed fragment and no drop-ins. Its source runtime accepts only INDEX commands,
  service authority and CPU. It is not a QUERY or human-session owner by implication.
- That native unit denies API config/secrets and other privileged paths. The existing
  protected provider-observation opener separately requires a root-held scope; the
  new receiver method does not open those handles or alter these restrictions.

Consequently, the earlier intention to reuse the Catalog socket is a transport
direction, NOT proof that the running Catalog process can construct the privileged
native QUERY/captured-session owner. Do not attach a privileged engine to the API,
grant Catalog/INDEX new permissions, reinterpret the INDEX service grant as QUERY,
or introduce a root broker merely to make this helper callable. First reconcile
the ordinary official Catalog authenticated-read boundary with the separately admitted
native execution/current-owner composition and its durable asynchronous lifecycle.
Any required purpose successor or installed privilege change must be explicit and
tested before activation. No installed authority/migration/service was changed here.
This is a remaining implementation dependency in the full goal, not a source PASS
for the live RPC path and not a reason to weaken source/session/policy gates.

## 25. Separate immutable completed reads from native execution authority

2026-10-14 UTC. Source inspection confirms the existing Identity-owned operator
fence declares `eom_catalog_manager_runtime` as its admitted execute role; the adapter
must independently revalidate actual installation rather than assuming it here. Official Catalog
source capture accepts that actual current-root fence and performs its own current
role/policy/source/report checks. The main design §6 authenticates callers at the
API/application boundary and §8 requires each result read to reauthorize that caller.
A committed QUERY's execution audit is provenance, not the new reader's session.

1. Responsibility: expose a read-only QUERY source owner using the same official
   Catalog registry/resolver and an explicitly supplied current Identity fence.
   Keep the existing native owner exclusively responsible for claim/launch/mutation.
2. Canonical source: current authenticated caller/source authorization plus exact
   committed Workflow, four checkpoints, receipt and canonical member bytes. Never
   use a historical execution session or a stored operator ID as current authority.
3. Identity: preserve original execution audit, Workflow/step/Job/Artifact/revisions
   and all raw/semantic hashes. New current read authority does not rewrite history.
4. Pointers: retain original control/source/input/producer and terminal closure;
   same caller as the original QUERY, same exact request, fresh first/late checks.
5. Access: existing indexed Workflow/definition/step lookups and bounded official
   source/view resolution. No launch, checkpoint write, native lease or model.
6. Structures: one explicit read-owner interface and shared source-resolution and
   canonical-publication functions used by both actual owners. No inheritance from
   the execution owner, fake capture, service impersonation or second result reader.
7. Cost: same bounded source/control/member work as before; no new cache, tables,
   scans, file copies or claimed latency improvement.
8. Transaction: retain one caller-owned current root and late reauthorization. The
   API authenticates every read; accepted background role use also needs its actual
   command/Workflow authority. This new port is not an unauthenticated ID lookup.
9. Dependencies: Runner infrastructure composes official Catalog/Identity; no domain
   infrastructure import. Share immutable local source values; preserve previous
   public imports so existing native clients retain the same behavior.
10. Failure/replay: absent/foreign/currently denied read authority, changed source or
    nonterminal/tampered execution fails. No automatic fallback from an expired
    native capture to this read owner. A trusted caller must explicitly compose a
    fresh supported current read boundary. Execution and retry still require the
    original genuine captured-session owner, policy/lease/admission and checkpoints.
11. Alternative: sending Root/native authority into ordinary Catalog just to read
    a committed Artifact conflates read permission with execution privilege. Keeping
    a native owner behind every completed read also couples long-lived immutable
    evidence to a short-lived execution session. Separate the two actual use cases
    without removing either's checks or activating an unsupported runtime.

No wire schema or released protocol meaning changes. Existing schemas are validated
by the same functions. This source separation does not establish the installed
authenticated RPC or automatically offer a QUERY operation to the INDEX service.

### 25.1 Verified late QUERY Artifact lifecycle gap

A new separate-Session SQLite regression withdraws QUERY revision approval during
the late source callback. The reader still returned verified bytes (DID NOT RAISE):
late source checks covered sources/controls, not that already-read QUERY Artifact.
The same risk applies to its separate completion receipt. Preserve this failing
evidence; do not label it a reproduced production incident.

Use the existing root-local `PinnedArtifactReadContext` for both receipt and QUERY
members, with explicit same-root/settings validation. The shared canonical closure
and consumer's final source handoff call its existing small scalar provenance
refresh. Current approval/producer/identity metadata is canonical; cached immutable
bytes are not current permission. No new persistent state, cache/framework, wire,
dependency, source grant or permission is introduced. All exact member IDs/revisions,
schema/media/hash/producer checks stay with their existing owners. Metadata remains
bounded by the few pinned Artifacts, using three primary-key batches per check, not
per-member SQL or repeated file IO. The same active root owns the read window; a
missing/changed/withdrawn member fails without repair, re-encoding or new submission.
Clearing byte caches or running another model would not address this mutable-metadata
boundary and is not a simpler correct alternative. This is a point-in-time late
check, not distributed atomicity or an authorization receipt transferable to callers.

The additional baseline regression confirms two issues in the owning metadata reader:
refreshing an ORM row could also change the supposed original hash comparison value;
expiring four captured ORM rows caused11 queries rather than three scalar batches.
Capture the small immutable provenance fields as a frozen local value at initial
prefetch, distinct from live ORM objects retained for ordinary leaf checks. IDs,
producer/type/hash/size/path are original comparison values; approvals and producer
state still come from current canonical scalar reads. No schema, authority, lifecycle,
cache or storage change is needed. The snapshot is bounded O(n) small metadata, not
a second Artifact or persistent derived value. Current Root checks and pending-write
refusal remain. Tests reject changed original values even after ORM refresh and keep
the three-query bound after ORM expiry. This fixes the owner rather than clearing
caches or adding caller-specific refresh workarounds.

### 25.2 Read/execution separation and lifecycle source checkpoint — 2026-10-14 UTC

`CatalogReferenceQueryReadOwner` now supplies the explicit current read boundary;
it has no submission/claim/launch/mutation methods and does not inherit from the
native owner. Shared source/config/input functions retain the original checks and
public native imports. Native execution still constructs the original genuine
captured-session owner and keeps its lease/policy/admission/recovery rules. No
expired native owner automatically becomes a new read owner.

The consumer now calls one shared read-only checkpoint/receipt/member resolver
rather than constructing an execution-completion object. Native completion uses
that same canonical closure. One root-local provenance context covers both QUERY
and receipt Artifacts and is refreshed after the final current source check.
Small original provenance values are frozen independently of refreshable ORM rows.

Final33-suite source regression was split into disjoint17/16-file groups:
**312 PASS /138.52s +371 PASS /77.49s =683 PASS**. Strict mypy11 and Ruff/format14
PASS. File groups are stored with the execution evidence, not overlapping counts.
New tests cover explicit fresh read authority while the native port denies, missing
or late-denied current authority, preserved public aliases, terminal-closure negatives
through both owners, canonical consumer delivery without an execution constructor,
shared-reader root/settings mismatch, and external late QUERY/receipt approval or
producer changes. SQLite publication/member bytes are actual; current Identity,
Workflow/source/launcher seams remain explicitly synthetic where stated.

Additional metadata regressions reproduce original-hash comparison loss after ORM
refresh and11 queries after expiring four rows. With the immutable local baseline,
both pass and provenance remains three scalar batches without file rehash. Focused
40/85 and earlier681 counts overlap the final683 and are not additional totals.
The retained initial fixture failures were stale monkeypatch locations after moving
source/canonical functions, not a reason to weaken their guards; fixtures now patch
the actual owning functions. The three real negative regression failures are retained.

After the final metadata change, the existing guarded disposable native-stage suite
passed **68 tests /46.61s**. Before/after inspections verify disposable identity,
head0055 and zero other connections. Earlier68 is not additive. This proves existing
native persistence/submission/recovery regression, not new live authenticated RPC,
actual QUERY forward or new plan23 persistence. No production DB, runtime, migration,
policy, Pack, Graph, model or corpus-encoding change occurred.

Evidence prefix: `/tmp/eom-identity-provider-install.nAaycoDM/similarity-read-owner-split-`.
At20:33:24 UTC the original QUERY root/child were again S+ in the same live pane,
still awaiting its original Studio input; no restart/capture/forward was performed.
Next: select an exact stored completed QUERY through an authenticated read use case,
compose the closed Catalog RPC and current actor/fence, then finish shared API/role
activation and actual bounded acceptance. Native submission remains a separate
supported asynchronous owner path; INDEX authority is not broadened. Other consumers,
coverage and actual CPU/GPU/default-device requirements remain in the active goal.

Candidate `873c5bab30e66ca86a9fa127fe949e47d73762e3` passed full three-wheel/RECORD
build and isolated owner-pair/explicit-three-wheel import proofs. Actual read owner,
shared canonical reader, unchanged public native aliases, API and existing schema
closures resolve only from the selected archives. The read owner has no execution
methods/inheritance; no DB/capture/publication/model was called by the proofs.
No checkout, undeclared wheel, installed EOM-prefix or ML fallback was permitted.
Raw SHA: platform `1c57f601e56b06a7f6f0537b9b76408f76072438e4f0410bb64efdd91bd5d840`;
contracts `cf47f5ca180c3483cd190fec575fe5a358b225841899cf02838db7bcecee4a8c`;
API `19fad5bfa0c173bfcd847f860f78d17f34d3735a8fa66ed77f2fc0a1a0c5bc21`.
Evidence: `similarity-read-owner-split-{release-build,owner-pair-proof,three-wheel-proof}.log`;
exact disjoint file groups/counts: `similarity-read-owner-split-test-groups.json`.
The candidate is not installed or activated; current provider/owner pins are preserved.

## 26. Exact completed-QUERY Catalog read binding — design before implementation

1. Responsibility: authenticated API-to-Catalog read on the existing private socket;
   no model execution, submission, recovery or INDEX-service privilege expansion.
2. Canonical source: existing Workflow initial request, terminal history, official
   source/index registry and committed QUERY/receipt Artifacts.
3. Identity: exact Workflow ID plus original request and context-request semantic
   SHA values. Neither an Artifact path nor a newest-successful lookup selects it.
4. Resolution: current actual actor, own creator, original request equality/hash,
   terminal closure, current source/Graph/policy permissions and canonical member
   provenance remain mandatory. A new read fence is not an old execution capture.
5. Access: primary-key Workflow lookup and bounded ordered candidate composition;
   no scanning other users' requests or copying vector/full Item bytes over RPC.
6. Structures: existing PK/FK/checkpoint indexes, frozen typed selector and existing
   common context. No table, index, queue, cache or dependency is added.
7. Scale: one selected Workflow, at most1024 scoped sources and64 candidates under
   existing limits. Selection is indexed; numeric ranking keeps its existing bound.
8. Transaction: one caller-owned root for current Identity/source/terminal checks
   and common context; late selection/source/provenance checks before returning.
9. Ownership: schema/Pydantic values in contracts; Catalog read service composes
   existing Workflow read adapters; API adapter only transports authenticated actor.
   Native execution constructors are not part of the read service.
10. Failure: closed metadata-only errors, no data on failure, no retry submission or
    latest fallback. Repeated reads reauthorize exact pins and make no writes.
11. Alternative: sending the whole stored Workflow request or scanning latest is
    larger and permits ambiguous selection. A three-field exact selector suffices.

The existing API-only peer gate applies. The chat-owner UID retains only its
existing chat operations; this RPC does not expose a worker tool or public endpoint.
Optional composition fails unavailable until independently admitted current Identity
fence and trusted released configuration are supplied. Source tests cannot activate
the SQL owner function, service grants or native QUERY execution.

### 26.1 Source implementation and verification — 2026-10-14 UTC

Schema-first `system-rag-similarity-read/1.0` is registered with identical canonical
and package resources (raw SHA `6cdf5bf757b524968f7ffa5fe7dae093f7ca01cf28bd5fc20708c27e4e687dbe`).
The three-field selector pins Workflow ID, original Workflow-request SHA and
context-request SHA. Only the fixed API peer can use `READ_SIMILARITY_CONTEXT`;
the chat UID's existing allowlist is unchanged. Reply binding covers the actual
actor and entire request hash, with exact context-request identity and closed errors.

`CatalogSimilarityContextReadService` selects the actual stored initial request
by primary key only after its explicit current Identity fence. It rejects missing
or foreign creators, non-completed/divergent requests, changed pins and terminal
source/output changes. The existing common composer and canonical QUERY reader
retain the same root and source/index/Graph/policy checks. The optional outer
Artifact reader is checked against that root/settings and revalidates QUERY/receipt
provenance after the final outer checks without re-reading model bytes. There is
no native execution constructor, old session/capture reuse, latest query search,
new table, mutation, dependency, vector RPC payload or source-policy expansion.

Disjoint source groups: **62 PASS /31.88s** (four new read contract/boundary/service/
provenance suites), **60 PASS /82.15s** (four existing consumer/read-owner/session/
Catalog-boundary suites), **23 PASS /12.17s** (three resource/dependency/consumer
boundary suites): **145 distinct tests**. Strict mypy7 and Ruff/format11 PASS.
Earlier21/58 and intermediate failing invocations overlap these groups and are
not additional totals. Initial test-fixture errors were corrected without weakening
contract, owner, root or provenance checks; their logs are retained.

Tests include actual temporary SQLite PK lookup (two SELECTs per service read at
the explicitly synthetic owner boundary), repeat reads with no writes, actual Unix
socket round trips and wrong server/client UID rejection, chat-peer refusal, altered
actor/request/context replies, malformed/oversize frames, current and late denial,
changed terminal sources/output, shared-root/settings negatives, and actual temporary
QUERY/receipt Artifact bytes withdrawn after the canonical consumer returns.
Identity/source/Workflow and numeric seams remain synthetic where each suite says so.
No PostgreSQL persistence behavior changed. Existing disposable68 evidence remains
historical; these source tests are not fresh PostgreSQL or actual operator-RPC proof.

Evidence prefix: `/tmp/eom-identity-provider-install.nAaycoDM/similarity-read-rpc-`.
No production deployment, control/Pack publication, admission, QUERY forward, seed/
delta rerun or GPU benchmark occurred. At21:03:31 UTC the original genuine QUERY
process pair remained S+ in its original live pane, still at the original Studio
input gate. It was not restarted or supplied commands. Installed source pins remain
unchanged. Production composition must still supply independently admitted Identity
function owner and trusted released read configuration; default unavailable is not
silently converted to an authority grant. Full-goal consumer activation, actual QUERY,
automatic coverage and CPU/GPU/default-device requirements remain open.

Candidate `50077c31f50a846105bcceafb9bcf73f0a1f7dd1` passed the three-wheel build
and full RECORD inspection. Isolated owner-pair (platform/contracts only) and
explicit three-wheel probes also PASS: the new selector/schema/hash, closed reply,
Catalog service/socket composition, optional shared provenance reader and API client
resolve transitively from the selected archives. All EOM imports outside those
archives, including checkout, existing prefix and undeclared API wheel fallback,
are denied; no ML module or runtime DB/capture/model call is used by the proofs.
This is package closure, not an installed operator-RPC acceptance.

Raw wheel SHA: platform `85b323b9c00c0595ef60e150c3bd21a15a3192b26cc2461eb477beed98441d45`;
contracts `6818488595898cae41a90c10e2fbeb6370de2bdd377436edc53b8f479ce58cdf`;
API `41c2da6edf0f21cc29da6b3cd55423ee67020ea182a57e9a6e769f546806614f`.
Evidence suffixes under the same prefix: `release-build.log`, `owner-pair-proof.log`,
`three-wheel-proof.log`, `acceptance.log`, `existing-regression.log`,
`resource-boundaries.log`, `mypy-seven.log`. The candidate is pushed, not installed.

## 27. Existing Catalog runtime composition — design before implementation

1. Boundary: optionally compose the completed-read service in the existing Catalog
   process; keep its same DB role/socket/sandbox, with no native launcher or claims.
2. Canonical inputs: root-protected non-secret released reader configuration and
   independently installed Identity function, plus the existing canonical reads.
3. Identity: configuration schema/raw SHA pin numerical namespace and original
   QUERY controls; the database owner role/name OID is a pin, not an operator grant.
4. Resolution: fixed no-follow configuration file, root-owned protected ancestors,
   bounded stable descriptor/raw SHA, closed schema/canonical bytes; validate the
   actual installed function against its independent owner before constructing.
5. Access: load one small configuration at startup, then exact QUERY lookups with
   a fresh root/current caller on every request; no latest/corpus scan at startup.
6. Structures: frozen configuration and existing owner/service objects. No table,
   index, queue, registration, persistent cache or new dependency.
7. Scale: one current configured compatible namespace/control set; file at most64KiB.
   Startup cost is bounded configuration parse and fixed SQL security inspection.
8. Transactions: startup inspection is read-only; each RPC retains its existing
   independent root. No operator is authorized by startup and no session retained.
9. Ownership: pure schema/model in catalog contracts; protected file/composition
   adapter in Catalog; the existing runner passes the optional service to its socket.
10. Failure: disabled by default with no file/DB access. Explicit enable with invalid
    configuration/function fails closed before serving; a closed diagnostic is
    emitted without raw config, database URL or exception text. Rollback disables
    the optional mode and restarts the same compatible service; history is untouched.
11. Alternative: deriving controls/OID from the requesting model or silently choosing
    current/latest would remove the independent trusted selection. A new root broker,
    queue or INDEX service privilege would be unnecessary for completed reads.

The optional systemd environment file contains only mode and raw configuration SHA.
No credential is added or stored. Installing/enabling it remains a separate explicit
release step; no actual admission is inferred from source or synthetic IO tests.

### 27.1 Implemented source and tests — 2026-10-14 UTC

`system-rag-similarity-reader-configuration/1.0` is registered with a matching
canonical/package resource (raw SHA `56e414955beda6fd1c9abf05e7acc77175c60c0374caf0e615496a5c73cec2a9`).
The pure model pins corpus/namespace/document space/recipe/source classes, exact
original QUERY policy/bundle and independent database owner name/OID. It refuses
extra actor/permission/secret/path fields, namespace mismatch and ambiguous bytes.
It authenticates no operator and grants/installs nothing.

The actual existing Catalog runner now passes the optional service to its existing
socket. Default `EOM_SIMILARITY_READ_MODE=DISABLED` does not load the configuration
or contact a database on behalf of this feature. `ENABLED` additionally requires
`EOM_SIMILARITY_READ_CONFIG_SHA256` and the exact canonical non-secret file
`/etc/eom/catalog-similarity-read.json`. The loader uses no-follow descriptor-relative
ancestor traversal, protected root ownership, bounded regular-file bytes, exact SHA,
and stable file/named-entry/ancestor identity. It accepts root-owned0640/0644 only.
There is no alternate request path or source/worker-selected filename.

Before building `CatalogReferenceQueryReadOwner`, startup verifies PostgreSQL and
actual current DB role `eom_catalog_manager_runtime`, then independently inspects
the existing Identity function using its exact owner pin. Only the existing
`PostgresOperatorAuthorizationFence` is composed. No native owner, captured session,
claim, launcher, role expansion, model lookup or current/latest index is created.
An explicit invalid enable fails before serving and emits only
`CATALOG_SIMILARITY_READ_UNAVAILABLE`. The standard unit gains optional readonly
environment/config paths, not another unit, UID, group, secret or writable area.

Final one-process source gate: **148 PASS /48.03s** across12 distinct files; strict
mypy4, Ruff/format10 and `systemd-analyze verify` PASS. The earlier35,52,68,77 and3
focused counts overlap this final gate and are not additional totals. Tests cover
the actual runner's enabled/disabled/invalid forwarding, true readonly factory
composition after synthetic installation observations, role/dialect/function denials,
and two users' overlapping actual SQLite PK reads with separate creator/session/root.
Actual temporary file descriptors exercise symlink/hardlink, mode, size, hash, leaf/
ancestor replacement, mid-read mutation and descriptor cleanup. Root ownership and
directory-protection observations in those filesystem tests are explicitly synthetic;
they do not establish live protected installation. IAM/source/numeric and startup
function inspection seams are also synthetic where documented in each test file.

Evidence prefix: `/tmp/eom-identity-provider-install.nAaycoDM/similarity-read-runtime-`;
`acceptance.log`, `mypy-final.log`, `unit-verify.log`. No production DB, migration,
function/ACL, policy/Pack, service restart, native QUERY or CUDA operation ran.
The actual installed Identity function/current owner remains **NOT_REVALIDATED**;
source existence is not live admission. The standalone noninteractive sudo probe
required a password; no TTL/grant change or repeated password request was attempted.
The original genuine QUERY handle was not re-polled inside its30-minute cadence.

Deployment still requires the compatible release/rollback window and trusted values
from the actual published QUERY controls and independent DB owner. Install the exact
non-secret canonical JSON and root-protected optional environment with only the two
mode/SHA settings, then restart the existing Catalog through the standard installer.
Do not enable it from a synthetic example or manufacture the function/OID to pass.
If independently inspected prerequisites are absent/drifted, leave mode disabled
and use the official Identity-owner installation boundary; never run ad-hoc repair.
Rollback selects DISABLED and the prior compatible installed release, not a data
rewrite. Current original canary/API/owner pins remain untouched pending its result.
Full-goal actual QUERY/replay, variation/review/API activation, remaining consumers,
continuous coverage and measured CPU/CUDA/default selection remain open.

Candidate `bfdd28321af6b7f83419158befb182322222030e` passed the complete three-wheel
build/RECORD inspection and independent isolated owner-pair/explicit-three-wheel
probes. They resolve the new configuration schema/hash and local references, actual
Catalog runner factory and closed incomplete-enable guard entirely from selected
archives. Disabled factory evaluation performs no DB/file operation. EOM imports
from checkout, installed prefix or undeclared wheels and ML fallback are forbidden.
These are package checks, not protected installation or actual function admission.

Raw wheel SHA: platform `7fb5d152f73a652dce26c9ba4961c5022c60c68f8c4dd5edc12e974613e8f9d4`;
contracts `23a57ed25f270f69095eb32471ef5b15d8b03c11b72ca1475bc1c4f848b46f25`;
API `9e3d29a273ad6d557bceef4bd62a8e9509b8fd7126c08546ab47c298144088ba`.
Evidence suffixes: `release-build.log`, `owner-pair-proof.log`, `three-wheel-proof.log`
under the same runtime evidence prefix. The candidate is pushed, not installed.

## 28. Authenticated API common-context read — design before implementation

1. Boundary: reuse the existing inference-transfer router, API authentication and
   private Catalog client; this readonly operation launches/submits nothing.
2. Canonical source: exact completed Workflow/QUERY and current Catalog source read,
   not the public body or an API-side database/NAS/embedding search.
3. Identity: public body is only the existing three-field immutable selector.
4. Checks: actual authenticated actor and current read permissions first; exact
   selector/context hash and closed result/error validation before returning.
5. Access: one fixed Catalog RPC per read; repeats reauthorize rather than cache.
6. Structures: existing frozen selector/context, small error-status map; no storage,
   queue, idempotency claim, token persistence, new schema family or dependency.
7. Scale: public selector body at most4KiB; existing context/frame bounds apply.
8. Concurrency: independent ordinary authenticated requests and Catalog roots; no
   API transaction/lease survives network or model execution because neither starts.
9. Ownership: router handles presentation limits; API use case supplies actual
   actor and permission checks; Catalog retains source/Artifact/Identity authority.
10. Failure: expired login/denied/missing or corrupt pins/unavailable owner are safe
    explicit errors. No latest, model retry, stale context or partial result fallback.
11. Alternative: a new search API/framework or direct Catalog DB access would
    duplicate the completed common read and breach the existing owner boundary.

This first approved-reference binding requires past-exam/source read permissions,
matching the currently admitted PAST_EXAM_VARIATION adapter. It is not new-item
generation, worker-tool activation or proof that the production reader is enabled.
Export and compare the actual OpenAPI snapshot after adding the readonly route;
preserve all released predecessor schemas and existing mutation semantics.

### 28.1 Implemented API/read gate — 2026-10-14 UTC

The existing router now exposes readonly POST
`/api/v1/knowledge/inference-transfer/similarity-context`, operation
`inference_transfer_similarity_context_read`. Its only public body is the canonical
three-field selector. The existing application composition injects the fixed Catalog
client and actual authenticated operator; it does not construct a Catalog/native
owner in the API. Existing comparison1.0/1.1 and this read share one public
`authorize_inference_transfer_read` rule. The current past-exam binding additionally
requires CONTENT_INTAKE_READ before dispatch. No workflow start/approval/claim or
Idempotency-Key is used. Repeat reads reauthorize; successful responses use no-store.

A reproduced seven-case input regression showed that the canonical model's JSON
Schema exception was not an HTTP/Pydantic input exception. The API contract now
inherits that exact selector and wraps only schema-validation exceptions into a
generic input ValueError. It duplicates no fields/rules, relaxes no schema and adds
no global exception handler that could misclassify corrupt owner results as client
errors. Missing/extra/invalid authority or pointer fields return safe422 rather
than an internal exception. Owner/result validation still has its separate closed
403/409/422/503 meaning and returns no partial context on failure.

Final13-file source gate: **308 PASS /85.28s**, strict mypy5, Ruff/format7 and diff
checks PASS. This includes actual FastAPI parsing/routing/OpenAPI, synthetic
authenticated identities and Catalog ports, original metadata/snapshot/comparison/
retry regressions, actual temporary private socket/file/SQLite read cases and
resource/dependency guards. These are not live token/session, source or operator-RPC
acceptance. The earlier38, initial31 PASS/7 FAIL and previous308 execution overlap
the final gate and are not additional totals; failure logs remain preserved.
The sole warning is the existing Starlette/httpx TestClient deprecation, not a
new dependency problem or reason to change runtime packages.

The actual offline OpenAPI exporter regenerated the snapshot/hash. Its raw SHA is
`6aa72d9da03a0fe4245601b9fea04a8adfa99d7453dc93c79224ecf5133dbe09`;
the existing breaking-change comparator reports no predecessor break. Route versus
snapshot equality and deterministic export also pass. The Identity provider's pinned
`eom_api/lifespan.py` member changes in this candidate, so future installation must
admit the exact new compatible provider release, not reuse old loaded-code evidence.

Evidence prefix: `/tmp/eom-identity-provider-install.nAaycoDM/similarity-read-api-`;
`acceptance-final.log`, `mypy-final.log`, `openapi-export-final.log`,
`openapi-compatibility.log` and preserved initial/focused logs.
At21:33:38 UTC both original QUERY processes were S+ in the same live pane and its
log still ended at the original Studio-input gate. This respected the30-minute
cadence; no restart, new login request, capture or native forward occurred.

No production install, DB/schema/migration, Identity grant, control/Pack, native
execution or GPU operation changed. The public read connection is not automatic
item-start preparation, a worker tool or live activation. Next actual steps remain
genuine QUERY/replay, independently admitted Catalog configuration/function, compatible
API/provider release and exact-reference item preparation/role activation. In
particular the root-only native provider observation must not be simulated inside
the unprivileged API/Catalog or bypassed to force new QUERY submission to succeed.
Use the existing supported Orchestrator/native boundary; do not expand INDEX
authority or add a parallel queue/root broker. All original consumers, continuous
coverage and measured device/default requirements remain in the active full goal.

Candidate `a45870fe660aafc8b392fb9b4d402d026da371e9` passed full three-wheel/RECORD
build and independent isolated owner-pair/three-wheel probes. The owner pair resolves
the API selector facade and preserves canonical validation with safe input errors.
The three-wheel probe constructs the ACTUAL packaged app with explicit synthetic
invalid DB credentials (no connection), verifies the new fixed Catalog client/service,
and compares its full OpenAPI to the packaged snapshot/hash and readonly operation.
No EOM import may fall back to checkout, installed prefix or undeclared archives;
no ML module, runtime DB/capture/model call or publication is used by the proofs.
This proves package closure/contract equality, not live authentication or retrieval.

Raw wheel SHA: platform `5a5a908fe97d4819294cdeaa1ecc1b1afbc6453c01618febbee741ffadc1ba98`;
contracts `2db479ae497329dcf79d05229c66c4b1ca1c85be1495256a417ef5a239b4472c`;
API `3c3b94196b688c415384e3ec5daafb1731ec1c2112b0938c3cc35bf4dedc4303`.
Evidence suffixes: `release-build.log`, `owner-pair-proof.log`, `three-wheel-proof.log`
under the API evidence prefix. The candidate is pushed, not installed/activated.

## 29. Authoring preparation must not inherit read-only authority

Design before change, 2026-10-14 UTC:

1. Boundary: the existing item-similarity preparation use case may publish through
   the Orchestrator; completed QUERY reads do not permit that side effect.
2. Canonical authority: current Identity role assignments/permissions in the same
   fenced root, not a caller field, stored role or successful earlier read.
3. Identity: preserve actual operator, original QUERY and all immutable source pins.
4. Checks: require current WORKFLOW_START after fencing the actual operator, before
   context composition/publication and again before returning a prepared plan.
5. Access: reuse Identity's indexed `effective_permissions` query; no source scan.
6. Structures: existing frozen permission set and IAM indexes, no cache or schema.
7. Cost: two bounded permission queries per preparation; no per-candidate lookup,
   new binary materialization, dependency or performance claim.
8. Concurrency: retain the existing operator fence through the caller-owned root;
   supported IAM writers cooperate with that fence. The separate Orchestrator
   publication remains independently committed, not a distributed transaction.
9. Ownership: runner application calls the existing Identity repository interface;
   read-only Catalog context operations remain unchanged and need no start grant.
10. Failure: absent/revoked start authority denies handoff, including late failure.
    Preserve any independently committed publication and its original replay key.
    IAM unavailable is explicit unavailable, never a permission or latest fallback.
11. Alternative: rejecting read-only owners entirely couples reads to native launch
    admission. Trusting that every injected owner implicitly requires start authority
    is insufficient after the explicit read/execution split. Check the actual action
    in its owning use case rather than broadening the reader or SQL fence.

Separately, move exact completed-QUERY selection into one public runner read helper
for both Catalog and subsequent consumers. Preserve creator-before-content checks,
canonical three-field validation, active non-nested root and indexed Workflow lookup.
This is selection metadata, not permission, execution admission or a worker tool.
No server-side selector storage or global multi-workflow provider is introduced by
this local guard/refactor, and no existing runtime or released schema is rewritten.

### 29.1 Source verification checkpoint

The read-only-owner/action gap was reproduced in two real temporary IAM-table cases:
missing WORKFLOW_START before composition and removal after publication. Both
incorrectly returned a prepared result before the fix. The original capture/source
observations are synthetic, so these tests do not claim a production authorization
exploit. The preparation owner now uses the existing current permission query in
the same fenced root at entry and final handoff. Late denial preserves the committed
publication; restoring authority replays the same Job/member without rewriting it.

Completed selection is now the public `select_completed_reference_query_request`
helper in the existing runner read module. Catalog's first and late reads use that
one rule. Active root, closed selector/caller values, exact hashes and creator-before-
content checks are covered; ordinary reads still require no WORKFLOW_START.
A focused refactor regression initially remapped SOURCE_ACCESS_DENIED to a generic
invalid-query error because the stable exception inherits ValueError. The explicit
stable-error pass-through fixes this without weakening denials or schemas.

Final19-file source regression: **324 PASS /159.92s**; strict mypy3, Ruff/format5 and
diff checks PASS. Focused50 and earlier failures overlap this total and are retained,
not added. Tests use actual SQLite IAM joins, publisher/replay, exact Workflow lookup,
temporary Artifact/socket/file behavior, API validation and dependency guards; source
and current Identity admission seams remain explicitly synthetic. The sole warning
is the existing Starlette/httpx TestClient deprecation.

Evidence prefix: `/tmp/eom-identity-provider-install.nAaycoDM/similarity-authoring-read-guard-`.
Logs include `red`, `reproduced`, `focused`, `focused-final`, `acceptance` and
`mypy-final`. The first red run had a fixture-only enum typo; the next reproduced
the actual missing action check. No production DB/grant/schema, Artifact, installed
service, source coverage, Pack/policy or native/model/device execution changed.
This does not complete automatic item-start/native admission, shared multi-workflow
selection/consumer activation or the original CPU/CUDA comparison requirement.

Candidate `e668e671f7aaaedd1763ab931551b45bbb60eb0a` passed the full three-wheel
build/RECORD check plus isolated owner-pair and explicit-three-wheel probes. The
public selector helper, preparation action guard and actual Catalog consumer resolve
from those selected archives. The packaged API app/OpenAPI equality still passes;
no source checkout, installed-prefix/undeclared-wheel or ML import fallback is
allowed. These inspect packaged composition, not runtime IAM/DB/model execution.

Raw wheel SHA: platform `fdab2989ae7d7df1d67983f96376657861d4e7478d7e9d19cf5cf9e3d3b82ef1`;
contracts `4d081e4aee37fa5f23b79f7d8b3b145c6a4ef5896ec6b101133b72eb2e604a77`;
API `0b0b2d515f591ac9abaaa4299d3e8ff0cb603e6212e6461ef93168bd885c66b9`.
Logs `release-build`, `owner-pair-proof` and `three-wheel-proof` share the evidence
prefix above. Source/build is pushed; production installation/activation is separate.

## 30. Per-Workflow completed QUERY selection for concurrent role delivery

Design before implementation, 2026-10-14 UTC:

1. Boundary: replace neither native QUERY execution nor worker protocols. Add a
   multi-Workflow application adapter to the existing optional role-context port.
2. Canonical source: stored item Workflow/plan23 plus the original completed QUERY,
   current Catalog source owner and committed context Artifact, not process state.
3. Identity: retain Workflow logical identity, original QUERY Workflow ID, original
   request SHA and context-request SHA. No process-global actor/query fallback.
4. Pointer: reuse the existing closed three-field CompletedSimilarityQuerySelection
   as `runtime_context.similarity_query`. It is a selector, never a permission grant.
   Validate the item creator and plan/context hash before exact QUERY selection;
   staging retains current source, terminal history and canonical byte checks.
5. Access: indexed primary-key Workflow/step/plan/definition/QUERY lookup in the
   existing caller root. No latest scan, list search or reverse artifact discovery.
6. Structures: existing JSON metadata column and frozen selector; no new schema
   family, migration, cache, queue, index or dependency. Share role-binding rules
   with the existing fixed-query adapter rather than copying them.
7. Cost: constant bounded metadata lookups per role; source staging keeps its
   existing bounded per-candidate behavior. No measured latency claim.
8. Concurrency: each preparation uses its own caller-owned active root, actual
   stored creator and exact selection. A shared provider retains only trusted owner
   configuration. Existing command/step fencing and max-three-review flow remain.
9. Ownership: runner owns Workflow selection/binding; Identity and Catalog own
   actual current authorization/source resolution. Orchestrator owns materialization.
10. Failure: plan23 with absent/changed/foreign/nonterminal selector fails explicitly.
    Legacy no-plan/plan19 paths remain unchanged; never infer a query or upgrade history.
    The fixed-query adapter stays available for its existing bounded acceptance path.
11. Alternative: one fixed QUERY in a long-running shared provider cannot service
    unrelated concurrent items. A global query cache, new plan successor just for
    selection, or reading context bytes before original creator checks is unnecessary.

Only a trusted creation/preparation boundary may persist this small selector with
the first plan. This source step does not yet add a public selector to item requests,
rewrite old plan23 history, enable a production provider or claim that the ordinary
runner DB role can use the Catalog-only SQL fence. Compatible owner/runtime admission
and the actual API preparation transaction are still required before activation.

The owner preparation result carries this existing frozen selector alongside its
checked plan/publication and request/Evidence/preset hashes. It does not serialize
an actor grant, add public HTTP fields or alter plan23 bytes. A missing/invalid
original QUERY hash fails before composition/publication. Persisting the selector
in the actual creation transaction remains the next API integration step; the role
adapter must not compensate by scanning for a recent or matching query.

### 30.1 Shared-provider source checkpoint — 2026-10-14 UTC

`CatalogWorkflowSimilarityRoleContextProvider` implements the existing role port
using each stored Workflow's closed selector and actual creator. The bounded fixed-
QUERY adapter remains supported. Both share one role/definition/request/plan binding
rule; the shared adapter retains only its trusted read owner, not users or queries.
Original metadata selection is the same public runner helper used by Catalog reads.
Canonical source/terminal/member verification still occurs during existing common
context materialization; metadata selection alone is not that verification.

Final21-file regression: **379 PASS /171.35s**; strict mypy2, Ruff/format4 and diff
checks PASS. The earlier existing63 and focused78 overlap this result and are not
added. Two real temporary SQLite roots use one provider concurrently for different
creators, item/query IDs and authoring/review roles. Cross-creator, missing/extra/
changed selector, changed plan hash and nonterminal/divergent original queries fail.
Review attempts2/3 retain their original selector, and no-plan/plan19 retain the
original non-similarity path. A SQL trace observes14 SELECTs for two preparations:
two caller loads plus five exact indexed provider reads each, no write or query scan.

The temporary plan table deliberately omits PostgreSQL-only DDL constraints. IAM,
native source/terminal execution and control publication are synthetic in these new
metadata tests; they do not prove PostgreSQL constraints, a genuine completed QUERY
or live consumer activation. Existing artifact/receipt/materialization regressions
remain separate evidence. The sole warning is the existing TestClient deprecation.
Initial fixture errors retained in logs were missing native indexes, inconsistent
unavailable-view reasons and a nested Graph revision field. The actual schema was
not relaxed to accept them. The SQL-count expectation was corrected from16 to the
observed14, not by adding queries to satisfy the test.

Evidence prefix: `/tmp/eom-identity-provider-install.nAaycoDM/similarity-workflow-role-`;
`existing`, `focused`, `fixture-*`, `focused-final`, `acceptance`, `mypy-final`.
No production install, DB/grant/migration/schema, Artifact, native/ML/device operation
or historical selector/plan rewrite occurred. API transactional selector persistence,
admitted ordinary-runner owner composition and actual C2 item acceptance remain open.
The genuine QUERY operation retains its original authentication-input gate and
processes; its30-minute observation cadence is not replaced by these source tests.

Candidate `2d3c8b39c61ce41d147b5c1ad8e896d40e344e9c` passed the full three-wheel
build/RECORD gate and isolated owner-pair/explicit-three-wheel import probes. They
resolve the shared provider, original bounded provider and frozen selector handoff
from selected archives only. Pack/schema pins and actual packaged API/OpenAPI remain
consistent, with no checkout, installed-prefix, undeclared wheel or ML fallback.
The probes perform no current source/IAM/model operation and do not activate the adapter.

Initial package probes correctly refused the old six-field local preparation-result
expectation after adding `query_selection`. Their logs remain preserved. The exact
seven-field expectation was updated and both probes rerun against the same unmodified
candidate wheels, not weakened to accept arbitrary fields or changed runtime bytes.

Raw wheel SHA: platform `2e9afb696cd33d00e4bdf83066f5a66c169db9f5199c9a84c09793ee81164e95`;
contracts `57904cbb77d218b529417310b25378cec416e4adafa2db3e164a068426c4eea1`;
API `93391139e6edf911c18c83dd9485a7e93f16e0a4fdf94d2deeec5f62394d0d7d`.
Logs `release-build`, `owner-pair-proof-final`, `three-wheel-proof-final` share the
source evidence prefix above. This candidate is pushed, not installed/activated.

## 31. First item-start transaction and immutable private preparation acceptance

Design before change, 2026-10-14 UTC:

1. Boundary: extend the existing application command's trusted Python preparation
   handoff, not the public WorkflowStartRequest, router, worker or native authority.
2. Canonical source: actual authenticated actor, exact request, Catalog Evidence V5,
   released preset and bound Content Pack/definition in the existing transaction.
3. Identity: keep Workflow/plan/Artifact revisions distinct. Carry the preparation's
   actual operator plus its existing three-field QUERY selector; neither is a grant.
4. Checks: closed preparation values and actual actor/request first; exact Evidence,
   preset and full expected resolution before accepting a fresh Workflow. Pure plan23
   binding remains before the single original plan-record call.
5. Access: existing preflight/creation and indexed replay/active-equivalent lookups.
   No new search, DB/NAS read owner, native launch or latest fallback in the API.
6. Structures: existing runtime-context metadata stores `similarity_query` and one
   `similarity_preparation_v1_sha256`. No schema family, migration, cache or queue.
7. Cost: bounded pure value validation/hash and a shallow metadata-map update;
   no repeated file reads/rehashing, model computation or extra replay source query.
8. Transaction: on a fresh Workflow, plan23 + selector + accepted fingerprint + START
   enqueue commit together. Publication happened at its existing separate owner;
   a later transaction failure never means that publication was absent.
9. Ownership: the API application owns acceptance; the existing resolver owns plan
   recording; runner owns execution and current Catalog source/Identity staging.
   No domain-to-infrastructure import or new dependency is introduced.
10. Replay: no-preparation replays retain their original immediate receipt path.
    An explicitly supplied preparation must match its accepted selector/fingerprint.
    Active-equivalent work cannot acquire/replace context. Drift/conflicts fail;
    independent committed Artifacts and historical execution remain preserved.
11. Alternative: adding selector input to HTTP would expose internal orchestration;
    upgrading an already recorded plan19 violates immutable acceptance. Recomputing
    acceptance from mutable source/activation on replay breaks original receipt
    semantics, so persist the small original acceptance fingerprint instead.

The v1 fingerprint is canonical accepted input identity, not an authorization cache
or derived search score. It covers actual operator, request/Evidence/preset hashes,
full resolution, QUERY selector, delivery and context semantic hash under the frozen
purpose `ITEM_SIMILARITY_PREPARATION_V1`. Never change that algorithm in place for
existing history. No source bytes or full context are stored in Workflow metadata.
The optional trusted handoff remains disabled for public requests until the existing
owner/native preparation transport is actually composed/admitted. Source acceptance
of this transaction does not prove live end-to-end C2, native admission or deployment.

### 31.1 Application transaction/replay source checkpoint — 2026-10-14 UTC

The real `CommandAdapter.start_workflow` accepts an optional trusted Python-only
`PreparedItemSimilarity` and validates it before any Catalog action. Its normal
public route supplies no preparation: no HTTP field, worker behavior or activation
was added. Pure checks bind actual operator/request, exact publication/delivery,
selector, full resolution and transaction-selected Evidence/preset. The immutable
v1 fingerprint also includes the publication producer Job/manifest metadata.

For a fresh Workflow the existing resolver receives its checked context before
the one plan-record call, then the existing transaction saves plan23, selector,
fingerprint and START. A provisional Workflow insertion remains in that same root;
any resolution/plan/enqueue failure rolls it back. Existing same-key receipt reads
precede mutable controls and do not read source bytes. An explicit changed/private
preparation conflicts on both replay and existing-equivalent work; absent preparation
does not erase an original accepted context or upgrade a historical plan19.

Final27-file regression: **431 PASS /172.71s**, strict mypy3, Ruff/format5 and diff
checks PASS. Earlier existing43 and focused18 overlap the final gate, not additional
totals. New tests use actual public request validation/conversion, the actual command
adapter, repository Workflow/event/command creation, real temporary SQLite roots and
the existing real resolver with explicitly synthetic controls/final record owner.
Outer BEGIN is explicit for correct SQLite SAVEPOINT rollback assertions. The
temporary plan metadata table omits PostgreSQL-only constraints: this is NOT new
PostgreSQL plan23 persistence or actual Identity/source/native acceptance.

Cases cover exact/no-preparation replay without Catalog/control reads, original
binding on active equivalence, cross-operator/change conflicts, no plan19 upgrade,
pack/preset/Evidence drift, final enqueue rollback with prior context Artifact kept,
closed private value/public input rejection, source-withdrawn metadata receipts and
the exact deterministic fingerprint algorithm. No candidates/query payload is added
to Workflow metadata. Initial fixture failure lacked image/registration role policies;
the synthetic preset was completed rather than weakening the real four-role definition.
The sole warning remains the existing Starlette/httpx TestClient deprecation.

Evidence prefix: `/tmp/eom-identity-provider-install.nAaycoDM/similarity-start-binding-`;
`existing`, `focused`, `fixture-roles`, `acceptance`, `mypy-final`. No new production
DB/schema/grant, Artifact, native/model/GPU execution or installed runtime changed.
The original QUERY was observed again at22:33:40 UTC: same two live processes/pane,
still at its original Studio input gate, with no capture/model forward. No restart,
duplicate login prompt or command sent into that prompt occurred. Next observation
is at/after23:03:40 UTC. Real owner transport/automatic preparation, compatible
installation, C2 item acceptance, continuous coverage and device evaluation remain.

Candidate `7d426e2eec56c0f8d046f9c88db0fd9d44f1b8cd` passed full three-wheel/RECORD
inspection and independent isolated owner-pair/explicit-three-wheel probes. The owner
pair verifies the exact eight-field frozen handoff, including actual operator. The
three-wheel probe constructs the actual packaged app and checks its private command
parameter, separate public DTO, acceptance helper exports and complete unchanged
OpenAPI snapshot. All EOM imports resolve only from the selected archives; no checkout,
installed-prefix, undeclared wheel or ML fallback is allowed. No DB/current source,
HMAC capture, publication, model or runtime mutation is executed by these probes.
Focused21 PASS /11.81s after the identifier typing change overlaps the full431 gate.

Raw wheel SHA: platform `51bcbb00018b8fa158ac4f6cd0091ed827cbd65422cc56fe7051fc18d957ccaa`;
contracts `319283dc134753cde0996859b1db11c00996db7a5acfbcedfada9db59df4470f`;
API `6ea8c719122f45481b0e767b3e5ae2703e3273124b7ba7badfe8c34069add3b7`.
Logs `release-build`, `owner-pair-proof`, `three-wheel-proof` share the evidence
prefix above. The candidate is pushed, not installed/activated.
