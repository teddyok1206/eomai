# ADR 0060: Keep execution batches out of user projections

## Status

Accepted.

## Decision

Execution batches, recovery batches, work units, claims, leases, and retry partitions are private
orchestration state. Product-facing APIs and Studio views expose domain objects instead: the active
knowledge corpus revision, its published Graph snapshot, immutable assessment occurrences, source
documents, and approved Item revisions. Batch identifiers remain available through explicitly
administrator-only operational endpoints so a future operations page can diagnose and manage the
orchestrator without weakening the product boundary.

The assessment-learning product projection is rooted at the active integrated-science corpus and
its pinned current Graph snapshot. The Graph snapshot is the canonical source. It is not reconstructed
by adding batch counters. Exam uniqueness is the immutable assessment occurrence revision ID, Item
uniqueness is the immutable Item revision ID, and source-PDF uniqueness is the tuple of source
artifact revision ID and member path referenced by the snapshot's assessment source bundles.

## Data shape and access pattern

The frequent operations are one keyed current-corpus lookup, ordered iteration over exam occurrences,
membership/deduplication, and source-page resolution. PostgreSQL B-tree/unique indexes on corpus key,
Graph snapshot placement, assessment occurrence revision, source-bundle member, and extraction work
unit bundle pointers support these operations. Projection code uses maps and sets, yielding O(I + P)
time and O(E + P) memory for `I` Graph Item placements, `E` exams, and `P` source pointers. At the
current scale that is 520 placements, 25 exams, and 50 source PDFs; the contract bounds remain much
higher.

No new persistence or cache is introduced. Each response is one read-only database snapshot. Page
bytes are still materialized only at the existing authorized download boundary. The API resolves an
occurrence revision to its pinned source-bundle revision and then to a private accepted work-unit
locator; that internal locator is never serialized to the user.

## Transactions, failure, and dependency direction

These projections are read-only and have no retry or idempotency side effect. Missing current corpus,
dangling pointers, multiple conflicting source bundles, unexpected source roles, duplicate placement
keys, or hash/lifecycle drift fail explicitly. The API application/query layer owns aggregation. The
Catalog application adapter remains responsible for safe source-page dereferencing. The Web gateway
only validates and presents the batch-free API contract.

Legacy batch contracts and administrator-only endpoints are retained byte-for-byte for operational
diagnostics and future administrator tooling. New product code must not call them or serialize their
identifiers. A user projection may include immutable logical IDs, revision IDs, Artifact pointers,
and hashes when they identify domain evidence; it must not include batch, work-unit, claim, lease, or
retry-partition identifiers.

## Rejected simpler alternative

Summing successful batch counters is simpler but incorrect: recovery batches overlap their original
batches and make the same exam and Item appear more than once. Hiding the batch label only in HTML is
also insufficient because IDs would still leak through JSON and image URLs. The selected design
deduplicates at the canonical Graph revision and keeps batch IDs behind the administrator boundary.
