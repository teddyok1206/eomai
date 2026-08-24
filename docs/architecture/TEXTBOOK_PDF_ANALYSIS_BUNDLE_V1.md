# Textbook PDF Analysis Bundle V1

Status: reviewed pilot design

Date: 2026-08-24 UTC

## 1. Responsibility and boundary

This design adds a content-addressed Markdown review bundle for a textbook PDF. The bundle is an
intermediate analysis artifact: it preserves page identity, extracted text, and proposed EOM
curriculum mappings without treating a temporary filesystem path as canonical identity.

The production boundary remains:

```text
reviewed original Artifact Revision
  -> deterministic page-range materialization (when the PDF exceeds 100 MiB)
  -> staged local worker input
  -> Knowledge Analysis proposal Artifact Revision
  -> human review
  -> accepted Knowledge Graph projection
```

The pilot tool stops before Artifact registration, NAS commit, worker execution, graph publication,
or DB mutation. A pilot manifest must therefore declare `PRE_CANONICAL_REVIEW_ONLY`. It is evidence
for reviewing extraction and mappings, not a canonical source.

## 2. Canonical source

The future canonical source is one approved Artifact Revision containing the original PDF. Its
logical Artifact ID, immutable Artifact Revision ID, member path, media type, and SHA-256 remain
separate. Page-range PDFs and Markdown pages are derived materializations and never replace it.

The current uploaded files are protected staging inputs. Their SHA-256, byte size, and page count
are pinned in each pilot manifest, but the absence of an approved Artifact pointer keeps the bundle
pre-canonical. Rights evidence must be reviewed before production registration or model exposure.

## 3. Logical entity and revision model

One textbook edition and volume is the logical document. A particular publisher PDF is an immutable
source revision. The analysis bundle is a separate immutable derived revision identified by its own
bundle ID and self-hash. Page anchors are immutable children of that bundle and use physical PDF
page numbers; printed page numbers are optional display metadata.

The editorial curriculum hierarchy remains the separate EOM taxonomy documented in
`EOM_INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_V1.md`. A mapping joins a pinned page range to an EOM
middle-unit key. It does not rewrite either source structure.

## 4. Pointers and resolution checks

For every build, resolution must verify:

- the source is a regular, non-symlink, single-link PDF;
- observed SHA-256, size, and page count equal the pinned source observation;
- a canonical bundle has an approved Artifact member pointer with the same SHA-256;
- every Markdown member path is normalized, relative, unique, and under `pages/`;
- every Markdown file hash and extracted-text hash matches the manifest;
- physical pages are unique, ordered, contiguous, and cover the whole source;
- curriculum mappings reference existing page anchors and known EOM unit keys;
- mappings are `PROPOSED` until human review confirms them;
- the manifest self-hash matches canonical JSON excluding the self-hash field.

Missing members, stale pointers, hash drift, page gaps, duplicate mappings, and path escapes fail
closed. No implicit "latest revision" lookup is permitted.

## 5. Primary access patterns and structures

| Access pattern | Structure |
| --- | --- |
| page by physical number | ordered tuple plus unique page-number constraint |
| member/hash verification | keyed map built once from manifest pages |
| unit-to-page traversal | sparse mapping list, projected later to graph adjacency |
| deterministic iteration | ascending physical page and EOM unit key order |
| reproducible history | immutable source observation and bundle self-hash |

The expected scale is 100–500 pages and fewer than 100 curriculum mappings per volume. Validation is
O(p + m) time and O(p + m) memory for `p` pages and `m` mappings. Page text remains in Markdown
members, not duplicated inside PostgreSQL or the manifest.

## 6. PDF range contract

The existing immutable
`pdf-page-range-materialization-manifest/1.0` contract is authoritative for PDFs larger than the
100 MiB Content Intake member limit. The global limit is not changed. A trusted Catalog-side
adapter may materialize deterministic child PDFs whose contiguous ranges cover every physical page
and whose individual sizes do not exceed 100 MiB. Only the Orchestrator may commit those validated
files to NAS.

The Markdown bundle records anchors against original physical pages. An implementation processing a
child page-range PDF must translate local child pages back to those original page numbers using the
page-range manifest.

## 7. Transaction and concurrency boundary

The local pilot writes into a newly created 0700 output directory, uses temporary files followed by
atomic rename, and refuses a pre-existing output. It performs no database transaction.

Production creation must use the existing application-service and Orchestrator transaction boundary:
claim one idempotency key, validate all members, commit one immutable Artifact Revision, and publish
no graph state before human acceptance. Concurrent requests for the same source revision and options
must converge on one idempotent result or fail with a stable conflict.

## 8. Dependency direction and adapter ownership

JSON Schema and frozen Pydantic models live in Catalog contracts. External PDF executables and
filesystem operations belong to an infrastructure/operator adapter. Workflow workers consume staged
local input only and return structured output only. They never read or write NAS and never call one
another. Graph publication remains owned by Catalog application services after Orchestrator commit.

The pilot uses an already available local Poppler executable as an explicitly selected adapter. This
does not add a production dependency and must not create an EOMIS runtime dependency; production
packaging must declare and verify its own PDF implementation before rollout.

## 9. Failure, retry, and idempotency

Extraction is deterministic for the pinned source hash, extractor implementation/version/options,
and mapping input. A failed pilot leaves no valid manifest and may be retried only into a new empty
directory. It never overwrites a previous bundle.

Stable failure classes include unsafe source, source identity mismatch, unsupported/encrypted PDF,
extractor failure, output size violation, page coverage mismatch, unsafe member path, member hash
mismatch, mapping range error, and manifest hash mismatch.

## 10. Pilot acceptance

The first pilot is MiraeN Integrated Science 1, EOM unit `1-(1) 시간과 공간`, physical PDF pages
16–19 (printed pages 14–17). It passes only when:

- all four pages render and yield page-scoped Markdown;
- the extracted text is non-empty and contains Korean text;
- visual page review and text-layer page boundaries agree;
- every page/member hash validates;
- the mapping resolves only to `1-(1)` and remains `PROPOSED`;
- no source, derivative, or excerpt is committed to Git, DB, or NAS.

After pilot acceptance, the same implementation may process both MiraeN volumes. Full-volume output
is still review-only until rights review and canonical Artifact registration are complete.

## 11. Simpler alternative and why it is insufficient

A folder of untracked Markdown files without a manifest would be faster, but it would lose source
identity, page coverage, deterministic hashes, mapping review state, and a safe transition to the
existing Knowledge Analysis/Graph pipeline. Copying the original PDF into every bundle would violate
the single-canonical-artifact rule. Increasing the global intake limit would weaken unrelated input
boundaries. The proposed bundle is therefore the smallest additive contract that preserves the
required provenance while keeping the pilot non-canonical.

## 12. Current mapping policy

Publisher sections and EOM editorial units are separate structures. Mapping is many-to-many and
source-evidenced:

- one publisher section may support several EOM units;
- one EOM unit may use several page spans or publishers;
- a page may map to more than one unit when the concepts genuinely overlap;
- page ranges are evidence anchors, not ownership of the underlying content;
- all automated mappings begin as `PROPOSED` with bounded confidence.

The first full pass maps the MiraeN table of contents and section ranges. Fine-grained concepts,
claims, figures, tables, equations, and cross-publisher equivalence remain a subsequent Knowledge
Analysis review step rather than being invented from filenames or table-of-contents metadata.
