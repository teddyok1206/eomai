# Knowledge-Backed Item Execution V3

Status: Phase 10 implementation contract
Date: 2026-08-24 UTC

## Responsibility and boundary

This design connects an approved educational retrieval intent to the existing fresh-session item
workflow without giving a worker access to PostgreSQL, the Education Graph, NAS, credentials, or
mutable current pointers. The Application use case accepts educational intent, the Catalog
application boundary resolves and publishes one bounded Evidence Bundle, and the Orchestrator pins
that bundle in one immutable execution plan before any worker lease is claimed.

The existing reference-only and explicit general-model-knowledge paths remain valid. Historical
`execution-preset-revision/1.0`, `resolved-execution-plan/1.0`, and knowledge-analysis
`resolved-execution-plan/2.0` bytes and behavior are not changed.

## Canonical sources and revision model

The canonical sources are:

1. the logical knowledge corpus and its immutable published Graph Snapshot Revision;
2. one released Education Retrieval Access Policy Revision;
3. one immutable Education Retrieval Request V2;
4. one logical Evidence Bundle and one immutable published Evidence Bundle Revision;
5. the manifest and bounded Markdown context Artifact Revisions referenced by that bundle;
6. one released Execution Preset Revision V2; and
7. one immutable Resolved Execution Plan V3 pinned to one workflow occurrence.

The V2 policy is published under the separate logical preset key `knowledge-grounded-item`.
Historical and source-free requests continue to resolve `standard-item` through the V1 contract;
the rollout never changes that logical preset's current Revision to a V2 document.

The workflow workspace contains only temporary materializations. Neither `references/evidence/`
nor any filesystem path is an identity.

## Educational request contract

The browser may supply only an approved `educational-retrieval-requirement/1.0` value:

- a stable corpus key;
- one closed query kind;
- a stable curriculum root key and/or controlled topic keys;
- required item element kinds; and
- allowed source classes.

It cannot supply a Graph Snapshot Revision, storage path, access-policy revision, arbitrary graph
query, SQL, traversal depth, token budget, permission set, model, reasoning effort, or worker slot.
The released Execution Preset selects the access policy, maximum budget, and role exposure policy.

## Required pointers and resolution checks

Before workflow creation, the Catalog application operation resolves and validates:

- corpus key -> active logical corpus -> exact current published Graph Snapshot Revision;
- stable curriculum keys -> exactly one node/unit in that snapshot;
- preset-selected policy revision -> released state and exact content hash;
- caller -> active operator role and sorted permission-set hash;
- selected evidence -> approved immutable source/item/component revisions, schema, media type, SHA,
  rights class, answer-bearing policy, and snapshot membership; and
- Evidence Bundle manifest/context -> approved regular Artifact members with exact IDs, revisions,
  member paths, schema/media types, byte hashes, and deterministic manifest self-hash.

The Resolved Execution Plan V3 pins the retrieval request hash, snapshot revision, access-policy
revision/hash, Evidence Bundle logical/revision IDs, manifest Artifact pointer and self-hash,
context Artifact pointer, preset revision/hash, Content Pack release/hash, selected model/effort,
and every instruction/reference bundle pointer. No later `current_revision_id` lookup may alter an
existing plan.

## Access patterns and data structures

- workflow replay: unique indexed lookup by `workflow_id`, expected O(log n);
- Evidence Bundle lookup: primary/unique revision and retrieval-request keys, expected O(log n);
- role materialization policy: bounded map keyed by role, at most five entries, O(1) expected;
- authorized Artifact Revision membership: a set derived from one plan and its manifests, O(1)
  membership per materialized member;
- deterministic step order: immutable tuple in workflow-definition order; and
- graph retrieval: the Phase 9 indexed lexical, closure, and adjacency queries remain unchanged.

No new graph backend, vector dependency, repeated list scan, large DB payload, or persisted copied
context is introduced. PostgreSQL stores the immutable plan JSON and pointers; Markdown bytes remain
in the canonical Artifact store.

## Preset V2 and least-needed context

`execution-preset-revision/2.0` adds one retrieval policy:

- exact access-policy revision ID and SHA;
- allowed corpus keys, query kinds, and source classes;
- a bounded maximum Evidence Budget; and
- a role map whose value is `EVIDENCE_CONTEXT` or `NONE`.

The standard knowledge-backed policy exposes context to `authoring`, `image`, and `review` and
exposes none to `item_management`. A step cannot broaden this setting. A request whose corpus,
query kind, source class, or required budget is outside the released preset fails before workflow
creation and before a Codex lease.

## Transaction, concurrency, retry, and idempotency

The Application use case first reads and pins the active definition, Content Pack, and released
preset policy. It then invokes the private Catalog operation outside an API DB transaction. Catalog
selects the current graph snapshot once and publishes the Evidence Bundle under an idempotency key
derived from the API request idempotency identity and the preset revision. A replay with identical
input returns the same bundle; different input under the same key fails.

The subsequent workflow transaction revalidates the same preset revision and exact Evidence Bundle
pointers, creates the workflow occurrence and V3 plan, then enqueues the existing start command.
If the workflow transaction fails after Evidence Bundle publication, the immutable bundle remains
an attributable, harmless orphan and an exact replay reuses it. It is never silently rebound to a
new snapshot or preset. Concurrent plan creation remains protected by the unique workflow-plan key.

## Materialization and dependency direction

The Orchestrator owns materialization. For a role marked `EVIDENCE_CONTEXT` it:

1. derives an exact Artifact Revision allowlist from the plan;
2. resolves the manifest Artifact and recomputes its file SHA;
3. validates the manifest with JSON Schema 2020-12 and Pydantic;
4. checks every pinned request/snapshot/policy/bundle/context identity and hash against the plan;
5. resolves the context Artifact as a regular non-symlink canonical member; and
6. writes it once as `references/evidence/context.md` with the existing private workspace modes.

Roles marked `NONE` receive no evidence file. Workers receive only job-local files and structured
worker input through the Orchestrator. Catalog remains the owner of graph retrieval and Artifact
publication; the API owns authentication/presentation; domain contracts import no infrastructure.

## Failure behavior

Graph miss, stale corpus/snapshot/policy/preset/source pointer, permission mismatch, manifest/hash
mismatch, path escape, symlink, unsupported role exposure, budget overflow, and idempotency conflict
are stable fail-closed errors. They never trigger a broader query, implicit latest substitution,
general-model-knowledge fallback, worker claim, or partial canonical Item registration.

The simpler alternative—placing a graph path or snapshot ID in the worker prompt—is insufficient:
it bypasses authorization, loses revision/hash provenance, makes replay depend on mutable state, and
violates worker isolation. Adding Evidence Bundle fields to historical V1 plan/preset schemas is
also rejected because it would reinterpret immutable protocol history.

## Acceptance invariants

- reference-only and explicit general-knowledge workflows retain their V1 plan path;
- one graph miss creates no workflow, lease, job, or Codex invocation;
- a V3 plan remains byte-stable when current graph/preset pointers later change;
- stale or forged manifest/context pointers fail before materialization;
- authoring/image/review receive exactly one bounded context file; item management receives none;
- event data contains only IDs, hashes, counts, model/effort, and no paths or evidence content; and
- a successful workflow still produces one canonical approved Item Revision usable by the existing
  HWPX and secure-download boundaries.

## Controlled rollout boundary

Source completion does not publish or activate a live graph, access policy, Evidence Bundle, or
execution preset and does not invoke Codex. Runtime rollout must preserve the existing
`standard-item` V1 preset and publish a separate `knowledge-grounded-item` V2 logical preset. Before
enabling the GUI opt-in, an operator must verify that its allowed corpus key resolves to one active
corpus with one published current Graph Snapshot, its pinned access-policy revision is released,
and every referenced instruction, Content Pack, and preset pointer matches the reviewed source
release. The GUI flag remains false by default.

Deployment is dual-read: historical V1/V2 plans remain readable, and only V3 plans expose the new
pointer-only reviewer provenance. A runtime acceptance needs an independently authorized graph
publication and a single fresh workflow. Failure rolls back the GUI capability/preset selection,
not historical plans or graph revisions; no implicit fallback to `standard-item` or general model
knowledge is permitted.
