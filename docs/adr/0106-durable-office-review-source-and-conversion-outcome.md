# ADR 0106: Durable Office-review source admission and typed conversion outcomes

- Status: Accepted for implementation
- Date: 2026-09-23

## Context

Office document review currently copies an uploaded PDF, HWP, or HWPX into a private conversion
workspace and commits the original source only after Office-to-PDF conversion and page rendering
have both succeeded. The workspace is removed unconditionally. A converter failure therefore leaves
only the upload SHA-256 and a broad error code in PostgreSQL; the exact untrusted source and bounded
converter diagnostics are lost. Re-uploading the same bytes can reproduce the failure but cannot
make it diagnosable after the request ends.

This violates the intended canonical-source boundary. The uploaded file is the canonical input,
while conversion PDF and page PNGs are derived projections. Admission of the source must not depend
on the success of a replaceable conversion adapter.

## Decision

### Responsibility and system boundary

The Catalog document-intake application first validates and commits the exact uploaded Office source
as an immutable source Artifact Revision. Only then does it materialize that pinned member into the
isolated converter workspace. The converter remains a read-only adapter: it writes only its private
workspace and never writes NAS or PostgreSQL. The Artifact-owning application validates and commits
derived projection members.

The private Catalog application response becomes a successor contract. On success it returns a
source pointer plus a separate projection pointer. On conversion failure it returns the stable error
code and the already committed source pointer. API coordination stores only the compact source
Artifact identity alongside the existing upload hash. No binary payload is stored in PostgreSQL.

### Canonical source and revision model

```text
uploaded Office source logical Artifact
    -> immutable source revision
    -> source/original.hwp|hwpx
    -> source-upload-manifest.json

document logical ID
    -> immutable projection revision
    -> document-review-intake-manifest/3.0
       -> pinned original-source Artifact member pointer
       -> derived source/original.pdf
       -> ordered page PNG members
       -> exact converter and renderer identities
```

The original source bytes occur in exactly one canonical Artifact. A successful projection points
to that revision and does not copy the Office bytes into the projection Artifact. Released V2 intake
Artifacts and pointers remain valid and byte-unchanged.

### Required pointers and resolution checks

The source pointer carries logical Artifact ID, immutable Artifact Revision ID, member path,
SHA-256, byte length, media type, and schema reference. Before conversion or correction, resolution
validates Artifact/revision existence and relationship, successful immutable lifecycle, exact member
metadata, storage containment, regular single-link file identity, bounded size, and SHA-256. Missing,
stale, mismatched, or unauthorized pointers fail explicitly; no latest revision is substituted.

The projection manifest pins the source pointer and its own self-hash. All PDF and page members share
the projection Artifact Revision. The original Office member is intentionally in the separate source
revision.

### Typed conversion outcome

The isolated converter writes one canonical `office-document-conversion-outcome/1.0` JSON file in
its private workspace. It contains only bounded metadata: instance ID, source format/hash/size,
converter release hashes, terminal status, stable stage/error code, log hashes/sizes, and output
hash/size on success. It does not contain document text, arbitrary exception strings, filesystem
paths, or log bytes. JSON Schema 2020-12 and a frozen Pydantic model validate the file. The Catalog
adapter accepts no converter result without this outcome.

### Access patterns, structures, and indexes

Primary operations are:

- key lookup of one review-set member by `(review_set_id, document_role)` using the existing primary
  key;
- idempotent source admission by the existing unique Catalog job idempotency key;
- exact Artifact member lookup by Artifact/revision/member identity using existing indexed records;
- ordered page iteration using immutable tuples; and
- membership/duplicate checks using sets and manifest name maps.

Expected scale remains at most 256 MiB per source, 4,096 HWPX members, and 2,000 rendered pages.
Source hashing and package validation are `O(B)` in input bytes. Member lookup is indexed and does
not scan all prior uploads. PostgreSQL stores constant-size pointers only.

The existing `document_review_set_members` source Artifact columns become valid as soon as source
admission succeeds, including a retryable conversion failure. Constraints are replaced in one
migration; no new binary or arbitrary JSON column is added. The existing primary and partial lease
indexes already match the access pattern, so no new index is needed.

### Transactions, concurrency, retry, and idempotency

Source Artifact commit, conversion, projection Artifact commit, and API coordination remain separate
bounded transactions. The source admission idempotency key binds actor, set/member, filename,
format, size, and hash. Replaying identical bytes adopts the same source revision; different bytes
fail closed. A lease owner is unique per claim. A stale claimant cannot overwrite a newer result.

A conversion failure records the source pointer and typed failure code, clears the lease, and remains
retryable. Retrying the exact member reuses the canonical source Artifact. Historical failures are
not rewritten to success. Successful projection creates a new immutable revision and keeps the
original source revision pinned for correction and audit.

### Dependency direction and ownership

JSON Schema and catalog-contract Pydantic models own the successor wire and manifest contracts.
Application services own admission, idempotency, transactions, and Artifact commits. The systemd
LibreOffice/H2Orestart code is an infrastructure adapter. API and Studio consume typed application
results; they never resolve NAS paths or infer converter state. Workers do not communicate directly
and do not write NAS.

### Failure behavior

Unsafe source metadata/package structure fails before source admission. Once exact source admission
succeeds, converter registration, execution, timeout, exit status, missing output, and invalid output
produce distinct stable codes backed by the typed outcome. If outcome creation or validation fails,
the adapter returns `OFFICE_DOCUMENT_CONVERSION_OUTCOME_INVALID` and never accepts an output.

### Simpler alternative rejected

Keeping failed workspaces under `/var/lib` would turn temporary paths into accidental identity,
lack lifecycle and permission semantics, and still lose evidence during cleanup. Recording only raw
stderr in PostgreSQL would leak unbounded untrusted text and omit the source bytes. Committing a
failure bundle that later duplicates the source inside a successful V2 Artifact would violate the
single-canonical-source rule. The successor split-source/projection contract is the smallest design
that preserves exact evidence, retry, correction, and immutable history without a new queue or
framework.
