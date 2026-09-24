# ADR 0110: Native PDF review comment panel

## Status

Accepted for implementation on 2026-09-24.

## Context

The released annotated-PDF delivery (`catalog/1.19`) paints numbered red rectangles into a derived
PDF.  This is portable visual evidence, but it does not create PDF annotation objects.  Acrobat,
Hancom, and other viewers therefore cannot list the review findings in their comment/annotation
panel.  The earlier EOM_AI client demonstrated that a location marker is most useful when the same
finding is also available from the viewer's native comment panel.  EOM_AI remains a read-only design
reference; its external-API and mutable desktop execution model are not reused.

The source PDF, completed review result, and released V1 annotation artifacts are immutable.  A
renderer upgrade must not make an old semantic request silently resolve to different bytes.

## Decision

### Protocol successor

Keep the public annotation V1 and Catalog `document-review-pdf-annotation-* /1.0` contracts
byte-stable.  Add:

- public API `document-review-annotation-v2` request with required profile
  `NUMBERED_BOXES_WITH_NATIVE_COMMENTS`;
- Catalog request/manifest/result/response `document-review-pdf-annotation-* /2.0`;
- Catalog protocol `catalog/1.21`;
- renderer identity `pymupdf-qpdf-rsvg-document-review-annotation`.

The existing endpoint accepts the V1 or V2 public request.  V1 remains the historical numbered-box
delivery.  Scientific Studio submits V2.  The V2 profile is part of the semantic request hash, so a
completed historical V1 review can produce one new V2 derivative without changing or shadowing its
old artifact.

### Canonical source and comment selection

The committed role result remains the canonical finding text.  Catalog resolves and validates that
exact result Artifact before rendering.  The API sends only typed source/result pointers and
location marks; it does not copy finding prose into a second cross-service payload.

Every red rectangle remains visible.  Native panel entries use one primary anchor per
`(finding_id, document_role)`, chosen by the already canonical mark order `(role, page, ordinal,
anchor_id)`.  This avoids duplicate panel rows for a finding that needs several location boxes,
while paired question/solution findings retain one role-local panel entry in each relevant PDF.

The native entry contains the finding ordinal, title, category, severity, description, and complete
recommendation.  Its manifest descriptor binds the selected anchor, page, role, UTF-8 content
length, and content SHA-256.  The ordered descriptor tuple has a canonical set hash.  Finding text is
a bounded immutable value derived from the result; PDF bytes remain the only large payload.

### Rendering and safety

Catalog first produces the released red-box overlay using root-owned `qpdf`, `rsvg-convert`, and
`pdfinfo`.  It then uses pinned PyMuPDF/MuPDF to add one standard `/Square` annotation per panel
entry.  The square has a transparent visual border because the existing overlay is authoritative;
`/Contents`, `/T`, `/Subj`, `/NM`, page, and rectangle make it visible in standard comment panels.
Creation and modification dates use a fixed UTC value, and document metadata is normalized before a
non-incremental deterministic save.

Catalog reopens the final PDF and verifies the exact annotation count, subtype, unique name, page,
rectangle, title, subject, content hash, and absence of external actions, file specifications,
embedded files, JavaScript, remote destinations, or launch actions.  The output then passes `qpdf
--check` and the existing bounded regular-file checks before Artifact commit.

PyMuPDF `>=1.26.7,<1.27` is a new production dependency.  It is justified because the installed
qpdf CLI can validate and rewrite PDFs but has no supported interface for creating standard
annotation dictionaries.  Hand-editing QDF object syntax would duplicate a PDF object model and be
less safe and maintainable.  The renderer receipt pins the Python module and native extension
hashes as well as the library version.

### Access patterns and complexity

Findings and marks are indexed in bounded in-memory maps by finding ID and `(finding ID, role)`.
Selection, rendering, and verification are O(p + a + f), where `p` is page count, `a` is anchor
count, and `f` is panel-entry count.  No repeated global list scans or new database lookup is
introduced.  Persistence continues to use the existing immutable annotation receipt and its unique
`(operator, workflow, semantic request hash)` constraint; no migration is required.

### Transaction, retry, and rollback

Catalog commits PDF bytes, manifest, and result as one file-set Artifact after every validation.
The API stores only immutable pointers/hashes in its existing transaction.  Same-key replay returns
the exact V2 artifact.  A renderer or validation failure commits neither a successful Artifact nor
an API receipt and never mutates the source or review result.

Rollback makes Studio submit V1 again and deploys the previous Catalog/API/Web release.  V2
artifacts remain readable through their pinned output pointer and the unchanged media endpoint.

## Rejected alternatives

Changing V1 output bytes would violate historical semantic identity and make existing idempotency
receipts return the wrong profile.  One native annotation per anchor would flood the panel with
duplicate rows.  A client-only panel would not travel with the downloaded PDF.  Writing annotation
objects in a worker would bypass Catalog validation and artifact ownership.  Hand-building PDF
objects or depending on the old EOM_AI runtime would create an unsafe parallel renderer boundary.
