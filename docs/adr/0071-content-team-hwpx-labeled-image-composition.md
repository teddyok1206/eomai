# ADR 0071: Content-team HWPX labeled-block and image composition

## Status

Accepted.

## Context and responsibility

Item Content V3 already permits an ordered combination of `DATA`/`CONDITION` labeled blocks and
one or two `IMAGE` visual slots.  The immutable HwpQuestionEditor handoff implements those shapes as
separate parser branches over the same reviewed visual-area table.  A valid Item containing both
therefore reached HWPX rendering before failing: the labeled-block branch rejected the following
image marker.  A labeled-only Item also retained the handoff's empty two-column visual sample.

The Catalog Item Revision remains the canonical source.  The HWPX builder is a projection adapter;
it may change only presentation geometry at its validated materialization boundary and must not
rewrite the approved Item, image bytes, or immutable handoff archive.

## Decision

1. For labeled blocks plus image-only visual layouts, render the labeled blocks first through the
   existing reviewed handoff branch.  Then replace the same structurally identified visual-area
   sample with one or two image placeholders through the reviewed visual-slot renderer.  The
   existing image binder finally replaces those placeholders with the exact pinned PNG members.
2. If no typed visual exists, hide the empty visual sample even when labeled blocks exist.  Actual
   labeled-block tables are separate prototype-derived nodes and remain untouched.
3. Keep `IMAGE_TABLE`, `TABLE_IMAGE`, and table-only combinations on the native handoff branch.
   Those layouts require table dependency installation and are not silently coerced into this
   image-only projection.
4. Record whether the composition was applied and its exact slot count in the renderer report.
   The wire contracts remain unchanged: they already define the valid typed combination.

The frequent operations are one ordered pass over at most two visual slots and one indexed ZIP
member lookup.  XML structural lookup and archive rewriting are linear in the bounded HWPX member
and node counts.  No large payload or derived copy is persisted in PostgreSQL.

## Safety, failure, and retry

The handoff ZIP, Item JSON/Markdown, and PNGs are independently hash-validated before execution.
The visual area must match its reviewed structural signature exactly; zero or multiple matches fail
closed.  Repackaging uses a fresh same-directory temporary file, validates package safety, and then
atomically replaces only the workspace projection.  The orchestrator-owned HWPX manager continues
to commit a successful artifact to NAS only after the isolated renderer result is validated.

The HWPX builder has a separate runtime environment from the API release.  Its deployment verifier
therefore compares the installed composition adapter byte-for-byte with the repository source, in
addition to the entry point, exam renderer, models, and schemas.  A generic API deployment cannot
silently leave an older composition adapter installed.

Retries use the existing idempotent build boundary.  A terminal failed build is not mutated; a new
attempt receives a new build identity while referencing the same immutable Item Revision.

## Alternatives

Changing the approved Item to remove its `DATA` block would destroy the intended exam structure.
Changing the team-lead prompts or duplicating the image inside a labeled-block string would bypass
typed image identity and validation.  Publishing a new 44 MiB handoff snapshot solely to connect two
already reviewed renderers would add a larger immutable release surface without changing the wire
contract, so the narrow projection adapter is preferred.
