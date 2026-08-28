# Generated item vector stimulus V2

## Decision

EOM produces new assessment visuals through a vector-first pipeline. An image worker returns a
bounded SVG overlay as typed JSON data. Catalog treats that SVG as untrusted input, validates a
small reviewed subset, adds a deterministic background, emits a canonical SVG, rasterizes it to the
fixed 800×500 PNG required by the current HWPX template, and commits both files in one immutable
Artifact Revision. The approved Item Revision continues to point to the PNG member; the SVG member
is retained for reproducibility, editing, and future delivery formats.

The existing `workflow-role/1.3.0` and `*-result@4.0` bytes remain historical and unchanged. V2 uses
one new role-protocol family and one new workflow definition. A workflow never mixes old and new
result families.

## Responsibility and boundary

- Authoring chooses the visual kind and records exact scientific constraints.
- The image worker creates only the typed drawing result and SVG overlay. It has no network, DB,
  NAS, provider credential, or peer-worker access.
- Catalog owns SVG validation, deterministic background composition, rasterization, Artifact
  registration, and the pointer inserted into canonical `ITEM_CONTENT`.
- HWPX remains a delivery adapter for the approved PNG pointer.
- A future local generative provider is an infrastructure adapter invoked by the orchestrated
  Catalog use case, never by a worker. External LLM/image APIs remain forbidden by `AGENTS.md`.

## Routing policy

| Visual need | Default route | Reason |
| --- | --- | --- |
| graph, table-like plot, circuit, apparatus, map, particle model | deterministic SVG | numeric and geometric fidelity |
| stylized person, organism, scene, or composite | SVG overlay first | editable, auditable, print-safe |
| organic background that cannot be expressed safely as SVG | local generative background plus SVG overlay | separate nondeterministic pixels from exact labels and geometry |
| reviewed staff artwork | immutable reviewed artifact plus SVG overlay | preserve human review and provenance |

V2 initially enables deterministic SVG. The two background-provider routes are reserved typed
values and fail closed until a reviewed local provider adapter and its capacity boundary are
deployed. There is no implicit fallback from a requested generative or reviewed background to a
different visual.

## Canonical source and revision model

```text
image role result Artifact Revision
    -> typed image plan + untrusted SVG overlay
    -> Catalog validation/materialization
    -> generated stimulus Artifact Revision
         - generated-stimulus.svg
         - generated-stimulus.png (primary current delivery member)
    -> approved ITEM_CONTENT image pointer
    -> approved Item Revision
```

Workflow ID, role-result Artifact ID/revision/hash, stimulus Artifact ID/revision/hash, Item ID,
Item Revision ID, renderer identity, and member names remain separate. A workspace file is temporary
materialization, not canonical identity.

## Pointer and validation contract

Before committing output, Catalog verifies:

1. the authoring and image results are the matching V5 schema family;
2. all copied brief fields are exactly equal;
3. the SVG is bounded UTF-8 text with no DTD, entity, script, stylesheet, external reference,
   embedded raster, animation, filter, event handler, or foreign namespace;
4. the root canvas is exactly `800×500` with `viewBox="0 0 800 500"`;
5. every element, attribute, coordinate, color, stroke width, font size, text value, path command,
   and total node count satisfies the reviewed allowlist;
6. canonical serialization is stable and produces the same SHA for the same plan;
7. rasterizer and Korean font identities are fixed, their exact byte hashes are recorded, the
   renderer process has a bounded timeout/output size, and its result is a regular non-symlink PNG
   with the exact dimensions;
8. both SVG and PNG are committed together and the returned pointer identifies the exact PNG
   member and Artifact Revision.

## Access patterns and data structures

- Result and artifact resolution is indexed opaque-ID lookup.
- SVG elements are bounded ordered trees; one depth-first pass validates and reconstructs a clean
  tree, O(nodes + attribute bytes), with at most 256 elements and 64 KiB input.
- Allowed elements and attributes use immutable sets/maps for O(1) membership and rule lookup.
- Background primitives are an ordered immutable tuple so canonical SVG bytes are stable.
- Artifact membership is a keyed manifest; no PNG or SVG bytes enter PostgreSQL.

At 800×500, raster output and working memory remain bounded. Provider work, if introduced, uses a
separate queue/capacity limit and cannot consume the textbook-analysis Slot 5.

## Transaction, concurrency, and idempotency

Catalog materializes beneath its private staging root. The image-result revision, renderer contract
version, and canonical drawing hash form the artifact idempotency input. The expected hashes and
typed metadata of both members are checked against the committed manifest, including idempotent
re-entry. File commit completes before the workflow context stores the stimulus pointer.
Reconciliation re-resolves the same immutable role result and reuses the same artifact; it never
selects a newer result or provider output. A renderer-policy change requires a new renderer contract
version rather than changing the meaning of an existing key.

A future nondeterministic provider request must have a persisted idempotency key and one accepted
provider output revision. Automatic regeneration is forbidden unless a separate attempt is
explicitly authorized.

## Dependency direction

Workflow schemas and frozen models own the message contract. Catalog owns the SVG security policy
and renderer adapter. The workflow engine calls the existing Catalog port. No domain or contract
module imports subprocess, filesystem, HTTP, or provider infrastructure.

The runtime dependencies for deterministic SVG rasterization are Ubuntu's official `librsvg2-bin`
and `fonts-droid-fallback` packages. Catalog invokes the fixed `/usr/bin/rsvg-convert` path after the
SVG has been sanitized and permits only `Droid Sans Fallback` from the fixed system font path. The
renderer version and both executable/font hashes are recorded in Artifact provenance. This is
chosen instead of a broad Python graphics dependency because it provides mature Korean text/path
rasterization while the process boundary remains independently timeout- and size-bounded.

## Failure and rollback

Unsafe SVG, changed authoring constraints, unavailable provider, missing rasterizer, timeout,
invalid output metadata, or hash/pointer mismatch fails the image step before Item registration.
No partial Item Revision is created. V4 workflows and artifacts remain readable and executable.
Rollback selects the prior workflow definition, Content Pack release, and execution preset; it does
not rewrite any V5 result or artifact.

## Simpler alternative and why it is insufficient

Continuing the V1 line-graph-only Python renderer cannot express people, organisms, apparatus,
maps, or composite scenes. Accepting arbitrary SVG directly would permit active content, external
loads, resource exhaustion, and unstable raster output. Generating only raster pixels loses exact
labels, geometry, editability, and deterministic recomposition. The bounded SVG overlay plus
Catalog-owned background and rasterization is the smallest extension that supports the requested
visual range while preserving the existing security and provenance model.
