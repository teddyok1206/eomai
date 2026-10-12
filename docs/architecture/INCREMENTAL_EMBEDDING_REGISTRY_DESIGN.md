# Incremental embedding Catalog registry

Date: 2026-10-12 UTC. Status: **design proposal; no migration, admission, runtime,
or service authority is activated by this document**.

This is the concrete next persistence boundary for
[the integrated design](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md),
[the native execution boundary](INCREMENTAL_EMBEDDING_EXECUTION_BOUNDARY.md), and
[the implemented Artifact boundary](INCREMENTAL_EMBEDDING_ARTIFACT_BOUNDARY.md).
The source-only contracts/codec/delta planner/Artifact store are implementation
inputs, not evidence of installed indexing support. New names below are proposals.

## 1. Responsibility, canonical source, and current evidence

Catalog owns source eligibility, exact source/report/profile resolution, immutable
registered associations, and index selection. WorkflowRunner owns durable work,
commands and leases. Orchestrator owns protected execution, validation and Artifact
commit. The encoder receives staged local input and submits local output only.
No worker queries PostgreSQL, commits NAS, or talks to another worker.

The existing canonical discovery boundary is a committed
`KnowledgeGraphPublicationRecord` in `knowledge_graph_publications`, joined to
`KnowledgeSnapshotAnalysisRecord` in `knowledge_snapshot_analyses`. Publication
inserts membership and advances `knowledge_corpora` in one Catalog transaction.
`KnowledgeGraphPublicationService` locks the corpus and checks the
expected current snapshot after Artifact publication. Do not replace this with
upload timestamps, Item approval events, or uncommitted analysis output.

The actual source admission boundary is
`KnowledgeRetrievalApplicationService.admit_read_only_candidate_pool()`, composed
by `CatalogInferenceTransferSourceAdapter`. It checks Graph/policy pins, source
classes, lifecycle, accepted base analysis, answer-bearing access and, where
requested, exact past-exam occurrence membership. Its current bounded limit is
1,024 analyses and it returns `truncated`; it is not an unbounded pagination API.
The source adapter resolves accepted additive V10 reports through
`resolve_solution_evidence_by_base_run()`. The existing partial unique index
`uq_knowledge_analysis_accepted_solution_predecessor` protects one accepted V10
successor per base run. This is a report uniqueness rule, not an encoding claim.

Canonical numerical bytes are the committed `vectors.f32` member; canonical row
identity is its same-file-set `shard.json`. `EmbeddingArtifactStore` currently
publishes `result.json`, `shard.json`, and `vectors.f32` through
`ControlFileSetPublisher`. The accepted Item/report and Graph remain canonical
sources. A profile is deterministically rebuilt by the official projection;
there is **no existing persistent profile table to reference with a fake FK**.

The four new Catalog tables below are immutable registration/provenance metadata
and the canonical mutable index selection. Their indexed scalar projections must
equal validated Artifact/source contracts. They do not become independent copies
of Item content, report text, model weights, or vector arrays. The vector/index is
a reproducible derived search artifact, not the canonical Item or an access cache.
No new mutable eligibility cache, encoder-space registry, queue, or broker is needed.

## 2. Identities and resolution rules

Use the existing frozen contracts and canonical SHA-256 calculation:

- `EmbeddingEncodingIdentity`: `storage_partition`, `space_sha256`,
  `input_text_sha256`, and `encoding_sha256`. The digest is not a logical Item ID.
- `EmbeddingSourceBinding`: exact source, profile, additive solution evidence,
  Graph snapshot, access policy, projection/view recipe, encoding and row pointer.
- `EmbeddingIndexManifest`: logical `index_id`, immutable `index_revision_id`,
  predecessor manifest, namespace, ordered bindings/shards and `index_sha256`.

`EmbeddingSpace` is a small immutable value with its own fingerprint, not an entity
requiring another table. Its Artifact provenance pins model/tokenizer/pooling/
prefix/dimension/normalization/overflow and CPU/CUDA runtime/precision. Never mix
same-dimension vectors from different spaces. `storage_partition` is an enforced
isolation scope derived by the owner, not a user-chosen deduplication shortcut.

Every Artifact member group below means separate scalar columns
`<prefix>_artifact_id varchar(41)`, `<prefix>_artifact_revision_id varchar(36)`,
`<prefix>_member_path varchar(512)`, `<prefix>_schema_ref varchar(256)`,
`<prefix>_media_type varchar(128)`, and `<prefix>_sha256 varchar(71)`.
The pair has a composite `ON DELETE RESTRICT` FK to
`artifact_revisions(logical_artifact_id, revision_id)`, which already has
`uq_artifact_revision_identity`. This proves artifact/revision pairing, **not**
member existence or hash correctness. Member resolution must additionally check
approved Artifact/revision, outer manifest identity/hash, member descriptor,
schema/version, media, bounded size, raw bytes/hash and current permission.
No member table currently exists; do not pretend a member-path FK is available.
NAS paths are obtained only through the owner resolver, not stored as identity here.

All digest columns use `CHECK value ~ '^sha256:[0-9a-f]{64}$'`; all timestamps are
`timestamptz` written in UTC. Foreign keys below use `RESTRICT`, not cascade deletion
of historical provenance. New rows have no pending/running/failed state.

## 3. Exact smallest Catalog tables

### 3.1 `embedding_encodings` — one committed numerical row per encoding key

| Column | Type / invariant |
|---|---|
| `encoding_sha256` | `varchar(71)` PK; exact frozen identity digest |
| `storage_partition` | `varchar(64)`; existing partition pattern |
| `space_sha256`, `input_text_sha256` | `varchar(71)` |
| `shard_*` | Artifact member group; `shard.json`, `embedding-vector-shard/1.0`, JSON |
| `row_index` | integer; `0 <= row_index < 1024` for shard 1.0 |
| `registered_at` | UTC `timestamptz` |

Add `uq_embedding_encoding_input(storage_partition, space_sha256,
input_text_sha256)` and `uq_embedding_encoding_row(shard_artifact_revision_id,
shard_member_path, row_index)`. The first is the numerical deduplication boundary;
the second prevents two keys claiming a single row. PK/uniques are B-tree indexes;
the input unique already supports partition/space ordered membership, so do not
add a redundant separate space index. Add B-tree
`ix_embedding_encoding_shard(shard_artifact_id, shard_artifact_revision_id)` for
artifact-reference/audit lookup. There is no `binary`, `vector`, text or report column.

Registration resolves `shard_*`, obtains its same-file-set binary descriptor, and
checks its raw SHA/size/shape/finite/unit norm through the existing codec. The row's
identity must match the reconstructed key and row index exactly. Binary descriptor,
dimension and space values are read from the immutable shard rather than duplicated
in every DB row. Repeated key with the exact same pointer is replay; a different
pointer is an explicit registration conflict, not a pointer update. A concurrent
loser's extra Artifact is retained as an unreferenced derived Artifact for audited
reconciliation; it does not replace the chosen canonical row.

### 3.2 `embedding_source_bindings` — exact association, not a second Item

| Column | Type / invariant |
|---|---|
| `binding_sha256` | `varchar(71)` PK; existing complete binding digest |
| `encoding_sha256` | FK to `embedding_encodings.encoding_sha256` |
| `item_id`, `item_revision_id` | `varchar(37)`, `varchar(40)`; composite FK to existing `item_revisions(item_id, item_revision_id)` |
| `source_class` | `varchar(16)` CHECK `PAST_EXAM` / `APPROVED_ITEM` |
| `source_sha256` | exact original Item member hash |
| `base_analysis_run_id`, `solution_analysis_run_id` | `varchar(44)` FKs to `knowledge_analysis_runs.analysis_run_id`; distinct |
| `solution_pointer_sha256` | exact `KnowledgeSolutionEvidencePointer.pointer_sha256` |
| `profile_id`, `profile_revision_id`, `profile_sha256` | `varchar(49)`, `varchar(52)`, `varchar(71)`; existing profile patterns, no invented FK |
| `graph_snapshot_revision_id` | `varchar(41)` FK to `knowledge_graph_snapshots` |
| `policy_revision_id`, `policy_sha256` | `varchar(42)` FK to `education_retrieval_access_policy_revisions`, exact policy hash |
| `view` | `varchar(16)` CHECK existing three `ExperimentView` values |
| `recipe_sha256` | frozen `ExperimentViewRecipe` hash |
| `projection_version` | `varchar(64)`; exact `accepted-solution-comparison/1.0` in first release |
| `binding_manifest_*` | member pointer containing canonical binding; locator rules below |
| `registered_at` | UTC `timestamptz` |

`binding_manifest_*` initially refers to committed `index.json` with
`embedding-index-manifest/1.0`. Locate the one binding by `binding_sha256`, then
verify all flattened columns against it; it must also match the unique source
revision entry. This is not a JSONPath supplied by the model. Thus the full source
variant (including an `ApprovedPastExamItemKnowledgeSourceV3` evidence chain),
source/member schema and hash, report/receipt/accepted-result pointers, recipe and
Graph manifest pointer live once at an explicit canonical Artifact boundary.
The row does not copy their nested payloads. A later binding-page contract changes
the allowed `binding_manifest_*` schema/member family explicitly (§7); it never
silently reinterprets an old member.

The Artifact is committed before this registration; no FK to an index revision row
is necessary, so there is no circular registration dependency. Catalog validates
the full DTO through `validate_embedding_source_binding()` after official source
resolution. `binding_sha256` identifies this immutable value, not a new logical
entity. The profile pointer is rebuilt and checked, never resolved to latest.

Add B-tree unique `uq_embedding_binding_association(item_revision_id,
graph_snapshot_revision_id, policy_revision_id, recipe_sha256, view,
projection_version, base_analysis_run_id, profile_revision_id, solution_analysis_run_id,
encoding_sha256)`. This is the exact committed association uniqueness rule.
Hash equality and every scalar pointer must agree on replay. Add B-tree
`ix_embedding_binding_delta(graph_snapshot_revision_id, policy_revision_id,
recipe_sha256, view, projection_version, item_revision_id, base_analysis_run_id,
solution_analysis_run_id)` for missing-binding
membership lookup, `ix_embedding_binding_encoding(encoding_sha256)` for reverse
references, and `ix_embedding_binding_source(item_id, item_revision_id)` for
source history/revocation queries. No GIN index is needed: queries use scalar keys,
not arbitrary JSON containment. There is no mutable `eligible` flag.

### 3.3 `embedding_indexes` — logical index head

| Column | Type / invariant |
|---|---|
| `index_id` | `varchar(47)` PK; `embeddingindex_` identity |
| `corpus_id` | `varchar(39)` FK to `knowledge_corpora` |
| `storage_partition`, `space_sha256` | `varchar(64)`, `varchar(71)` |
| `view`, `recipe_sha256`, `projection_version` | same scalar pins as binding |
| `population_scope` | `varchar(64)`; released `InferenceTransferPopulationScope` value |
| `current_index_revision_id` | nullable `varchar(50)`; composite current FK below |
| `lock_version` | integer CHECK `>= 1` |
| `created_at`, `updated_at` | UTC `timestamptz` |

Unique B-tree namespace `uq_embedding_index_namespace(corpus_id,
storage_partition, space_sha256, view, recipe_sha256, projection_version,
population_scope)` ensures one head per released selection scope. Corpus/space/view
are not merged by human display name. The current pointer and lock version are
canonical mutable selection; they are not an authorization cache. Access policy
pins belong to immutable revision/association provenance, allowing an explicitly
validated policy successor to advance the same head without rewriting history.
Add a composite FK `(index_id, current_index_revision_id)` to
`embedding_index_revisions(index_id, index_revision_id)` using the existing
head/revision late-FK migration pattern. No standalone current revision FK that
permits a different index's revision is sufficient.

### 3.4 `embedding_index_revisions` — admitted immutable snapshot

| Column | Type / invariant |
|---|---|
| `index_revision_id` | `varchar(50)` PK; `embeddingindexrev_` identity |
| `index_id` | FK to `embedding_indexes.index_id` |
| `revision_number` | integer CHECK `>= 1` |
| `previous_index_revision_id` | nullable; composite `(index_id, previous_index_revision_id)` FK to this table; not self |
| `graph_snapshot_revision_id` | FK to `knowledge_graph_snapshots` |
| `policy_revision_id`, `policy_sha256` | FK to released access policy, exact hash |
| `manifest_*` | immutable `index.json` member group; 1.0 or explicitly released successor |
| `index_sha256` | semantic `EmbeddingIndexManifest.index_sha256`; distinct from member raw SHA |
| `source_set_sha256`, `binding_set_sha256` | canonical sorted exact admitted source pointers / exact ordered binding digests |
| `eligible_source_count`, `binding_count` | nonnegative bigint; available-view coverage denominator/numerator |
| `operation_key`, `registration_request_sha256` | `varchar(128)`, `varchar(71)`; exact registration replay |
| `created_at` | UTC `timestamptz` |

Add B-tree uniques `uq_embedding_index_revision_number(index_id, revision_number)`,
`uq_embedding_index_revision_identity(index_id, index_revision_id)`,
`uq_embedding_index_registration(operation_key)`, and
`uq_embedding_index_manifest(manifest_artifact_id, manifest_artifact_revision_id,
manifest_member_path)`. Add B-tree `ix_embedding_index_revision_graph(
graph_snapshot_revision_id, index_id, revision_number)` for publication coverage.
No separate `(index_id, revision_number)` lookup index duplicates its unique index.
The source/binding set hashes and counts are immutable projections/cache checks of
validated canonical membership, not alternative source truth or permission proof.

The current 1.0 Artifact has at least one binding. A zero-eligible-source transition
must not preserve a misleading stale usable head or fabricate a 1.0 empty manifest:
return explicit no-coverage/unavailable and require the empty-snapshot successor
in §7 before publishing an empty current revision. Query-time reauthorization
already excludes revoked members independently of this publication delay.

## 4. Missing-binding discovery and Graph-only changes

The public Catalog indexing query must be a successor of the official candidate
admission, not SQL exposed to workers. Its owner captures actual principal, exact
Graph/policy/recipe/space/partition/population pins, resolves an ordered bounded
page and returns typed source/profile/available-view references and coverage.
No fabricated query Item is needed. Reuse the existing no-query
`InferenceTransferCorpusReadCommand` concept, but do not claim its current
operator-only `_scope()` or bounded pool implements background paging.

The relational first-stage anti-join is `NOT EXISTS` against
`embedding_source_bindings` for each admitted `item_revision_id` and selected base
analysis/V10 solution-run identity plus exact Graph/policy/view/recipe/projection
pins. Join the accepted V10 successor before that membership test; a binding for
another base analysis of the same Item must not suppress newly available evidence.
A second bounded resolution rebuilds the profile and exact view text, then probes
the complete association unique and `embedding_encodings` by encoding key. Any
coarse lookup lacking the exact selected report/profile closure is only a hint,
never grounds for declaring coverage complete. All source classes,
lifecycle, occurrence and answer-bearing filters apply **before** paging/limits.
Use a map of profiles by base run and a set/map of encoding keys; do not issue one
query per Item or repeatedly scan the existing binding list.

An anti-join hit is not automatically model work. It produces one of: unavailable
view/report/overflow coverage, new association using an existing encoding, an
existing durable encoding reservation, or truly new numerical work. Counts for
eligible sources, available views, bindings, encoded keys and reused keys stay
separate. Missing report remains `WAITING_FOR_SOLUTION_REPORT` proposal coverage,
not a successful CONTENT-only vector or a failed original learning transaction.

A Graph successor changes profile/binding hashes even for unchanged numerical
input. Reauthorize the new Graph/source/report closure and create the new binding;
lookup `(storage_partition, space_sha256, input_text_sha256)` reuses the committed
row. Do not copy `vectors.f32` or resubmit the encoder. Policy changes likewise
require current authorization and new association provenance. If exact source,
report or view text changes, compute only missing new encoding keys.

Existing `uq_knowledge_snapshot_analysis(graph_snapshot_revision_id,
analysis_run_id)` supports snapshot-ordered keyset membership and
`ix_knowledge_snapshot_source_revision(source_kind, source_revision_id)` supports
source history. Do not invent a snapshot/source-revision unique constraint:
multiple accepted analyses can exist and official resolution must define the
selected source occurrence. The new query plan must demonstrate indexed
anti-join and bounded batch resolution at synthetic scale. Add a composite
membership index only if `EXPLAIN` proves existing indexes are insufficient.
Timestamp cursors/notifications are hints; repeated exact missing-association
queries are completion evidence. Same timestamps and late commits cannot be
discarded by a watermark.

## 5. Per-encoding reservation through existing owners

A unique **batch** input hash does not prevent duplicated computation for batches
`[a,b]` and `[b,c]`. Catalog's committed-only unique key is too late to prevent both
workers computing `b`. No pending row or lock lease is added to Catalog.

The required native Orchestrator successor uses existing `jobs.idempotency_key`
to reserve **each** encoding: `embedding-encode:` plus its 64-character digest.
Introduce one exact internal structured task/protocol for this purpose, not a
general job/plugin registry. Its immutable computational request contains the
encoding identity and full matching space pin; source/Graph/batch-specific audit
context is recorded as validated attachment/claim events, not mixed into this
deduplication request hash. A changed source's authority never follows from the
reservation. Each attaching Workflow reauthorizes its own exact input and binds
its own provenance separately.

In particular, current `IncrementalEmbeddingInput/1.0` pins a **launch** `job_id`,
ordered rows and `input_set_sha256`, and its `request_sha256` hashes that complete
batch. Do not use that batch hash/Job ID as the per-encoding computational request
or put a source grant into it. The reservation request and the launch request are
different closed typed contracts; launch ownership records tie them together.
Neither proposed reserve/attach/complete/result-read public application port is
currently implemented or admitted. `submit_structured_job()` is a storage
primitive, not authority to call it with an arbitrary native task.

The owner batch sequence is:

1. Recheck committed encoding keys, sort/deduplicate missing keys, reserve each
   through the Orchestrator public application port. `submit_structured_job()`
   supplies the existing unique key, but its current pre-read/insert implementation
   needs a savepoint/unique-race reread and exact conflict check in the new use case.
2. Lock acquired Job rows in sorted key order, attach each previously unowned key
   to one immutable Workflow/step/attempt launch identity in a typed Job event,
   and transition through the existing Job states. Losers receive owner/status
   pointers and reconcile; they do not launch the shared key. Reserve and owner
   attachment are one owner transaction. The Workflow command remains the queue;
   these Jobs are not separately polled by a new scheduler.
3. Commit that transaction before encoding. The bounded launch input contains
   only keys owned by this launch. If an overlap leaves no owned keys, wait for
   the existing owner receipt and perform association-only registration.
4. Validate/commit the numerical file set once. Complete each owned reservation
   with the exact shared Artifact row pointer in a bounded typed Job event. A
   shared shard is referenced by many reservations; it is never copied per Job.

These reservation Jobs do not claim to each publish a separate Artifact. The
current `JobRecord` requires allocated `logical_artifact_id`/`revision_id`; those
remain unused reserved IDs for this explicitly defined purpose and are never
rewritten to the shared publisher's IDs. The actual publisher Job owns the one
canonical shard. Current ORM relations do not enforce one Artifact for every
successful Job, but a native pointer-result completion/read contract and tests
are still required; this is not permission to reinterpret existing Job purposes.
If that scoped purpose is rejected, the safe smaller fallback is singleton
per-key native launches, with measured cold-load cost—not batch-only deduplication.

The durable owner event is authoritative for launch attachment; Job row locks and
the existing Workflow command lease generation/token fence arbitrate completion.
Source eligibility must be rechecked before launch and Artifact registration.
No SQL transaction stays open while the model runs. Lease expiry, process death or
timeout are **not** proof that computation did not occur. Reconcile the original
Workflow/attempt/protected O_EXCL workspace and publication key before any retry.
Known output is validated and recommitted/re-registered without inference.
Uncertain work stays explicit until supported recovery determines its outcome.
Terminal failed/cancelled Jobs are not reset or hidden behind a different key;
a retry requires a typed successor/recovery authorization linked to the original
reservation. The first release may block terminal retry rather than invent it.

Existing `create_workflow_instance()` accepts legacy/transfer request types and
derives agent-role protocols; it does **not** currently admit this native request.
`workflow_instances.ck_workflow_instances_stage` also lacks `LOCAL_EMBEDDING`.
The new native admission/storage/helper/executor and stage migration are separate
prerequisites. `workflow_step_runs.step_type` has no enum CHECK to expand. Preserve
existing command enum, FIFO/claim index, attempt unique, lease token/generation
fence and state transition tables. No Codex slot or fake worker role is assigned.

## 6. Commit, registration, CAS, replay and failure

The Graph publication transaction finishes first. Orchestrator commits vector and
index Artifacts; Catalog then registers validated metadata. There is no distributed
SQL/NAS atomic transaction. A committed vector alone is reusable output, not proof
of Catalog binding/index admission.

Catalog registration takes a closed schema-first command with exact operation
key/request hash, Artifact receipt/member pointers, expected current index
revision and expected `lock_version`. It resolves the source/report/Graph/policy
again under current authority, resolves all committed shards once, and validates
binding/index closure and namespace. The root's logical/revision IDs must match
the requested head/revision, every binding must match the registration's one
Graph and policy pin, and the graph's corpus must match the head's `corpus_id`.
These are admission rules to test explicitly: current manifest 1.0's pure
namespace validator alone does not enforce homogeneous Graph/policy bindings.
One Catalog transaction inserts missing
encoding rows, binding rows and index revision, then performs:

```sql
UPDATE embedding_indexes
SET current_index_revision_id = :new_revision,
    lock_version = lock_version + 1, updated_at = :utc_now
WHERE index_id = :index_id AND lock_version = :expected_version
  AND current_index_revision_id IS NOT DISTINCT FROM :expected_revision;
```

Exactly one updated row is required. Use the namespace unique for concurrent first
head creation and reread on conflict. A CAS miss rolls back that registration
transaction and returns `EMBEDDING_INDEX_STALE_CURRENT`; do not overwrite, mutate
the immutable predecessor, or pretend the unselected Artifact became current.
The reconciler builds an explicit successor against the now-current predecessor,
reusing committed numerical rows. No unnecessary model rerun is involved.

Replay checks `operation_key` first: same request hash plus exact pointers returns
the original registered revision and reports whether it is still current;
different hash is `EMBEDDING_REGISTRATION_CONFLICT`. It must not advance the head
back to an old revision. The returned prior/new revision, version, operation key
and state are typed values. `index_sha256`, member raw SHA and outer Artifact
manifest SHA stay separate. Preserve original publication UTC/source-commit pins
for publisher replay; a new timestamp is not the same immutable request.

Artifact commit followed by DB failure is reconciled from the same Job/publication
receipt and operation key. Registration rereads and reauthorizes those exact
pointers, never substitutes latest or reencodes. A revoked source at this point
prevents registration; preserve the committed derived Artifact and failed/audited
history without exposing it in current retrieval. Missing/stale pointers, wrong
schema/media, hash drift, conflicting key and unavailable authority are distinct
stable errors, not CPU fallback or infinite retries.

## 7. The 1,024-binding cap and required growth successor

`EmbeddingVectorShardManifest/1.0` and native input/result batches are at most
1,024 rows; binary is at most 16 MiB and dimension 4,096. Keep those bounded
numerical contracts. `EmbeddingIndexManifest/1.0` separately caps **bindings and
shards at 1,024**, sorts unique source revisions, and supports one view per index.
It cannot represent a 1,025-source index. The old 520-source experiment is not a
future corpus bound. `truncated=true` must never be called complete coverage.

Before a corpus exceeds 1,024 eligible source revisions per view, release a
schema-first `embedding-binding-page/1.0` and
`embedding-index-manifest/1.1` successor, with frozen models and registered schema
URIs. The page contains at most 1,024 ordered complete binding DTOs plus namespace,
source-key range, count and semantic digest. The root contains exact ordered page
member pointers, disjoint ascending key ranges, total counts/set hashes, exact
space/recipe, Graph/policy pins and predecessor pointer. The DB binding locator
can then point to the page, while the same four tables remain sufficient.

Commit each immutable page through the existing publisher, then a small root
Artifact references those page Artifacts and the existing shards; avoid one file
set that exceeds `MAX_FILE_SET_MEMBERS=1024`. Root validation streams pages,
checks global source uniqueness/order and complete count/hash closure; independent
page PASS is insufficient. Unchanged page/shard members can be referenced without
copying bytes. A changed Graph alters binding provenance and may require new
binding pages, but never requires recopying/reencoding unchanged vectors.

The first successor must state a finite page/root bound (proposed 1,024 pages,
therefore 1,048,576 bindings) and explicit byte budgets. It must not claim unlimited
scale. A larger corpus requires a separately released root-of-roots successor or
explicit partitioned indexes; return a limit error rather than truncate. Empty
roots with zero pages/count and deterministic empty hashes are supported only by
the successor. Predecessor parsing dispatches explicitly between 1.0/1.1; do not
edit released 1.0 bytes or loosen its schema.

Discovery also needs a public Catalog paging successor: a server-issued keyset
cursor pins Graph/policy/recipe/space/partition/population and the last unique
analysis/source key; each page reauthorizes those exact pins. There is no silent
latest snapshot between pages. The current candidate pool's `maximum_candidates`
plus `truncated` API is not that successor. Reconciliation reruns missing-binding
lookup after cursor completion so newly available reports and late metadata
registration are not lost. Exact vector retrieval likewise streams the whole
authorized index's pages/shards with bounded top-k, not only page one or Graph top64.

## 8. Operator audit is not background service authority

Current `LocalEmbeddingWorkflowRequest/1.0` contains
`requested_by_operator_id` and `requester_permissions_sha256`. Its parser says
those pins grant no source access. Current Catalog `_scope()` loads an active
`OperatorRecord`, requires actual permissions and selects a real released
`ADMIN`/`EDITOR`/`REVIEWER` role. Current
`EducationRetrievalAccessPolicy/1.0` has only role lists; it has no scoped indexing
service principal. Generic `ActorType.SYSTEM` or a static workflow actor is not a
Catalog service admission capability. A stale `guiadmin` ID/session, WORKER role
claim, ADMIN impersonation or DTO-provided permission hash cannot fill this gap.

The minimum required authority successor is deliberately purpose-specific:

1. Identity/control owner registers an immutable, revocable local service
   identity/revision bound to the authenticated Orchestrator/Runner owner runtime,
   **not** a worker account, copied Codex auth, interactive password or ambient UID.
   The local authenticated owner transport resolves this identity server-side.
   Its durable registration/activation is a separate identity-owner design gate;
   no service identity table or active grant is asserted to exist today.
2. Release `education-retrieval-access-policy/1.1`, preserving 1.0 role semantics,
   with an explicit `LOCAL_EMBEDDING_INDEX` service grant: exact service identity
   revision, allowed corpus IDs/storage partitions/source classes/population
   scopes, answer-bearing processing permission, model/recipe/resource profiles,
   and bounded batch/page budgets. Grant only discover/resolve/reauthorize and
   derived embedding registration; no Item approval, report acceptance, Graph
   publication, user retrieval impersonation or arbitrary filesystem capability.
3. Release `local-embedding-workflow-request/1.1` with a closed discriminated
   server-captured authority context (`OPERATOR` or `LOCAL_INDEXING_SERVICE`). The
   service branch pins identity/revision, released service-policy revision/hash,
   granted scope and authorization-audit digest; optional initiating operator
   remains separate audit provenance. Preserve 1.0 operator-only historical bytes.
4. Add a trusted Catalog indexing scope/admission leaf composing the **same official
   Graph/source/report resolver**. Validate the active service grant before Job
   reservation, launch, commit/registration and reconciliation. Never pass a
   service ID through current operator `_scope()` or fabricate a requester role.

The grant pins and checks the released retrieval policy separately from numerical
space. Revoking service authority blocks new work/replay admission; changing a
policy cannot make an old request newly authorized by reinterpretation. Existing
consumer retrieval still reauthorizes the actual current operator and pinned
source/Graph/policy; background authority is never transferred to that user.
CPU/CUDA purpose/resource admission and GPU lease remain independent release
gates. No indexing service authority is inferred from an idle GPU or Codex slot.

## 9. Persistence protection, access patterns and exit gates

The dominant operations are exact key lookup/deduplication, Graph membership
anti-join, ordered immutable manifests, append-only history, existing command
claim and index CAS. For N eligible sources and V available views, association
storage is O(NV) per retained Graph/policy revision; encoding storage is O(Ud)
for U unique actual texts in a space. B-tree lookup/claim is O(log U); bounded
dedup/resolution is O(B) expected map/set work plus indexed DB lookups. Exact
cosine remains O(Ud), with bounded heap/top-k working memory and authorized source
mapping. Neural compute cost needs measurement, not an O(Ud) assertion.

Catalog infrastructure owns ORM/migrations/public query/register application
services. Contracts/domain remain IO-free; Runner/Orchestrator call typed ports,
not Catalog private repositories. SQLAlchemy/FS/NAS/CUDA imports do not move into
contract or domain packages. No new dependency is required by this design.

Use append-only UPDATE/DELETE rejection triggers for the three immutable tables,
plus a head identity/namespace immutability guard allowing only current pointer,
version and UTC update time changes. These are **new** guards; existing graph
snapshot models/constraints do not supply them automatically. Schema-first
register/query/reservation/result contracts precede worker/runtime changes.

Extend `services/catalog_service/eom_catalog_service/runtime_privileges.py` and
the existing `scripts/catalog/bootstrap_runtime_role.py` reconciliation with
SELECT/INSERT on four tables and UPDATE only on the head. The current runtime
role is `eom_catalog_manager_runtime`, not an imagined `eom_catalog` role. Preserve
no DELETE/DDL/superuser/role-membership grants; narrow column UPDATE is preferred
for the new head and must be reflected in readiness. Runner/Orchestrator owner
roles get only their supported Job/command/service ports, not direct mutation of
Catalog rows. Do not execute role bootstrap as part of this design task.

Disposable opt-in PostgreSQL tests must cover composite artifact/source/head FKs,
wrong-index predecessor/current rejection, hash/row mismatch, append-only guards,
exact replay/conflict, concurrent first head/CAS, limited-role grants and denied
DELETE/DDL, and guarded up/down/up migrations. Downgrade refuses nonempty new
registry/native workflow history; it never deletes Artifacts or approved history.
Focused source tests cover report missing, unavailable view/overflow, Graph-only
binding with zero encoder calls, overlapping `[a,b]`/`[b,c]` one compute per key,
uncertain launch, commit-before-registration recovery, source/service revocation,
space/recipe switch and no raw binary/complete reports in DB. Add 1,024/1,025
manifest and 1,024-page overflow/empty-root/paging closure tests for the successor,
plus a synthetic anti-join query-plan/throughput test. Run formatter/linter/type
checker and focused regression before core merge; production DB/model/NAS tests
remain separately admitted and opt-in.

The simpler alternative—only a batch Artifact plus a current path—cannot answer
exact missing-binding queries, reserve overlapping encoding keys, pin historical
source associations or reject wrong-index CAS. A full vector DB, generic worker
queue or persistent model/profile framework is unnecessary for these invariants.
This four-table design, existing durable work owners and the explicit service/
paging successors are the smallest supported boundary. Report SOURCE_PASS,
DISPOSABLE_DB_PASS, INSTALLED, ACTIVE and LIVE_VERIFIED separately; this document
alone establishes none of them.
