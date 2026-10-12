# Native embedding Runner and service admission proposal

2026-10-12 UTC. The four protocol families below are approved for source-only implementation;
Runner/Job behavior, migrations and activation are still proposals requiring owner review.
Read alongside the main incremental
embedding design, execution boundary and registry design §§5/8. No migration number is reserved.

## Eleven-point boundary

1. **Responsibility:** Catalog owns current source/report/Graph/policy eligibility and deterministic
   view projection; Runner owns the existing Workflow/command queue and step state; Orchestrator
   owns per-encoding reservation, protected native launch, resource admission and Artifact commit.
   Add one fixed `LOCAL_EMBEDDING` application-purpose branch and one mandatory isolated executor,
   not a generic dispatcher, queue, scheduler, plugin registry or Codex role. An absent executor,
   live authority source or admitted runtime/policy is unavailable **before Workflow/Job creation
   or command claim**, never fallback to `PlatformRoleJobExecutor`.
2. **Canonical source:** start with the official bounded admitted corpus and exact missing-binding
   query, not timestamps, upload events or an invented population. Persist only a pointer-only
   source-plan manifest and exact native input/output Artifact pointers. The plan contains source,
   profile/report/evidence, Graph/policy, recipe, encoding demands and coverage metadata, not source
   or report bodies. Catalog materializes only owned encoding text at the protected native-input
   boundary. Missing accepted reports remain coverage limitations; no fake CRUX or Item approval.
3. **Identity/revision:** separate Workflow intent, per-encoding computational Job, owned native
   launch Job, publication owner Job and logical index/revision. Preserve released definition 1.0,
   role/execution hashes, native input/result 1.0 and operator-only Workflow request 1.0 bytes.
   The already implemented fixed native definition schema 1.1/version 1.0.0 and
   `definition_execution_protocol()` can be reused without changing its graph or historical
   canonical hash. New admission fields belong to request 1.1, not in-place mutation of 1.0.
4. **Resolution:** the new request pins exact definition hash, corpus/Graph/access-policy,
   namespace/space/runtime bundle, source-plan raw and semantic hashes, native execution-policy
   raw and semantic hashes and a small immutable resource profile. Resolve existence, schema/media,
   approved immutable Artifact state, size/raw SHA and semantic closure; compare every profile and
   runtime value to the independently installed owner configuration. Approved control bytes or
   DTO-held hashes are not a released policy, source eligibility or permission grant. Source and
   authority checks repeat before reservation, launch, commit, metadata registration and replay.
5. **Access patterns:** exact encoding-key membership, bounded ordered missing-binding selection,
   unique reservation, sorted Job-row locking, existing indexed FIFO/SKIP LOCKED claim and append-only
   owner events. Avoid N+1/full-corpus rebuilding. A read-only candidate-purpose check must precede
   claim, and the claim must target that exact candidate under the existing token/generation fence;
   it must not accidentally select another purpose after readiness was checked. An unavailable
   optional native adapter must leave native commands unclaimed without disabling legacy work.
6. **Structures/indexes:** reuse `jobs.idempotency_key` with `embedding-encode:` plus the encoding
   digest; temporary maps/sets deduplicate and order keys. Reuse existing Job events and Workflow
   commands, attempt unique, lease identity and transition tables. No pending Catalog row or
   separate reservation table/queue is added. The native reserve/attach/complete/read application
   port needs its own closed request/event/result protocol before behavior; `submit_structured_job`
   alone is not that port or authority to submit arbitrary native tasks.
7. **Scale/cost:** first operator seed is one explicitly requested bounded corpus/Graph/view scope,
   at most 1,024 source demands and existing native row/byte limits; no implicit full corpus sweep.
   Request envelope remains ≤64 KiB; plan metadata ≤64 MiB; owned input ≤64 MiB and binary ≤16 MiB.
   CPU/GPU profile pins device, actual numeric runtime, threads/batch recipe, CPU quota, memory,
   timeout, tasks/output limits and `maximum_active_launches=1`. Profile values are integers/closed
   literals with a semantic hash, not mutable global configuration. Bounds do not prove actual
   machine capacity: released owner policy and measured runtime admission must establish it.
8. **Transactions/concurrency:** reserve and attach each missing key in one short Orchestrator
   owner transaction, with sorted row locks and a savepoint/unique-race reread plus exact conflict
   check. `[a,b]` and `[b,c]` give one owner for `b`; the loser launches only its owned keys or waits
   for the original pointer. Do not hold SQL transactions through inference. Existing command
   heartbeat/token/generation fences completion; expiry is not proof of nonexecution. A narrowly
   scoped native-capacity advisory transaction lock can atomically count/claim **native launch**
   Jobs, not reservation Jobs, with `worker_slot_id=NULL`. An uncertain launch retains active
   capacity until supported unit/cgroup/output reconciliation proves its outcome. CUDA additionally
   needs the independently admitted shared physical GPU lease held through execution/output sync;
   flock closure alone never proves orphan-process/device cleanup.
9. **Dependency/authority:** contracts remain IO-free; Runner calls explicit Catalog/Orchestrator
   public application ports, never private repositories. First seed is operator-only through an
   actual authenticated owner call and current official source policy. Persisted operator ID,
   permission digest or old session is audit provenance only, not a background grant. IAM's current
   public seam is `OperatorAuthorizationFence.fence_current_operator(session, operator_id)`; it
   returns no grant, has no concrete/default implementation and must fence the short root transaction
   against revoke/disable/delete/password-reset writers. It does not establish session freshness or
   a service identity. Missing authenticated continuation/current checks leave queued native work
   unavailable before claim; no credentials are persisted or sent to the worker.
   Proposed operator seed requires actual current `workflow:start` and the separately admitted
   native-purpose policy; source reads use the official retrieval policy, and final registration
   retains Catalog's current `knowledge_graph:publish` guard. Neither permission alone activates
   native compute or grants a service principal. The exact new-purpose mapping needs owner review.
10. **Failure/replay:** retain the original plan and owned launch association. Do not rewrite the
    initial Workflow request when overlapping reservation leaves only a subset. Validate result
    against the exact **owned** native input/request hash, not the all-demand plan hash. Each
    per-encoding completion event references its one canonical shared shard row; allocated Artifact
    IDs on reservation Jobs remain unused and are not rewritten to the publisher's IDs. Explicit
    typed pointer-result reading is required; do not reinterpret legacy successful Job purposes.
    Known output is recommitted/re-registered by the same key; uncertain/partial output is never
    overwritten or silently re-encoded. Terminal reservation failure is not reset or bypassed by
    a new key. First release may reject terminal retry until an explicit linked recovery successor.
11. **Simpler alternative:** batch-only idempotency duplicates `b`; Catalog's committed encoding
    unique is too late. A Codex worker/Pack/rubric adds false authority and wrong capacity. A new
    queue or scheduling framework duplicates existing durability. If pointer-result reservation
    Jobs are not admitted, the safe fallback is singleton per-key launches with measured cold-load
    cost, not a weakened batch-only claim. Preserve the legacy CPU experiment runtime/manifest/unit.

## Minimal schema successor proposal

These names/fields are proposals, not registered contracts or service grants. Before behavior,
define JSON Schema 2020-12, exact canonical hashes and frozen models for:

| Contract | Minimum immutable closure |
| --- | --- |
| `local-embedding-workflow-request/1.1` | Fixed purpose/definition, discriminated server-captured actor audit, source-plan pointer, Graph/policy/namespace/space, runtime-bundle pointer, native policy pointer and small resource value |
| `local-embedding-source-plan/1.0` | Bounded ordered source/profile/evidence demands and encoding identities, recipe/space/Graph/policy, eligible/report-missing coverage; no text, row guesses or grants |
| `embedding-encoding-job/1.0` | Fixed per-encoding request with full space pin; closed attach/complete/read-result events with exact launch/Workflow/step/attempt/fence and shared row receipt |
| `local-embedding-execution-policy/1.0` | Fixed native purpose, exact admitted definition/runtime/resource-profile hashes and bounded budgets; one configured released policy Artifact, not a Codex preset or new policy registry |

The first schema's closed frame below is the proposed minimum. Existing catalog `$ref`s remain
the authoritative types. The new plan/policy member schema URIs are deliberately unregistered;
their own standalone 2020-12/frozen contracts must be completed before parsing this request in a
runner. JSON Schema does not establish live actor authority, release state, canonical hash equality
or runtime/resource consistency; the owner application supplies those checks.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "eom://schemas/workflow/local-embedding-workflow-request/1.1",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "request_name", "purpose", "workflow_definition_key", "workflow_definition_version", "workflow_definition_sha256", "actor_context", "corpus_id", "graph_snapshot", "access_policy_revision_id", "access_policy_sha256", "namespace", "space", "runtime_bundle", "source_plan", "source_plan_sha256", "native_execution_policy", "native_execution_policy_sha256", "resource_profile", "request_sha256"],
  "properties": {
    "schema_version": {"const": "local-embedding-workflow-request/1.1"},
    "request_name": {"const": "LOCAL_EMBEDDING_WORKFLOW_REQUEST"},
    "purpose": {"const": "LOCAL_EMBEDDING"},
    "workflow_definition_key": {"const": "local-embedding-index"},
    "workflow_definition_version": {"const": "1.0.0"},
    "workflow_definition_sha256": {"$ref": "#/$defs/hash"},
    "actor_context": {"oneOf": [{"$ref": "#/$defs/operatorAudit"}, {"$ref": "#/$defs/serviceAudit"}]},
    "corpus_id": {"type": "string", "pattern": "^corpus_[0-9a-f]{32}$"},
    "graph_snapshot": {"$ref": "eom://schemas/knowledge/knowledge-types-v1#/$defs/graphSnapshotPointer"},
    "access_policy_revision_id": {"type": "string", "pattern": "^accessrev_[0-9a-f]{32}$"},
    "access_policy_sha256": {"$ref": "#/$defs/hash"},
    "namespace": {"$ref": "eom://schemas/knowledge/embedding-registry/1.0#/$defs/namespace"},
    "space": {"$ref": "eom://schemas/knowledge/item-inference-transfer-embedding/1.0#/$defs/space"},
    "runtime_bundle": {"$ref": "eom://schemas/knowledge/embedding-runtime-bundle/1.0#/$defs/bundlePointer"},
    "source_plan": {"allOf": [{"$ref": "eom://schemas/knowledge/item-inference-transfer-embedding/1.0#/$defs/artifactMember"}, {"properties": {"member_path": {"const": "source-plan.json"}, "schema_ref": {"const": "eom://schemas/workflow/local-embedding-source-plan/1.0"}, "media_type": {"const": "application/json"}}}]},
    "source_plan_sha256": {"$ref": "#/$defs/hash"},
    "native_execution_policy": {"allOf": [{"$ref": "eom://schemas/knowledge/item-inference-transfer-embedding/1.0#/$defs/artifactMember"}, {"properties": {"member_path": {"const": "policy.json"}, "schema_ref": {"const": "eom://schemas/workflow/local-embedding-execution-policy/1.0"}, "media_type": {"const": "application/json"}}}]},
    "native_execution_policy_sha256": {"$ref": "#/$defs/hash"},
    "resource_profile": {"$ref": "#/$defs/resourceProfile"},
    "request_sha256": {"$ref": "#/$defs/hash"}
  },
  "$defs": {
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "operatorAudit": {
      "type": "object", "additionalProperties": false,
      "required": ["kind", "operator_id", "requester_permissions_sha256"],
      "properties": {
        "kind": {"const": "OPERATOR"},
        "operator_id": {"type": "string", "pattern": "^operator_[0-9a-f]{32}$"},
        "requester_permissions_sha256": {"$ref": "#/$defs/hash"}
      }
    },
    "serviceAudit": {
      "type": "object", "additionalProperties": false,
      "required": ["kind", "service_id", "service_revision_id", "service_identity_sha256", "service_policy_revision_id", "service_policy_sha256", "authorization_audit_sha256"],
      "properties": {
        "kind": {"const": "LOCAL_INDEXING_SERVICE"},
        "service_id": {"type": "string", "pattern": "^localindexservice_[0-9a-f]{32}$"},
        "service_revision_id": {"type": "string", "pattern": "^localindexservicerev_[0-9a-f]{32}$"},
        "service_identity_sha256": {"$ref": "#/$defs/hash"},
        "service_policy_revision_id": {"type": "string", "pattern": "^accessrev_[0-9a-f]{32}$"},
        "service_policy_sha256": {"$ref": "#/$defs/hash"},
        "authorization_audit_sha256": {"$ref": "#/$defs/hash"}
      }
    },
    "resourceProfile": {
      "type": "object", "additionalProperties": false,
      "required": ["device", "threads", "batch_size", "memory_max_bytes", "cpu_quota_percent", "timeout_seconds", "tasks_max", "output_max_bytes", "maximum_active_launches", "physical_gpu_lease", "network", "resource_profile_sha256"],
      "properties": {
        "device": {"enum": ["CPU", "CUDA"]},
        "threads": {"type": "integer", "minimum": 1, "maximum": 16},
        "batch_size": {"type": "integer", "minimum": 1, "maximum": 16},
        "memory_max_bytes": {"type": "integer", "minimum": 268435456, "maximum": 34359738368},
        "cpu_quota_percent": {"type": "integer", "minimum": 100, "maximum": 1600},
        "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 1800},
        "tasks_max": {"type": "integer", "minimum": 1, "maximum": 64},
        "output_max_bytes": {"type": "integer", "minimum": 1, "maximum": 67108864},
        "maximum_active_launches": {"type": "integer", "const": 1},
        "physical_gpu_lease": {"enum": ["NONE", "SHARED_GPU0"]},
        "network": {"const": "DISABLED"},
        "resource_profile_sha256": {"$ref": "#/$defs/hash"}
      },
      "allOf": [{"if": {"properties": {"device": {"const": "CPU"}}}, "then": {"properties": {"physical_gpu_lease": {"const": "NONE"}}}, "else": {"properties": {"physical_gpu_lease": {"const": "SHARED_GPU0"}}}}]
    }
  }
}
```

Service identity namespace/registration semantics above require Identity-owner review; no service
ID or grant is created by this proposal. First implementation accepts operator seed through the
   real owner context only; service parsing alone must return explicit unavailable. Background
activation separately requires official immutable/revocable Identity registration bound to the
authenticated owner transport and `education-retrieval-access-policy/1.1` with a literal
`LOCAL_EMBEDDING_INDEX` grant: exact identity revision, corpora/storage/source/population scopes,
answer-bearing processing allowance, model/recipe/resource pins and bounded budgets. No Item
approval, report acceptance, Graph publication, user impersonation or arbitrary path grant.
Optional initiating operator remains separate audit provenance, never the service principal.

## Owner sequence and immutable launch association

1. Authenticated owner seed call → current IAM/source/purpose/runtime checks → official bounded
   plan. Runner atomically stores the native request and `START_WORKFLOW` in its existing transaction.
   No secret/token or source/report body enters `initial_request`/`runtime_context`.
2. Read-only exact candidate/purpose readiness → same-candidate claim → existing command lease
   scope. Create only `step_type=application`, `worker_role=NULL`, fixed `encode_batch`/result schema.
3. Orchestrator public owner port rechecks registered rows, atomically reserves sorted missing keys
   and attaches owned keys to one exact Workflow/step/attempt/launch identity. Attachment records
   original plan/request hash separately from eventual owned native input pointer/hash and resource
   profile. Jobs are not polled by another scheduler. Native-capacity admission counts launch Jobs,
   not every per-encoding reservation, and never consumes Codex slots/auth bindings.
4. Close SQL transaction. Reauthorize exact owned sources; build one canonical
   `IncrementalEmbeddingInput/1.0` for the owned subset, protect it with the existing O_EXCL/FD/epoch
   handoff pattern, and invoke only the admitted isolated descriptor executor. Pin actual bundle,
   device/precision/runtime, batch/thread recipe, budget, command fence and launch association.
5. Validate known output against that owned input. Reauthorize before Artifact commit; complete
   reservations with exact shared row pointers in typed owner events. Reconcile any borrowed keys
   without duplicate inference. Catalog final verification/registration independently reauthorizes
   all source/Artifact references and performs its own exact CAS. A step is not complete merely
   because its owned subset encoded while required borrowed keys/registration remain pending.

Existing result Artifact store currently accepts Workflow request 1.0 and equates its input pointer
and input-set hash with the native launch. Supporting the new source-plan/owned-subset separation
therefore needs an explicit trusted launch-association overload/adapter, not a forged 1.0 request,
changed hash, ignored comparison or mutation of the initial Workflow snapshot.

## Exact proposed paths, DB scope and known gaps

| Owner | Future reviewed paths / evidence |
| --- | --- |
| Workflow contracts | `packages/workflow/eom_workflow/local_embedding_workflow.py` and additive `resources/local-embedding-workflow-request-v1_1.schema.json`; new plan/encoding-event/policy schema resources and frozen models before worker changes; existing definition and `definition_execution_protocol.py` bytes preserved where no semantic change is required |
| Runner admission/storage | New fixed-purpose `services/workflow_runner/eom_workflow_runner/local_embedding_admission.py`; `repository.py` native request storage/fingerprint/create, exact candidate claim; `models.py` and `state_machine.py` native guards/stage only |
| Runner execution | New fixed-purpose `local_embedding_execution_port.py`; `engine.py` LocalEmbeddingStep branch/readiness-before-claim protection; `readiness.py` native-only checks and `composition.py` explicit optional adapter, with unavailable-before-claim and legacy compatibility tests |
| Orchestrator owner | New purpose-specific `services/orchestrator/eom_orchestrator/embedding_encoding_reservations.py` public reserve/attach/complete/read use case; existing `repository.py` storage primitive remains nonauthoritative; later trusted native launcher/execution association and existing Artifact store composition |
| Catalog / IAM | Supported existing Catalog source/registry public ports; separately reviewed service-policy successor and official Identity implementation. Do not import their private repositories. Current IAM interface path is `services/identity_service/eom_identity_service/operator_authorization_fence.py`; this proposal does not edit it |
| Source and disposable tests | Native contract/Runner unavailable-before-claim/encoding overlap tests, then guarded independent-process reservation races, lease-loss completion fencing, authority revocation/password-reset, limited-role and up/down/up tests; no live model/NAS/production DB fixtures |

The native migration has the **post-0052 / “0053-scope”** discussed in the execution boundary, not
an allocated revision ID. Change only the stage CHECK to admit `LOCAL_EMBEDDING` and add total-boolean
native step guards. There is no existing step-type enum CHECK to widen. Suggested logical guards:
`step_type='application'` iff `result_schema IS NOT DISTINCT FROM 'incremental-embedding-result@1.0'`;
for that branch require `worker_role IS NULL` and `step_key='encode_batch'`. Using ordinary equality
on nullable `result_schema` would incorrectly let CHECK's SQL UNKNOWN pass. Runner independently
validates the exact parent definition/request purpose; a cross-table CHECK must not be invented.
Keep command enums/queue indexes/attempt unique/Job FK/states unchanged. Downgrade refuses remaining
native history rather than deleting or rewriting it. No `CURRENT_MIGRATION` edit or DDL is authorized.

Observed gaps: `create_workflow_instance()` still accepts only legacy/transfer request types and
extracts agent role protocols; model/stage CHECK and Runner `_advance()` lack native support.
`WorkflowRuntimeReadiness`/composition build Codex slots/auth; `RoleExecutionPolicy` requires a worker
role/model/instruction/pool and `WorkerLeaseRecord` requires nonnullable Codex binding/slot with
CODEX/KNOWLEDGE_ANALYSIS workload only. None is native authority or capacity. The per-key native Job
public port, source-plan/launch association, actual isolated launcher/profile gate, concrete IAM
fence and service principal/policy activation remain unimplemented/unadmitted at this proposal.

The mandatory same-input CPU/GPU benchmark/result correctness and default-device activation remain
part of the overall goal, not deferred out of scope. Native admission must verify FP32, TF32 disabled,
no truncation, identical upstream weights/tokenizer/file hashes and distinct runtime/space identity.
If CUDA is measured superior and all isolation/shared-lease/image regression/capacity gates pass,
release explicit GPU-default policy and verify actual default activation/rollback. Until those gates,
retain CPU baseline. Do not silently fall back on hash/result/authority errors or uncertain execution.

The original inline draft passed local JSON parsing and `Draft202012Validator.check_schema` only.
It is retained as proposal history, not the authoritative released schema. The additive canonical
resources and frozen source models below are the protocol-stage implementation; neither the draft
nor passing source tests establishes service or runtime readiness.

## Approved protocol-only implementation boundary

The existing workflow schema module already owns the exact public Catalog `$ref` boundary. Its
additive fixed-four-resource loader checks packaged schema bytes, expected SHA and schema identity;
it extends the public Catalog registry without online retrieval. Role resources/inventories,
execution hashes, definition bytes, request 1.0 and native input/result 1.0 remain unchanged. No new
dependency is introduced: existing Pydantic, jsonschema, referencing and identifier serialization
are reused. No provider/plugin registry, dispatcher, storage adapter or application behavior is added.

Canonical resources in `schemas/workflow/`, with byte-identical packaged mirrors in
`packages/workflow/eom_workflow/resources/`:

- `local-embedding-workflow-request-v1_1.schema.json`
- `local-embedding-source-plan-v1.schema.json`
- `embedding-encoding-job-v1.schema.json`
- `local-embedding-execution-policy-v1.schema.json`

Frozen model modules are respectively `local_embedding_request.py`, `local_embedding_source_plan.py`,
`local_embedding_encoding_job.py` and `local_embedding_execution_policy.py` under
`packages/workflow/eom_workflow/`. Public exports and validation registration are additive.

The authoritative resource profile adds explicit `gpu_vram_max_bytes`: CPU requires zero/no GPU
lease; CUDA requires `SHARED_GPU0` and permits the predeclared **8 GiB** VRAM limit. The initial fixture
uses **6 GiB host memory** and **8 GiB VRAM**, consistent with the reviewed performance gate. Schema
RAM bounds are not machine capacity authorization: an owner must compare the complete exact profile
with independently released configuration and measured admission, not authorize a request's chosen
32 GiB merely because it parses. No post-hoc benchmark thresholds, precision shortcut or implicit
CPU fallback are added. Query-purpose benchmarking still needs its separately reviewed wire/owner
path; DOCUMENT native contracts do not authorize disguising QUERY work as corpus encoding.

Source plans use ordered immutable tuples and O(n) maps/sets (plus O(n log n) canonical unique encoding
ordering), at most 1,024 sources/demands. Demands, report-missing IDs and unavailable-view records must
exhaustively and disjointly cover the exact source set. Different sources may reference one encoding.
Full V3 past-exam provenance is retained where the namespace requires it; the public pure entry
closure compares the existing profile1.0 core V2 source plus exact profile/evidence/Graph/projection
and rendered view hash. That comparison never grants current source/report authority. Zero demands
are deliberate report/view coverage metadata; the min-one native input/launch contracts prevent a
fake zero-row Artifact or encoding Job. Future owner behavior must treat such a plan as coverage-only.

Encoding-family REQUEST, LAUNCH_ASSOCIATION, ATTACHED, COMPLETED and READ_RESULT records are closed,
typed and canonically hashed. The computational key is `embedding-encode:` plus exact encoding SHA;
original Workflow/plan hash is separate from the owned subset input hash. Every owner event retains
the existing reservation Job's allocated Artifact IDs unchanged; shared result/shard/binary pointers
must be one exact file set and must not substitute those allocations. Actual row/result closure
compares distinct raw-member and semantic hashes and exact owned input. No binary/vector/source
payload, worker role, lease secret, path choice or authority field is carried. Public command ID,
runner ID and generation are fence **audit**, not a usable live lease token. The explicit Orchestrator
owner Protocol has no implementation/default or grant; atomic existing-Job reservation, live token
fencing, Artifact lifecycle, finite/L2 binary validation and source reauthorization remain next-stage
owner obligations. `[a,b]`/`[b,c]` tests prove equal computational keys, not actual concurrency behavior.

Models revalidate raw nested frozen values before parsing. Pydantic serialization can turn a copied
boolean into its declared integer; therefore `model_dump` alone is not the first validation boundary.
The purpose-specific value walk preserves actual booleans, rejects floats/unsupported values, and
bounds nesting to 32, object fields to 64 and collections to 1,024. New strict integer fields then
reject copied/constructed bool-integer bypasses. Public parsers first validate the bounded closed
2020-12 frame and return content-free stable errors. Only parse failures are wrapped; these modules
have no IO lifecycle to hide. Service audit may parse, but `require_local_embedding_operator_seed`
returns `LOCAL_EMBEDDING_SERVICE_UNAVAILABLE` for it. Returned operator audit is still not actual
authentication, session freshness, permission or IAM/source fencing.

Source fixtures/tests are `tests/unit/local_embedding_admission_fixtures.py` and
`tests/unit/test_local_embedding_admission_contracts.py`. They exercise exact refs/hashes, coverage,
copy/construct revalidation, bounded integer recipes, overlap/subset identity, pointer-only events,
raw-versus-semantic hashes, read states, schema drift and forbidden infrastructure imports without
DB, NAS, model, GPU or network work. The separate native Runner/repository/service policy migration,
mandatory isolated executor, actual same-input CPU/GPU benchmark and GPU-default activation remain
unimplemented/unadmitted by this protocol stage.

Final source gate: 139 new synthetic contract tests, 475 tests across the eight-file native/legacy
protocol suite, and five no-install package-resource tests PASS (four wheel/install tests deliberately
deselected). Ruff check/format and strict mypy on the eight owned Python files PASS. All commands used
explicit Conda environments; no live/disposable DB, package install, GPU/model/network, NAS, runtime,
migration or Git operation was performed. These are source protocol results, not release readiness.
