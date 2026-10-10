# Inference-transfer candidate population scope

Status: source-only opt-in foundation; no public API, socket operation, runtime
activation, model execution, or production corpus acceptance is added here.

## Design note

1. **Responsibility and boundary.** Catalog owns admission of exact Item sources.
   The inference-transfer use case asks for either `ALL_ADMITTED_GRAPH_ITEMS`
   (the existing additive default) or `OCCURRENCE_BACKED_PAST_EXAM`. The latter is
   a population restriction, never an authority grant. Existing released V2
   retrieval requests, ranking and evidence publication remain unchanged.
2. **Canonical source.** Published Graph associations, accepted analysis runs,
   historically approved Item revisions, and snapshot-local
   `assessment_item_occurrence_references` are authoritative. Original M01's
   occurrence-backed 520 targets excluded the non-occurrence trusted-RAG canary;
   520 is historical evidence, not a permanent runtime count or code constant.
3. **Logical and revision model.** This introduces only a small immutable enum
   and internal command field. It creates no logical entity, persisted revision,
   table, migration, cache, duplicate report, or new search engine. Caller-pinned
   Graph and access-policy revisions define the read scope.
4. **Pointers and checks.** Occurrence membership must match the exact Graph
   revision, accepted base analysis run, Item logical ID and Item revision from
   the admitted Graph association. A different historical revision of the same
   Item, another analysis run, or another Graph does not satisfy membership.
   Existing source/artifact/schema/hash/lifecycle checks still resolve the source.
5. **Access patterns.** Admission uses indexed immutable membership, grouped
   source enumeration, bounded ordered iteration, and exact run lookup. Final
   authorization rechecks the same complete admitted scope, including sources
   without reports; it does not only recheck the selected top-ranked profiles.
6. **Structures and indexes.** A correlated SQL `EXISTS` applies occurrence and
   `PAST_EXAM` source-class constraints before the distinct analysis limit.
   Existing unique `(graph_snapshot_revision_id, analysis_run_id)` and B-tree
   `(graph_snapshot_revision_id, item_revision_id)` occurrence indexes support
   lookup. `EXISTS` cannot multiply sources when several placements are present.
   The existing canonical source resolver owns deeper placement validation.
7. **Scale and complexity.** The existing maximum of 1,024 sources covers the
   historical 520-item pilot. Admission performs one grouped bounded query and
   one bounded pointer query, with indexed occurrence checks; application
   deduplication uses maps/sets. Overflow retains the existing explicit truncated
   population or pointer-budget error. No new per-source SQL membership loop is
   added. Existing canonical-resolution costs are not claimed to be optimized.
8. **Transaction and concurrency.** The Catalog adapter uses its existing
   read-only repeatable-read transactions. Initial admission and final
   reauthorization each use the same typed population scope and exact policy/
   Graph pins. Revoked or changed membership fails the frozen population check;
   there is no direct row correction or implicit latest fallback.
9. **Dependency direction and ownership.** A pure enum module is shared by the
   application command and Catalog SQL admission DTO. It imports no database,
   filesystem, model, API or worker code. The Catalog adapter derives actor roles
   and permissions from supported identity records and passes the population
   value to the existing owner boundary. No model-supplied authority is accepted.
10. **Failure, retry and idempotency.** Unknown enum values are rejected. Missing
    occurrence membership produces no eligible source, not invented evidence.
    Reauthorization drift raises the existing exact-pin mismatch. Reads are
    side-effect free and replay the same immutable pins; profile/report absence
    remains explicit. The default retains the prior all-admitted pool semantics.
11. **Simpler alternative.** Filtering an already-limited pool in Python would
    allow a canary or mismatched placement to consume the budget, silently miss
    eligible original items, and lose membership during reauthorization. The
    single pre-limit `EXISTS` extends the existing service without those defects.

## Validation scope

Unit tests cover the default, enum validation, exact correlated identities,
pre-limit authority/source filtering, propagation, and final scope reuse/drift.
Guarded disposable PostgreSQL fixtures cover missing canary occurrences,
incorrect historical Item/Graph/run references, answer-bearing restrictions,
bounded population order and duplicate placement immunity. They do not establish
production actor authority, NAS resolution, the current original-corpus count,
or native embedding quality. Those remain separate installed-runtime acceptance
tasks.

## Exact pair source authorization

The public Catalog-owned `authorize_pair(command, left_profile, right_profile)`
read boundary is a second, bounded consumer of the same admission/projector:

1. Catalog owns source authorization; Orchestrator may consume an injected
   owner port, without importing Catalog implementation or accepting model roles.
2. Canonical inputs remain published Graph associations, the two accepted base
   runs, accepted V10 Artifact chains and validated report bytes.
3. No new entity, persistence or wire schema is created. Existing profile logical
   ID, revision ID and hash remain separate exact immutable values.
4. Both supplied profiles are revalidated, must pin the command's exact Graph,
   and must reproduce the supported deterministic projector output completely.
   Correct hash or `APPROVED` text alone is never accepted as authority.
5. Access is exact membership lookup for two distinct accepted base run IDs.
   Actual actor permissions, roles, pinned policy, source class, lifecycle and
   population scope are reapplied; unsupported producers fail explicitly.
6. The existing indexed exact-run filter and correlated occurrence `EXISTS`
   select the two sources before limits. Batched report/Artifact resolution and
   maps keyed by immutable run/profile identities avoid per-source scans.
7. Cost is bounded by two sources/reports plus existing canonical resolution;
   whole-corpus admission and embedding work are not needed for a pair check.
8. One read-only repeatable-read transaction checks current authority and exact
   sources, re-resolves both reports, and compares both rebuilt frozen profiles.
9. Shared Catalog profile preparation owns accepted-result hash/UTC timestamp
   validation and deterministic projection for both corpus loading and pair
   authorization. The pure projector remains infrastructure-independent.
10. Missing/revoked/stale/changed references fail closed with stable codes. Reads
    are replayable; no successor, latest replacement or row correction is made.
    `CODEX_DERIVED` is explicitly unavailable until its accepted profile Artifact
    ownership/resolution boundary exists.
11. Reusing whole-corpus authorization would be simpler but needlessly resolve
    up to 1,024 sources for every pair. Trusting a supplied profile hash would be
    cheaper but would permit invented claims. The shared two-source replay avoids
    both problems without a parallel framework.

This is a source-only owner boundary, not installation, API/socket admission,
production actor authentication or worker execution activation. Tests use mocked
official source/report resolvers; guarded SQL fixtures separately prove exact
two-run prefiltered occurrence membership.
