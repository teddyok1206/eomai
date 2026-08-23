# Codex and Education Knowledge Protocol Compatibility

Status: Phase 1 contract baseline

Effective source baseline: `65970dcd32556530faf251f0ca48ad3aa7acae5f`

Last reviewed: 2026-08-23 UTC

## 1. Boundary

This document fixes the first immutable wire contracts for the Codex execution control plane and
the Education Knowledge plane. It does not create database tables, select a production model,
publish a Graph Snapshot, grant credentials, or authorize a live Codex run.

Execution-control contracts are owned by `eom_workflow` because the workflow and Orchestrator must
share them before claim. Knowledge-analysis, graph, retrieval, and evidence contracts are owned by
`eom_catalog_contracts` because they resolve approved Catalog source and Item revision pointers.
Neither package imports persistence, systemd, Codex CLI, NAS, HTTP, or service implementations.

## 2. Immutable schema inventory

| Contract | Schema ID | Package owner |
| --- | --- | --- |
| Execution Preset Revision | `eom://schemas/workflow/execution-preset-revision/1.0` | `eom_workflow` |
| Instruction Bundle Manifest | `eom://schemas/workflow/instruction-bundle-manifest/1.0` | `eom_workflow` |
| Reference Bundle Manifest | `eom://schemas/workflow/reference-bundle-manifest/1.0` | `eom_workflow` |
| Resolved Execution Plan | `eom://schemas/workflow/resolved-execution-plan/1.0` | `eom_workflow` |
| Codex Auth Health View | `eom://schemas/workflow/codex-auth-health-view/1.0` | `eom_workflow` |
| Codex Capability Snapshot | `eom://schemas/workflow/codex-capability-snapshot/1.0` | `eom_workflow` |
| Worker Capacity Policy | `eom://schemas/workflow/worker-capacity-policy/1.0` | `eom_workflow` |
| Worker Lease View | `eom://schemas/workflow/worker-lease-view/1.0` | `eom_workflow` |
| Knowledge Analysis Request | `eom://schemas/knowledge/knowledge-analysis-request/1.0` | `eom_catalog_contracts` |
| Knowledge Analysis Result | `eom://schemas/knowledge/knowledge-analysis-result/1.0` | `eom_catalog_contracts` |
| Knowledge Graph Snapshot Manifest | `eom://schemas/knowledge/knowledge-graph-snapshot-manifest/1.0` | `eom_catalog_contracts` |
| Education Retrieval Request | `eom://schemas/knowledge/education-retrieval-request/1.0` | `eom_catalog_contracts` |
| Evidence Bundle Manifest | `eom://schemas/knowledge/evidence-bundle-manifest/1.0` | `eom_catalog_contracts` |

`control-plane-types-v1` and `knowledge-types-v1` are package-owned support schemas. They make the
artifact, bundle, source-revision, Graph Snapshot, anchor, model, and role pointer shapes
authoritative within their respective domains. They are immutable resources even though they are
not application endpoint payloads.

Canonical schema bytes under `schemas/` and installed resource bytes are required to match. Each
runtime loader verifies a pinned SHA-256 before parsing and validates with JSON Schema 2020-12.
Changing any published byte requires a new schema ID and compatibility entry.

## 3. Endpoint and protocol compatibility table

| Producer/use case | Accepted input | Produced output | Additional pinned compatibility |
| --- | --- | --- | --- |
| preset release | Execution Preset Revision 1.0 | immutable released preset revision | one or more explicit `workflow-role/x.y.z` values; released capacity policy revision |
| instruction release | Instruction Bundle Manifest 1.0 | immutable bundle revision | Markdown artifact members beneath `instructions/` only |
| reference release | Reference Bundle Manifest 1.0 | immutable bundle revision | approved source revision and rights-policy revision per member; Markdown beneath `references/` only |
| workflow creation/resolution | released preset, workflow definition, Content Pack release | Resolved Execution Plan 1.0 | exact preset, workflow definition, Content Pack and capacity-policy hashes; optional Graph/Evidence revisions as a matched pair |
| pre-claim auth observation | exact fixed worker identity | Codex Auth Health View 1.0 | short TTL; no credential material |
| pre-claim capability observation | exact fixed worker identity and installed CLI | Codex Capability Snapshot 1.0 | short TTL; model plus supported effort pairs are observations, not account entitlement promises |
| capacity admission/reconciliation | released capacity policy and eligible slot | Worker Lease View 1.0 | five configured slots maximum, three active Codex maximum, one active lease per slot |
| knowledge-analysis workflow | Knowledge Analysis Request 1.0 | Knowledge Analysis Result 1.0 proposal | one approved source revision; released analysis preset; all claims and graph proposals anchored to that source |
| graph publisher | accepted analysis result artifacts and approved source revisions | Knowledge Graph Snapshot Manifest 1.0 | ontology `education-knowledge-graph/1.0`; prior snapshot pinned when present; projections are derived artifacts |
| retrieval application service | Education Retrieval Request 1.0 | internal ranked selection | exact published Graph Snapshot and access-policy revision; bounded local hybrid retrieval |
| Evidence Bundle publisher | ranked selection and original retrieval request | Evidence Bundle Manifest 1.0 | exact request hash, Graph Snapshot pointer, access policy, source revisions, members, anchors and budgets |
| item workflow resolver | Evidence Bundle Manifest 1.0 plus released preset | Resolved Execution Plan 1.0 | Evidence Bundle always carries its Graph Snapshot revision; role materializer validates every pointer again |

The first retrieval version deliberately supports `CURRICULUM_COMPONENTS`,
`APPROVED_ITEM_STRUCTURE`, and `ITEM_PREPARATION`. `ITEM_USAGE_HISTORY`, origin filters, and exact
Product/Form/Assembly filters are not guessed into V1. They require the Phase 6 contracts selected
under ADRs 0038 and 0039 and will use a new additive or breaking retrieval schema version.

Existing workflow role protocols `workflow-role/1.0.1` through `workflow-role/1.3.0` and their
result schemas remain byte-identical. The control-plane contracts wrap selection and provenance;
they do not reinterpret historical worker messages.

## 4. Resolution and security invariants

Every dereference validates logical identity, immutable revision identity, lifecycle, schema,
media type, permission, artifact identity, artifact revision, member containment, non-symlink file
type, and expected SHA-256. A missing or stale revision fails explicitly; no resolver substitutes a
current/latest revision.

Only normalized relative members under the declared roots may be materialized. Absolute paths,
`..` traversal, NAS paths, raw source bytes, raw prompts, session IDs, tokens, credentials, and
credential paths are absent from all contracts. Source content remains an Artifact Revision;
PostgreSQL will later store pointers and bounded metadata only.

Codex model names in a preset are reviewed ordered candidates. A capability observation establishes
whether a specific fixed identity and installed CLI can currently use a model/effort pair. It does
not infer entitlement from a marketing list. Codex supports explicit CLI model selection and a
model-dependent reasoning-effort setting, as documented in the official
[Codex model guide](https://learn.chatgpt.com/docs/models) and
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

General model knowledge is either denied or explicitly recorded. Knowledge-analysis mode
`AUXILIARY_UNATTRIBUTED` never permits model knowledge to masquerade as a citation: every accepted
node, edge, and claim in an analysis proposal resolves to an anchor in the pinned source revision.

## 5. Typed invariants beyond JSON Schema

Frozen Pydantic models additionally require:

- unique preset roles and ordered unique model/effort candidates;
- matched Instruction/Reference Bundle logical and revision ID families;
- unique materialization paths, reference keys, plan step keys, capability models, pools and slots;
- Evidence Bundle pointers only when a Graph Snapshot is also pinned;
- monotonic auth/capability observation windows and lease lifetimes;
- terminal lease states with exact release time and stable reason code;
- graph edges whose endpoints exist, proposal references whose anchors exist, and anchors whose
  source revision matches the analyzed revision;
- unique snapshot source revisions and analysis artifacts, with exact source counts;
- explicit curriculum scope for curriculum and item-structure queries;
- unique Evidence Bundle sources per intended use and exact entry-derived counts.

Confidence and relevance values use integer milli-units from 0 through 1000. EOM canonical JSON
intentionally rejects floating-point values, so this representation remains deterministic across
Python, PostgreSQL, JSON Schema validators, and artifact manifests.

These are deterministic validation rules. Workers never expand the ontology, repair pointers,
change capacity, publish graph state, or select credentials.

## 6. Versioning and rollout rule

Phase 1 stops at source contracts and tests. Phase 2 may add persistence only after its design note
defines ownership, access patterns, indexes, transactions, concurrency, idempotency, migration, and
rollback. No production database or service deployment is authorized by these schemas alone.

When rollout eventually begins, dual-read code lands before new writes. Historical workflows keep
their pinned role protocol, workflow definition, Content Pack, preset, and evidence identities.
Rollback stops new selection while preserving immutable revisions already written.
