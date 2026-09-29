# ADR 0155: Unlabeled single-image material box

## Status

Accepted.

## Context

`assessment-item-content/3.0` already distinguishes `IMAGE_ONLY` from `IMAGE_IMAGE`.  The former
means one unlabeled image, while the latter means two ordered images with editable `(가)` and
`(나)` labels.  The reviewed HwpQuestionEditor handoff nevertheless represents every image area
with the same two-column sample table.  EOM removed the label row for `IMAGE_ONLY` but left the
unused right cell and the sample row's small fixed height.  A real one-image build therefore
contained the pinned PNG bytes but could render an empty second cell and clip the picture.  The
same Item also rendered the companion DATA block as a separately titled `<자료>` table even though
the DATA text and image form one student-visible material.

The approved Item Revision and its image Artifact Revision remain canonical.  This decision changes
only the HWPX presentation projection and future Content Pack instructions.  Historical Items and
HWPX Artifacts are immutable.

## Decision

1. `IMAGE_ONLY` is a one-row, one-column image layout.  The unused right cell is removed, the
   remaining cell spans the full material width, and its minimum height accommodates the pinned
   800x500 PNG.  It never has `(가)` or `(나)`.
2. When an IMAGE layout has its required DATA block, HWPX removes only the DATA heading row and
   moves the reviewed image layout into that DATA body.  The result is one outer material box with
   student-visible facts followed by the image.  The inner layout border is hidden.  A two-image
   layout keeps two image columns and editable `(가)`/`(나)` text inside the same outer box.
3. Standalone DATA and CONDITION blocks keep their existing labels.  TABLE, MIXED, INQUIRY, and
   text-only projections are unchanged.
4. Future authoring must introduce one IMAGE material once.  It must not coordinate one companion
   DATA block and its image as if they were two independent sources (for example, `자료와 그림`).
   Literal block markers such as `<자료>` do not belong in `stem`; deterministic serialization owns
   those markers.  Review reports this as the repairable
   `MATERIAL_PRESENTATION_REDUNDANT` finding.

## Structure, complexity, and safety

The renderer resolves the already bounded visual table and at most two labeled-block table reports
by ID, then performs one linear XML traversal.  Time and temporary space are `O(E)` for the bounded
section element count.  No database state, Artifact bytes, or pointer identity changes.  The PNG
remains one package-internal `BinData` member referenced by its existing binary item ID; no path or
binary is copied into PostgreSQL.

The rewrite occurs after the immutable handoff validator has accepted the authored content and
before pinned PNG injection.  It fails closed on an absent or ambiguous DATA table, visual table,
cell, paragraph, or size node.  Package safety is revalidated before replacement.  Retry uses the
existing new-build identity; a historical delivery is never mutated.

The simpler alternative of hiding only the empty cell would retain a semantically two-column table
and could still clip the image.  Removing only the `<자료>` text would leave a blank heading row.
Rewriting the approved Item would incorrectly turn a presentation repair into canonical-content
mutation.  The bounded projection is therefore the smallest complete fix.
