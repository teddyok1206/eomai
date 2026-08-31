# Graph-Grounded Single-Item Production E2E V1

Status: implementation and controlled-rollout contract
Date: 2026-08-31 UTC

## 1. Responsibility and boundary

This milestone makes one reviewed Integrated Science curriculum selection usable by the existing
single-item pipeline:

```text
Scientific Studio reviewed draft
  -> Application API curriculum resolution
  -> current published Integrated Science textbook Graph Snapshot
  -> bounded Evidence Bundle
  -> immutable resolved execution plan
  -> fresh orchestrated authoring, image, review, and registration
  -> approved current Item Revision
  -> one eom-template HWPX build
  -> secure Application API download
```

The browser supplies editorial intent and natural-language guidance. It does not select a Graph
revision, access-policy revision, Evidence Bundle, storage path, worker, model, or runtime account.
Catalog owns retrieval and Evidence publication; Orchestrator owns plan pinning and worker
materialization; Item Registry owns the approved Item Revision; HWPX Application Manager owns the
build and download boundary.

This work does not alter textbook-analysis batches, the published full-corpus Graph, historical
workflows, historical presets, HWPX templates, port 8000, or EOMIS.

## 2. Canonical sources and revision model

The canonical production corpus key is `integrated-science-textbooks`. The Application API
capability projection is the authoritative public statement that this corpus has a current,
published snapshot containing the complete pinned editorial hierarchy. Scientific Studio obtains
the corpus key from that projection instead of maintaining a second operational constant.

Reproducible execution pins:

- editorial outline key, revision, SHA-256, selected unit, and resolved Graph stable key;
- corpus key and current published Graph Snapshot Revision;
- released retrieval access-policy revision and SHA-256;
- released `knowledge-grounded-item` Execution Preset Revision and policy SHA-256;
- published Evidence Bundle Revision, manifest/context Artifact Revisions, and hashes;
- active Content Pack release and hash;
- workflow definition version/hash and role protocol;
- generated Item logical ID and immutable approved current Revision; and
- HWPX build, output Artifact Revision, output SHA-256, and downloaded SHA-256.

Historical `science-core` fixtures and preset revisions remain immutable. A new released preset
revision permits the production corpus; no historical plan or result is reinterpreted.

## 3. Pointer resolution checks

Before any worker lease, the request must fail closed unless all of these are true:

1. the selected editorial unit resolves in the pinned outline;
2. the browser supplied no Graph root or topic key;
3. the requested corpus equals the server-advertised production corpus;
4. the current corpus is active and points to one published Graph Snapshot Revision;
5. the exact editorial Graph root and full required hierarchy closure exist in that snapshot;
6. the preset is released, compatible with the workflow role protocol, and permits the corpus,
   query kind, source classes, and requested budget;
7. the access policy is released and its ID/hash agree with the preset;
8. every selected evidence entry has an approved immutable source pointer, allowed rights/source
   class, schema/media contract, and exact SHA-256; and
9. the Evidence Bundle and resolved plan agree on every snapshot, policy, Artifact, and hash
   pointer.

No missing or stale pointer may resolve to an implicit latest revision or to general model
knowledge as a fallback.

## 4. Dominant access patterns and data structures

- Editorial unit lookup and ancestor fill: immutable maps keyed by reviewed unit key, expected
  O(1) lookup and O(depth) traversal where depth is at most three.
- Current corpus/preset resolution: indexed unique-key lookup plus one immutable revision pointer,
  expected O(log n).
- Curriculum subtree retrieval: indexed closure lookup bounded by one ancestor unit.
- Evidence deduplication and membership: sets/unique constraints over immutable revision IDs.
- Workflow/build replay: unique idempotency key plus canonical request fingerprint.
- Reviewer history: descending indexed timestamp queries with bounded pages and pointer-only DTOs.
- State/event history: append-only monotonic events; no copied binary content in PostgreSQL.

Expected production scale is tens of curriculum units, thousands of graph nodes, hundreds of
thousands of future items, and bounded reviewer pages. No whole-graph scan or N+1 Artifact
resolution belongs in the browser path.

## 5. Transaction and concurrency boundary

Capability inspection is read-only. Evidence publication occurs before workflow creation and is
idempotent under the API-derived request identity. The workflow transaction rechecks the exact
definition and preset, pins the already-published Evidence Bundle, creates one occurrence and plan,
and enqueues one start command. A concurrent current-pointer change causes an explicit conflict.

Human approval remains a separate optimistic-concurrency boundary. Registration creates one
approved Item Revision and atomically sets the Item current-revision pointer. HWPX submission is a
separate one-shot application command after eligibility is proven.

## 6. Failure, retry, and idempotency

- Capability unavailable: disable Graph grounding; curriculum classification remains usable.
- Corpus/preset/policy/snapshot mismatch: fail before Evidence publication or worker claim.
- Evidence publication succeeds but workflow creation fails: retain the attributable immutable
  bundle; an exact replay reuses it.
- Worker, review, registration, HWPX, or download failure: preserve the occurrence and evidence;
  never submit automatically with a new idempotency key.
- Browser replay after draft mutation: return a stable conflict using the full draft-spec hash.
- The live milestone permits one fresh workflow and one HWPX build. Any further attempt requires a
  new explicit authorization.

## 7. Dependency direction and adapter ownership

The pinned curriculum contract owns editorial identities and the canonical production corpus
identity. API contracts constrain presentation input. The Application adapter derives internal
retrieval scope and calls Catalog through its private application protocol. Catalog alone reads
Graph and publishes evidence. Orchestrator alone materializes bounded context to worker
workspaces. Workers neither query Graph/DB/NAS nor communicate with each other. Scientific Studio
depends only on Application API projections and never imports Catalog infrastructure.

## 8. Reviewer provenance and history

The workflow read model must expose pointer-only provenance: plan, preset, corpus, query kind,
curriculum root, Graph Snapshot Revision, Evidence Bundle Revision, retrieval request, access
policy, hashes, and resolved timestamp. The completed workflow must surface its registered Item and
Revision so the current preview and HWPX panels can be populated without asking the user to copy
opaque IDs. Recent Item and recent HWPX lists remain bounded projections; they do not duplicate
content or artifact bytes.

## 9. Validation and acceptance

Source acceptance requires schema/model negatives, historical-fixture compatibility, exact corpus
derivation, forged-corpus rejection, unavailable-capability rejection, preset policy denial,
Evidence pointer/hash failures, idempotent replay, transaction-boundary tests, prompt/materializer
tests, GUI contract/browser tests, OpenAPI determinism, Ruff, formatting, strict mypy, repository
boundary scan, release builds, and isolated PostgreSQL integration.

Runtime acceptance requires a clean reviewed commit, exact installed provenance, the new released
preset revision, active Content Pack compatibility, READY Graph capability, and unchanged existing
services. The one live item must complete through approval and registration; its current approved
Revision must build exactly once with `eom-template`, validate, register an output Artifact
Revision, and download through the private Manager socket with matching SHA-256.

## 10. Rollback and immutable preservation

Code rollback reinstalls the previous reviewed API/GUI release. Preset rollback changes only the
logical current-revision pointer through the reviewed control-plane lifecycle; immutable preset
revisions and resolved plans remain. Graph rollback is out of scope and no Graph row is changed by
this milestone. A failed live acceptance leaves its workflow/build records as evidence and does
not alter canonical historical items.

## 11. Simpler alternatives rejected

Replacing `science-core` with another hard-coded GUI string is insufficient because it preserves
two independently mutable sources of truth and can again advertise a Graph different from the one
submitted. Letting the browser provide a Graph revision or access policy is insufficient because
it breaks authorization and replay. Mutating the existing preset revision is insufficient because
it rewrites history. Bypassing Evidence Bundle publication and handing Graph paths to a worker is
insufficient because it violates pointer validation, worker isolation, and reproducibility.
