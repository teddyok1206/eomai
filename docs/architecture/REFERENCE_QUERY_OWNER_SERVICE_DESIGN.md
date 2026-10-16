# Fixed native reference QUERY owner service

2026-10-15 UTC. This implements the remaining native producer composition for
the existing preparation transport. It does not activate ordinary HTTP/consumers.

1. Responsibility: one protected, purpose-only native Orchestrator service accepts
   current API captures, constructs the existing canonical preparation application
   and offers its original Workflow to the single finite driver. API/Catalog never
   receive native database credentials or execution privileges.
2. Canonical source: existing immutable policy/bundle/control/installation records
   and official source/Graph/policy resolvers. The new small root-owned configuration
   is deployment selection, not a source permission, service identity or new queue.
3. Identity/revision: owner source commit and independently reviewed API wheel/code/
   config pins are separate from runtime-bundle/policy/Graph/source revisions and
   hashes. Configuration bytes are immutable and externally hash-pinned at install.
4. Pointers: reuse registered policy/bundle/recipe/namespace values. Actual pinned
   control reads and physical launcher readiness are required at startup; each
   request still fences the actual captured human and current source/index roots.
5. Access: startup exact control lookup, request exact idempotency/Workflow lookup,
   bounded source reads, same original command claim. No corpus scan in the socket
   adapter, arbitrary file operation, model-selected config or latest substitution.
6. Structures: frozen typed deployment values, finite request semaphore/thread pool
   with no unbounded pending submissions, and one explicit shared finite driver.
7. Scale/complexity: request capacity4, backlog4, wire8KiB/4KiB plus original Identity
   limits; O(1) active connections/driver handles and existing bounded source data.
8. Transactions: application admission/replay/read commits before driver offer.
   No SQL root spans native calculation. Startup reads only control metadata and
   does not submit, claim, encode or change an index/current pointer.
9. Ownership: root supervisor opens the existing installed provider observation,
   including secret **O_PATH metadata only**, then forks/drops all supplementary
   groups and UID/GID to the existing native owner. Only that child binds/accepts.
   The Thread adapter depends on the application port. Numerical workers never
   inherit database/env/provider handles; existing fixed launchers own that isolation.
10. Failure: invalid/missing/replaced provider/config/control/runtime fails closed.
    No auth cache, password/login endpoint, expiry extension, automatic new-key
    retry, direct state repair or root-listener UID fallback. Shutdown drains
    bounded requests/native driver; pending original jobs retain canonical history.
11. Simpler alternative: executing in API violates the privilege/Artifact boundary;
    a root request handler is unnecessary; reusing the indexing-service identity
    would conflate service and actual-human authority. Existing transport, Identity
    observation, Launcher, Runner and package installer are reused instead.

## Deployment metadata and lifecycle

Define JSON Schema2020-12 before parsing the new non-secret owner configuration.
It contains corpus/namespace/recipe/source classes, exact QUERY policy and bundle,
native source commit, existing database-owner/verifier pins, fixed environment
hashes and independently reviewed API/code/config pins. It contains no credential,
actor, source list, Graph selection, socket path, arbitrary executable or TTL.
Actual API code-member inventory is checked by the existing provider, not granted
by a configurable list. CPU and900-second fresh capture limits remain unchanged.

Root provisions only `/run/eom-reference-query-owner` as native-owner:eom-api2750
and existing private owner staging. Child-created socket inherits eom-api0660;
native owner gains no API-group membership/private secret read. No numerical
environment, existing CPU unit, worker groups or old release is rewritten.
Service starts only after compatible API/provider installation and readiness.
API/provider replacement invalidates the held observation and requires a reviewed
restart with current exact pins, not silent rebinding to another process.

The service template reuses the existing controller database environment, blocks
repository/worker homes/Codex auth and image resources, and retains only the same
three bounded supervisor UID/GID/drop and read-search capabilities. On the installed
systemd255, explicit User=root with empty ambient omitted effective CAP_SETUID;
the supervisor therefore explicitly carries only CAP_SETUID through its exec.
Child startup requires all real/effective/saved UID/GIDs to be native, groups empty,
permitted/effective/ambient capability sets zero and NoNewPrivs=1 before application
imports or request handling. No additional bounded capability or worker privilege
is granted. Provider config/code/secret names must not
be individually masked or bind-mounted: that could hide actual replacement epochs.
ProtectSystem=strict supplies read-only access without per-file snapshot aliases.
The root supervisor's secret descriptor remains O_PATH, never secret bytes.
Tmpfiles provisions the fixed SGID socket parent at boot; the entry never repairs
existing wrong ownership/mode. Request handling is not performed by the root parent.

The entry's small stdlib-only installed-prefix check is deliberately self-contained:
importing a shared EOM bootstrap helper before checking that prefix would reverse
the trust boundary. A selected-prefix import finder denies checkout/ambient EOM
fallback and numerical libraries. Fork signals are blocked until both parent/child
stop handlers exist. Startup control reads are shared with existing request reads;
policy/bundle consistency remains one pure rule, not a fabricated source context.

## Gates

Closed schema/mirror/hash/canonical values and bad path/actor/role injection;
current owner/application/driver composition, read-only startup and pinned controls;
bounded real local sockets, wrong peer/capture denial and semaphore saturation;
clean shutdown/socket identity; isolated wheel-only imports and source bytes.
Tests that simulate IAM/unit/account observations are not protected-install evidence.
Protected root provisioning/UID/GID/secret-denial, actual installed API exchange,
same-key HTTP prepare/poll/replay and current Catalog/plan handoff remain separate
live gates. No new item/exam production is needed for this service boundary.

## Source checkpoint — 2026-10-15 20:18 UTC

The closed deployment schema, non-root request server, installed supervisor,
current-human runtime factory, shared startup/request control validation and
draining finite driver are implemented. No new dependency, DB migration, queue,
session cache, fresh-auth extension or numerical import was introduced.

- Shared source regression: **1011 PASS** in274.26s; one existing Starlette/httpx
  deprecation warning. Focused service tests45 PASS overlap this suite.
- Guarded disposable PostgreSQL stage: **105 PASS** in93.09s, including three
  read-only startup/control tests. Inspection after the suite: migration0055,
  read-only inspection and zero other connections. No production pytest target.
- Ruff14 files and strict mypy7 production modules PASS. Rendered service template
  passes `systemd-analyze verify`; this is syntax evidence, not an installed unit.
- Earlier negative-test expectation and synthetic provider/Mock/resource fixtures
  were corrected; failed logs remain locally retained. In particular the fixed
  CPU resource guard was not weakened to accommodate an incompatible fixture.

Unit/provider/account observations and launcher are simulated in composition
tests. Actual Unix framing/HMAC and disposable SQL execute, but they do not prove
root provisioning, real child privileges, systemd namespace or live API exchange.
The earlier genuine QUERY/replay/context acceptance belongs to installed owner
517e4551 and its9-member provider, not this new12-member source candidate.

Ordinary HTTP/lifespan, consumer activation, protected configuration/installation
and same-key browser preparation remain pending. Index coverage remains2/520;
automatic indexing is drained and CPU remains the default. No model/GPU execution,
new source encoding, item generation or privileged service activation occurred in
this source checkpoint.

### Packaged source closure

Candidate `a0082e2f4571b3169769ddd49db20bf064f7098d` was built with the existing
`scripts/api/deploy_release.sh --build-only` path (exit0; wheel RECORD PASS).
The platform/API-contract pair passes strict isolated imports and exact source
byte comparison for28 members; selecting the API wheel adds its actual client
for29. Both deny checkout/ambient installed fallback and numerical imports;
the selected provider inventory is12. This is offline package closure, not service
installation or actual root/UID admission. The probe was corrected to parse only
Python members as AST, not the newly included JSON schema or systemd template.

Selected wheel SHA-256 (raw, no `sha256:` prefix):

| Wheel | SHA-256 |
|---|---|
| eom_platform | `91c11068bfd243543738ffd3e04c2802162b8ef195b37cd06c69cedcf778af87` |
| eom_api_contracts | `55ad0dfb526473dc5eb434bb3e05c2c19a5065ecff79c5369dc223ec582c7c06` |
| eom_application_api | `2f71d0133b131ad010fbbe4aa74b8d7771859a8432d5f15ba4393f45a8d6f909` |

Local package directory:
`/tmp/eom-api-build/a0082e2f4571b3169769ddd49db20bf064f7098d.H0sy7w/dist`.
No auth/capture, database mutation or numerical execution occurs in this probe.

## HTTP preparation boundary

The next adapter reuses the released closed preparation request/reply schema,
without a new selection, queue, artifact or DB model. A protected
`POST /api/v1/knowledge/reference-queries/preparation` accepts only the existing
source/Graph/policy pins, request hash and original key. Its Idempotency-Key
header must equal the body key; the native application already namespaces that
key by the actual operator. A changed correlation ID cannot authorize new work.

The API authenticates and captures the actual current Identity pair for this
operation, requires WORKFLOW_START and existing fresh-auth policy, and passes it
to the fixed native client. It does not ask for another password, mint an Actor,
keep captures, read Catalog files or execute models. A default-off API setting
controls this adapter until the compatible protected service is ready.

Preparation is a state-changing, exact-key re-observation: PENDING returns202,
other canonical states return200, all no-store. Do not use the API's cached
command response: caching the first PENDING would conceal later READY. Every
explicit poll reauthenticates and reauthorizes the same original selection via
the owner; timeout does not trigger a transport retry/new key. The API creates
neither a Workflow nor an accepted item itself. Completed selection is output
only, not caller authority to skip canonical result or item-scope validation.

Wire limit8KiB includes HTTP whitespace. The presentation model translates
jsonschema failures to sanitized HTTP422 without weakening the canonical schema.
No new index or query scan is needed; lookups and concurrency remain owned by
the existing native preparation application. Blocking socket exchange is run
outside the HTTP event loop. Browser BFF forwarding must separately use its
existing session/CSRF boundary before this route becomes a user-facing action.

### HTTP source verification — 2026-10-15 20:31 UTC

The default-off composition, presentation wrapper and protected HTTP operation
are implemented. The current authentication dependency captures the actual
Identity pair for this operation, not merely an Actor. OpenAPI documents both
PENDING202 and canonical200 responses; all successful observations are no-store.

**339 PASS** in35.28s cover HTTP, actual Unix/HMAC exchange, same-key explicit
polls reaching READY without cached PENDING, missing permission/login/freshness,
forced password change, key mismatch, closed/malformed/oversized input, redacted
unknown transport outcomes, shared authentication and release/security inventory.
Identity/kernel/source observations in the socket test remain synthetic. Real
protected API/service activation and browser forwarding are not proven by it.
Strict mypy7 production modules, Ruff/format11 files, shell syntax and diff PASS.

Earlier failures are preserved in local logs. Three deployment tests still
expected0053 rather than the already implemented0055 callback family; expectations
were aligned without changing any migration/grant/runtime callback. One OpenAPI
test raced a response-metadata export during development and was rerun against the
frozen final source. The added one-exchange socket harness initially timed out
its250ms idle accept during cold HTTP startup; it now permits a bounded10s accept,
like the actual server's idle retry loop. Actual capture10s and transport30s
limits, provider checks and production socket behavior were not relaxed.

The existing105-test disposable PostgreSQL evidence covers the unchanged native
preparation/startup/driver persistence code; this HTTP change adds no DB state or
schema. The whole goal is not complete: protected service activation, automatic
missing-binding reconciliation, normal consumers and CPU/CUDA comparison remain.

### Installed-but-inactive owner and HTTP package

The existing protected owner installer (raw SHA
`559ada516fe9d46f57926aad70699e81deba5f1a18b4e25e3f6e6bcdf1384b71`)
installed the previously verified a0082e2f platform/contracts pair into its
separate immutable prefix. Root-owned release0755 and entry0444 were observed;
RECORD/pair installation PASS, `OWNER_ACTIVATION=NOT_PERFORMED` and numerical CPU
runtime unchanged. Existing owner517e4551 and API75fdc265 are not replaced by
this inactive installation. No new service, request or model was started.

HTTP candidate `86506f59181a92adb74c60e26a5ce5f76f8b0f41`, tree
`92deaaf997c6a8339a170b1cc04730d39013c717`, passes the complete build-only
three-wheel/RECORD/installed-contract simulation. Strict isolated selected-wheel
imports and byte closure PASS for28 pair members and32 with the HTTP/API wheel,
including the presentation wrapper, application and router. Provider family12;
checkout/ambient EOM fallback and numerical imports denied. Package directory:
`/tmp/eom-api-build/86506f59181a92adb74c60e26a5ce5f76f8b0f41.gAIuac/dist`.

| HTTP candidate wheel | Raw SHA-256 |
|---|---|
| eom_platform | `2b8eef15668de0ee51cb2fe8c8873612a9826acb805d065f7486b31a7fb51f5c` |
| eom_api_contracts | `e4b194eab5ed5213fc32590a8876e51e95832c3408e25d6b60fc102c71439744` |
| eom_application_api | `bd325bfa6990f1f3e14a6815be9e291c5b68d8420534a7dfceec67cb3f712f54` |

These offline candidates are not the active API/provider. A compatible release
must select actual API/config/code pins, provision fixed private directories and
unit, run actual child/provider/control readiness and then enable HTTP. Do not
mix the old live9-member observation with the new12-member owner/client family.
Existing sudo authentication was reused in EOM:1; no new Studio login was asked
for, no credential was stored and no old QUERY was restarted.

### Actual startup diagnostics

The first installed service attempt failed before child UID drop with a raw
PermissionError, without any request/model execution. Add only bounded errno and
owned-module/line fields to the existing sanitized event. Exception messages,
filesystem filenames, locals and full tracebacks remain excluded. This supports
diagnosis instead of granting more privileges or blind restart. Actual release
and incomplete startup evidence are recorded in
[the operational checkpoint](../operations/REFERENCE_QUERY_SERVICE_LIVE_RELEASE_2026-10-15.md).

### Verified UID-drop correction

Actual transient, no-data/no-model probes isolated the installed service-manager
behavior: implicit-root profile passes; explicit User=root/Group=root with empty
ambient has bounding0xc4 but permitted/effective0x44, and setresuid returns EPERM.
Explicit supervisor AmbientCapabilities=CAP_SETUID restores the same bounded0xc4;
the native child then has UID990/GID1000, empty groups, zero permitted/effective
capabilities and NoNewPrivs=1. This is observed systemd255 behavior, not a claim
that a bounding declaration alone proves actual privileges.

Use the existing systemd mechanism, not root request handling or larger bounding
sets. The retained-privilege guard is added before any application imports, with
negative tests for saved root IDs, groups, permitted/effective/ambient caps,
NoNewPrivs, missing/duplicate/oversized proc metadata. Source79 PASS/19.81s and
strict type1/lint/format PASS. Existing SQL105 evidence is unchanged; this fix does
not change DB schema, control/source policies or request/capture semantics.
The installed start remains a separate required gate. Background numerical
workers keep their separate fixed unit, identity and privilege boundary.

Primary reference for the configuration mechanism:
[systemd255 capabilities/security documentation](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.exec.xml).

## Correct controller credential selection — 2026-10-16

Actual05:37 UTC login succeeded but native preparation failed before any Workflow.
The real service EnvironmentFile was subsequently reproduced under UID990 in a
finite read-only unit: it selected eom_catalog_manager_runtime/OID94661, whereas
the released owner configuration pins eom_app/OID16385. That Catalog role correctly
cannot lock the three IAM session targets. Earlier outside-service probes used the
native controller credential and therefore did not reproduce the service role.
They remain metadata evidence, not proof of correct service credential selection.

1. Responsibility/boundary: correct only this current-human native QUERY service's
   existing configured controller connection. Do not change the working machine-
   identity INDEX service or grant Catalog IAM UPDATE.
2. Canonical source: existing protected native controller credential and the
   released configuration's database-owner name/OID, not a user/model-supplied URL.
3. Identity/revision: retain database owner, provider, source/policy/space/control
   and historical request identities. A new owner wheel/unit is an explicit release.
4. Pointer resolution: startup now compares actual CURRENT_USER/SESSION_USER/OID
   with its existing owner pin in the existing READ ONLY preflight, before control
   reads/launcher construction. This is connection compatibility, not human or
   source authorization; every request still uses its full fresh Identity fence.
5. Access pattern: one indexed pg_roles lookup on startup. No source scan, queue,
   recurring work or model operation is needed to diagnose the connection.
6. Structures/indexes: reuse the frozen owner pin and PostgreSQL role key; no new
   DB/index/schema/wire contract, authority registry or dependency.
7. Complexity: O(1) bounded startup metadata observation. Request work is unchanged.
8. Transaction/concurrency: read-only root, no IAM locks or mutations. Publish a
   root-only fixed service environment before selecting its new unit. No restart
   while an executable/current claim, driver or physical execution is unresolved.
   Historical non-terminal rows require explicit original-allocation/lease/physical
   classification, not blanket success, deletion or automatic retry.
9. Ownership/dependency: the protected release owner materializes the existing
   controller URL only in `/etc/eom/secrets/reference-query-owner.env` (root0600).
   PID1 loads it for this owner; the service cannot read that file directly.
   API/Catalog/numerical workers get no credential or new privilege. Existing
   sanitized native launch environments must remain unchanged.
10. Failure/retry: missing/wrong connection fails at startup, not after another
    user login. No source-policy/TTL/fence weakening, role grant or DB row repair.
    Preserve original key and failure; rollback selects previous unit/config,
    not data deletion. Never print/hash/archive secret environment contents.
11. Simpler alternative: continuing to reuse the Catalog environment is invalid
    for the already pinned direct caller-root session fence. Giving Catalog IAM
    UPDATE would broaden an unrelated boundary. A second auth implementation or
    SECURITY DEFINER session protocol is unnecessary for this scoped correction.

The dedicated credential file is one explicit service-configuration materialization
boundary, not a second canonical credential/identity. Its upstream remains the
existing protected controller secret. Rotation must regenerate this derivative
through the release owner before a compatible restart; stale/wrong-role values
fail closed. A later general credential-delivery mechanism is not prebuilt here.

Source verification:183 focused/source checks and strict mypy for the runtime
module PASS. Final guarded PostgreSQL178 PASS/144.64s, with independent before/
after owner/marker/head0055/zero-other-connection guards. Three direct READ ONLY
checks exercise a real matching owner, wrong role and wrong OID. The older boot
fixture explicitly maps its deployment-only eom_app pin to the guarded disposable
owner; scientific source/provider/account observations remain synthetic. The first
four boot tests correctly rejected putting a disposable role into the unchanged
eom_app-only deployment schema. The fixture was corrected, not that released
schema or any production role. Original failed log is preserved.

The protected environment preparer stopped before creating any target file:
read-only preflight found one existing non-terminal QUERY command. Inspection
confirms the new secret file does not exist, and no service/role/DB state changed.
This is not the latest HTTP call, which had workflow_id=null. Classify that
original command/physical execution before any service restart or supported
reconciliation; do not terminalize it or submit another key to satisfy deployment.
Evidence prefix:`/tmp/eom-identity-provider-install.nAaycoDM/query-database-role-`.

### Actual protected selection

The row was subsequently identified as the exact preserved pre-atomic
`workflow_38a7254f053449739ef31f5d535ff604`/original command described in
[the historical acceptance](../status/REFERENCE_QUERY_LIVE_ACCEPTANCE_2026-10-15.md).
Fresh read-only inspection verifies its original request hash/step, expired
lease since10/15 16:33:57 UTC, attempt/generation1, no output or native launch Job,
and no active physical QUERY units. Thus executable QUERY work=0, preserved
unallocated non-terminal history=1. None of those rows was edited or retried.

The root-only fixed environment was then created0600 from the existing protected
controller credential after exact role/OID checks. API/Catalog/INDEX credentials,
roles/grants, schema and policies are unchanged. The first conservative STOP is
preserved; it is not reclassified as a successful write. Corrected candidate
`1dd35b9a859f499580f6b5704e873cb7625aec8c` passes standard3-wheel/RECORD/OpenAPI,
source-free2-wheel301-module/legacy wire proof and protected pair installation.
An actual fixed-systemd UID990/no-groups/no-retained-capabilities preflight passes
the new startup role guard, installed provider, exact controls and physical
launcher readiness, without a socket, human capture, claim or model launch.

Only the QUERY service was then replaced and observed READY, active/success and
still enabled: PID1496865, invocation`de6e8fabd34c44a982bae93b569735a0`.
Configuration raw SHA`72c8b522949e3c3fb6d2644d363221ecd0b778399cfdc3ebfa607cdb26371494`;
unit raw SHA`1587e09469ed8430ec9de6d0b16b933971f6a38e5b667e082463a960c7786fcb`.
API/Catalog/INDEX process and invocation identities were independently preserved.
Rollback non-secret unit/config/receipt:
`/var/lib/eom-release-operator-stage.2857bf77-6g9mpdap/query-controller-1dd35b9a`.
No source/DB state, old failure, Artifact, query key or numerical default changed.

This closes the installed connection defect, not the full genuine HTTP/source
gate. The first script had already exited and discarded its token. A continuation
uses the exact original request/key and one fresh actual guiadmin login, retaining
its session in memory if an observation stops. It supports only explicit same-key
re-observation after diagnosis, no automatic login/new key/model retry. No password,
token or cookie is written. It was waiting at its one new prompt at06:18 UTC.

Actual evidence: `query-service-database-diagnosis.log`,
`query-original-history-quiescence.log`, `query-controller-environment-prepared.log`,
`query-controller-actual-preflight.log`, `query-controller-selection.log`, plus
source/build/install logs under`/tmp/eom-identity-provider-install.nAaycoDM`.
