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
