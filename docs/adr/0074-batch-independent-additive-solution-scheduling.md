# ADR 0074: Batch-independent additive solution-report scheduling

## Status

Accepted

## Responsibility and boundary

The Catalog automatic-learning application service schedules an additive V10 solution report after
an accepted V9 past-exam analysis exists. Extraction batches remain private orchestration details
for intake, promotion, and initial V9 analysis. They do not define the identity or lifecycle of an
already accepted analysis and must not decide whether that analysis receives its additive report.

The canonical sources are `knowledge_analysis_runs`, the immutable accepted V9 result pointer, and
the V10 predecessor relation. Item, Item Revision, analysis run, accepted-result Artifact,
proposal Artifact, and content hashes remain separate identities. V10 continues to pin and reuse
the exact V9 result and eight proposal-member pointers; it never copies their payloads.

## Access patterns and data structures

The dominant operations are:

- ordered lookup of one accepted V9 past-exam run with no V10 successor;
- bounded lookup of active V10 runs for reconciliation;
- membership lookup of explicitly allowlisted failed V10 attempts;
- fail-stop lookup of any terminal V10 leaf without a successor.

These are relational key, membership, and anti-join operations. The existing B-tree index on
`predecessor_analysis_run_id`, state/created-at index, idempotency-key uniqueness, and partial unique
index allowing at most one accepted V10 successor per predecessor are authoritative. Queries use
indexed predecessor joins and bounded ordered results; Python combines at most two bounded active
sets in `O(1)` space and time. Expected scale is thousands to low tens of thousands of analyses.
No batch-sized in-memory list, N+1 lookup, new cache, or binary database value is introduced.

## Decision

- V10 candidate, active-run, retry, and terminal-leaf selection is global for accepted
  `PAST_EXAM` V9 analyses and their V10 successors.
- Initial extraction, promotion, V9 scheduling, and Graph publication remain limited to the
  configured private batch scopes.
- Global V10 selectors identify the typed request schema and predecessor relationship directly;
  they do not traverse extraction batch tables.
- The two-run capacity bound remains unchanged. Active global V10 rows and batch-scoped pre-V10
  rows are merged by stable `(created_at, analysis_run_id)` order and capped at two.
- Ordinary product projections remain batch-free. Existing ID-oriented batch routes and records
  remain available for later administrator tooling and are not removed.

## Transactions, concurrency, failure, and retry

The existing preset-pin shared lock covers selection and creation. V10 creation locks the base run,
uses a deterministic idempotency key, and the database partial unique index prevents two accepted
successors. Reconciliation and acceptance retain their existing transactions and pointer checks.
Any unallowlisted terminal V10 leaf stops automation globally; an explicitly allowlisted failed V10
gets at most one deterministic retry. Dangling predecessors, changed hashes, and stale pointers fail
closed without substituting a latest revision.

The application service owns orchestration. Workers still receive staged typed input, do not access
PostgreSQL or NAS, and return a local structured result; only the orchestrator/Catalog boundary
commits validated artifacts.

## Simpler alternative and why it is insufficient

Keeping the extraction-batch join in V10 selectors would process the present 520 rows but silently
skip future accepted V9 analyses from an unconfigured or retired batch. Adding every future batch ID
to an environment variable would expose an ingestion detail as product behavior and require manual
coordination forever. Removing batch scope from the entire service would wrongly broaden intake and
Graph mutations. Limiting only the additive V10 lineage to its canonical predecessor relation is the
smallest correct boundary.

## Verification

Focused tests prove that an accepted V9 row outside configured batches is selected, its active V10
successor is reconciled, its failed terminal V10 leaf stops automation, and explicit retry remains
single-use. Existing tests continue to prove batch-scoped intake behavior, deterministic ordering,
idempotent replay, two-slot capacity, and terminal fail-stop semantics.
