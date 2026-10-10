# Inference-transfer authorized corpus snapshot

Status: **DESIGN_ONLY**. This document does not add a socket/API operation,
install a release, authenticate an operator, export a production corpus, run a
model, or authorize a deployment. The staged experiment contract and local
harness exist in source; their provenance labels are not access credentials.

## Existing boundaries and the missing connection

The smallest extension belongs to Catalog's existing private read application
boundary, reached through an authenticated Application API principal. It is not
a worker tool, a checkout script with production database credentials, or a
parallel search engine.

| Boundary | Existing behavior | Reuse or limitation |
| --- | --- | --- |
| API authentication | `dependencies.get_authentication` authenticates the real operator/session; `require_permission` checks current permissions | Derive actor identity here, never from request/model fields |
| Private Catalog transport | `application_server` checks `SO_PEERCRED`, supported operations and a 4 MiB frame limit; clients check fixed socket/server identity | Add an explicit operation to installed compatible contracts; existing peers do not automatically gain new operations |
| Chat knowledge read/RAG | Exact selected Item and Graph/policy resolution, actor checks and bounded materialization | Small conversational contexts and report summaries are not full corpus export or full solution-report access |
| Candidate/source admission | `admit_read_only_candidate_pool` and `CatalogInferenceTransferSourceAdapter` derive current actor authority and exact source eligibility | Reuse the occurrence-backed scope and exact resolver; do not invent an export ACL |
| Accepted solution reports | `resolve_solution_evidence_by_base_run` validates accepted V10 successor/report/receipt chains in a batch | Reuse full typed reports, accepted timestamps and the one deterministic projector |
| Canonical Item | Approved source member points to exact Item JSON; `read_item_content` validates supported canonical schemas | Render an explicit no-solution view; do not use HTML preview, PDF OCR guesses, or chat excerpts |
| Owner materialization/staging | Bounded approved Artifact reads and owner-created local workspaces already exist | Owner stages the frozen request; worker/CPU harness receives local files, not NAS/DB authority |
| Experiment harness | `run_staged_inference_transfer_experiment` consumes a frozen local request; the CLI validates input bytes/hash/workspace | Neither harness nor `AUTHORIZED_CORPUS_SNAPSHOT` text authenticates current access |

Source locations are listed below. Runtime installation and activation of the
new extension are **NOT_VERIFIED** by this source investigation.

## Required design note — eleven decisions

1. **Responsibility and boundary.** Add one opt-in private read-operation family
   owned by Catalog, provisionally `INFERENCE_TRANSFER_SNAPSHOT`, with typed
   `PREPARE`, `READ` and `AUTHORIZE` requests. An authenticated API use case
   constructs the trusted private request using its actual principal. Public
   input selects exact Graph/policy pins, occurrence population, views, budget
   and query identities; it contains no actor, role, permission list, filesystem
   path or claimed authorization. A future authenticated maintenance client may
   call that use case; a local `--actor ADMIN` argument is not an equivalent
   boundary. JSON Schema 2020-12 and Pydantic precede behavior. Existing V2
   retrieval and chat wire contracts remain unchanged.

2. **Canonical source.** Published Graph associations, snapshot-local Item
   occurrence references, exact eligible approved Item source members and
   accepted V10 report Artifact chains remain authoritative. The original M01
   target was 520 occurrence-backed approved past-exam analyses; its trusted-RAG
   canary intentionally lacked that membership. The new snapshot recomputes the
   exact authorized occurrence set for the pinned Graph. It does not hardcode
   520 or infer current completion from a historical audit. Sources without an
   accepted report remain in the source population and explicit missing-report
   count, not silently removed from the denominator. No copied corpus becomes
   canonical.

3. **Logical entities and revisions.** Reuse the frozen experiment logical ID,
   revision ID, request hash, profile IDs/revisions/hashes, source revisions and
   model/view recipe pins. A prepared snapshot is a derived immutable value,
   not a new database aggregate, vector index, registry or mutable cache.
   A compact header contains the exact Graph/policy, population scope, source
   count/set hash, profile count/set hash, projection/view recipe pins and its
   own canonical hash. A bounded index identifies exact base runs and profile
   pointers for chunk selection. Its hash detects identity drift; it is not a
   bearer capability or permission proof. The existing experiment request is
   assembled only after all required chunks have been validated.

4. **Pointers and resolution checks.** `PREPARE` uses Catalog admission and
   accepted-report resolution to freeze exact eligible sources and regenerate
   deterministic profiles. `READ` reauthenticates the current actor, rechecks
   the same policy/Graph/population, and resolves the selected exact source,
   schema, media type, Artifact/member/hash, accepted report and profile
   equality. `AUTHORIZE` repeats full source/profile-set validation immediately
   before result publication/commit. Every phase compares its exact pins with
   the prepared header. A manifest marked `CATALOG_AUTHORIZED_SNAPSHOT`, a
   self-consistent profile hash, cached metadata or an `APPROVED` literal alone
   cannot authorize dereferencing. A different historical Item revision or
   Graph occurrence cannot satisfy membership. `CODEX_DERIVED` profiles remain
   unavailable until an accepted producer Artifact boundary exists.

5. **Primary access patterns.** Prepare a bounded immutable source set once;
   look up exact base-run/profile identities; deduplicate by immutable keys;
   iterate stable chunks; render three complete typed views; run the existing
   lexical Graph query per selected query; then reauthorize the complete set.
   No operation substitutes latest during replay. The authenticated session is
   checked per API call. Catalog independently checks current operator status,
   permissions, policy roles, source classes and answer-bearing access: profile
   claims can contain answers even when the content view excludes solutions.

6. **Data structures and indexes.** Reuse the pre-limit correlated occurrence
   `EXISTS`, exact-run indexes, distinct source grouping and batch solution
   resolution. Maps keyed by base run/profile pointer and sets for uniqueness
   prevent duplicate placements from creating duplicate profiles. Freeze a
   sorted tuple and hash of the complete admitted population. Transport chunks
   are bounded by entry count **and actual encoded frame bytes**, with no
   scientific text truncation. Full V3 source/page chains can be large; do not
   send the whole population in a single assumed-small frame. A compact index
   plus typed chunks carries the existing full source values where required.
   Chunk identity includes the same header hash and exact selected IDs. No new
   database index is justified before examining the reused query plan.

7. **Scale, cost and bounds.** The existing 1,024-source bound covers the
   historical pilot. Require `truncated=False` for a full-population F6 claim;
   a bounded subset is a separately named experiment, not “the 520 corpus.”
   Proposed transport maximum is 64 entries per chunk under the existing
   4 MiB frame limit; oversize entries fail explicitly, rather than dropping
   conditions or final negations. Existing owner Artifact reads support batches
   of up to 128 members; materialize bounded chunks and avoid per-item SQL.
   In-memory maps and staged input are O(N); exact embedding comparison cost
   is already budgeted by the experiment contract. Reconstructing admission on
   each read may cost O(C × N) owner checks for C chunks. At this bounded pilot
   scale that is a simpler, honest baseline than adding a persistent snapshot
   cache; no latency improvement is claimed without a benchmark.

8. **Transactions, concurrency and publication.** Each Catalog phase uses a
   read-only repeatable-read transaction. That does not make several HTTP calls
   one transaction: equality of frozen set/profile hashes bridges calls, and
   final full reauthorization rejects revocation or drift. Owner staging is an
   explicit local materialization boundary using fixed private workspace rules,
   bounded reads, file-descriptor identity, no symlinks and canonical SHA checks.
   The harness writes local results only. Result publication is separate and
   uses the existing Orchestrator validated Artifact commit owner; it is not
   authorized by running the CLI or by this design. A permission change during
   model execution prevents final publication. Historical accepted evidence is
   not edited to make an experiment pass.

9. **Dependency direction and adapter ownership.** Frozen snapshot wire/value
   contracts import no SQL/filesystem packages. Catalog owns actual identity,
   Graph/policy/source/report checks and the pure canonical-question renderer.
   API owns session authentication and passes trusted principal context to its
   private Catalog client. Orchestrator owns staging, experiment scheduling and
   validated result commit; it consumes injected public owner ports, not
   Catalog private helpers. The local harness remains removable and cannot
   access production PostgreSQL/NAS. No new dependency or external model API is
   required. Enabling an installed API/private socket operation and selecting a
   compatible release are explicit later gates, not effects of documentation.

10. **Failure, retry and idempotency.** Missing authorization/runtime operation,
    revoked access, population drift, stale source/report/profile pins, hash or
    schema mismatch, unsupported content, oversized frames and missing reports
    have distinct stable outcomes. Reads replay the same pins with fresh access
    checks. Expired sessions require reauthentication; they do not justify
    switching to an administrator actor. Partial local chunks are not an
    accepted complete snapshot. Input/output hashes and existing immutable
    experiment identities prevent timeout replay from being mistaken for a
    new run. An empty official Graph result differs from a baseline that was
    never materialized. No direct database correction or implicit retry with
    broader source classes is allowed.

11. **Simpler alternatives and why they fail.** Existing chat context is
    smaller but contains excerpts/summaries and does not freeze the original
    population or complete three views. Downloading files manually or running
    source code with an arbitrary actor bypasses installed authority and cannot
    establish F6 acceptance. Trusting a staged request's authorization label
    avoids owner checks but permits invented source/profile values. A new
    export database, search engine, generic jobs framework or signed-capability
    system would be larger than needed. The additive authenticated read family,
    frozen hashes, bounded chunks and existing owner staging close the actual
    gap without those alternatives.

## Three-view production rules

The producer reuses `ExperimentViewRecipe` and the existing staged request;
it must not silently change the recipe's meaning.

| View | Allowed source/projection | Required exclusions or limitations |
| --- | --- | --- |
| `CONTENT` | Complete candidate-visible canonical question text, in authored order; native tables, statements, choices, inquiry and inline equations | Exclude all answer/solution/explanation containers, internal IDs, hashes, paths, prompt/handoff data and non-question scores. No PDF/image pixel claim from text-only access |
| `CONCRETE_FACETS` | Exact deterministic profile claim text and facet labels, preserving units, conditions, negation and outcomes | This existing recipe can contain judged conclusions/misconceptions; do not call it answer-free or a human-confirmed decisive insight |
| `METADATA` | Sorted allowlisted fields with values demonstrably extracted from exact canonical Item or accepted report bytes | Registry `metadata_json`, Graph labels and model guesses are not automatically bound to either permitted basis hash. Omit unsupported fields with explicit limitations; do not relabel their provenance |

For canonical V1 include the ordered `body` and candidate-facing `interaction`;
omit `solution`. For canonical V2/V3 include `stem`, `bottom_stem`, inquiry,
labeled block contents, ordered native table contents/visual captions where
available, statements and choices; omit `answer` and `explanations`. The
aggregate `equation_sources` field is not blindly included because it can mix
question and explanation equations; preserve the inline question equations
instead. Image-slot presence can support structural metadata, not invented
descriptions of the pixels. Unsupported original Item content schema is an
explicit unavailable view, not permission to fall back to the answer-inclusive
chat representation.

The source Item member SHA, Item revision manifest SHA, accepted report SHA,
profile SHA and rendered text SHA are different values. `read_item_content`
validates the Item JSON after exact owner materialization. `CanonicalExperimentItemText`
then pins that original member and the separate complete rendered text hash.
Content-member schema/media identity must actually be a supported canonical Item
JSON before rendering; not every arbitrary source member is assumed to be one.

## Official lexical Graph baseline

Use the existing owner `topic_keys_for_terms` and `retrieve_read_only` with the
same exact Graph/policy and actual actor authority. The query term recipe is a
versioned bounded deterministic selection from authorized candidate-visible
question text/available metadata, not a model's claimed Graph IDs. Record the
actual typed command hash, result hash and ordered exact source/profile mapping.
Filter the resulting sources into the frozen authorized profile set; do not
invent Graph placement or reinterpret cosine as Graph relevance.

Do **not** set `target_item_revision_id` to the query Item for this baseline.
The existing 1:1 retrieval path filters its results to that exact Item and would
therefore become self-only after query exclusion. Comparative retrieval uses
`target=None` plus real resolved topic keys. The existing official retrieval
budget/ranking may return out-of-population or report-missing sources; after
filtering there may be fewer comparison candidates. Record that limitation
without rewriting released ranking, widening access policy or claiming an
unmaterialized baseline is empty.

## Minimal implementation and activation gates

1. Define the additive snapshot operation schemas, compact header/index/chunk
   and stable failures; reuse current experiment/profile/source contracts.
2. Implement Catalog owner preparation/read/full authorization and a pure
   no-solution renderer/metadata extractor, with mocked official owner ports.
3. Add the private Catalog client/server dispatch and explicit peer operation
   allowlist; bind an authenticated API maintenance use case to the actual
   principal. No public worker-supplied actor/authority fields.
4. Compose existing Orchestrator owner staging with the local harness; validate
   the frozen request and result, and reauthorize before any authorized commit.
5. Run focused source tests and guarded disposable PostgreSQL membership/query
   tests, packaging/installed-identity and negative transport/RBAC checks.
6. Separately approve compatible installation/activation and bounded authenticated
   production snapshot preparation. Until then, real-corpus F6 remains
   `AUTHORIZED_SNAPSHOT_NOT_AVAILABLE`; synthetic/offline prototype results
   cannot close that gate.

Required tests include actual principal injection and forbidden model roles;
unsupported peers/operations; policy/source class/answer-bearing denial;
exact occurrence membership before limits; canary exclusion; duplicate
placement immunity; missing-report population preservation; full-set/profile
hash mismatch; chunk replay with frozen Graph and no latest fallback; revoked
non-selected sources at final authorization; canonical V1/V2/V3 question-only
rendering and answer-leak negatives; native table/units/negation preservation;
metadata field origin; unsupported schema/oversize rejection; exact official
baseline mapping; safe local staging; and no worker direct NAS/DB dependency.

## Source reference map

- API principal: `apps/application_api/eom_api/dependencies.py` and
  `routers/general_chat.py`.
- Trusted private binding: `services/orchestrator/eom_orchestrator/general_chat_knowledge.py`,
  `services/catalog_service/eom_catalog_service/application_server.py`,
  `packages/catalog_contracts/eom_catalog_contracts/application.py`.
- Current conversational resolution: `chat_knowledge_resolution.py` and
  `chat_rag_resolution.py` in Catalog.
- Exact occurrence admission/profile replay: `inference_transfer_catalog_adapter.py`,
  `knowledge_retrieval_service.py`, `solution_evidence_resolution.py`, and
  [candidate population scope](ITEM_INFERENCE_TRANSFER_CORPUS_SCOPE.md).
- Canonical validation/render inputs: `item_content_contract.py`,
  `packages/catalog_contracts/eom_catalog_contracts/assessment_item.py`,
  `packages/hwpx_contracts/eom_hwpx_contracts/models.py`.
- Owner materialization/staging: `services/orchestrator/eom_orchestrator/control_artifact_resolution.py`,
  `execution_materializer.py` and `worker.py`.
- Staged experiment: `packages/catalog_contracts/eom_catalog_contracts/inference_transfer_experiment.py`,
  `services/catalog_service/eom_catalog_service/inference_transfer_experiment.py`,
  `scripts/embedding/run_inference_transfer_experiment.py`, and
  [experiment design](ITEM_INFERENCE_TRANSFER_EXPERIMENT.md).
- Historical denominator evidence: `docs/status/M01_SOLUTION_REPORT_BACKFILL_2026-09-15.md`.

No operational source data, credentials, prompts, long logs or generated
experiment inputs/outputs are included in this document.
