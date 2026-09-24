# ADR 0105: Paired document review and immutable annotated PDF

## Status

Accepted for implementation on 2026-09-22.

## Context

The released document-review path accepts one immutable PDF projection and returns page-anchored
findings.  Real editorial work often has two independently paginated sources: a problem booklet and
an answer/explanation booklet.  A reviewer must be able to say both where the problem appears and
where its answer or explanation appears.  Treating the two files as one byte stream would make page
identity ambiguous and would weaken replay, authorization, and hash verification.

The earlier EOM_AI desktop review UI demonstrated that page-local normalized rectangles are useful
for visual review.  Its external-API execution model and mutable client behavior are not reused.
EOM keeps local workers, orchestrator mediation, immutable Artifact revisions, and server-side
authorization.

Users also want a visually annotated PDF.  The source PDF must never be edited.  Annotation is a
derived review deliverable, not a corrected source and not a worker-owned NAS write.

## Decision

### Protocol successor

Keep `pdf-document-review@1.0.0`, `workflow-role/1.25.0`, and result `@1.0` byte-stable.  Add a
successor pair:

- Workflow `pdf-document-review@1.1.0`;
- role protocol `workflow-role/1.26.0`;
- result `pdf-document-review-result@2.0`;
- request `paired-document-review-request/1.0`.

The request contains an ordered tuple with exactly two members: `QUESTION`, then `SOLUTION`.  Each
member points to one immutable Catalog document revision and its PDF projection.  Every review
anchor carries its document role, physical page number, page-image hash, normalized parts-per-million
rectangle, and optional short quote/hash.  Cross-document checks always carry a non-empty question
anchor set.  They carry a non-empty solution anchor set for `MATCHED`, `MISMATCH`, and
`INSUFFICIENT`; `MISSING` carries no solution anchor so the protocol cannot invent a location for
absent content.

### Canonical source and identity

The canonical sources remain the two Catalog-owned document revisions.  The paired review request,
Workflow, result Artifact, annotation manifest, and annotated PDF are separate immutable revisions.
A filesystem path is never used as identity.  Reproducible history pins both document revisions,
page-image hashes, the preset revision, and the request hash.

### Upload aggregate and access patterns

The API owns a small coordination aggregate:

```text
review set (key lookup by set id, owner-ordered listing)
  -> member[QUESTION] (unique by set id + role)
  -> member[SOLUTION] (unique by set id + role)
  -> at most one Workflow pointer
```

Uploaded bytes are streamed to the existing Catalog intake one member at a time and are never stored
in PostgreSQL.  Dominant operations are primary-key lookup, membership by `(review_set_id, role)`,
owner/date listing, and expired-lease lookup.  B-tree primary/unique/partial indexes implement these
operations.  All set transitions use a row lock and compare the per-member server-generated lease
owner.  Starting the Workflow is idempotent on the review-set identity.  Expected scale is hundreds
of sets and at most two members per set, so all in-memory set operations are constant-sized; global
listing remains indexed and paginated.

### Materialization and dependency direction

The API calls existing application adapters; it does not write Catalog tables.  Catalog commits each
source revision.  The orchestrator resolves the successor plan, authorizes both revisions, and stages
them under role-separated paths:

```text
source/question/images/page-000001.png
source/question/text/page-000001.json
source/solution/images/page-000001.png
source/solution/text/page-000001.json
```

Workers only read that workspace and submit a typed local result.  They do not communicate with each
other and do not write to NAS.  The orchestrator validates result identities, roles, page numbers,
page hashes, quote hashes, cross-document relations, and mutation=false before the normal Artifact
commit.

### Annotated PDF

Catalog owns annotation materialization after a validated committed review result.  For each source
role it creates a new Artifact revision containing:

- the unchanged source PDF hash/pointer in a typed manifest;
- one derived annotated PDF;
- a canonical annotation manifest binding finding ordinal, finding ID, document role, page, and
  normalized rectangle;
- tool identities and output hashes.

The renderer creates page-local SVG overlays from validated rectangles, converts them with the
installed root-owned `rsvg-convert`, and applies them with the installed root-owned `qpdf`.  The
overlay contains numbered red rectangles only; finding text remains in the typed result/UI.  This
avoids font substitution and keeps exact finding text searchable in the application.  Output is
validated as a bounded PDF with no external-file reference before Catalog commits it.  The operation
is idempotent on source revision + review-result revision + canonical annotation-set hash + renderer
identity.  Original source bytes and document revisions are never changed.

The annotation request hash is a semantic hash and deliberately excludes the HTTP/Catalog
idempotency key.  The transport key controls claim and replay of one submission; it is not product
identity.  Catalog derives the annotation ID and Artifact commit key from the semantic request hash
and pinned renderer identity, so equivalent requests with different transport keys converge on one
canonical Artifact.  The API keeps an indexed unique key on owner + Workflow + semantic request
hash and stores role-addressed output pointers in a child relation keyed by annotation ID + role.
Sequential lookup is O(log n), fixed one-or-two-role assembly is O(1), and concurrent creation is
closed by both the database unique constraint and the Catalog semantic commit key.

The API receipt and its output pointers are immutable after insertion.  Creation therefore performs
an ordinary primary-key lookup under the reviewed `SELECT` + `INSERT` runtime privilege boundary;
it does not acquire `SELECT ... FOR UPDATE`.  Concurrent creators are serialized by the primary and
owner + Workflow + semantic-request unique constraints.  The losing transaction follows the
`IntegrityError` path, reloads the committed receipt, and accepts it only after exact pointer/hash
comparison.  Granting table-wide `UPDATE` merely to lock an immutable row would broaden authority
without adding a concurrency invariant.

The two input Artifact families intentionally use different resolvers.  Catalog source PDFs are
file-set members and therefore resolve through the exact member entry in the Catalog file-set
manifest.  The review result is an orchestrator structured Artifact whose canonical primary member
is `result.json`; its `ArtifactManifest` records the primary content hash and byte count rather than
a file-set `files` array.  Catalog resolves that result by logical Artifact ID, pinned revision ID,
approved lifecycle, exact content hash, bounded regular `result.json`, and canonical byte count,
then applies the role-result JSON Schema and Pydantic validation.  Treating the structured result as
a Catalog file-set member is invalid even though both Artifact families materialize a file named
`result.json`.

Stable `DOCUMENT_REVIEW_*` derivative errors cross the private Catalog boundary unchanged.  The API
must not collapse pointer, renderer, or source mismatches into a generic availability error; this
preserves actionable failure identity while leaving source and completed review revisions intact.

### Graph knowledge

This successor does not fabricate a broad or relevance-free Graph bundle.  Existing review behavior
continues to solve and verify the supplied documents with provenance.  A later Graph-grounded review
successor must first add an orchestrator-mediated planning step that produces bounded curriculum/topic
keys, then ask Catalog for an exact Evidence Bundle and require evidence-use receipts.  Silently
attaching unrelated top-ranked corpus entries would weaken review quality and is rejected as an
alternative.

### Control-plane succession

The V2 PDF-review control bootstrap is a successor of the released V1 preset and instruction
bundle, not an independent bootstrap that may replace current pointers opportunistically.  Before
publishing any successor control revision it pins and validates the exact current V1 preset
revision and policy hash plus the V1 instruction-bundle revision, manifest hash, and control
document hash.  The changed platform and role instructions use new control Artifact identities;
the shared logical instruction bundle advances through adjacent revision 2 with compare-and-swap.
The shared logical preset appends a new DRAFT and RELEASED pair and retains all V1 revisions.

Replay accepts either the exact V1 predecessor as current (first publication) or the already
released exact V2 successor as current.  An unrelated current revision, stale predecessor, changed
hash, skipped bundle revision, or unresolved competing draft fails closed.  The V2 bootstrap had
not been released before these predecessor fields were added; the released V1 schema, control
records, and instruction bytes remain unchanged.

## Failure, retry, and rollback

- Missing, stale, unauthorized, wrong-media, wrong-schema, or hash-mismatched pointers fail closed.
- Re-upload with the same member key must use identical bytes; a different hash is a conflict.
- A set cannot start until both members are committed and role-distinct.
- Timeout does not imply failure; same-key replay reloads the committed member or Workflow.
- Annotation failure leaves the completed review intact and produces no successful annotation
  pointer.  Retry uses the same immutable inputs and idempotency key.
- Rollback disables the successor Workflow/API surface.  V1 review and every historical Artifact
  remain readable.

## Simpler alternatives rejected

Adding `solution_document` to the released V1 request would reinterpret historical protocol bytes.
Concatenating PDFs would destroy independent page identity.  Storing files in PostgreSQL would
duplicate canonical Artifact bytes.  Letting the worker annotate or write the PDF would bypass
orchestrator validation and NAS ownership.  Client-only canvas markings would not create a portable,
hash-pinned review deliverable.
