# System RAG similarity context implementation boundary

Written: 2026-10-12 UTC. Inspected Git base: `550a239cac74b8255bf33467b78671b6d37f811f`.
Status: **DESIGN + CONTRACT-ONLY SOURCE CHECKPOINT; behavior NOT IMPLEMENTED / NOT ACTIVATED**.
The separately approved contract-only implementation is recorded in section 8. Source observations are not
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
