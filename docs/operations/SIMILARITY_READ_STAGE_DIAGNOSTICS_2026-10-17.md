# Installed bounded similarity-read timing; actual measurement pending

2026-10-17 UTC. **INSTALLED / SERVICE_STARTUP_PASS / MEASUREMENT_AUTH_PENDING**.
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
at least24h (not before2026-10-18 18:23 UTC)** while independent authorized work
continues. It is not a successful login, a stored credential or permission to
extend auth/sudo lifetimes. Preserve already successful and failed observations;
leave genuinely credentialed checks pending instead of inventing acceptance.
