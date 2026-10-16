# C5 protected release preparation and actual C1 read discovery

2026-10-16 UTC. Full incremental-RAG goal remains ACTIVE. This is operating
preparation/diagnosis, **not installed C5 activation or authenticated read PASS**.

## Prepared exact candidate

- Source `cb9eabc47c83534d20441e43651fb80c04bb9559`, tree
  `e49e17114edb132389a28e819473111e56199c27`, main/origin clean.
- Inspected delivery:
  `/tmp/eom-api-build/cb9eabc47c83534d20441e43651fb80c04bb9559.475XdT`.
- Source archive SHA `22a698b998eec41b647d8122f10ab4d93b0ac5bbe0c8666823db3c1e79a913be`.

| Wheel | Raw SHA-256 |
| --- | --- |
| platform | `585632e43872a28d4b025da07036c8c2d85bdf15c3fa5243c8421ee9b98575c9` |
| API contracts | `ee64dfc8e1d9dca95afdcf5c6702de3f5c10edfa5bee56a413f77377babe657f` |
| API | `3f96d6d648ded7cf560fe871132786d439aa68932039616e18309a4fcb404caa` |

The existing EOM2 pane `%89` retained valid sudo authentication. No password was
requested, copied or saved. The reviewed protected materializer was reused with
only the immutable SPECS/EVIDENCE constants changed; AST comparison proves the
remaining logic unchanged. Installed private helper raw SHA:
`3291dc7d86ca7e798656f00de58d35a355ce22735ab7c127dedcb337558082dd`.
One guard invocation initially referenced absent `/usr/bin/rg` after installing the
exact helper but before executing it. The existing installed hash was independently
verified and the shell comparison corrected; no second install or weakened hash
check was needed. Original failure marker is preserved.

Protected materialization succeeded19:16:45:
`/var/lib/eom-release-operator-stage.cb9eabc4-35c1jnh2`.
Context1.4 raw SHA:
`80a26baa0e5b57c736de6fc102c452f70ab301092db415eaf2cc694f4a5d8fcb`.
Existing independently reviewed launcher/helper performed ADMIT and exited0 with
`release_operator=ADMIT_PASS`. It used the old accepted protected interpreter,
not developer Python or the unadmitted CUDA candidate. Migration remains0055.

No package installation, service drain/restart, API-provider rebind, flag enable,
Graph/policy change, DB mutation, model execution or HWPX generation occurred.
API/Catalog184d6dca, QUERY0fab and INDEXc698 were not replaced. New code remains
default-off. Preserve this stage even if a later fix requires another candidate;
new source/wheel bytes require their own context/admission, never this receipt.

## Original actual-user HTTP observer

At the scheduled19:18 observation the original process PID2391005 was live, but
its authoritative state had advanced to `AWAIT_EXPLICIT_REPLAY`, not LOGIN.
Its safe event log establishes:

| UTC | Actual result |
| --- | --- |
|19:02:31.885927|guiadmin login PASS; credentials in memory only|
|19:02:43.967797|same original preparation READY|
|19:02:53.604202|same-key replay returned200 before the read|
|19:03:23.646246|context read503, `SIMILARITY_CONTEXT_UNAVAILABLE`|

The existing request/key/Workflow and successful numerical Job are unchanged.
No new request identity, model retry, row repair or success-history rewrite was
performed. API completion event `req_a67a20911914ff30854e436b45ba27e8` records the
context route at **30039.625ms**, matching the fixed Unix client's30s deadline.
The first READY/replay durations were12077.562ms/9635.921ms. These are real timing
observations, not yet proof of the backend's exact bottleneck or a successful
read. Catalog source/decoding reuse and bounded read lifetime need investigation
before replay; do not merely claim timeout means a corrupt result.

The last login's900s freshness window has elapsed. Preserve the live observer and
do not ask repeatedly or deliberately replay into a known freshness failure.
After a verified fix, use its supported controls; a necessary replacement must
end the old observer first and retain the same completed request. Never patch a
live process, save/recover its token, extend TTL or rerun the successful encoder.

## Background operating metadata, not source authorization

Existing INDEX PID2387580/invocation`cde19addd2d84a7fade202ef746da965` was active at
19:18. Next routine check is no earlier than19:48:08. A separate failure-diagnosis
READ ONLY transaction19:21:59 reported257 aggregate encodings/bindings,71 immutable
index revisions and6 logical indexes. These are **not257 distinct Items**, raw
vector integrity revalidation or complete520-target coverage.

The latest three listed namespace revisions have binding counts95/77/85 with
eligible-source count545; this observation does not reconstruct missing reports
or assign view labels without resolving those exact index manifests. Three real
recent INDEX commands reached SUCCEEDED at18:58:19,19:09:18 and19:20:17. The new
19:21:14 reconciliation is QUEUED, not terminal proof. The operational query's
historical service-ID filter is not used as current queue/quiescence authority.
`pg_stat_activity` state/wait details were redacted, so no historical blocking
conclusion is drawn from them.

Temporary bounded operating logs are in `/tmp/eom-c5-release-SnFSsn5F` and the
unchanged original observer directory. No secret, source content or full log is
committed or sent to Slack. Next: investigate common read's repeated immutable
materialization/budget with source and synthetic benchmark evidence, then build
the corrected compatible candidate before any installation or actual-user replay.
