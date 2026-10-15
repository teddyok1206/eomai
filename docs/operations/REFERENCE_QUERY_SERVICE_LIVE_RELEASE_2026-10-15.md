# Native QUERY service: coordinated live release

2026-10-15 UTC. The full original system-RAG goal remains active. This is not a
claim of browser/consumer activation, larger vector coverage or CUDA acceptance.

## Compatible API release — 20:46 UTC

- API/platform/contracts source: `2857bf7740848ccae822c0f0971f607adf331b4b`, tree
  `a9b08a885fb27823c3aa8b10c8be50108f1579e6`. Actual API PID1045380.
- Standard build/RECORD/installed-contract checks, native PDF verification,
  exact0055 migration verification, existing runtime-role reconciliation,
  deployment metadata and actual API isolation callbacks PASS. No migration.
- Official quiescence passed twice before stop: all eight original services
  active, no executable database work or native running unit. Existing supported
  maintenance fence was used after stop. No row/history repair.
- API stopped20:44:56; API ready by20:46:09. The five shared consumers were
  restarted by the standard deploy; three original chat/broker services were
  restored explicitly. All eight original services active, API LIVE/READY PASS.
- Installed protected API config selects the new preparation endpoint;
  raw SHA `9dba4470328e5f97884cfd2bfe27ee43d10b7dae9c2d9ec504eab1800d3a73c8`.
  Previous nonsecret config is retained in the root-private stage.
- Actual installed route/permission/fresh-auth/200+202 response metadata PASS
  without database access; no-bearer request returns401 AUTH_TOKEN_INVALID.
  This is not a genuine current-operator HTTP preparation acceptance.

Actual standard delivery (separate from independently built staging wheels):

| Wheel | Raw SHA-256 |
|---|---|
| platform | `1bbc59461172123b962da9717fde40daaf3792a1e79710826b3fc50b84003cb1` |
| API contracts | `7067d292e483938dfbe21b98a7af46abdf8eafd1a91f82b7c8c63010550126fd` |
| API | `875efb1333d3b1c2571c90750ecaba56b5a5959a8b32ced504826c2bb40e0e13` |

Delivery directory:
`/tmp/eom-api-build/2857bf7740848ccae822c0f0971f607adf331b4b.CIXdbA/dist`.
Protected context:
`/var/lib/eom-release-operator-stage.2857bf77-6g9mpdap/operator-context.json`,
raw SHA `9c335011054fcb58b9001a6a84dde7f21fff2d9e8c15472900aa3e10386634a1`.
Existing release operator1.4 ADMIT_PASS and exact callbacks were reused; the first
incorrect ADMIT/callback invocation was rejected before side effects, corrected
once, and its failed log is preserved. No admission rule was changed.
Recovery record:
`/var/lib/eom-api/deployments/2857bf7740848ccae822c0f0971f607adf331b4b.json`.
No blind downgrade or history deletion is authorized by this record.

## Native owner first startup — not accepted

The inactive installed a0082e2f owner was selected separately from the API. Existing
canonical completed QUERY metadata/control reads supplied the policy/bundle/recipe
pins in a read-only eom_app/OID16385 root. This did not grant source access, reuse
expired auth or execute a QUERY. The socket parent is native-owner:eom-api2750;
no API supplementary group was added to the native owner. Private state folders
are native-owner0700, configuration root0444 and unit root0644.

Before activation, the configuration was finalized against the actual standard
delivery wheel, not a build-timestamp-different staging wheel. All12 reviewed code
pins are identical; actual deployment record and installed source/tree agree.
Final configuration raw SHA:
`88ecace59036e02260e784a392093516d3ccc6058594be8ef60cc28de7d7f34d`.
Final first unit raw SHA:
`22e7cab07772896606e7f080afcb5780bcb97b8ebd6ec1f0afe3083aec08c7c0`.
Original staged configuration/unit bytes are preserved separately.

The20:48:15 start exited1 at20:48:19 with PermissionError. Log PID1048137 is the
fork child, still UID0; original supervisor PID1048118 waited and exited1. Thus the
error is before the child's completed UID drop/request-serving path, not a worker
result or evidence that authentication/model execution failed. The service stays
disabled/failed; no automatic restart and no new model/request occurred. Existing
API/chat/Web remain healthy. Root/API/worker permissions have not been widened.

The original message omitted a source location. A minimal source successor adds
only errno and a bounded owned-module/line diagnostic (no message, filename,
locals or full traceback); tests68 PASS/19.84s, Ruff/format/strict type1 PASS.
This observation change is not a repair or startup PASS. Actual cause inspection,
tested correction and installed readiness are still required.

Temporary bounded logs: `/tmp/eom-identity-provider-install.nAaycoDM/query-owner-coordinated-*`.
No credential, worker prompt/result, item contents or full log is in Git/Slack.
Existing QUERY acceptance5fc6d194 and its9-member owner517 remain historical;
this new release uses the12-member family and never borrows old success as proof.
Automatic indexing remains inactive/disabled with last accepted coverage2/520;
CPU is default and GPU comparison/default admission remain incomplete.

## Startup cause isolated — 21:09 UTC

Diagnostic successor9badb032 was built/RECORD checked, isolated owner-pair byte
closure28 PASS, and installed separately without replacing API2857bf77. The
first diagnostic run identified entry183/setresuid, EPERM. Its config raw SHA
`9d52fc37d1b518a0b4fac840ff2c7f068be6fdddb6b1bff44c96383b4d3ded9b`,
unit `c9f4f5bc1f85e0933856570952af3763d440eb29fe9707ebc7db1f02bde947d9`.
An instrumented startup read only proc UID/GID/capability fields (no env/memory):
the actual supervisor/child bounding set was0xc4, but permitted/effective were0x44
before the drop. CAP_SETUID0x80 was absent, so UID0 alone was not sufficient.

Finite transient probes, without data, database, model or auth captures:

| Exact observed boundary | Outcome |
|---|---|
| Same three bounded caps, implicit root | UID drop PASS, child permitted/effective0 |
| Owner imports and then full hardening/path/resource profile | PASS, child permitted/effective0 |
| Actual installed provider FDs plus fork/signal masking | PASS; no key bytes read |
| Explicit User=root/Group=root, ambient empty | FAIL: permitted/effective0x44, UID drop EPERM |
| Explicit root, only CAP_SETUID ambient, unchanged bounding0xc4 | PASS: parent0xc4, child990/1000, empty groups, permitted/effective0, NoNewPrivs1 |

The correction therefore preserves the existing bounded capability set and
explicit root supervisor identity, passes only the intended UID switch through
exec, and adds a fail-closed child privilege guard before application imports.
No root listener, new worker groups, saved root identity, fresh-auth extension,
DB row fix or source permission expansion is introduced. No code was changed
behind any installed immutable prefix. Earlier failure/probe logs are retained.

Corrected source tests79 PASS/19.81s (includes previous68), Ruff/format/type1 PASS.

## Corrected native owner — live at21:12 UTC

Owner source `8c4110412bb60e940ef07ea497c4eef3f3ea5253` was separately built,
RECORD checked and admitted through the isolated28-member owner-pair byte closure.
The existing owner installer installed a new immutable prefix; API2857bf77,
the numerical environment, database schema and all source/control pins are unchanged.

- Configuration raw SHA:
  `1a1d5761aff96306569894ab5b5e38d093c5724c4458342495eb08920d481f24`.
- Unit raw SHA:
  `d30cbb37edeb91615ce31de7819dbfff768e65e2438c33ce66ac6f11ccf0aaa0`.
- Start21:12:21; `REFERENCE_QUERY_OWNER_READY`21:12:37.848890 UTC.
- Actual supervisor PID1064946: UID/GID0, bounded/permitted/effective0xc4,
  ambient0x80, NoNewPrivs1. It holds metadata only and does not listen for requests.
- Actual serving child PID1064962: all real/effective/saved/filesystem UIDs990,
  GIDs1000, supplementary groups empty, permitted/effective/ambient capabilities0,
  NoNewPrivs1 and Seccomp2. Its inherited0x80 alone confers no executable privilege;
  nonroot saved IDs and NoNewPrivs prevent recovering privileges through exec.
- Socket parent native-owner:eom-api2750; socket native-owner:eom-api0660.
  No supplementary group was added. Unit enabled after readiness/credential checks.
- Original eight services and Scientific Studio (`eom-web-gui`) remain active.

`NATIVE_QUERY_OWNER_STARTUP=PASS` is narrower than genuine authenticated preparation
or a consumer acceptance. No new QUERY/model run or authentication capture occurred
in this startup verification. Actual API preparation/replay, Catalog completed read,
ordinary workflow consumers, automatic index coverage and GPU admission remain open.
The failed predecessor starts and their evidence are preserved, not reclassified.

## Next bounded activation: Catalog reader selection

This is configuration of the existing Catalog composition, not a new search,
registry, queue, wire schema or database migration. Canonical source remains the
registered completed QUERY and exact source/Graph/policy/index revisions. The
nonsecret reader configuration copies only the installed owner's reviewed
corpus/namespace/recipe/policy/bundle/database-owner selection; document space is
resolved through the existing pinned control reader, not guessed from dimensions.
Configuration raw SHA is a deployment selection, not operator/source authority.

The existing Catalog runtime role independently inspects Identity's installed
authorization fence before composing completed reads. No role/ACL/IAM changes are
allowed to make this inspection pass. Primary operations remain exact indexed
selection and bounded source resolution; no new data structure or cache is added.
Publication uses its existing Artifact owner and dedicated staging folders;
workflow reads retain their separate existing flag and runner-only peer boundary.

Sequence: canonical/schema/config check; finite installed preflight under the
actual Catalog identity; existing supported quiescence check; select a small
systemd drop-in and restart Catalog only; verify socket and original services.
Only then use the genuine authenticated API for preparation/replay/completed read.
An independent config preflight is not a source authorization or live read PASS.
Rollback removes only the new drop-in, restarts the original Catalog composition,
and preserves all QUERY, Artifact and failed execution history. Unsupported
selectors or timeouts keep their original key and fail explicitly; no automatic
new QUERY, latest substitution or direct database result repair is permitted.

### Preflight discovery — activation held, existing runtime unchanged

Actual restricted Catalog preflight passed file/schema/raw hash and actual database
role checks but failed the independent Identity routine admission. Read-only
inventory then found **zero** `public.eom_fence_operator_authorization_v1` routines.
This is a missing installation prerequisite, not evidence of corrupt source data
or failed native execution. Reader flags remain disabled; no restart or login.

The next source step is an Identity-owned install operation for the existing fixed
SQL contract: clean actual pinned owner root, bounded installation lock, atomic
CREATE/PUBLIC revoke/fixed Catalog EXECUTE grant, exact post-inspection and no-write
replay. Existing drift/overload fails without repair. No table/schema grants,
credentials, role membership, permission policy, new migration/table/index or
runtime self-installation. The original fence proposal already assigns this to
the release owner; read-only runtime admission must not install it as a fallback.
Source and disposable DDL/replay/drift/rollback/concurrency tests precede an
independent protected owner installation. This discovery changes the immediate
dependency from configuration-only activation; it does not reopen native readiness.

Identity owner-install source verification:119 focused tests/4.85s,44 dependency/
related owner regressions/12.88s,94 test-harness/profile tests/1.16s, strict mypy1,
Ruff/format4 production/test files PASS. The marked disposable standalone suite
passed14/0.48s, including actual DDL/replay/drift/concurrent-lock and late-failure
rollback. The first run exposed lazy Session savepoint enlistment: issuing DDL on
the pre-savepoint Connection did not activate the savepoint. The implementation
now enlists via `session.connection()` inside the nested boundary before DDL;
the test proves new function/ACL absence after failed final inspection. That
failure and an independent unbound unit-fixture teardown error are retained in
local logs. Neither occurred on the operating database. Existing testdb stage
routing now includes this suite. The full marked native-stage/runner/persistence
regression passed119/92.89s (previous105 plus14 installation cases, not an extra
independent133). Final read-only disposable identity/head/other-connection
inspection is required again before deployment. No production pytest was used.

### Installed prerequisite — 21:30 UTC

Source `5b0804f0690c8dfb1abb320a5ff751e2ed70bbe1` passed the standard three-wheel
build/RECORD/installed simulation, isolated28-member owner pair and three explicit
Identity installer/SQL/public-export wheel-to-source comparisons. Platform raw SHA
`48d0afb614e1509cc5fc4285045083c00720af433a69c9a8ee063d2bf0d5bfe4`,
contracts `65e8f3ed3ad810c3ec9677cd22df9e143299cb0499b247022ab16b464f617d5a`.
Only a separate immutable owner prefix was installed; API2857bf77, live owner8c411041
and CPU runtime were not replaced or restarted.

The protected finite Identity owner operation created the fixed routine at
21:30:37.814349 UTC, actual eom_app/OID16385. Independent postcommit inspection
PASS; body SHA `df9f676d1cb4c587598ee81d22c68a7a21b81deb0e4da28aa01e26c446fa9801`.
Only fixed routine CREATE/PUBLIC EXECUTE revoke/Catalog EXECUTE grant occurred;
no IAM table/schema/cluster-role/policy/data modification, model or operator capture.
The new routine is not automatically dropped as a rollback: feature activation can
be disabled without deleting this reviewed prerequisite or any accepted history.
Root-private receipt is retained with the existing deployment stage. Actual
Catalog-role post-install finite preflight then PASS/3.831s, including existing
reader/workflow/publication composition and private publication staging readiness.
Configuration raw SHA:
`ee9e749d902981c5c175d9192b096f41b6c47bf3af47d046960216f026a37223`.
The final disposable inspection confirmed the exact identity/head0055 and zero
other connections. These checks still do not claim genuine source read acceptance.

### Catalog composition enabled — 21:32 UTC

The root-owned0644 drop-in `40-eom-similarity.conf` has raw SHA
`3883b37b4e5e0362c0c0da4694827164fd3db3ef6dd0f285a99b33da133538ed`.
It selects the verified reader config and separately enables existing completed
reads, context publication and runner-only materialization. Catalog source stays
2857bf77; ordinary runner consumption remains disabled. No Pack/plan was activated.
Only Catalog was gracefully restarted: old PID1045340 exited normally21:32:03,
new PID1078492 active with NRestarts0. API PID1045380 and native supervisor1064946
are unchanged. All original eight services, Scientific Studio and native owner
are active; the existing official API health-only smoke PASS.

Actual manager socket remains catalog-manager:eom-api0660, directory0750.
The separately enabled existing server added only the named runner990 ACL
(directory r-x, socket rw-), preserving group/mask/other permissions. This grants
no group membership, DB secret or source authority. Schema/readiness/ACL activation
is not a genuine authenticated preparation or current-source read PASS. One bounded
ordinary HTTP preparation/replay/read canary is prepared, but no Studio credential
has been requested or captured at this checkpoint; no new QUERY/model has run.

The actual named runner UID990 socket probe confirmed READ_SIMILARITY_CONTEXT and
PUBLISH_ITEM_SIMILARITY_CONTEXT connections close before dispatch. Its separately
allowed READ_WORKFLOW_SIMILARITY_MATERIALS reached only schema rejection for a
deliberately incomplete frame, no source/DB/model read. These three OS-peer probes
do not prove a valid role request's current source/plan authorization.
