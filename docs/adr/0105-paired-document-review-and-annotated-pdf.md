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
rectangle, and optional short quote/hash.  Cross-document checks carry separate non-empty question
and solution anchor sets and an explicit `MATCHED`, `MISMATCH`, `MISSING`, or `INSUFFICIENT` outcome.

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

### Graph knowledge

This successor does not fabricate a broad or relevance-free Graph bundle.  Existing review behavior
continues to solve and verify the supplied documents with provenance.  A later Graph-grounded review
successor must first add an orchestrator-mediated planning step that produces bounded curriculum/topic
keys, then ask Catalog for an exact Evidence Bundle and require evidence-use receipts.  Silently
attaching unrelated top-ranked corpus entries would weaken review quality and is rejected as an
alternative.

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

