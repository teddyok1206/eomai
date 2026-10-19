# Graph query planner statistics maintenance

2026-10-14 UTC. Owner maintenance, not a new worker/runtime feature.

## Evidence and bounded action

The unchanged official population query estimates1 admitted source although the
actual pinned scope admits520. Read-only metadata finds current Graph nodes17390,
associations1040 and source pointers72869, while these tables' last auto-ANALYZE
is2026-09-10. The append-only totals are about786k nodes/47k associations/2.7M
pointers; recent inserts remain below the default proportional analyze trigger.
Same-role diagnostics observed long active selection queries, no blocking PID.
These observations motivate a statistics refresh; estimates alone are not a
measured execution-time improvement or proof of every latency cause.

Canonical sources remain immutable source/report/Graph/Artifact revisions. Planner
statistics are PostgreSQL-derived caches; refreshing them changes no source row,
logical/revision/hash, permission, execution identity, code or DB migration head.
All original source and late actor fences continue. No worker receives DB rights.

The genuine protected DB/table owner may run only these three fixed actions:

```sql
ANALYZE app.knowledge_nodes (graph_snapshot_revision_id, node_id);
ANALYZE app.knowledge_snapshot_analyses
    (graph_snapshot_revision_id, analysis_run_id, source_kind, source_revision_id);
ANALYZE app.knowledge_node_source_pointers
    (graph_snapshot_revision_id, analysis_run_id, node_id, source_revision_id, source_class);
```

Verify the actual owner against the installed nonsecret owner pin and the exact
three table owners, with no SET ROLE or privilege grant. Use a separate bounded
transaction per table: lock_timeout2s and statement_timeout90s. Do not run a whole
database scan, VACUUM FULL, data repair, index rebuild, new encoding or Workflow
resubmission. ANALYZE samples metadata columns and updates derived statistics;
no Item/prompt/result content is returned. Existing schema and lookup indexes stay.

## Verification and failure behavior

Keep the original active Workflow/command/lease and service invocation. Capture
before/after official EXPLAIN shape/estimates, actual pinned row counts, last
analyze metadata and subsequent original execution timings. Do not equate a lower
estimated cost to measured speed. The operation has no idempotency identity and
does not authorize model retry; preserve every actually completed table refresh.
On owner mismatch/timeout, stop rather than broaden permissions or restart work.
Statistics are approximate and cannot be restored by copying a history record;
the fallback is a subsequent authorized refresh after diagnosis, not source edits.

Review recurrence after evidence: a small new Graph may not cross a global large
table threshold. Do not add a new maintenance queue/framework or automatically
grant ANALYZE to Catalog. Any durable per-table autovacuum tuning or owner-owned
post-publication maintenance must be measured and reviewed separately.

Primary references: [PostgreSQL ANALYZE](https://www.postgresql.org/docs/16/sql-analyze.html)
and [autovacuum settings](https://www.postgresql.org/docs/16/runtime-config-autovacuum.html).

## Actual 2026-10-14 result

The three fixed column-only actions completed at12:42:06–07 UTC in approximately
107ms/95ms/1470ms, under the actual table-owner login. Pinned Graph counts stayed
17390 nodes/1040 analyses/72869 pointers. No data/schema/permission/runtime edit.
The subsequent exact metadata EXPLAIN ANALYZE hit its10s statement timeout;
statistics refresh is therefore NOT a latency PASS. Global autovacuum settings
were not queried; the default-threshold comparison above is not a measurement of
this server's effective settings. See
`../architecture/LOCAL_INDEXING_SELECTION_AND_INITIALIZATION.md` for the bounded
selection correction and its separate correctness/performance gates.

Local evidence:
`/tmp/eom-identity-provider-install.nAaycoDM/native-index-planner-statistics-refresh.log`,
`native-index-post-statistics-observation.log`,
`native-index-query-measurement-result.log` in the same directory. These are
temporary operational evidence, not new canonical source/index artifacts.

## Actual 2026-10-19 INDEX21 maintenance

At 19:58:08 UTC, the fixed metadata observation for
`graphrev_8f3ff9b22d592ecf661fec7116a5cab9` found that this Graph was absent from
the most-common-values statistics for `knowledge_nodes.graph_snapshot_revision_id`
and `knowledge_node_source_pointers.graph_snapshot_revision_id`. Both last manual
analyzes were from 2026-10-14; their last auto-analyzes were from 2026-09-10.
The association table had auto-analyzed at 18:08:16 on 2026-10-19 and already
included this Graph. These are table-specific observations, not a claim that all
database statistics were stale.

The genuine direct table/schema owner `eom_app`, OID 16385, with no selected role,
completed the same three fixed column-only ANALYZE actions at 19:58:34–36 UTC:

| Table | Pinned Graph rows, before = after | ANALYZE elapsed |
|---|---:|---:|
| `knowledge_nodes` | 17,405 | 254ms |
| `knowledge_snapshot_analyses` | 1,041 | 101ms |
| `knowledge_node_source_pointers` | 72,937 | 1,343ms |

The post-observation found the Graph in the node and pointer most-common-values
statistics as well. No source row, schema, index definition, grant, code, runtime
pin or model configuration changed. This was owner maintenance of derived planner
statistics, not source authorization or a new runtime ANALYZE permission.

Before/after EXPLAIN-only snapshots used the same exact four source revisions,
Graph, request/source-plan pins and two statement-template hashes. After refresh,
the plan used existing `ix_knowledge_snapshot_source_revision` and
`knowledge_nodes_pkey` (Index Only Scan), rather than the prior node-type-index
path. No query execution, actual rows/loops or EXPLAIN ANALYZE was collected by
these snapshots. Candidate estimated total cost **increased** from 42.71 to 8389.41;
estimated cost is not elapsed time and is not evidence that execution became slower.

Subsequent original runtime stage events at 19:58:48–56 recorded
`LOCK_POPULATION=142ms` and `ADMIT_CANDIDATES=6522ms`. Earlier events in the same
saved log recorded approximately 31.9–32.3s locks and 32.7–33.3s admissions, with
some admissions around 69s. The runtime stage records omit the selected-source
bound/scope (`k`), so this is an observed timing change, **not an identical-scope
benchmark, causal speedup ratio, end-to-end completion or final HTTP latency PASS**.

At the 19:59:01 checkpoint, the original Workflow was still RUNNING, with an
allocated coordinator Job in VALIDATING_RESULT and ALLOCATION/INDEX_PREPARED
checkpoints; no completed index was observed. The prior 19:54:53 normal MAIN-only
SIGTERM still awaited completion of its current run-once operation. The max64
configuration successor was DRAFT with 14 pure tests passing, **not selected**.
New-Graph baseline proof, the generated target binding and final QUERY/HTTP proof
remained pending at this checkpoint.

Evidence root: `/tmp/eom-registered-review-patch.zbfFVg5a/`:

- `index21-graph-statistics-observe.json`, rawSHA `5a4ed30085e5945ed5dcf79bc198e7146d4da3a14ec2603644452a9a3a03db7b`.
- `index21-graph-statistics-apply.jsonl`, rawSHA `f2280430fbc96474a0606418eb6bdf7de11b6760299c988ccf7f2d393511d4ae`.
- `index21-selected4-explain.json`, rawSHA `b0cc1a60333f92e81d1a7de4329ed5b235e7c097a77df6991d20f0fa1c5e5584`.
- `index21-selected4-explain-post-stats.json`, rawSHA `6de762d0d7d1421960b676083fa7ba3bc16015f4adfece456b3bee114ce30013`.
- `index21-events-post-stats.log`, rawSHA `beb2bf52497031d81b68371ca2b9e23660a6cff184857a9f7f57bfcfd6fcfd05`.
- `index21-completion-post-stats.json`, rawSHA `887acaa526ee0c72657b79d1ed3209e79ab6d44845bd7187c57284cd1a220671`.

A future small Graph can again be absent from statistics on these large
append-only tables. Reuse this evidence-led, bounded owner-maintenance boundary
when needed; this checkpoint introduces no automatic ANALYZE grant, maintenance
framework, autovacuum change or post-publication hook.
