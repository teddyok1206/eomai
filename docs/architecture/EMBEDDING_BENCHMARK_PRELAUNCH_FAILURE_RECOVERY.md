# Benchmark pre-launch failure closure

Design before behavior, 2026-10-21 UTC. This is a failure-recording use case, not a
retry, a successful launch receipt, or a change to the frozen six-launch program.

## Scope and canonical sources

The original CPU1 reservation is retained. An explicit root observation can prove
that preparation failed before the native service started. An actual, freshly
authenticated administrator may then close that original Job as FAILED through
the Orchestrator application. Nothing rewrites the reserved invocation, output
files, root uncertainty, or prior events. No model, unit start/stop/reset, cleanup,
NAS commit, or replacement execution occurs in this use case.

Canonical identities are the original BenchmarkOwnerRequest1.0, original Job and
reserved invocation, protected owner association, root handoff/uncertainty, and
PID1's exact controller/native unit observations. New observation/decision values
have no independent entity lifecycle: they are small immutable event metadata,
with semantic SHA-256 distinct from Job/execution/revision identities.

## Narrow additive contract

Add `embedding-benchmark-prelaunch-failure/1.0` only; preserve released benchmark1.0
and launch-control1.0 schema bytes. Define ROOT_OBSERVATION, FAILURE_DECISION, and
PREDECESSOR_REFERENCE. Parsing any value confers no authority. The contract pins
Job, request hash, CPU1 execution/invocation/association, original failed controller
unit/invocation/source/supervisor hash, root uncertainty and metadata snapshot hash.
It contains no item text, vectors, credentials, arbitrary commands or paths.

## Root inspection and protected proof resolution

- Root reuses BenchmarkRootStagedFiles and keeps its read-only FDs/epochs while
  inspecting the exact invocation and 16 native-owned empty outputs. No worker
  writer, permission expansion, or source-input text reread is needed.
- Require `launch.env`, `root-prepared.json`, `root-completion.json`, and
  `control.sock` absent with descriptor-relative no-follow checks. Any existing
  symlink counts as present, never absent. Require canonical root-uncertain bytes
  matching the original association/Job/invocation, not another failure.
- Require the original owner process gone and its original monotonic deadline
  expired. Require the exact original controller invocation failed and quiescent;
  pin its protected supervisor bytes and source. Require native CPU service/socket
  loaded with the exact expected fragments, no drop-ins/reload drift, no invocation,
  start/exit timestamp, active state, process, pending Job, cgroup or FD store.
- Combine the current boot ID, exact unit metadata, required absences and bounded
  stat epochs of invocation/uncertainty/output directories/members in a deterministic
  snapshot hash. The root observer validates ACLs and content hashes initially;
  late epoch checks detect subsequent content, ACL, ownership or inode changes.
- A root-produced canonical observation is create-once at a fixed recovery root,
  keyed by the full execution ID. Root ownership, protected ancestors, exact mode,
  no ACL/symlink/hardlink, bounded size, expected raw SHA and canonical/schema checks
  are mandatory. It is a local proof materialization, not a NAS artifact or user grant.
  Preserve existing records: exact replay only; conflicts are errors.
- The actual owner adapter captures that protected proof and independently rechecks
  current unit/controller/boot/process/absence/stat snapshot before returning it and
  again before SQL commit. An arbitrary parsed report or model-supplied boolean
  cannot be injected into production composition. Old observations are reusable
  only while their complete current snapshot still matches; no auth extension.

## Application transaction, replay and data structures

Expensive inspection occurs outside SQL. Under the existing Catalog owner admission
(actual opaque session, fresh authentication, current ADMIN/control/source/Graph
policy), lock the indexed original Job and read its bounded ordered journal.
Require RUNNING, exactly one unresolved CPU1 reservation and zero receipts. Recheck
the captured observation, append one typed RUNNING -> FAILED decision using the
existing state machine and stable content-free error code, recheck observation and
late source/Identity fences, then commit. A failure rolls back that SQL transaction.

The journal explicitly validates the new closure event and its linkage before its
generic transition branch. It cannot launder arbitrary failure payloads. Exact
replay returns the original sequence/UTC timestamp/decision with created=false;
it does not mint a new observation/time or change a different terminal failure.

Access patterns are indexed Job/key lookup, row lock, bounded ordered event scan,
and fixed-member map/set lookup. Cost is O(events + fixed members + path depth),
bounded by the existing 32-event journal and 16-output CPU1 layout. No migration,
table, cache, queue, global capacity claim or generic recovery framework is needed.
Healthy INDEX/QUERY work is not blocked by a closure that starts no compute.

## Explicit successor, not an unresolved-ID bypass

A successor must pin the predecessor Job, original request hash, closure event
sequence and decision hash. Verify FAILED and that exact typed decision using
current authority; reject unresolved, foreign, forged or differently failed parents.
Require the same logical benchmark and a distinct immutable revision; sources,
Graph/policy, model/runtime, recipe and measurement thresholds stay fixed. Only
then may the ordinary new-revision submission/capacity gates run. Never mutate
the old request, hide its failure, select latest, or discover a parent with a JSON
scan. This explicit guard is required before any successor model execution.

## Ownership, alternatives and validation

Contracts depend on values only. Catalog owns protected files/PID1/Identity/source
adapters; Orchestrator owns closure transactions and event semantics. Production
composition selects concrete supported adapters. CLI only presents typed inputs.

Direct row updates, invoking private `_fail`, restarting the old association,
manufacturing a launch receipt, or merely changing revision identity are insufficient:
they lack verified authority/evidence or contradict immutable execution history.

Test schema/Pydantic/canonical alignment, missing/tampered/stale proof, nonroot or
symlink producer, nonempty/linked output, missing required uncertainty, active or
previously-started native unit, changed controller/boot/process/deadline, late epoch
or permission revocation, journal laundering, replay/conflict/concurrent closure,
and unresolved/foreign successor denial. Persistence/concurrency uses disposable
PostgreSQL only. Actual restricted-UID/capability tests use private /run fixtures;
source PASS does not count as six genuine model runs or GPU activation.
