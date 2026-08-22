# Generated item stimulus V1

## Decision

The knowledge-item workflow may ask the dedicated image Codex worker to author a bounded line-graph
drawing specification. The worker returns only a small typed value object. Catalog validates and
renders that value into an 800×500 PNG, commits one immutable artifact revision, and assembles its
pinned pointer into canonical `ITEM_CONTENT`. No image is prepared before the workflow and no worker
receives NAS or database access.

1. **Responsibility and boundary.** Authoring owns the scientific item draft and image brief. The
   image role owns the drawing choices. Catalog owns deterministic PNG materialization, artifact
   commit, and final Item assembly. HWPX remains a delivery adapter for an approved Item Revision.
2. **Canonical source.** Before registration, role-result artifact revisions are immutable
   provenance. After materialization, the PNG artifact revision is the canonical media. The approved
   `ITEM_CONTENT` revision pins it; a workspace copy is never canonical.
3. **Entities and revisions.** Workflow/job IDs, JSON result artifacts, generated-media artifact and
   revision IDs, Item/Item Revision IDs, and the PNG SHA-256 remain distinct.
4. **Pointers and checks.** Catalog resolves the exact image-role result revision, validates its
   schema and identity, renders a regular PNG, verifies dimensions/media/hash, commits it once, and
   stores a typed pointer. Registration rejects missing, stale, mismatched, or unapproved pointers.
5. **Access patterns.** Results and artifacts use indexed opaque-ID lookups. Drawing points are an
   ordered immutable tuple and are traversed once. Component lookup remains keyed by type/ordinal.
6. **Structures and indexes.** Existing job/artifact/revision indexes and uniqueness constraints are
   retained. The bounded line series is a tuple because stable order is part of the drawing. No new
   persistent index or schema is required.
7. **Scale and complexity.** A drawing has 2–8 points and an 800×500 RGB canvas. Validation is O(n),
   rasterization is O(width×height + plotted pixels), and peak working memory is bounded below
   5 MiB. PNG bytes
   never enter PostgreSQL.
8. **Transaction and concurrency.** The image-result revision and workflow ID form the Catalog
   artifact idempotency key. File commit completes before its pointer is persisted in workflow
   context. Registration pins that pointer in its existing transaction boundary.
9. **Dependency direction.** Workflow contracts define the draft/drawing messages. Catalog's image
   adapter implements rendering and storage. The workflow application calls the Catalog port;
   workers do not call each other, Catalog, DB, NAS, or HWPX.
10. **Failure, retry, and idempotency.** Invalid points, unsafe text, renderer errors, hash mismatch,
    or pointer mismatch fail closed. Reconciliation resolves the same result revision and reuses the
    idempotent artifact. It never substitutes a newer image.
11. **Simpler alternative.** A pre-provisioned PNG does not satisfy workflow-time drawing. Base64 in
    JSON duplicates a large payload and persists it in DB. Allowing a worker to write NAS bypasses
    validation and orchestration. A bounded drawing value plus trusted materializer is the smallest
    design that preserves the established security and provenance boundaries.

V1 deliberately supports the current real use case: a small line graph accompanying a data-table
science item. Future diagram kinds require a new schema version and renderer branch; V1 is not an
open-ended graphics framework.
