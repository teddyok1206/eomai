# ADR 0111: Readable PDF review annotations

## Status

Accepted for successor implementation on 2026-10-26 UTC. This decision does not
activate a release or rewrite an existing annotated PDF.

## Boundary and canonical source

The completed, validated review result and pinned source PDF revisions remain
canonical. Catalog alone renders and commits a derived PDF. API transports typed
pointers and the exact finding anchors; Web displays the same review result. No
worker writes an output PDF, and no source PDF or historical V1/V2 delivery changes.

The existing public V2 and Catalog requests V1–V4 keep their bytes and semantics.
A public successor request selects the readable presentation; Catalog request V5
pins that choice in `request_sha256`. Manifest/result/response V3 and renderer V3
record the indigo EOM presentation instead of falsely reporting the predecessor's
red stroke. A V5 request never falls back to the old rendering profile on failure.
Historical exact-key replay returns its historical Artifact.

## Presentation rule

For each `(finding_id, document_role)`, choose one deterministic primary anchor:
prefer an anchor whose quote contains the recommendation's existing text, then a
nonempty quote, then canonical page/anchor order. The primary anchor gets the
number and the sole native PDF panel comment. Secondary locations receive a thin
outline without duplicate numbers or panel rows. The comment uses Korean labels
and an action-first order: role/page, cited text if present, reason, recommendation,
and proposed wording. It must not claim a quote when the validated anchor has none.

The new overlay uses the Studio brand indigo with lighter box strokes and a pale
number badge; the PDF's original pixels receive no opaque region fill. It places
number badges in nearby page whitespace when available,
avoids every marked region and previously placed badge, and links displaced badges
to their region. If a page has no suitable whitespace, use a small edge badge and
keep the finding's precise rectangle visible instead of obscuring the target text
with a full-size filled label. PDF page size, original content and original
annotations are preserved. Native comment rectangles map display-space normalized
regions through the page's rotation/crop transform; unsupported geometry fails
closed rather than issuing a misleading location.

Studio's page markers are keyboard-accessible buttons. A marker selects and scrolls
to its finding; selecting a finding navigates to and highlights its primary marker.
Non-finding cross-document verification markers remain visual-only until that
separate interaction is designed. Downloaded PDFs remain portable without Studio.

## Data and execution

Access is by bounded maps keyed by `(finding_id, role)` and `anchor_id`, then ordered
per-page iteration. At most 4,096 marks and 1,024 comments are accepted by the
existing contracts. Selection and validation are O(m); per-page layout sorts marks
and scans a bounded set of candidate badge positions, O(m log m + m*k), with fixed
candidate count `k`. No DB table, index, queue or large binary row is added.

The operation reauthorizes and validates exact source/result pointers before
rendering. Source and result hashes, annotation-set hash, request hash, renderer
identity and output file hashes remain distinct. Existing Artifact file-set commit
and idempotency boundaries apply. On renderer, geometry or verification failure,
no successful Artifact/receipt is committed; retry uses the same request identity.
Rollback selects the previous UI request/compatible release without deleting new
Artifacts or reinterpreting old ones.

The simpler alternative of changing the current renderer in place is insufficient:
the same released semantic request could then produce a different PDF. A separate
PDF subsystem is unnecessary because Catalog already owns source resolution,
rendering and immutable delivery. No new runtime dependency is required.

## Acceptance

Test multi-anchor and paired roles, page-top/dense/two-column layouts, rotation and
CropBox, Korean long comments, source immutability, native panel contents/count,
unsafe-action rejection, byte/hash replay and historical V2 output. Inspect at
least one actual downloaded document in a PDF viewer; structural `qpdf` checks are
not a substitute for the visual result.
