# ADR 0057: Item-content V3 Catalog protocol identity

## Status

Accepted

## Context and responsibility

Catalog owns the transaction that turns a validated registration result into immutable Item and
Artifact revisions. Item-content V3 was assigned `catalog/1.3`, but that immutable key already
identifies the knowledge-analysis-document contract bundle. The protocol-version repository
correctly rejects a second schema hash for the same key, so V3 registration cannot commit.

The canonical protocol identities are the version/hash pairs registered in `protocol_versions`.
Item logical IDs, Item revision IDs, Artifact logical IDs, Artifact revision IDs, content hashes,
and protocol identities remain separate. Existing `catalog/1.3` rows and artifacts continue to mean
knowledge-analysis-document and are never rewritten or reinterpreted.

## Decision

- Item-content V3 uses the unused immutable successor `catalog/1.13` with schema hash
  `sha256:4e5fe407e576b68a4162c9105e8cf31f765cfd8fea21982f36be49503505f797`.
- The Item-content V3 schema and artifact members are unchanged. Only the previously conflicting
  protocol identity changes.
- Every existing protocol assignment other than the unusable V3 collision, plus all protocol rows
  and previously committed Artifact files, remains unchanged. The successor row is created by the
  existing repository boundary on the first V3 commit.
- Workflow Catalog and direct Item-content import both consume the one successor constant; neither
  resolves an implicit latest version.

## Pointers and access patterns

The dominant operation is an indexed lookup by protocol-version primary key followed by a constant-
time schema-hash comparison. The existing map-like database key and uniqueness constraint match
that access pattern. Each committed job pins the exact protocol version and hash, while the Artifact
manifest continues to pin member names, media types, schema references, byte counts, and content
hashes. Resolution fails explicitly for a missing target or hash mismatch; no fallback or version
substitution is introduced.

The expected scale is tens of protocol rows, with `O(1)` indexed lookup time and `O(1)` storage per
immutable contract bundle. No new cache, binary database value, repeated scan, index, or dependency
is required.

## Transactions, concurrency, and failure behavior

`ensure_protocol_version` remains inside the existing Catalog Artifact transaction. Concurrent
first use is protected by the protocol-version primary key, and idempotent reuse succeeds only for
the same version/hash pair. A conflict fails closed before Item or Artifact commit. Job and workflow
retry semantics do not change; this decision does not retry or alter the already failed workflow.

The application service selects the typed protocol constant and the repository enforces immutable
identity. Domain and contract packages remain independent of Catalog infrastructure, and workers
still neither persist artifacts nor communicate directly.

## Alternatives

Rewriting the existing `catalog/1.3` row or changing its hash would reinterpret successful
knowledge-analysis history and violate immutable protocol identity. Reusing another occupied key
would repeat the collision. Adding a migration or a new registry abstraction is unnecessary because
the existing repository already provides the required keyed uniqueness and transactional check.
The adjacent unused `catalog/1.13` identity is the smallest protocol-safe correction.

## Verification

Tests assert that all current Catalog contract bundles have unique version keys, both `catalog/1.3`
and `catalog/1.13` coexist with their exact hashes in the repository, and Workflow Catalog forwards
the exact V3 successor version/hash to Artifact commit. Existing rows and files require no mutation.
