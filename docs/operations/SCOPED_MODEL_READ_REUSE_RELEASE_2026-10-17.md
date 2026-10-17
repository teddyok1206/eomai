# Scoped immutable model reuse: compatible operating release

2026-10-17 UTC. **INSTALLED / SERVICE_STARTUP_PASS / ACTUAL_CONTEXT_READ_PENDING**.
The full incremental-RAG goal remains ACTIVE/NOT_COMPLETE. This is not a successful
original-context delivery/latency result or full C1–C5/CUDA acceptance.

Source rationale and tests:
[scoped decoding design](../architecture/SCOPED_TYPED_ARTIFACT_DECODING.md),
[source/PG/package checkpoint](../status/SCOPED_ARTIFACT_MODEL_REUSE_CHECKPOINT_2026-10-17.md).
The [original HTTP failure](../status/REFERENCE_QUERY_HTTP_READ_TIMEOUT_2026-10-17.md)
and earlier installed e132c1aa remain separate immutable history.

## Exact source and preparation

Operating candidate `4222ca9a9747eee4ab9d3da1b67a6d4188f8d33c`, tree
`11d1369e966403e161217b12bd5e37b0b890f0f8`. Only documentation changed after core
f5994de2. Comparing all three wheels found identical member sets and code bytes;
only API build-info.json and its RECORD changed. Source217 focused/strict4 and
guarded PostgreSQL47+213/cleanup gates apply to the unchanged runtime code.
The new candidate independently passed three-wheel RECORD and isolated182-module
import/optional-port/two-consumer composition checks without source/test/ML imports.

Archive raw SHA `29ca2c1d6db81b6e15d917704248fb5141e277798acc41135baad0ebe78a11bf`.
Existing materializer AST changed only SPECS/EVIDENCE constants; helper raw SHA
`62e3b452da1ff1f3cd4dc8225dc6e6178dd16c7b722ace6bfb7ad6bae3b69298`.
Root-private stage `/var/lib/eom-release-operator-stage.4222ca9a-7p5vhm08`, context1.4
raw SHA `66d52413642c08b41ff4f5e49bd3ed2e45303e38d4a4e8909d09bf2361dae07e`.
The existing protected runtime/launcher returned `ADMIT_PASS callback=ADMIT` for
this exact context. f5994de2's prior receipt was **not** reused for different bytes.

## Normal drain and maintenance

15:23:14: only the exact owner main processes received supported SIGTERM:

- QUERY PID3633843, invocation `ae90dbc175f741ddb7b8092024e6771c`;
- INDEX PID3633849, invocation `7c9ea0c56cb2425cbf7d0a194e2118e1`.

No numerical child was signaled or force-killed; no systemd stop timeout was used.
QUERY exited0; INDEX finished its in-progress processing and exited0 by15:26:53.
Both had MainPID0, inactive/dead, Result=success, ExecMainStatus0 and empty cgroups;
no native embedding unit remained active. A missing observation was never treated
as termination and no model/job was retried to make drain succeed.

The existing supported maintenance helper was changed only to the exact new
protected source/site stage. Helper raw SHA
`10fe5ae7529c094a56ff08c0f65935b0e16067f0402e1b07718322fd220716ac`.
CHECK15:27:03 and independent STOP15:27:17 both passed DB/worker/native quiescence;
eight original shared services were stopped under the existing maintenance fence.
No direct row repair, migration upgrade, history rewrite or authority expansion.

A preliminary metadata-only capture incorrectly expected the old deployment
record to be root-owned and stopped before effects. Inspection of the official
record writer confirmed its expected eom-api ownership0600. Only that diagnostic
expectation was corrected, preserving the failed script. Runtime/config root
ownership checks were not relaxed. The prior record and all old wheels remain.

## Actual standard installation

Standard `scripts/api/deploy_release.sh --install` ran once from clean4222ca9a with
the matching admitted context. PDF runtime, migration0055 verification, API role
bootstrap, Catalog/HWPX role reconciliation, wheel RECORD, deployment metadata,
pidfd fail-closed capability, health and actual API isolation all passed. There was
no schema upgrade, timeout increase, model change or numerical QUERY regeneration.

Actual installed delivery (different ZIP materialization from build-only wheels):
`/tmp/eom-api-build/4222ca9a9747eee4ab9d3da1b67a6d4188f8d33c.jRpwtg/dist`.

| Actual installed wheel | Raw SHA-256 |
| --- | --- |
| platform | `5f2dd089d3e69a2012b727df86fae1f2124e55ff685488e29056e22e8be97f1b` |
| API contracts | `5625782a37a150e6343a0af95187a8b4fa4f217fa3fa63b7bce9865314fbb774` |
| API | `2fb715a246b8408091292e2e914f1cea6284b98646f771131c80052a35b50df6` |

Installed API build metadata reports4222ca9a. All four changed Catalog modules
match their reviewed source/wheel bytes. The original30s client deadline remains.
Rollback record:
`/var/lib/eom-api/deployments/4222ca9a9747eee4ab9d3da1b67a6d4188f8d33c.json`.
Verified previous e132c1aa wheels, record and nonsecret provider predecessors remain;
rollback still requires schema/head and compatible-set checks, not blind downgrade.

## Provider alignment and service restoration

Existing fixed provider selector was adapted to4222ca9a's exact installed API wheel,
reviewed code members, previous config/unit hashes and stopped QUERY invocation.
Helper raw SHA `fbe029367a785fcfcb9f3f8343cc10b504dbd5ad3897197cc48f5084fd8ef6df`.
PREPARE/SELECT/START all passed. Only the QUERY api_provider, its unit configuration
hash and nonsecret Chat release pin changed. Previous bytes are retained under
`/var/lib/eom-query-provider-4222ca9a`. This is not session capture or a user grant.

Eight original shared services were restored active with NeedDaemonReload=no.
QUERY READY was actually observed15:30:37, invocation
`1f3ff7fa288747d6bf832906b99d9f13`, main PID494137. Actual socket UID990/GID985,
mode0660 was checked; the developer account's inability to stat its private parent
was not misreported as a missing socket. API/Catalog PIDs491463/491426 are active
with invocations `0b67149fea634f27bdbef35026d182a2`/
`f8946d1d04c04ba6a23bc916d1fd3f3b`. Health-only smoke passed again after restoration.

INDEX's exact three config/runtime/unit hashes were rechecked unchanged before
restart. Its original c6983332 owner remains selected, new PID494402/invocation
`d5b4b9ba83754e95b4a1f99836e5d38e`; STARTED was observed15:31:07. Startup is not
a new binding/vector audit or full corpus coverage. CPU/model/space/Graph/policy,
all old Items/Artifacts/Jobs and unfinished private Chat/exam flags are unchanged.

### Due metadata observation —15:35:30 UTC

The scheduled read-only observation, after normal restoration, reports633 encoding
rows/633 bindings,165 immutable index revisions and6 logical indexes. Latest three
view binding counts are197/213/223, each recording545 eligible sources.15:04:40
counts were625/625/163; these are view relations, not633 distinct Items or full
coverage. The latest five work rows are2 REQUESTED/1 RUNNING/2 COMPLETED with null
failure codes; this bounded window does not prove global absence of failures.
No observation-triggered admission/retry/encode occurred. Next routine observation
is no earlier16:05:30 UTC; foreground operation handles are observed separately.

## Original-request verification still required

Old validator PID2895440 was confirmed live/foreground in AWAIT_EXPLICIT_REPLAY
after its actual403. It had no supported fresh-login control or retained refresh
pair. Supported QUIT ended it; original log/state and failed503/403 remain intact.
No process memory/terminal history/credentials were inspected, and TTL was not
extended or bypassed.

Replacement observer PID496875 is live/foreground in LOGIN on the same EOM window1
`rag-service-release`, with one necessarily fresh Studio guiadmin input requested.
It pins the **same** original key/operation/request hash/Workflow, submits no new
numerical query, and will test READY, replay, two equal authorized context reads
and conflicting-header409. It writes no credentials and stops on a failed window.
State file: `/tmp/eom-query-http-canary-8oxU2rnJ/continuation-state-scoped-model-4222ca9a.json`.
Observer raw SHA `c7c4979da171025fc8c13474e17a65887257936d589bab6598bd48f6b3c947e2`.

Operation evidence under `/tmp/eom-scoped-read-operating.VHKa7uPl` includes exact
intent/config hashes, ADMIT/install/provider/restoration results, safe startup
events and original-request observer output. Long logs/content/secrets are not
committed or sent to Slack. No authenticated HTTP or browser acceptance, live
latency improvement, C1–C5 activation or CPU/CUDA/default-device success is claimed.
