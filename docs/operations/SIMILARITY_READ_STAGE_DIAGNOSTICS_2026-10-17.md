# Installed bounded similarity-read timing; actual measurement pending

2026-10-17 UTC. **DF408FEF_INSTALLED / LOGGER_STARTUP_FIX_SOURCE_PASS /
CONTEXT_MEASUREMENT_PENDING**.
This is not original context-delivery acceptance or full incremental-RAG completion.
The last actual context503 remains the7fcd0865 observation17:10:01. The later
df408fef observation was stopped by authentication before reaching context read;
neither a new503 nor a latency improvement is inferred for the new release.

## Source, gates and exact materialization

Source `df408fef7067f73f793b7e05784dc40a06880722`, tree
`49ba61a212cca425aae525f2d86b5399fc05aa08` adds only closed-stage elapsed metadata
around existing read work. It does not change source/IAM/hash/receipt checks,
the four population captures, public schemas, persistence, numerical code/model,
encoder space or30s deadline. [Design and260 focused tests](../architecture/SCOPED_TYPED_ARTIFACT_DECODING.md#stage-diagnostics-source-gate-2026-10-17-utc).
Strict mypy3, Ruff/format4, business-method AST comparison, standard three-wheel
RECORD and isolated three-wheel301 EOM-module imports all PASS. No ML/test/source
imports occurred in the isolated import check. No new mutating DB suite ran for
this logging-only diff; previous PostgreSQL evidence is separate.

Build-only archive raw444758bd930cca11d2100a82f446b438c0cd68bfd49137e340a402c1f41cceb2
was copied with exact wheel pins into the existing protected release adapter.
Stage `/var/lib/eom-release-operator-stage.df408fef-fknsloho`, context1.4 raw
`4cbfead472590ba1209cc0ebafa8115c0f8529fb21127e432db1def5244f00d8`.
Materialization/ADMIT PASS. Materializer AST is unchanged except EVIDENCE/SPECS.
The provider helper changes only exact string pins, not operational guards.

## Actual drain, maintenance and standard installation

At17:18:57 supported SIGTERM targeted only the original QUERY main PID827051/
invocation83881eaa2f8e417b9919da8d9b2dbba7 and INDEX main PID827407/
invocation6294754abb174c8e85b8b0fac0776d43. INDEX finished its current work;
both owners were actually inactive/dead/MainPID0, success/exit0 with empty cgroups
by17:27:27. No child signal, force kill, retry, row repair or historical rewrite.
The foreground passive PID wait's completion was checked against systemd state,
not treated as sufficient evidence by itself.

Independent CHECK17:27:35 and STOP17:27:44 confirmed DB/worker/native quiescence
before stopping eight original services. Standard exact-source `--install`
completed once with exit0. Supported callbacks passed PDF runtime, migration0055
verification, API role bootstrap, Catalog/HWPX role reconciliation and API
isolation; wheel RECORD, deployment metadata and pidfd guards also passed.
No migration upgrade or model execution was submitted.

Actual installed ZIPs differ from build-only materialization:
`/tmp/eom-api-build/df408fef7067f73f793b7e05784dc40a06880722.qZVBuI/dist`.

| Wheel | Actual raw SHA-256 |
| --- | --- |
| platform | `018755d6eb5a4c5f079ea0f767cbe32021c7c222739be0bafebe16dac323089f` |
| API contracts | `83642598b7ccb1345c8f942229f6f7de5a7abc8dffae17c0bb51356392e0d37c` |
| API | `d10d2ce15312317a7ca36b548371c003ed855fd76659fcf2ab9769f62243e72a` |

Actual installed timing module equals source, raw
`2425e412df8bd55f791d2f8c4cabd18548ee2d8548a67736f95de9c8e5fecc00`.
Rollback record `/var/lib/eom-api/deployments/df408fef7067f73f793b7e05784dc40a06880722.json`.
Previous7fcd0865 actual wheels/config/deployment record were independently hashed
and retained. Rollback remains a compatible-set operation, not blind downgrade.

## Provider alignment and actual restoration

Provider PREPARE/SELECT/START all PASS; protected helper raw
`47f0c6758dc22aa4562eec2f9ad22c598f74224bb9af3d133ec665b3825581ec`.
Only QUERY API-provider pin/unit config hash and nonsecret Chat source pin change;
predecessors remain under `/var/lib/eom-query-provider-df408fef`. Eight original
shared services plus QUERY/INDEX were restored active with NeedDaemonReload=no.

- API main900537, invocation9bcac465bab94dcb97614e649999310a.
- Catalog main900493, invocation85196a9ddf644a1781224a2b33b50cb5.
- QUERY main902791, invocation8b6b2b63c5b24e26984f8a15538ac562,
  actual OWNER_READY17:30:27; socket UID990/GID985/mode0660.
- INDEX main903039, invocation492074d3114f47c9a234c11a2d7a2b14,
  actual SERVICE_STARTED17:31:05; all three original config/runtime/unit hashes
  unchanged. Existing CPU/model/indexing policy remains selected.
- Live=LIVE/ready=READY17:31:15.

No new vector-count observation is inferred from service startup. The last due
observation17:15:31 was661 view encodings/bindings, not661 unique Items or full
coverage. Next routine observation is no earlier17:45:31 UTC.

## Existing-session observation and next safe actions

The original observer PID837676 was confirmed alive at AWAIT_EXPLICIT_REPLAY.
After restoration it received one explicit REPLAY, not a new request/model/key.
At17:31:32 the preparation endpoint returned403 `AUTH_REAUTHENTICATION_REQUIRED`
before context read. Official refresh cannot reset password-authenticated_at and
must not defeat that requirement; no successful refresh is claimed here.

Source inspection explains the boundary precisely: preparation uses
`WORKFLOW_START, fresh=True`, whereas the existing completed-context endpoint is
a read-only operation with current Graph/Workflow/Item/analysis/source permission
checks and no workflow-start freshness grant. The diagnostic observer currently
replays preparation before attempting read, so this403 does not establish that
the separate read-only endpoint is forbidden. Nor does it justify relaxing the
preparation dependency. It cannot safely export its in-memory credentials or
change its running control protocol. Do not extract memory, credentials or
terminal history, replay again blindly, re-key or alter auth TTL/permissions.

The user is asleep and requested no further interactive login for24h. Honor that
as an execution constraint, not simulated authentication: defer the credentialed
measurement and continue independent work. Before any future login, fix the
temporary diagnostic sequence to support exact completed-read-only continuation
using the already validated selection, distinct from fresh-auth preparation
replay. Keep the real API permissions and original source/request/Workflow pins.
The read endpoint must still perform all current authorization itself.

Operation evidence: `/tmp/eom-read-timing-release-LcmcfxNq`; previous authenticated
observer log/state remain under the original shared-provenance/canary directories.
Only fixed metadata enters Git/Slack; no credentials, source bodies or full logs.
GPU preparation/actual six-run/default and remaining C1–C5 activation are still
required and incomplete. The complete goal is not marked achieved.

## Narrow logger startup correction — source only

Startup inspection found that the Catalog, INDEX and QUERY entrypoints do not
configure the root logger. Consequently the new INFO stage observations may be
filtered out even though their unit tests replace the logging call. This is a
diagnostic wiring defect, not evidence of a new source-read failure or permission
to change the thirty-second API deadline.

Configure only the dedicated stage logger at these three composition roots,
using the existing JSON formatter. Do not enable the root logger or third-party
SQL/HTTP loggers. Repeated configuration must leave one handler, propagation is
disabled, and setup failure cannot stop the business operation. No schema, DB,
queue, native model, authority or request identity changes. Verify real stderr
delivery with the root logger at WARNING, exact safe fields, no duplicate output,
unchanged root/sibling configuration and failed diagnostic setup. Installed
df408fef remains the operating release until a compatible deployment is verified.

Focused regression **224 PASS/16.07s**, strict type checking of four production
modules, Ruff/format and diff checks PASS. The first broader run was72 PASS/1 FAIL
because an older security test expected five native service files; the later CPU
probe made six. The assertion now enumerates the exact six reviewed templates and
still denies CAP_KILL in every native/INDEX unit. No privilege rule was relaxed.
The final224 include real success/failure stderr delivery with root WARNING,
exact redacted fields, repeat configuration, failed setup and three composition
roots. QUERY imports/configuration remain after verified UID/capability drop;
INDEX configuration follows its actual runtime capture. These are source proofs,
not a new installed measurement or resolution of the original503.

The user's unattended-work request means **no new interactive login prompts for
at least24h (renewed at2026-10-17 21:43 UTC; not before2026-10-18 21:43 UTC)** while independent authorized work
continues. It is not a successful login, a stored credential or permission to
extend auth/sudo lifetimes. Preserve already successful and failed observations;
leave genuinely credentialed checks pending instead of inventing acceptance.

Superseding unattended window, reconfirmed2026-10-18 05:07 UTC: **no new interactive login
before2026-10-19 05:10 UTC (14:10 Asia/Seoul)**, at least24h after the October18 05:07 UTC reconfirmation. This replaces every earlier
no-prompt deadline in this runbook and temporary diagnostic instructions. It is
not authentication, an auth lifetime extension or a scheduled login at expiry.
Use only already valid supported same-actor continuation/noninteractive sudo;
preserve denied original requests and continue independent authorized work.

One due30-minute observation used the unchanged pinned installed observer from
the same `%89` pane with `sudo -n`, no prompt or auth-lifetime change. As of
2026-10-18 05:26:12.760558 UTC:849 encodings/bindings,219 index revisions,6 logical
indexes; latest per-index coverage299/545,265/545,285/545. These are view bindings,
not849 distinct Items or full completion. Latest-five-only projection has1
REQUESTED/1 RUNNING/3 COMPLETED; it is not a global failed/lease census. Evidence:
`/tmp/eom-index-observation.Hg7nFQTe/index-observation.json`. Next routine read is
not before2026-10-18 05:56:12.761 UTC. No replay/model/migration or service restart.
See the current unattended-work section of
[the full goal](../architecture/SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md).

## Completed-read continuation is prepared without new login

The temporary diagnostic now has a separate **completed-result-read-only** entry:
`/tmp/eom-completed-context-read-WFk1Ch9h/read_original_completed_context.py`, raw
`1f97d883f6cdb3a94e3399cf9de98c867ce594b657e453b8dfcaf7a0f5d33d37`.
Default invocation validates only the exact saved canonical request and READY
reply/workflow/selection hashes. Actual installed-Python input check PASS;
HTTP calls/login prompts/model0. Saved READY is not current authorization.

Its explicit future interactive mode cannot run before the user's no-prompt
deadline. It uses one actual official login and the reviewed memory-only refresh
helper, then only the existing completed-context route. It does not replay
preparation, create another key/Workflow/query, extract another process's token,
relax freshness or persist credentials. On failure it awaits an explicit READ
in that same process; no automatic HTTP/model retry. Two successful reads must
retain exact selection/context identity and deterministic context, with separate
integer elapsed measurements. This does not claim fresh preparation replay PASS.

Synthetic diagnostic/session regression **33 PASS/4.64s**, Ruff/format PASS.
They cover denied HTTP, invalid/stale/nonready binding, schema/hash/cache failure,
changed second read, bounded/no-follow external inputs, no default auth import,
the no-prompt window, official refresh identity/expiry budget and memory cleanup.
The fake-login wire test also checks that `SecretStr` is unwrapped only into the
actual HTTP payload, never sent as its masked JSON representation or logged.
No genuine login/session/HTTP/source permission is inferred from synthetic tests.
Initial local test failures were fixture expectations (JSON Schema exception type
and `sys.dont_write_bytecode` location); production validation was not loosened.

The old observer and failed503 history are preserved. No new observer was started
at getpass and no user input was requested. Source22ea9d14's logger startup fix was
not yet deployed at that historical checkpoint. Later measurements follow below.

## Actual3195fa32 corrective release and same-session read —2026-10-18

The user's later explicit login offer superseded the unattended-login constraint
for one supervised invocation. Actual guiadmin login succeeded08:35:15 UTC on
685b54a2. Its original read returned503 after32s; complete server-stage evidence
showed78.5s in COMPOSE_CONTEXT. No replacement request/key/model was submitted.

Source3195fa327eb14722c7266fa64bc6ba5490d4352b batches fresh Item source relations,
reuses exact frozen current-metadata interpretations and removes duplicated
solution-resolution work. Source21-suite394 PASS/26.84s, strict mypy6 and Ruff14
PASS; the official disposable PostgreSQL gate89 PASS/19.36s, guarded cleanupPASS.
The temporary test database and test roles were removed; production DB tests0.

QUERY/INDEX received only their exact original-main normal drain signal and
finished successfully before CHECK/STOP. Standard --install ran once and
completed0 at unchanged production head20261017_0057. Actual delivery:
`/tmp/eom-api-build/3195fa327eb14722c7266fa64bc6ba5490d4352b.Lxt2Kc/dist`.
Its three wheels and1,990 installed members matched independently, including
unchanged file epochs. Build-only vPYB65 was explicitly not used as delivery.

| Actual installed wheel | Raw SHA-256 |
| --- | --- |
| platform | `a97357ca164289f53f23c96b64050edf6f5f14bf84eb74e6ff39189398136534` |
| API contracts | `f043881e6ff417d5020550c6893b569b9882f3b2ed2694d75053cf959aa35136` |
| API | `c7b527d2071993ce4afec583b22b2e5494cc4a7023dbde5f89a9a94c2974567e` |

Catalog's source tag advanced by its single exact source line only. Official
Chat restoration and QUERY provider PREPARE/SELECT/START all completed0. The
unchanged df408fef INDEX was restored; all10 services were active09:25:29.
Current-invocation QUERY_READY/INDEX_STARTED and API LIVE/READY were confirmed
separately. CPU/model/recipes, API flags, private Chat feature flags, worker
identities and900s fresh-auth policy were unchanged. INDEX uses its own retained
private code; shared API deployment is not an INDEX performance upgrade.

The resident client was preserved. Its explicit READ09:25:42 used official
same-session refresh with unchanged authenticated_at and no credential storage.
Original read again returned503 at09:26:14. Completed server observations showed
COMPOSE_CONTEXT66,401ms, before971ms, after1,093ms and final provenance72ms.
Four full population passes still dominate. Neither source PASS nor successful
installation closes C1. No preparation replay or new native/model work occurred.

Temporary evidence: `/tmp/eom-c1-next-release.PVv202vx` and the resident
`/tmp/eom-c1-consumer-u2HajatK`. The first combined postflight collector failed
without a complete projection; do not infer fresh counts from it. Subsequent
startup/health inspection was metadata-only. Last valid counts remain08:47:57;
no new full coverage is claimed. Follow the30-minute count-observation cadence.

Next: measure remaining repeated decoding/cache eviction before another narrow
fix; do not increase the API timeout, weaken source reauthorization, regenerate
the query or request another login merely to repeat the same failing read.
Full C1–C5, full eligible seed/delta evidence and actual six-run CPU/CUDA/default
gates remain open. Failure evidence and the compatible685 predecessor are retained.
## Actual7c19e6c6 rollout and preserved C1 failure —2026-10-18

The exact7c19e6c6905d22302ec0db3f89bd2b7e58954fe7 source passed27 focused
suites519 tests/266.45s, strict mypy4 and Ruff/format7. The source-only benchmark
numerical bridge and canonical per-launch receipt closure are included; actual
six-model measurement and final nine-gate acceptance have not occurred.

Normal exact-main QUERY/INDEX drain completed success/exit0 with empty cgroups.
The original INDEX work completed, without child signals or row repairs. The
single standard install completed0, DB head20261017_0057 unchanged. Delivery is
`/tmp/eom-api-build/7c19e6c6905d22302ec0db3f89bd2b7e58954fe7.qrOkyP`;
build-only `.XsZbWn` is not delivery. Independent verification matched1,991
installed members and unchanged file epochs.

| Actual installed wheel | Raw SHA-256 |
| --- | --- |
| platform | `97d79aeae04e2a38513bc2cbfdeb7c966c6f0f0291a35436886e0139b7b88eb8` |
| API contracts | `c65c8f777ee5014d211ca9f251593fc3c06263e439399ec26fe5c4f507209d29` |
| API | `4748ac6f7c1fe9b0e7fe4ae1bd721649b560e20570fc1729394f4109768c0d87` |

Postflight confirmed10 active services, current QUERY_READY/INDEX_STARTED and
API LIVE/READY. Private INDEX owner df408fef and QUERY owner0fab624c retained
their code/model/policy/recipe identities; QUERY provider points to actual new
API. Private Chat and authoring/exam similarity activation remain disabled.

Same resident-session READ10:00:45→10:01:17 returned503 after32s. Server
COMPOSE_CONTEXT56,028ms, before1,007ms, after1,317ms, final provenance78ms.
Physical/raw/model retention remains bounded and current checks unchanged; the
observed improvement is not delivery PASS. Catalog reached its existing1GiB
memory ceiling and used swap; this is evidence of pressure, not a complete
causal profile. No limit/default/timeout/auth policy was changed.

Valid postflight10:00:12.723382 recorded913 encodings/bindings,235 index revisions
and6 logical indexes. Its latest-three observation is309/545,319/545,285/545,
not all six heads or913 distinct Items. Next routine count observation is no
earlier10:30:12.724 UTC. Evidence `/tmp/eom-c1-cache-release.tG5O5Zqn`;
root source JUnit `/tmp/eom-c1-consumer-u2HajatK/c1-cache-root-final.xml`, raw
`02e716db90ff6aeb0ca76d8bd08360ebcb149a3f0c8c6f3e37d1aad2569c75b3`.

## 2026-10-18 bounded live stack sampling

The installed `7c19e6c6` original completed-query read still returned503. Its
existing metadata-only stages measured56,028ms for context composition; this is
not a delivery PASS. Do not increase the API deadline or weaken authorization.

Use `py-spy==0.4.2` only as a temporary development diagnostic, not an application
dependency: an external sampler can measure the actual Catalog process without
another service restart or in-process instrumentation release. The official
Linux x86-64 wheel is2,936,518bytes with SHA-256
`aeb0323409199c785f730645e9f4bb7a7b9ca2c481f2c331a55642b5d13fa52f`.
Download/extract outside every protected Conda environment; verify the wheel and
standalone executable before installing an owner-only diagnostic copy. Restrict
one sampling run to the current Catalog PID and invocation, at20Hz for at most
70seconds with nonblocking stack-only capture. Do not sample the resident login
client, use locals/arguments/native dumps/subprocess capture, export credentials,
change ptrace/sysctl/capabilities, or change production dependencies/configuration.
Retain output privately as diagnostic evidence, not Git or Slack content. A
permission denial stops sampling; it is not authority to relax runtime isolation.

The same original context READ may be observed once during this bounded sample;
it submits no preparation, model execution or new idempotency key. Sampling can
alter observed timing and is evidence of cost location, not a performance PASS.
The normal read still enforces all original source and operator checks. The
diagnostic tool remains removable without any production import dependency.
Primary tool documentation: https://github.com/benfred/py-spy .

Actual one-run observation: wheel/executable matched the pins above and
`9b4d1f39b2a47ae44f4c6a46f615dcc0287d7755beba5065f32391951e07d594`.
Only Catalog PID2015169/invocation97f70d3b0a57430bb1bfbf37b3596c8d was sampled.
The tool exited normally after70s with555 weighted samples and238 nonblocking
sampling errors; the errors limit representativeness and are not API errors.
The original READ returned503 at10:08:56, without another refresh/login/key.

Private raw profile `/tmp/eom-catalog-stack-profile.VkRwq67D/catalog-7c19-20261018T1010.raw`,
SHA-256 `ec4b851a82a804c8e415e440c5dc0da3c2081ea0ddb4ad31cbf111dd25f44692`.
463 samples contained the C1 dispatch frame;400 contained full source capture.
Inclusive counts (overlapping, not additive): candidate admission157, solution
profiles118, materialization65. Of62 decoder-call samples,61 were in the first
composition preparation, one in the preceding completed-source resolution,
and none in later view/final-reauthorization passes. Thus this sample does not
support ongoing decoded-cache churn. No budget increase is justified.

The measured repeated workload is broader: fresh source-resolution/ORM work and
strict deterministic projections are rebuilt four times. A correction must
separate first full materialization from fresh full current-input validation,
without skipping late membership/report/source/permission changes or relaxing
the original public validators. No such correction is yet installed here.

At the next due30-minute count observation10:30:28, bindings advanced913→921,
index revisions235→237, still6 logical indexes. Observed latest unique heads
were313/545,323/545,285/545; the bounded last-five-revision list is not an audit
of all six heads. Original INDEX had one RUNNING and one REQUESTED work among
the recent rows, with completed history preserved; no failure census is claimed.
Normal INDEX and QUERY remained active and API LIVE/READY. Next routine count
observation is no earlier11:00:28.376 UTC.

Because only8 view bindings advanced during this30-minute interval, a separate
single60-second20Hz nonblocking stack-only sample of the exact current private
INDEX owner is also authorized as the same bounded diagnostic. Use the existing
verified tool; keep no locals/arguments/model/child capture, configuration change
or additional count query. Its output measures an active computation, not a
reason to skip authority checks or raise memory limits. Shared API7c19 and the
private df408fef INDEX remain different installed code identities.

The INDEX sample completed normally:639 weighted samples,389 nonblocking misses;
raw `/tmp/eom-catalog-stack-profile.VkRwq67D/index-df40-20261018T1032.raw`, SHA-256
`08bcd635322eb4cdf940e1aeb5896c6cbab8162599fa07004811f104a8af24a0`.
Of382 identifiable main-thread samples,351 were inside post-native completion
validation,274 in registration observation and191 in registered-reference
verification. These inclusive counts overlap. No sampled main stack showed
native launch waiting or Item/profile projection.230 partial/other weights and
the sampling misses limit inference; this is not a wall-time decomposition or
proof of a model/memory fault. The source owner still parses cumulative original
index manifests in `verify_registered_references`; the C1 operator-only read-set
does not change that service path. Examine the existing canonical registration
and origin-membership proof before a separate bounded optimization; do not skip
its integrity checks or claim a shared API rollout speeds the private INDEX.
