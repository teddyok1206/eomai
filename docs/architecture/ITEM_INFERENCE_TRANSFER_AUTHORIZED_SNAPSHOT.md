# Inference-transfer authorized corpus snapshot

Status: **SOURCE_ONLY_BINDING**. The bounded snapshot contracts, Catalog owner
application/producer, fixed private-socket successor and authenticated API
composition are implemented in source, not installed or activated.
This document does not add a socket/API operation,
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
instead. V2/V3 inline formulas are not separately extracted as `FORMULA`
metadata, and the projection records this limitation. Inquiry `kind` (`탐구` or
`실험`) is preserved as exact `MATERIAL_FORM` metadata; it does not add section
caption prose to `CONTENT_ONLY`. Image-slot presence can support structural metadata, not invented
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
actual typed command hash and ordered exact source/profile mapping. The current
`SuppliedGraphBaseline.result_sha256` is the canonical hash of the **derived
baseline value** (query pointer, command hash, provenance and filtered ordered
profile pointers), not a hash of the raw official retrieval response and not an
Evidence Bundle verification receipt. The current contract does not store those
raw response bytes/receipt hashes; do not claim it proves their identity.
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

## Authenticated read connection — eleven decisions

This successor is **SOURCE_ONLY_BINDING**. The source implementation below does
not install or activate these endpoints, private peer permissions or staging.

1. **Responsibility/boundary.** Reuse the authenticated Application API and
   fixed private Catalog application socket. Add a dedicated read-only use case
   for the three snapshot phases, not a worker tool, shell `--actor` option or
   parallel socket service. A bounded API endpoint may accept the existing
   `InferenceTransferSnapshotRequest` discriminated phase directly. The proposed
   route is `/knowledge/inference-transfer/snapshot`; its exact route/operation
   identifier is a successor contract decision, not an installed fact.
2. **Canonical authority.** `get_authentication` supplies the current operator
   identity and session. API-side permission requirements reuse Item read,
   Graph retrieve, analysis read and (when needed) content-intake read. Catalog
   independently checks the current operator, policy role, answer-bearing
   permission, source lifecycle, exact Graph and occurrence membership. An
   authenticated API session alone does not waive Catalog policy.
3. **Identity/revisions.** Reuse the existing snapshot header/index/phase hashes;
   add no database entity, export job or persistent snapshot cache. The public
   request has no actor/role/permission fields. A small **private typed envelope**
   carries the API-derived operator ID plus the existing phase request. This
   envelope is not exposed as client-selectable authority. Header actor is
   server-captured audit/identity data and must equal the current authenticated
   operator in READ and AUTHORIZE.
4. **Resolution checks.** JSON Schema 2020-12 plus Pydantic validate the public
   phase and private envelope before dispatch; results pass both schema and
   contextual request/result checks. Installed Catalog captures the actual
   operator on every call, resolves the full source/report set and compares the
   exact frozen header before materializing selected Item members. Client hashes
   and `AUTHORIZED_CURRENT_READ` are not access credentials.
5. **Access patterns.** One PREPARE freezes an index; READ uses exact selected
   index entries, bounded ordered iteration and request-scoped maps; AUTHORIZE
   regenerates the full entry and official baseline sets. Replays reuse exact
   requests with fresh authentication. No raw Artifact/path endpoint is added.
6. **Structures/indexes.** Extend existing private operation dispatch/typed
   supported-client composition only. The fixed API UID may invoke this
   operation; the conversational chat-owner peer and worker UIDs may not.
   Preserve all prior peer operations. Reuse Catalog's indexed admission,
   occurrence EXISTS and accepted-report batches; no new index/migration follows
   merely from exposing the use case.
7. **Bounds/scale.** Preserve the existing **4 MiB private envelope** transport
   ceiling and enforce the snapshot body's/chunk's stricter **actual 3 MiB**
   encoded budget (including any lower caller-selected chunk limit). Wrapper
   fields do not consume the canonical snapshot body's budget. Do not
   concatenate the full corpus into one response. Canonical member reads have
   16 MiB/item, 128-member and 128 MiB/batch ceilings; project each returned batch
   immediately and discard raw bytes before reading the next. Request-scoped
   pointer maps deduplicate shared members. Derived views still obey their own
   bounds; large source data is never silently truncated.
8. **Transactions/concurrency.** Each owner call remains repeatable-read and
   read-only. There is no distributed transaction across API reads, staging and
   CPU execution. Frozen equality bridges reads; fresh final AUTHORIZE is
   required before any authorized result publication. Future staging is owned
   by existing Orchestrator local workspace/Artifact commit boundaries and does
   not grant API or worker writes to NAS.
9. **Dependency/ownership.** Public contracts depend on values only; API route
   calls its application service/private client; Catalog server composes the
   existing owner producer. Orchestrator consumes the supported client/owner
   port. CLI/harness remain local-input consumers. Do not import Catalog private
   helpers into API, Orchestrator or workers, and do not introduce a second DB
   credential or source-reader route.
10. **Failure/retry/idempotency.** Stable transport errors distinguish operation
    unavailable, forbidden/expired session, stale Graph/policy/profile/source,
    population drift, truncated scope and oversize chunk. The route is explicitly
    read-only; replay does not create rows, generate models or commit Artifacts.
    Unsupported mixed release sets fail unavailable. Final current-read approval
    is not cached as durable permission. Capture no cookies/secrets/full content
    in access logs or milestone reports.
11. **Simpler alternative.** An ordinary existing chat read would avoid a new
    private operation, but it cannot provide full canonical three-view content,
    the complete original denominator or final set/hash reauthorization. A
    checkout script with production credentials or user-selected actor would
    violate the existing authority boundary. The additive authenticated endpoint
    and existing fixed socket are the minimum connection; no separate export
    platform or general worker filesystem access is justified.

Before installing this successor, require authenticated API principal-injection
tests, forbidden public actor fields, fixed-peer negative tests (chat/worker),
request/result/frame bounds, current rights revocation, same-actor replay and
exact header/context closure. Installed wheel/RECORD and compatible API/Catalog
release identity must then be verified separately. No production canary, model
execution or export is authorized by this design subsection.

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
- Bounded snapshot values/binding: `inference_transfer_snapshot.py` and
  `inference_transfer_snapshot_binding.py` in Catalog contracts; source owner
  production/assembly: `inference_transfer_snapshot_catalog_adapter.py`,
  `inference_transfer_snapshot_service.py` and `inference_transfer_snapshot_dispatch.py`.
- Authenticated API successor: `routers/inference_transfer.py` and
  `services/inference_transfer_snapshot.py`, `inference_transfer_snapshot_port.py`,
  `inference_transfer_snapshot_client.py` in `apps/application_api/eom_api`.
- Owner materialization/staging: `services/orchestrator/eom_orchestrator/control_artifact_resolution.py`,
  `execution_materializer.py` and `worker.py`.
- Staged experiment: `packages/catalog_contracts/eom_catalog_contracts/inference_transfer_experiment.py`,
  `services/catalog_service/eom_catalog_service/inference_transfer_experiment.py`,
  `scripts/embedding/run_inference_transfer_experiment.py`, and
  [experiment design](ITEM_INFERENCE_TRANSFER_EXPERIMENT.md).
- Historical denominator evidence: `docs/status/M01_SOLUTION_REPORT_BACKFILL_2026-09-15.md`.

No operational source data, credentials, prompts, long logs or generated
experiment inputs/outputs are included in this document.
