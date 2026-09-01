# Local GPU image orchestration V1

Status: implementation design; production route disabled until source and runtime gates pass

Last reviewed: 2026-09-01 UTC

## Responsibility and boundary

The existing generated-item image step remains the durable orchestration record. A validated V5
image result may select `LOCAL_GENERATIVE_BACKGROUND`; Catalog then constructs one typed provider
request, rasterizes the sanitized SVG overlay, starts one fixed local GPU unit, validates the
background/composite receipt, and commits one immutable Artifact Revision. The isolated provider
performs only the pinned Pillow alpha-composite operation; Catalog owns its contract and validates
the result because Pillow and GPU dependencies deliberately remain outside the Catalog runtime.

The Codex worker never calls the model, sees the model store, writes NAS, or communicates with the
provider. The fixed provider unit has no network or NAS access. Catalog owns input staging,
composition policy, result validation, and artifact commit.

## Canonical source and revision model

```text
image result Artifact Revision
  -> immutable provider binding snapshot
  -> local generation request hash
  -> approved LocalImageModelRevision
  -> generated background + generation receipt
  -> sanitized SVG overlay
  -> deterministically composited PNG
  -> generated stimulus Artifact Revision
  -> Item Revision image component pointer
```

Paths are materialization locations, never identity. The model ID, model revision ID, manifest
SHA-256, image-result revision, request SHA-256, receipt SHA-256, member hashes, and final Artifact
Revision remain distinct.

## Required pointers and resolution checks

The operator binding pins the exact approved model pointer, sampler contract, timeout, and route
contract. Workflow binding copies this immutable value into runtime context before any worker runs.
Materialization rejects a missing/stale binding, changed binding hash, changed model manifest,
mixed workflow protocol family, unsafe workspace, symlink, wrong ownership/mode, changed receipt,
changed prompt hash, wrong canvas, wrong output hash, or unexpected Artifact member.

The generated background, canonical SVG overlay, provider receipt, and final PNG are separate
members of one keyed Artifact manifest. The Item points only to the final PNG member. Background
pixels never become the source of required labels, numeric scales, equations, or diagram topology.

## Dominant access patterns and data structures

- Provider binding: one key lookup by immutable binding SHA-256.
- Model files: manifest map keyed by relative path; verification is O(number of files + bytes).
- Workflow re-entry: deterministic request ID lookup by workflow/image revision/drawing/binding hash.
- GPU exclusion: one non-blocking OS file lock for the single physical GPU.
- Artifact members: fixed keyed map with four members and exact expected hashes.
- SVG validation: bounded ordered tree traversal, O(nodes + attribute bytes).

Expected scale is one GPU, one provider unit at a time, and at most one generated background per
image-result revision. A DB queue or general scheduler would add a parallel framework without a
second use case.

## Transaction and concurrency boundary

The existing workflow image step is the durable job and attempt record. Provider execution occurs
outside the Artifact commit transaction. Its fixed systemd unit holds the GPU lock from before
model load through receipt finalization. A crash releases the OS lock; the workflow step fails and
preserves its workspace for diagnosis.

A completed exact receipt is idempotent evidence. Re-entry with the same request validates and
reuses it without another model invocation. A partial workspace fails closed and is never silently
deleted or regenerated. Artifact commit remains the only NAS write boundary.

## Failure, retry, and idempotency

The request ID and idempotency key are derived from the pinned workflow ID, image-result revision,
drawing hash, and provider binding hash. Prompt, negative prompt, seed, sampler, model pointer, and
canvas are included in the self-hashed request.

Stable failures include unavailable binding/model/GPU, hash mismatch, timeout, OOM, invalid output,
unsafe workspace, and fixed-unit failure. There is no automatic fallback to deterministic SVG and
no automatic regeneration with a new seed. A different output requires an explicit new workflow
attempt.

## Dependency direction and adapter ownership

Image contracts contain only JSON Schema 2020-12 and frozen value models. Workflow contracts retain
the already-reserved production-route enum. Catalog application code owns request derivation,
workspace handoff, receipt validation, SVG sanitation, and Artifact commit. The isolated provider
owns PyTorch, Diffusers, CUDA, Pillow composition, and model-file access. The GUI and workers import
neither provider infrastructure nor GPU dependencies.

## Runtime and identity boundary

- `eom-workflow-runner`: creates an exact group handoff workspace and may start only a validated
  `eom-image-provider@imgreq_....service` instance.
- `eom-image`: has no login, sudo, Codex auth, DB credentials, NAS access, or worker membership; it
  can read the immutable model store and write only its exact request workspace.
- Model store: `root:eom-image`, directories 0750, files 0640.
- Workspace root: `root:eom-image:3770`; request workspace
  `eom-workflow-runner:eom-image:1730`; staged input 0440; provider output 0640. Sticky bits prevent
  the provider from replacing runner-owned inputs or deleting sibling workspaces, and the request
  directory deliberately omits group read/list permission.
- The workflow runner cannot read model weights. The provider cannot read source checkout, worker
  homes, EOM secrets, or NAS.

## Composition contract

Catalog reconstructs and sanitizes the SVG overlay, rasterizes it to a transparent 800x500 PNG
using the existing fixed librsvg/font contract, and stages that overlay beside the provider request.
The isolated provider uses pinned Pillow to alpha-composite the overlay over the 800x500 RGB
background. The final PNG is RGB, 800x500, bounded in size, and hash-verified.

The receipt records the background hash, overlay hash, final hash, model pointer, generation
request/receipt hashes, runtime versions, and compositor version. Exact scientific markings remain
in the SVG and its deterministic raster, not in model-generated pixels.

## Failure containment and rollback

Until a new immutable Content Pack release explicitly permits the local route, production remains
deterministic SVG only. Rollback reactivates the prior pack release and removes the provider unit
authorization; it does not rewrite workflows, receipts, artifacts, or model revisions. API, HWPX,
observability, textbook-analysis Slot 5, port 8000, and `/home/eom/EOMIS` are outside this change.

## Simpler alternative and why it is insufficient

Calling the CLI directly from the workflow runner would avoid a unit and handoff workspace, but it
would place CUDA dependencies and device access in the orchestrator process and expose model files
to it. Creating a new provider-job DB queue would satisfy future multi-provider scheduling but
duplicates the existing durable image step for a single GPU and one current provider. The fixed
unit plus existing step record is the smallest boundary that preserves isolation, idempotency, and
traceability.
