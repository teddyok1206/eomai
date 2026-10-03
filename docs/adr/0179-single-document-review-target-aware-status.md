# ADR 0179: Target-aware single-document review completion

## Status

Accepted on 2026-10-03.

## Boundary and canonical source

Single-document V1 computes `review_status` only from uncertain candidates. The shared V5 role
correctly requests human review for failed or insufficient verification targets, causing a live
V1 result with two confirmed findings to fail typed validation. Do not relabel that output as
COMPLETE, weaken scientific checks, or modify released V1 semantics.

Add single-document result `pdf-document-review-result@4.0`, worker protocol
`workflow-role/1.28.0`, and workflow definition `pdf-document-review@1.3.0`. V4 keeps the existing
single-document value shape, requires each of the ten verification axes exactly once, and uses
NEEDS_HUMAN_DECISION if any target is not VERIFIED or any candidate is UNCERTAIN. COMPLETE requires
all ten axes VERIFIED and no uncertain candidate. Confirmed findings and recommendations remain
available; execution completion is distinct from content approval.

Released V1/V2/V3 schema bytes and protocol hashes remain unchanged. A new protocol is necessary
because the registered protocol hash includes its result schemas. Reuse the existing V13 plan
shape: it already pins the exact workflow definition/hash, document, preset, and instruction
revision; no additional plan field or database migration is required.

## Identity, resolution and ownership

- Workflow, job, document and Artifact logical identities, revisions and hashes remain separate.
- Readers choose the result contract from the pinned workflow definition and exact step/pointer
  schema, never from current activation or result contents. Old workflows retain their contract.
- Same-key request replay preserves old receipts before consulting mutable activation.
- Publish a V6 control successor with exact predecessor CAS, preserving paired Graph retrieval
  policy and adding the single-document protocol. The V13 job-local notice states the admitted
  contract; single-document work does not invent a second file or a Graph receipt.
- Add Catalog annotation/correction request successors and a correction-plan successor solely to
  carry the new result-schema pointer. Existing output/download shapes and renderers are reused.
- New single-document annotations default to the product's native numbered-comment panel; historical
  box-only commands retain their original profile. Commit protocols are successors (`catalog/1.23`
  annotation, `catalog/1.24` correction); old protocol identities/hashes are not widened.
- Contracts own value validation; applications own transactions/admission; existing adapters own
  storage, HTTP, filesystem and worker execution. No cross-worker communication or direct DB repair.

## Access patterns, complexity and concurrency

Exact contract/identity resolution uses small immutable lookup tables and indexed DB columns.
Verification axes use a set; candidate/finding correspondence uses keyed maps. Correspondence is
O(n); inherited canonical ordering checks are O(n log n), with O(n) bounded temporary space.
No new queue, cache, binary DB value, artifact copy or
dependency is introduced. Existing claim/lease, transaction and idempotency boundaries are reused.

## Failure, tests and rollback

Missing axes, incorrect status, invalid pointers, mismatched schema/definition, ordering errors and
stale predecessor publication fail explicitly. Preserve failed workflows and original output bytes;
do not sort or repair attestations after submission. Retry requires a new user request, not a DB
state rewrite.

Tests cover the actual status-mismatch shape, all ten axes, uncertainty, canonical schema/Pydantic
agreement, unchanged historical contracts/protocol hashes, stale/missing/hash pointers, exact replay,
result projection, PDF native comments and HWPX correction compatibility. Persistence tests use
only a disposable database. A live new review is distinct from synthetic test acceptance.

Rollback restores the prior compatible runtime/control activation and explicit single-document
workflow selection. New revisions/history remain preserved. Merely clarifying legacy COMPLETE was
rejected: it would leave insufficient checks reported as COMPLETE under the old product meaning.

## Source verification (2026-10-03 UTC)

- Focused source/API/delivery/dependency/legacy-protocol suite: 272 PASS.
- Ruff formatter/linter PASS; strict mypy PASS across 344 source files.
- Disposable PostgreSQL predecessor V1→V6 publication, exact CAS rejection, replay and immutable
  predecessor preservation: PASS. Disposable database and roles removed after verification.
- Historical failed output `job_e977afb58db3496ca5d537bca0b66c38`, SHA-256
  `cdc2aff6ea9368de03fff7d3d67269c57aa08d1f111852be5ecc2b04beaec889`, retained unchanged.
  A read-only counterfactual successor-schema check accepts its ten targets, two confirmed findings
  and NEEDS_HUMAN_DECISION. This does not register it, change its failed status or claim a new live
  worker completion. Model/GPU reruns: zero.
- Deployment and control publication are separate supported operational steps; source PASS alone
  does not establish installed activation or a newly completed user review.
