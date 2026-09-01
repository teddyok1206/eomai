# Generated item image planning V3

Status: implementation design

Last reviewed: 2026-09-01 UTC

## Responsibility and system boundary

The authoring role decides one explicit image production route before the image role runs. The
current EOM question template still requires one final 800×500 PNG stimulus; this decision controls
how that PNG is produced, not whether the template contains an image block.

Two routes are executable:

- `DETERMINISTIC_SVG`: graphs, tables, apparatus, maps, particle models, labels, equations, and
  geometric/scientific structure are drawn and rasterized deterministically. No local model request,
  GPU fixed unit, model load, or GPU lock may occur.
- `HYBRID_LOCAL_GENERATIVE`: the local model produces only the semantic raster layer that is hard to
  draw deterministically, such as a person, animal, organism, complex natural object, or realistic
  scene. A validated SVG overlay still owns every authoritative label, arrow, boundary, scale,
  equation, and geometric relation. Catalog composites both layers into the final PNG.

The word `realistic` in a route reason describes the presence of a natural object or scene; it does
not authorize photorealistic rendering. Both routes share one reviewed presentation language:
pure-white background, simplified anonymous forms, minimal facial detail, crisp dark outlines,
flat shapes, and restrained grayscale or limited flat color. It also requires one coherent
single-panel composition with the exact requested subject count and forbids collage/contact-sheet
layouts or duplicate subjects. The fixed local-provider adapter
prepends that style contract to every GPU request. Worker-authored generation text describes only
the subject, pose, and placement. Conflicting photo, detailed-face, 3D, gradient, shadow, dramatic
lighting, or cinematic directives fail before the fixed GPU unit starts.

External image APIs remain forbidden. `LOCAL_GENERATIVE_BACKGROUND` remains a historical V5 value
and is not reinterpreted.

## Canonical source and revision model

```text
authoring-result@6.0 image plan
    -> image-result@6.0 exact copied plan + SVG overlay
    -> deterministic SVG renderer
       OR pinned local raster provider + deterministic SVG renderer
    -> immutable generated-stimulus Artifact Revision
    -> approved Item Revision image component pointer
```

The workflow result revision, provider binding, provider request, generated raster member, SVG
member, final PNG member, receipt, and their hashes remain separate. Workspace paths are temporary
materialization locations, not identity.

## Image-plan contract

The vector image plan records a route and one reviewed reason code. Deterministic reasons and hybrid
reasons are disjoint. A deterministic plan requires `generation_prompt=null` and
`negative_prompt=null`; a hybrid plan requires a bounded generation prompt. JSON Schema and the
typed model enforce the same invariant before a worker result can be accepted.

The supported reason codes are intentionally small:

- deterministic: `DATA_VISUALIZATION`, `SCIENTIFIC_SCHEMATIC`, `GEOMETRIC_DIAGRAM`,
  `MAP_OR_SPATIAL_DIAGRAM`;
- hybrid: `HUMAN_OR_ANIMAL_REQUIRED`, `ORGANIC_OBJECT_REQUIRED`,
  `REALISTIC_NATURAL_SCENE_REQUIRED`, `COMPLEX_NATURAL_TEXTURE_REQUIRED`.

The route is not inferred from prompt text or image kind. A changed route or reason produces a new
role-result revision and a new artifact identity.

`generation_prompt` is content data rather than an unrestricted style prompt. Catalog owns the one
authoritative renderer style. This keeps deterministic Python/SVG diagrams and optional GPU pixels
visually coherent and prevents a later content worker from overriding the reviewed exam-figure
presentation boundary.

## Required pointers and resolution checks

Catalog validates the exact authoring/image schema family, byte-equivalent plan fields, SVG safety,
provider binding and model revision, request and receipt hashes, fixed output members, media type,
dimensions, ownership, mode, symlink status, and final artifact hash. It never resolves an implicit
latest model or substitutes another production route.

## Access patterns and data structures

- Route and reason validation use immutable sets, O(1) membership.
- Role-result and artifact resolution use indexed immutable revision IDs.
- SVG validation is one bounded ordered traversal, O(nodes + attribute bytes).
- Artifact assembly uses one keyed manifest; PNG/SVG bytes are never stored in PostgreSQL.
- The single-GPU route uses the existing fixed-unit lock and is reached only by the hybrid branch.

Expected per-item scale is one image plan, at most one local raster request, one SVG overlay, and one
final PNG. A general image scheduler would duplicate the existing durable workflow step without a
second scheduling use case.

## Transaction, concurrency, retry, and idempotency

The image workflow step is the durable attempt. Provider execution occurs outside the artifact
commit transaction. Its request identity pins the workflow, image-result revision, drawing hash,
and provider binding hash. Re-entry validates and reuses the exact receipt; it never chooses a new
seed or invokes the provider twice. There is no automatic route fallback. A provider failure fails
the image step before Item registration.

The deterministic branch never constructs a provider request. This is both a capacity invariant and
a security boundary: an item that does not require generative pixels cannot consume GPU time.

## Dependency direction and adapter ownership

Workflow schemas and frozen models own the plan. Catalog owns plan verification, SVG sanitation,
route dispatch, composition, and Artifact commit. The isolated provider owns only local model
inference and pixel composition. Workers have no DB, NAS, peer-worker, model-store, or provider
access. GUI/API clients do not select provider IDs or model revisions.

## Failure behavior and rollback

Unknown routes, mismatched reason/prompt combinations, changed authoring fields, unsafe SVG,
unavailable provider, invalid receipt, or hash mismatch fail closed. Historical V5 workflows and
Content Pack 1.4 remain readable. Rollback activates the preceding immutable Content Pack and
workflow definition without rewriting any result or artifact.

## Simpler alternative and why it is insufficient

A free `use_gpu` boolean duplicates the route and permits contradictory states. Inferring GPU use
from `kind` or prompt text is unstable and unauditable. Always invoking the model wastes scarce GPU
capacity and introduces nondeterministic pixels into diagrams that require exact geometry. The typed
route plus disjoint reason/prompt invariants is the smallest explicit design that satisfies the
current product need.
