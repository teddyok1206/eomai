# Mock Exam Exact Cohort Assembly V1

## Decision

The production workflow that creates 25 new Items must pin an exact, ordered assembly cohort before
previewing a mock-exam plan. The assessment-assembly boundary accepts a small immutable
`mock-exam-assembly-cohort/1.0` value containing positions 1 through 25 and their exact Item
Revision IDs. Its content hash and derived cohort ID are validated before candidate resolution.
General planner callers may omit the cohort; production callers must supply it to both preview and
create-planned operations.

## Required design procedure

1. **Responsibility and boundary.** Assessment-assembly owns exact cohort enforcement. The
   production coordinator constructs the cohort from completed one-Item workflows; the planner and
   Catalog repository resolve and enforce it. Workers neither assemble the form nor write storage.
2. **Canonical source.** The immutable cohort value supplied to preview is canonical for the
   production run. A ready plan embeds that value, and the released Assembly Manifest embeds the
   plan. No parallel cohort table or copied Item payload is created.
3. **Entity and revision model.** Each member pins an immutable Item Revision ID. The cohort itself
   is a frozen value object whose `cohort_id` is derived from `cohort_sha256`; it is not a mutable
   aggregate and has no independent revision chain.
4. **Pointers and checks.** Validation checks schema version, self-hash, derived identity, exact
   ordered positions, and unique Item Revision IDs. Resolution then requires every member to exist
   in the specified published Graph snapshot, to pass the current released rating policy, and to
   retain all existing Item manifest, content, review, lifecycle, schema, media-type, access, and
   SHA-256 checks. Missing, stale, or hash-mismatched targets fail explicitly.
5. **Access patterns.** The primary operations are ordered iteration over 25 slots, membership and
   duplicate detection, exact revision lookup, and position-to-revision lookup.
6. **Structures and indexes.** Tuples preserve canonical order. Sets enforce uniqueness. Dicts keyed
   by position and Item Revision ID provide expected O(1) matching. PostgreSQL candidate discovery
   adds one bounded `IN` predicate on indexed Item Revision identifiers; the existing Graph,
   review, component, artifact, and usage bulk queries remain set-oriented.
7. **Scale and complexity.** A production cohort is exactly 25 small pointers. Cohort preparation
   and validation are O(25) time and space. Candidate resolution remains O(n) over at most 25 cohort
   members instead of scanning up to 5,000 general candidates; no per-member SQL query is added.
8. **Transaction and concurrency.** Preview is read-only. Create-planned re-resolves the same cohort
   inside the existing Form/Assembly transaction and verifies the expected plan hash before
   publishing current pointers. Existing aggregate locks and uniqueness constraints remain the
   concurrency boundary.
9. **Dependency direction.** JSON Schema and frozen Catalog contracts define the protocol. The
   planner depends on those contracts. The PostgreSQL/NAS repository implements resolution, and
   the application service orchestrates it. Domain code does not import infrastructure.
10. **Failure, retry, and idempotency.** Cohort schema, duplicate, count, position, missing-member,
    or candidate mismatch errors are stable fail-closed outcomes. A retry with identical cohort,
    pinned Graph, policies, timestamp, and plan hash is deterministic. Replay revalidates cohort
    provenance against the stored plan and rejects changed inputs.
11. **Simpler alternative.** Filtering the planner result after unrestricted selection is
    insufficient: external candidates can displace generated Items, and ambiguous candidates can
    swap positions while still yielding 25 Items. Candidate filtering alone is also insufficient
    because one eligible cohort member could occupy another member's slot. Position-scoped planner
    options are therefore required.

## Review notes

- The cohort carries pointers only; Item bytes and review artifacts remain canonical in their
  existing Artifact Revisions.
- The general planner remains available by omitting `cohort`. Production use must never omit it.
- A ready cohort-scoped plan must contain exactly the cohort's 25 Item Revision IDs at their pinned
  positions; shortages contain the same cohort provenance but no partial placements.
