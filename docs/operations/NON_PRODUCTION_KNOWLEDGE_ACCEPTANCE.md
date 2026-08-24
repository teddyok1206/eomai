# Non-Production Knowledge Acceptance Data

Status: reviewed operating contract

Last reviewed: 2026-08-24 UTC

## Purpose and boundary

This runbook permits the smallest production-shaped data set needed to exercise the deployed
Knowledge Analysis, immutable Education Graph publication, and bounded Evidence Bundle paths before
reviewed curriculum, textbook, and historical-usage inputs are available. Acceptance data is never
presented as production educational authority and never changes an existing Item, Item Revision,
workflow, HWPX build, Product, Form, Publication, or Usage Record.

The initial run reuses one already approved current Item Revision as a pinned source. It creates one
fresh Knowledge Analysis, one dedicated acceptance corpus with one Graph Snapshot Revision, and one
Evidence Bundle. It does not create a legacy workbook, Product/Form placement, student record, or
knowledge-grounded Item workflow.

## Canonical source and identities

The source is an existing approved Item Revision selected immediately before the run. Eligibility
requires the logical Item, exact current Item Revision, ITEM_CONTENT Artifact Revision, media type,
schema, lifecycle, and SHA-256 to resolve without substitution. The run records these identities but
does not copy the Item JSON into its operator manifest.

Acceptance identities use this namespace:

```text
acceptance-p12-YYYYMMDD-<short-source-revision>
```

The corpus display name starts with `NON_PRODUCTION_ACCEPTANCE:`. Idempotency keys use the same
namespace and are stored only in a protected run-state directory. A generated run manifest records
IDs, revision IDs, hashes, state transitions, counts, timestamps, and the source commit. It contains
no item content, worker prompt/result, credentials, bearer token, database URL, or filesystem
content path.

## Pointer and publication contract

The acceptance chain is:

```text
approved Item -> pinned Item Revision -> approved ITEM_CONTENT Artifact Revision
              -> accepted Knowledge Analysis result Artifact Revision
              -> immutable Graph Snapshot Revision
              -> immutable Evidence Bundle Revision
```

Every boundary validates existence, exact revision, state, schema, media type, hash, and operator
authority. Knowledge Analysis runs through the existing orchestrator and support worker. Workers
receive only staged local inputs, have no database or NAS authority, and submit structured results
through the orchestrator. Catalog alone commits accepted artifacts and graph/evidence publications.

The graph corpus key is never reused for real data. Publication uses one sorted accepted-analysis
run set, one fixed publisher version, an explicit expected-current pointer, and a unique
idempotency key. Retrieval pins that exact snapshot and the released access-policy revision. It uses
one closed query kind and bounded budgets; it accepts no raw graph query, host path, NAS path, or
implicit latest source revision.

## Access patterns and scale

The sample has one source revision and is intended only to exercise exact-key lookup, immutable
revision resolution, indexed term lookup, and bounded adjacency selection. Expected cost is
`O(log n + k)` for indexed lookup, with `k` bounded by the Evidence Bundle budget. The persistent
structures remain the existing indexed PostgreSQL tables and typed manifests. A graph database,
vector dependency, cache, or new migration is not justified by this sample.

## Transaction, concurrency, and idempotency

Each state-changing boundary has one independently recorded authorization and idempotency key.
Knowledge Analysis submission, review, graph publication, and retrieval are separate transactions.
An exact replay returns the existing result; a same-key/different-input replay fails closed. The
run stops at the first terminal failure and never submits an automatic second Codex analysis.

Only one acceptance run may own the namespace. The protected state directory is created with mode
`0700`; marker and manifest files use `0600` and exclusive creation. The existing worker capacity
policy and global Codex limit remain unchanged.

## Review and acceptance

Before approval, an operator reviews the proposal's typed state, risk result, source pointers,
counts, unsupported/ambiguous findings, and bounded artifact metadata. Content is never sent to
Slack. Approval creates a new immutable accepted-result artifact; rejection creates no graph.

The Graph Snapshot must be `PUBLISHED`, contain exactly one source revision, and have nonzero node
and anchor counts. The Evidence Bundle must be `PUBLISHED`, pin the exact graph and policy, contain
at least one graph node and one source entry, remain within budget, and replay deterministically.
Service health, runtime identities, installed source provenance, Git cleanliness, and public Studio
health are checked after the run. No HWPX build or new Item workflow is part of this acceptance.

## Retirement and cleanup

Published Knowledge Analysis results, Graph Snapshots, Evidence Bundles, and their Artifact
Revisions are immutable audit history. They are not physically deleted, rewritten, or relabeled as
real data. When reviewed real data arrives:

1. publish the real corpus under a different reviewed corpus key;
2. switch any preset or user-visible selector only to the real corpus after pointer and retrieval
   acceptance passes;
3. retire the acceptance corpus header through a reviewed Catalog application command so it can no
   longer resolve for item production;
4. disable any acceptance-only UI opt-in or preset revision without deleting historical plans;
5. remove only disposable run-state, workspace, downloaded, and temporary materializations listed
   by the run manifest; and
6. retain the minimal immutable database/artifact lineage for audit and reproducibility.

The current Catalog model already distinguishes `ACTIVE` and `RETIRED` corpus lifecycle states, but
retirement must not be performed with raw SQL. If a reviewed Catalog retirement command is not yet
available at transition time, stop with `ACCEPTANCE_CORPUS_RETIREMENT_TOOLING_REQUIRED`; do not
delete rows or mutate current pointers manually.

## Excluded synthetic data

No synthetic legacy workbook or Usage Record is committed merely to populate a dashboard. Legacy
intake requires an actual reviewed workbook artifact, mapping-contract revision, and row decisions.
No invented curriculum hierarchy is marked authoritative. A future curriculum acceptance fixture
may use a separate non-production corpus and the same retirement contract, but it must not be mixed
with this one-item smoke corpus.

## Failure and rollback

A failure preserves created immutable evidence and records the first stable error. It does not
broaden permissions, bypass review, directly invoke a worker, repair a worker account, retry a
usage-consuming Codex submission, or silently fall back to general model knowledge. Before graph
publication, rollback is simply to stop. After publication, rollback means preventing selection of
the acceptance corpus and later retiring its mutable header; immutable snapshots remain preserved.

The simpler alternative of inserting graph or usage rows directly is insufficient because it
bypasses source validation, artifact ownership, idempotency, operator audit, and the exact runtime
boundaries this acceptance exists to test.
