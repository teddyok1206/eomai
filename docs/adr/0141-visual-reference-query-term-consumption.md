# ADR 0141: Consume the typed visual-reference morphology query

## Status

Accepted on 2026-09-28 UTC.

## Responsibility and boundary

The image worker supplies one validated English morphology subject. The Orchestrator preserves that
subject as immutable intent identity and derives one bounded Commons query by removing presentation
clauses while retaining a declared viewpoint. The isolated reference discoverer must search with the
typed `query_terms` field; it must not silently replace that field with the longer subject.

No worker receives network access, no worker writes NAS, and no external bytes enter a prompt. The
Orchestrator remains the only publisher of validated reference Artifacts. The existing discovery
command/result JSON Schema 2020-12 contracts already define sorted, unique query terms, so this
change fixes behavior to match the released protocol without changing schema bytes.

## Canonical source, identity, and pointers

The worker image-result Artifact Revision remains canonical for the drawing. Its exact drawing hash,
workflow/step/job identities, English subject, derived query tuple, discovery command hash, verified
Commons page revision, normalized PNG hash, and published bundle revision remain separate immutable
values. A URL is provenance, not identity. Workspace files are temporary materializations.

## Access pattern and data structures

The dominant operation is one bounded key search followed by ordered candidate filtering. The query
tuple is immutable and currently has one entry; candidates remain an ordered tuple with a maximum of
five, while page IDs, titles, URLs, and hashes use sets or maps for linear uniqueness checks. Runtime
work is `O(C)` time and space for `C <= 20` returned pages and at most five accepted candidates. No DB
table, index, cache, queue, or migration is added.

## Transaction, retry, and failure

The search is read-only. Publication happens only after candidate metadata, license, media, bounds,
downloaded bytes, normalization, schema, pointers, and hashes all validate. Byte-identical replay
uses the same command and publication identities. Missing or rejected candidates fail closed; there
is no fallback to arbitrary web search, another license class, or unpinned bytes.

The runner retries transient source and route unavailability. Deterministic input, discovery,
handoff, license, output, undeployed-route, and source-rejection detail codes terminate the current
step rather than consume the remaining attempts with an identical immutable request. Failed jobs
and workflow history remain append-only evidence; no row is reinterpreted as successful.

## Simpler alternative rejected

Searching the full descriptive subject was simpler but included direction, background, and isolation
clauses that produced no admissible automobile candidate in the real bounded canary. Removing the
typed query field would weaken auditability. Letting a worker provide URLs or download files would
break the orchestrator, rights, SSRF, and Artifact ownership boundaries.
