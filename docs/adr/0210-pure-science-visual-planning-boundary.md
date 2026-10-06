# ADR0210: Shared pure science-visual planning below service boundaries

Status: IMPLEMENTED AND SOURCE-VERIFIED; NOT DEPLOYED. 2026-10-06 UTC.

The existing dependency gate reports Orchestrator imports of Catalog's
`science_visual_expansion_planning` and `science_visual_pilot`. This predates the
contour consumer change (source400f1c09); the unchanged offending file has SHA
`e90d406b679c7602bc5d8724e6fda8d0d3fd07ba245b010f795e3d5804576c62`.
Do not suppress the gate or implement a second frozen-cohort selection rule.

1. Responsibility/boundary: deterministic corpus selection and expansion-source
   validation are pure domain rules shared by Catalog planning and Orchestrator
   admission. Move them below both services, not through a runtime Catalog call.
2. Canonical source: the existing typed corpus/authorization/predecessor plans;
   original document/group partition, ranked selection and validation algorithms
   are unchanged. No PDF/PNG/model/NAS/DB access in these rules.
3. Identity/revision: no new schema/protocol/plan identity meaning or migration;
   preserve all serialized plan bytes, logical/revision IDs, hashes and error codes.
4. Pointers: retain exact existing source/predecessor/authorization checks and
   permissions/hash/lifecycle resolution at the original I/O owner. Never latest.
5. Access patterns: document/group membership and keyed lookup; deterministic
   ranked pools, shard iteration and immutable tuples, as already implemented.
6. Structures/complexity: preserve maps/sets/sorted pools, O(n log n) time/O(n)
   space at at most5,000 documents. A module move is not a performance claim.
7. Transactions/concurrency: no new writes/cache/queue/claim; existing Catalog
   transaction and Orchestrator bounded input/staging/commit boundaries remain.
8. Dependency: public pure modules in `eom_catalog_contracts` depend only on
   existing Catalog DTOs and Image contracts plus the standard library. The new
   explicit first-party module dependency is required to share typed image-plan
   rules, not a third-party dependency. Image contracts do not depend back on
   Catalog contracts. Ordinary Catalog DTO imports do not load the planner.
9. Compatibility: old Catalog service modules re-export the same supported
   functions/error class; internal helper aliases remain for existing Catalog
   callers. New cross-service calls use public contract-module functions only.
10. Failure/retry: same validation errors and deterministic results; no live retry
    or data rewriting. Installed runtime/active training is not changed here.
11. Simpler alternative: copying the validator into Orchestrator or excluding
    the import from the architecture test creates drift or conceals the violation.
    Moving one authoritative implementation avoids both and adds no framework.

Verification: existing pilot/expansion/crop-discovery/source-admission tests,
frozen schema/manifest hashes and partition/replay fixtures; dependency gate;
strict typing/lint and packaging inspection. Production deployment is separate.

## Implementation and evidence

One authoritative implementation moved into public pure Catalog contract modules
`science_visual_pilot_planning` and `science_visual_expansion_planning`. Shared
grouping/ranking/partition/campaign helpers now have public names; compatibility
service modules re-export supported functions and legacy internal aliases.
Orchestrator imports only public contract-layer validation/error types. No new
third-party dependency, schema, binary copy, runtime registry or I/O was added.
Image contracts have no reverse Catalog dependency, so no package cycle is added.

Tests patch the actual public domain owner rather than a compatibility re-export.
A new identity test proves service and domain exports refer to the same functions
and error class. Existing partition/selection/campaign/expansion/source-admission
fixtures retain their meanings. The architecture gate's original failure was
preserved, not excluded. Initial two isolated failures after extraction were test
patches targeting the old shim, not changed selection rules; corrected owner
targeting and rerun yielded106 PASS. Final combined suite after public helper
names/compatibility identity coverage:1,150 PASS, strict typing12 modules and
Ruff/diff/shell PASS. Active fit and installed runtime remain unchanged.
