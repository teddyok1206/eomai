# Candidate pointer detail SQL access path

2026-10-29 UTC. This is the existing Catalog candidate-detail metadata query,
not a new retrieval engine, source grant, cache, index or numerical runtime.

## Boundary and invariant

The canonical source remains the pinned Graph's pointer/node rows and accepted
source resolution. The public application still authorizes before/after reading,
checks the exact Graph/policy/revision/hash/lifecycle, and materializes source
Artifacts through its existing reader. Logical/revision/Artifact/hash identity and
the owner transaction do not change. No database migration or dependency is added.

The dominant access is selected analysis-ID membership within one immutable Graph,
followed by exact node-key lookup and stable ordered iteration. A bounded source
population can contain hundreds of pointer rows per source. Existing indexes
begin with `(Graph,node,...)` or `(Graph,source_class,source_revision)`, not the
exact `(Graph,analysis)` membership operation used by this second query.

The application exposes its exact detail SQL as a static builder for SQL-only
tests. A PostgreSQL MATERIALIZED selected-pointer CTE reads the exact Graph,
analysis IDs and source classes once before the existing node join. It preserves
every pointer row (no DISTINCT), the orphan-node and answer-bearing filters,
occurrence-specific source class, `analysis,node,anchor` ordering, outer overflow
`LIMIT+1`, and ORM pointer/node identities with `populate_existing`.

This query shares the caller's existing transaction and locks. It does not reuse
permission/source decisions across roots, mutate state, retry a failed Workflow,
or change idempotency. Empty/overflow/stale/error behavior remains unchanged.
The SQL builder stays in the existing Catalog infrastructure owner; contracts and
domain packages gain no database dependency. Expected work is one relevant
pointer scan plus the ordinary node-key join and ordered result. The selected
relation uses O(selected pointer rows) transient database space, with PostgreSQL's
normal spill behavior. The existing maximum1,024 sources and outer pointer budget
are unchanged; the materialization does not create a durable derived population.

## Evidence and acceptance

An isolated disposable PostgreSQL test creates only `pg_temp` tables. It ANALYZEs
an old Graph with 520 analyses ×142 pointers and 20 nodes/source, then clones a
fresh Graph without ANALYZE. It executes the actual production detail statement
using custom and generic prepared plans for selected 8 and full 520 analyses.

Before the change, selected 8 custom took 1,000.528 ms and generic 31.089 ms. Full
custom exceeded the 20,000 ms statement guard. This exposed a second join that the
earlier candidate/membership CTE regression did not exercise. These are synthetic
metadata timings, not live source admission or CUDA throughput acceptance.

Repeated post-change execution, in milliseconds:

| Shape | Previous query | Materialized query |
| --- | ---: | ---: |
| Selected 8, custom | 1,000.528 | 117.433 |
| Selected 8, generic | 30.312 | 30.891 |
| Full 520, custom | >20,000 (cancelled) | 426.856 |
| Full 520, generic | 240.118 | 320.014 |

The generic path was already fast and is not universally faster after this
change. The trade-off is a small bounded materialization overhead to remove the
fresh-Graph custom-plan timeout. All four resulting plans scan the pointer table
once and materialize their selected relation once. Baseline generic references
remain executable in the isolated regression; the known-timing-out old full custom
query is not rerun on every test. This does not establish that the entire live
32.993-second ADMIT stage is SQL-only or eliminate its canonical Artifact checks.

The simpler alternative is leaving the ordinary join untouched or manually
ANALYZing each newly published Graph. The former reproduced the timeout; the
latter cannot guarantee estimates during publication and does not remove the
query's sensitivity. The materialization boundary is local to this one existing
query and does not create a durable derived population.

The focused disposable suite passes 61 tests. Separate semantic cases compare the
new query to the old query for duplicate node references, missing nodes,
answer-bearing authority, source class and occurrence restrictions, stable order,
the outer257th overflow sentinel, and identical ORM pointer/node identities.
The focused unit suite passes13 tests; Ruff format/lint and strict mypy pass.
No production database, physical GPU runtime, model, prompt or authentication state
was changed by these tests.
