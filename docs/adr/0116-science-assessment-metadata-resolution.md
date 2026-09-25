# ADR 0116: Science-assessment acquisition metadata resolution

- Status: Accepted for implementation
- Date: 2026-09-25 UTC
- Scope: deterministic publication eligibility for duplicate public PDF observations

## Decision

The immutable `science-assessment-web-acquisition/1.0` checkpoint remains the canonical record of
what the network acquisition adapter observed.  Publication does not edit that checkpoint when two
public aliases of the same PDF use conflicting exam metadata.  Instead, a separate
`science-assessment-metadata-resolution/1.0` projection groups successful observations by exact PDF
SHA-256, applies a self-hashed closed policy, and records one canonical metadata tuple per unique
PDF.  `science-assessment-web-corpus-manifest/2.0` binds both the raw acquisition hash and the
resolution hash.

The policy resolves each field independently from NFC-normalized link text and download URL.  It
prefers explicit subject, issuer, administration-year, grade, and session evidence over the
acquisition fallback.  Multi-subject listings are general science; an explicit single subject is
not generalized merely because the same label also says science inquiry.  Explicit KICE and
education-authority terms outrank generic `모의고사` aliases.  KICE academic years map to the
preceding administration year, and an explicit `수능` without `모의평가` maps to the CSAT session
before month-based classification.  Equal-precedence disagreement is an explicit
`SCIENCE_CORPUS_METADATA_RESOLUTION_AMBIGUOUS` failure; code never chooses the first or latest
observation.

## Responsibility, canonical source, and revision model

```text
immutable crawl plan
  -> immutable raw acquisition + exact PDF members
  -> immutable resolution policy
  -> self-hashed metadata-resolution projection
  -> Content Intake Artifact Revisions
  -> corpus manifest v2 with exact acquisition + resolution pins
```

The raw acquisition is canonical for origins, downloaded bytes, validation results, and failures.
The resolution projection is canonical only for publication metadata.  The PDF SHA-256 remains the
document identity; filenames and URLs remain locators/provenance.  Neither projection stores PDF
bytes.  The publication service independently recomputes the projection from the raw acquisition
before it opens a database transaction or stages Content Intake shards.

## Access patterns and data structures

The dominant operation is grouping up to 5,000 successful observations by SHA-256.  A dictionary
of lists provides expected O(n) grouping and O(unique documents + observations) memory.  Each
field resolver performs one bounded pass over a hash group.  Sets provide uniqueness and detect
same-rank disagreement.  Documents are sorted once by SHA-256 for deterministic serialization.
No database table or index is added; the existing Content Intake SHA-256 B-tree remains the source
reuse lookup.

## Transaction, concurrency, retry, and idempotency

Resolution is a pure, no-network, no-database operation.  Its canonical JSON is written once with
`O_EXCL`, and its self-hash plus raw acquisition hash make replay byte-deterministic.  Publication
validates the raw manifest, PDF members, policy, and resolution before any Content Intake write.
Existing content-addressed intake shards remain replay-safe.  A policy change requires a successor
policy/schema and therefore a new resolution and corpus identity; it never reinterprets a released
manifest in place.

## Dependency direction and failure behavior

JSON Schema 2020-12 and Pydantic models define the wire contract.  The Catalog application owns
resolution and publication behavior.  Filesystem, PDF validation, PostgreSQL, and NAS remain
infrastructure adapters.  Contract packages do not import those adapters.  Missing observations,
hash drift, summary drift, unknown rules, or ambiguous top-ranked evidence fail closed with stable
codes.  Workers are not involved and cannot write to NAS.

## Simpler alternative rejected

Picking the first alias is deterministic only by accidental sort order and silently converts
discovery-site mistakes into corpus truth.  Dropping every conflicting PDF would discard valid,
byte-identical public assessments.  Editing the raw acquisition would destroy the audit boundary.
The explicit projection is the smallest design that preserves all exact PDFs and origins while
making the interpretation policy reproducible.
