# Mixed source-plan2 boundary

2026-10-19 UTC. Additive source-only slice of
`REGISTERED_REVIEW_INCREMENTAL_INTEGRATION_DESIGN.md`; not runtime activation.

1. Responsibility: define the immutable metadata-only mixed source plan and pure
   builder/closure checks. Catalog still owns actual Graph eligibility and IAM.
2. Canonical source: authorized Catalog capture, original accepted-solution or
   registered-review profile/evidence, and real accepted V2 Graph base IDs.
3. Identity: source revision, base analysis run, branch evidence, profile and
   encoding remain distinct. A REVIEW Job is never a base or V10 solution ID.
4. Pointers: demands discriminate `ACCEPTED_SOLUTION_ANALYSIS` and
   `REGISTERED_ITEM_REVIEW_SOLUTION`; each preserves its exact evidence/profile.
   Graph/policy/corpus/space/recipe and namespace2 pins are checked, not resolved.
5. Access: source/base/entry lookup, exhaustive selected-source coverage, encoding
   deduplication and deterministic ordered serialization.
6. Structures: bounded immutable tuples plus revision/encoding maps and sets;
   no registry, cache, SQL, storage or mutable global state is added.
7. Scale: at most1,024 sources/demands, O(n + text bytes) lookup and validation,
   O(n log n) canonical sorting, existing64MiB metadata limit. Text stays in staged
   entry materialization, never duplicated into source-plan2.
8. Concurrency: pure values do not carry authority between roots. Owner obtains
   current source/base associations and retains all existing late source/IAM/CAS
   checks; neither parser nor builder admits a Job.
9. Dependency: workflow contract imports Catalog contracts only; Catalog builder
   uses the existing pure delta planner. It cannot query services or a database.
10. Failure: wrong branch/base/source/hash/Graph/coverage, duplicate/foreign target
    and truncated capture fail closed. Missing report and unavailable/empty view
    remain explicit, disjoint coverage states. No latest substitution or retries.
11. Simpler alternative: widening plan1 changes released meaning or invents V10
    evidence. New metadata-only plan2 is additive; existing encoding-job1,
    numerical space/shard and plan1 bytes/semantics are unchanged.

API: `LocalEmbeddingSourcePlanV2`, `parse_local_embedding_source_plan_v2`,
`validate_local_embedding_entry_source_v2`, `validate_local_embedding_plan_entries_v2`,
`validate_local_embedding_selected_index_coverage_v2` and Catalog
`build_local_embedding_source_plan_v2(..., base_analysis_run_ids=Mapping[str,str])`.
The entry validator/builder accept only the two real staged entry types. The
mapping asserts already owner-resolved associations; only legacy evidence can
also prove its own base ID. It does not manufacture Graph membership for REVIEW.

Source gate: new plan2/old builder/admission/receipt/coordinator/dependency six
suites316 PASS /47.54s, XML `/tmp/registered-review-source-plan2-freeze.xml`.
Earlier `/tmp/registered-review-source-plan2-final.xml` retained316 PASS/1 FAIL:
the released four-resource tuple was accidentally widened. The correction keeps
that exact tuple/order/hashes unchanged and adds a separate pinned plan2 resource
to the existing loader/registries; no old assertion was weakened. New schema
raw SHA is `sha256:cbf7c6647484bc59efa1a857669ebb67aa6cf49a2a1bfaa28a326bca364f88d0`.
Strict mypy4/Ruff4/format4 pass. No runtime, DB or model execution occurred.
