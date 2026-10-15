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
repository/worker homes/Codex auth and image resources, has no ambient capabilities,
and retains only root-supervisor UID/GID/drop and read-search capabilities. Child
UID drop clears effective privileges. Provider config/code/secret names must not
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
