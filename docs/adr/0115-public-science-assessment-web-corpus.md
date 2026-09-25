# ADR 0115: Public science-assessment web corpus intake

- Status: Accepted for implementation
- Date: 2026-09-25 UTC
- Scope: publicly downloadable KICE and education-authority science-assessment problem PDFs

## Decision

EOM will use `legendstudy.com` as a bounded discovery index for publicly linked assessment PDFs.
It is not the canonical publisher and its page text is not training material.  A discovered PDF is
eligible only when its link identifies a science problem paper issued by KICE or an education
authority, the download is available without authentication or access-control bypass, and the exact
bytes pass the untrusted-PDF boundary.  Where an official source URL is available it is retained as
preferred provenance; otherwise the public discovery page and final CDN URL are both retained.

The first corpus includes physics, chemistry, life science/biology, earth science, integrated
science, and general science across curricula and school years.  Answer sheets, explanation-only
documents, grade-cut images, advertisements, social-science papers, and publisher-created study
materials are excluded.  Successful acquisition creates immutable Content Intake sources only.  It
does not by itself approve model exposure, Graph publication, crop extraction, or LoRA training.

## Responsibility and boundary

The Catalog-owned acquisition application reads an immutable crawl plan, observes allowed category
pages at a bounded rate, extracts public PDF links, validates candidates, and materializes exact
bytes into a protected staging directory.  Network access is confined to the discovery host and the
plan's closed download-host allowlist.  The downloader never writes to NAS or PostgreSQL.

After acquisition validation, the existing Content Intake application shards unique PDFs into at
most 499 files and 2 GiB per batch and commits them through its existing Artifact boundary.  A final
small corpus manifest points to each immutable Content Intake source.  Workers never crawl, download,
or write the source corpus.

## Canonical source and revision model

```text
immutable crawl plan
  -> public post URL + public PDF link observations
  -> safely downloaded exact PDF bytes
  -> SHA-256 deduplication
  -> immutable Content Intake source Artifact Revision(s)
  -> corpus manifest with exact source-file pointers
```

The remote URL is provenance and a locator, not identity.  A document identity is derived from the
content SHA-256.  The final manifest preserves every duplicate discovery source while storing only
one canonical PDF.  Existing Content Intake rows with the same SHA-256 are referenced rather than
copied into another batch.

## Access patterns and data structures

The dominant operations are URL membership, post discovery, content-hash deduplication, exact
source-file lookup, ordered iteration, and bounded sharding.

- sets provide expected O(1) URL and post membership;
- maps keyed by SHA-256 provide expected O(1) deduplication and provenance aggregation;
- the existing indexed `content_intake_source_files.sha256` lookup resolves reusable sources;
- category and source lists are sorted once for deterministic output;
- acquisition is O(posts + links + downloaded bytes), with O(unique documents + provenance) memory;
- Content Intake sharding is a stable greedy pass, O(unique documents).

The expected initial scale is below 5,000 PDF observations and 500 unique problem PDFs per Content
Intake batch.  No new database table or index is required.  If observed source-file SHA lookup lacks
an index, that is fixed before publication rather than compensated by repeated table scans.

## Transaction, concurrency, retry, and idempotency

The crawl plan hash is immutable.  Each download is written to a new temporary file, bounded while
streaming, fsynced, structurally validated, and atomically promoted under its content hash.  A
changed redirect target, media type, body, or hash creates a different observation; it never
silently replaces accepted bytes.

The Content Intake fingerprint and unique source hashes are the canonical replay boundary.  A
failed crawl or download leaves no published dataset and can resume only from hash-verified local
materializations.  HTTP timeout is an unknown outcome for the individual request and is rechecked;
there is no blind parallel retry.  Publication stops on source mutation, unsafe PDF structure,
rights-policy mismatch, pointer drift, or canonical-hash mismatch.

## Dependency direction and adapters

The CLI validates presentation input and calls a Catalog application service.  The application
service owns crawl orchestration, validation, sharding, and Content Intake calls.  HTTP, filesystem,
PDF inspection, and PostgreSQL lookup are replaceable infrastructure adapters.  Contract packages
contain no HTTP, filesystem, SQLAlchemy, or NAS dependency.

## Simpler alternative rejected

Mirroring every `.pdf` link with `wget` is shorter but loses exam/subject/role provenance, can copy
non-science and explanation materials, duplicates existing canonical bytes, ignores unsafe PDFs,
and bypasses Content Intake.  Reusing the legacy EOMIS inventory contract would also be incorrect:
that contract's closed root aliases describe local legacy systems, not an external public discovery
source.  The dedicated, narrow corpus contract is the smallest truthful boundary.
