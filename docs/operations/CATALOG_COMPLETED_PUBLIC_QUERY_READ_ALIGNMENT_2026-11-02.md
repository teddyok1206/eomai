# Completed public QUERY read alignment

## Actual boundary and evidence

The user's GUI QUERY completed on CUDA as
`workflow_069bffbac9664bb7b73713efd82ee387`, native Job
`job_6bd96938000542c39683df78c7b5e473`, released coordinator2 with
ALLOCATION/EXECUTED/PUBLISHED/COMPLETED. The exact native launch and Workflow
idempotency keys each resolve to one identity. Output SHA is
`sha256:11ecd464bfe475b74df798ac2e01d1bdf17729b8345bd7e8619c2434303a0a05`.
The user still reports no result list. A completed read HTTP request took100,804ms;
the API's bounded Catalog result-read RPC remains90s. Do not call this GUI PASS.

The actual Catalog receiver is still8eb03e40. Its completed-source preparation
calls the old public helper that reads the full population and DOCUMENT vectors,
including when only the original anchor QUERY text is needed. QUERY's4f5f2e86
already has the corrected anchor-only helper. Catalog also lacks the previously
tested eb07e901 root-local immutable report-decoding reuse. Do not replace the
entire receiver with QUERY's wheel: it contains unrelated private-query changes.

## Narrow existing-owner correction

1. Boundary: Catalog's current-authority completed QUERY read, not encoding or API
   authentication. Backport only the already implemented anchor/decode corrections.
2. Canonical source: existing approved sources, committed members and completed
   QUERY2 receipt. No new registry, queue, index format, schema or migration.
3. Preserve logical/revision/Artifact/hash identities and the original query key.
4. Resolve the exact released manifest/schema/hash/namespace; capture only the
   anchor for QUERY preparation. Keep full DOCUMENT verification in final ranking.
5. Access: indexed anchor selection and root-local immutable decode lookup.
6. Reuse the existing bounded session/thread/root/settings-owned reader. Page
   readers share decoded immutable values, never current permissions or approval.
7. Remove unrelated O(population) preparation and repeated JSON/model decoding;
   retain the existing bounded cache and full ranking complexity/budgets.
8. Existing caller transaction, source locks, artifact epochs and late source/
   policy/Identity fences remain. No cross-request or authorization cache.
9. Dependencies stay in the same Catalog adapters; no new dependency.
10. Missing/stale/hash/revoked targets still fail. Read the same completed QUERY;
    no numerical retry, successor query, new key or old failure reinterpretation.
11. Increasing a timeout would leave the confirmed repeated read path in place.
    Deploy the narrow receiver correction, then verify the actual same-key GUI
    result, selected result in DB and another read without another native Job.

Before correction the actual8eb baseline regressions are2 FAIL/3 PASS: legacy and
registered public anchor preparation perform forbidden unrelated population IO.
The fix retains those three manifest/lifecycle negatives. Unit/installed tests
and readiness are not substitutes for the user GUI result/read/replay gate.

## Compatible rollout

Build a clean8eb-based Catalog-only owner successor. Preserve current API schema68,
QUERY4f5f2e86, INDEXaac48433, controllera70cd434, every numerical runtime/config,
the private feature activation state, credentials and canonical data. Change only
the receiver's protected package prefix through its existing unit override, with
the exact old bytes saved for rollback. A receiver restart must not restart GPU
INDEX/QUERY. If the pending read timed out, use the same browser operation/pins
for result observation after deployment. Normal reauthentication, if required by
the unchanged policy, is not permission to create another calculation.
