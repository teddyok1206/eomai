# ADR 0104: Office document review through immutable PDF projections and redline HWPX successors

- Status: Accepted for implementation
- Date: 2026-09-22

## Context

PDF document review already accepts one immutable PDF, renders exact page images, runs the fixed
document-review worker, and stores page-anchored findings. Users also need to submit HWP v5 and
HWPX documents. Codex must still receive the same bounded PDF/page representation. For a confirmed
text replacement in an HWPX source, the user also wants an explicit action that creates an editable
HWPX successor in which only the replacement text is red.

The source document must never be edited in place. A PDF anchor is not by itself a safe HWPX edit
address, and a worker recommendation is not authority to mutate a document. The current server has
Poppler but no Office-document converter. Ubuntu provides LibreOffice Writer and the H2Orestart
import filter. H2Orestart supports HWP v5 and HWPX import, but its registered filter is import-only;
it cannot truthfully export an arbitrary HWP source as HWPX.

## Decision

### Responsibility and boundary

Add a successor document-intake boundary that accepts PDF, HWP v5, and HWPX. PDF remains an
identity conversion. HWP/HWPX are opened by a fixed, offline LibreOffice + H2Orestart converter in
an isolated profile and exported to a bounded PDF. The existing PDF review workflow receives only
the exact derived PDF pointer and rendered page pointers. It does not receive Office bytes and its
review behavior does not change.

The original upload, derived review PDF, rendered page images, conversion identity, and hashes are
committed as one immutable intake Artifact Revision. The uploaded source is canonical; the PDF and
PNGs are reviewed projections.

Automatic correction is a separate explicit application command after a completed review. It is
available only when all of these conditions hold:

1. the immutable uploaded source is HWPX;
2. the selected finding is a final `CONFIRMED` finding from the exact committed review result;
3. its recommendation operation is `REPLACE` with non-empty `before_text` and `after_text`;
4. the exact normalized `before_text` has one and only one safe paragraph occurrence in the pinned
   base HWPX revision; and
5. the source package, XML parts, revision, hashes, lifecycle, and permissions validate again at
   execution time.

The action creates a new HWPX Artifact Revision. It never overwrites the upload or a prior corrected
revision. The replacement run inherits the source character style except that its text color is
`#FF0000`. Unchanged text and package members remain semantically unchanged. The output is HWPX
only; no corrected PDF or HWP is produced.

PDF sources are review-only. HWP sources are reviewable through the derived PDF, but automatic
correction is reported as unavailable until a separately reviewed HWP-to-HWPX exporter exists.
Reconstructing an arbitrary HWP through Markdown, HTML, DOCX, OCR, or page images would lose layout
or editability and must not be presented as a corrected source.

### Canonical source and revision model

```text
uploaded document logical ID -> immutable intake revision
                             -> exact original source member (PDF/HWP/HWPX)
                             -> exact review PDF member
                             -> ordered page PNG members
                             -> conversion manifest and hashes

completed review workflow    -> immutable result Artifact Revision
                             -> confirmed finding and recommendation

correction logical ID        -> pinned source/base HWPX revision
                             -> pinned review result revision + finding ID
                             -> immutable correction plan
                             -> validated redline HWPX Artifact Revision
```

Paths are storage locations, not identities. Every cross-service request carries logical ID,
revision ID, member path, schema/media type, content length, and SHA-256 needed for resolution.
The correction command returns only a typed Artifact member pointer and compact correction result;
the HWPX bytes cross the API boundary through a separate authenticated, hash-checked streaming
operation. No correction binary is copied into PostgreSQL or a JSON response.

### Converter dependency and isolation

The Office conversion adapter uses the distribution-owned LibreOffice Writer executable and the
H2Orestart extension because no existing EOM module can render arbitrary HWP/HWPX documents. This
is a real adapter boundary and the reason for the new system dependency. Ubuntu 24.04 supplies
H2Orestart 0.6.1 as the base package, but that importer aborts on valid newer HWPX features observed
in production documents. Each fresh conversion profile therefore registers the reviewed upstream
H2Orestart 0.7.14 OXT whose release digest is pinned by the installer and worker. The OXT remains a
root-owned, read-only runtime artifact outside Git; conversion still has no network access. The
release records the LibreOffice executable/version and exact extension bundle SHA-256 in the intake
manifest.

An image-heavy production HWPX exposed a second, narrower incompatibility in upstream 0.7.14. Its
picture-crop path asks LibreOffice to store each decoded `XGraphic` as an intermediate PNG before
Java crops it. The intermediate round-trip can terminate an otherwise valid conversion. EOM uses
compatibility revision `0.7.14-eom.1` (declared OXT version `0.7.14.1`) from the exact upstream tag.
The reviewed GPL-3.0 source patch decodes supported raster bytes directly with ImageIO and keeps the
already decoded original `XGraphic` when a vector or malformed crop cannot produce a safe raster
derivative. The upload itself is never rewritten. The repository stores the small source patch and
provenance, not the generated OXT; the installer accepts only the reviewed OXT and patch hashes and
places both in the root-owned vendor directory. The exact OXT hash continues to be recorded in the
existing conversion identity, so no released intake schema changes or silently reinterprets prior
conversions.

The dominant operation remains one ordered pass over the document pictures. Direct raster decoding
is linear in compressed input plus decoded pixels and removes one full intermediate PNG write/read.
No database, queue, worker protocol, or NAS ownership boundary changes. A failed conversion remains
retryable through the existing upload application command; it never edits an earlier attempt or
substitutes an implicit latest converter. The simpler alternatives—raising memory limits without
evidence, mutating uploaded crop metadata, or accepting an unpinned extension—would either fail to
address the importer boundary or break source fidelity and reproducibility.

The installer additionally requires the Ubuntu `unzip` package only to validate the OXT container
and its declared version before installation; it is not part of the runtime document parser.

H2Orestart maps HWP/HWPX equation controls to LibreOffice Math UNO objects, including equations
inside table cells. `libreoffice-writer` alone can load ordinary documents but returns no Math
property object when the separate `libreoffice-math` package is absent; the importer then aborts
without producing a PDF. The reviewed dependency closure therefore includes the same-version
`libreoffice-math` package. Installation and deployment verify the root-owned Math component and
registry files, and the isolated worker rejects a missing component at dependency validation rather
than reporting an ambiguous missing output. This adds no networked service or conversion path: Math
is a local LibreOffice component used by the already selected H2Orestart adapter.

Conversion uses a fresh mode-0700 workspace and a fresh LibreOffice user profile, no network, a
bounded wall-clock timeout, bounded input/output, and no NAS access from the converter process. The
Artifact-owning application validates the output PDF before commit. Macros, embedded executable
content, external links, duplicate ZIP entries, traversal, encrypted sources, and conversion
ambiguity fail closed.

### HWPX edit address and red style

The browser submits only a finding ID and concurrency/idempotency guards. It never submits an XML
part or filesystem path. The application derives a typed edit plan by scanning the HWPX section
parts once in spine order and building a map from normalized paragraph text to candidate
occurrences. Duplicate matches are rejected; they are not resolved by choosing the first match.

An edit address pins section member, paragraph ordinal, paragraph text SHA-256, Unicode start/end
offsets, source character-property ID, and before/after hashes. The editor checks all of them again.
It may split ordinary text runs, but it refuses selections that cross equations, pictures, controls,
paragraphs, or unsupported XML nodes.

The header character-property collection is keyed by integer ID. The editor clones the source
property, allocates `max(existing IDs) + 1`, changes only `textColor` to `#FF0000`, updates the
collection count, and assigns that ID only to the replacement run. A post-build validator requires
the exact replacement text, exact red property, preserved package safety, no external reference,
and a changed output SHA-256.

### Access patterns and data structures

Dominant operations are indexed identity lookup, ordered section/paragraph iteration, unique text
membership, immutable revision history, and idempotent creation.

- workflow/correction lookup uses indexed IDs and unique idempotency keys;
- source and result pointers use maps keyed by immutable ID/revision/member;
- HWPX members use a name-keyed map after duplicate and case-collision rejection;
- paragraph occurrences use a hash map from normalized text to an ordered tuple of addresses;
- selected finding IDs use a set for membership and duplicate rejection; and
- correction history is append-only and ordered by creation time and correction ID.

For package bytes `B`, paragraphs `P`, text code points `T`, and edits `E`, validation and indexing
are `O(B + P + T + E)` time and bounded linear memory. An edit does not repeatedly scan all
paragraphs per finding. The expected scale is at most 256 MiB per upload, 2,000 pages, 4,096 HWPX
members, and 32 selected corrections per command.

### Transactions, concurrency, retry, and idempotency

Upload intent claim, Catalog intake commit, Workflow start, correction creation, and output commit
remain separate bounded transactions. Exact idempotency keys and immutable input hashes make a
timeout replay adopt the same result. Correction creation has a unique identity over review result
revision, base HWPX revision, and ordered finding IDs. A stale base revision or reused key with
different input fails explicitly.

No database transaction spans LibreOffice conversion or HWPX rewriting. State transitions are
compare-and-set. Failed attempts and prior revisions remain historical evidence; they are never
rewritten to success.

### Dependency direction

JSON Schema and frozen Pydantic value models own the wire contracts. Application services own
authorization, idempotency, transactions, and pointer resolution. LibreOffice and HWPX XML/ZIP
handling are infrastructure adapters. Scientific Studio calls application use cases and never
reads NAS or constructs edit addresses. The review worker remains read-only and has no correction
authority.

### Failure behavior

Unsupported signatures/versions, converter absence or drift, encrypted documents, timeout,
unsafe HWPX packages, malformed XML, ambiguous/missing before text, stale review/source pointers,
unsupported recommendation operations, concurrent base drift, and validation mismatch return
stable failures. The UI disables correction when the source or finding is ineligible and explains
why. It never fabricates a successful corrected document.

### Simpler alternatives rejected

Changing the existing PDF V1 schemas would reinterpret released history. Sending HWP/HWPX directly
to Codex would create format- and sandbox-dependent behavior. Editing the upload in place would
destroy provenance. Blind string replacement across ZIP XML could change duplicate text or corrupt
controls. Reconstructing HWP as HWPX through an unrelated intermediate format would not preserve
the user's document. A new generic document framework or queue is unnecessary; the existing upload,
Workflow, Catalog Artifact, and HWPX validation boundaries can be extended with successor contracts.
