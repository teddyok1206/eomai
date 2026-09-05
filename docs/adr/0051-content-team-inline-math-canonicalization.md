# ADR 0051: Content-team inline-math canonicalization

## Status

Accepted.

## Responsibility and boundary

The workflow protocol boundary canonicalizes only source spellings that the pinned content-team
Markdown/HWPX program cannot represent. It joins an ASCII unit or symbol to an immediately adjacent
subscript/superscript math span and renders a pure numeric coordinate pair as ordinary visible text.
The Markdown parser also preserves every paragraph inside a labeled data or condition block.
Workers still return the versioned authoring result; the orchestrator remains the only artifact
committer and the HWPX adapter remains downstream infrastructure.

## Canonical source, revisions, and pointers

The approved authoring artifact revision and its SHA-256 remain the immutable source identity.
Validation produces a deterministic typed projection for downstream review, registration, and HWPX
materialization; it does not rewrite the stored artifact or change its logical ID, revision ID, or
content hash. Downstream prompts continue to pin that exact artifact pointer while embedding the
validated projection.

## Access patterns and data structures

The dominant operation is one ordered traversal of the small authored value tree. Dictionaries keep
field lookup at O(1); ordered lists and tuples preserve author order; a derived tuple indexes inline
equation occurrences. Canonicalization is O(n) in authored JSON/text size and uses O(n) transient
space for the immutable projection. No database index, schema, cache, queue, or large binary copy is
introduced.

## Transactions, concurrency, and adapters

No persistence transaction is added. Artifact resolution first validates the pinned revision,
manifest, media type, lifecycle, and hashes through the existing catalog adapter. Canonicalization
then runs in the workflow contract layer before a prompt is rendered. The dependency direction stays
interface → application service → workflow/domain contracts → HWPX value contracts; workers and
domain not access PostgreSQL or NAS.

## Failure, retry, and idempotency

Unsupported equations, ambiguous visual boundaries, stale equation indexes, and lossy Markdown
round trips fail explicitly before registration or HWPX build. Reapplying canonicalization is
idempotent. It neither creates a worker attempt nor permits a silent latest-revision substitution.
Tests cover missing source boundaries, multiline labeled blocks, rebuilt equation indexes, and the
actual previously generated artifact.

#### Alternative

Special-casing a unit, coordinate, topic, or item would be smaller but would encode sample content
as policy and fail on the next equivalent spelling. Rewriting the immutable artifact would destroy
provenance. A general Markdown grammar replacement would be broader than required. The chosen
bounded normalization and parser correction preserve both the team program and the existing typed
framework.
