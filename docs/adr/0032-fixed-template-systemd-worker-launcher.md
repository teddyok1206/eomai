# ADR 0032: Fixed-Template systemd Worker Launcher

## Status

Accepted

## Context and boundary

The unprivileged `eom` workflow runner prepares a private-group workspace and asks the system
manager to execute Codex as one of five fixed `eom-cdx-N` identities. The previous adapter called
`systemd-run` and supplied the UID, GID, command, environment, paths, and sandbox properties for
each job. Granting that caller the systemd `manage-units` privilege needed by
`StartTransientUnit()` would make the authorization boundary materially broader than the EOM
worker contract.

The canonical job identity is the existing `job_[0-9a-f]{32}` identifier. PostgreSQL remains the
canonical queue and concurrency boundary. A systemd instance name is only an execution pointer to
the already-created immutable job workspace; it is not a replacement queue or a new job identity.

## Decision

Install five root-owned worker templates and five root-owned harmless probe templates. Each worker
template fixes its Linux user, group, executable, workspace root, HOME, Codex path, environment,
resource limits, and filesystem sandbox. The caller may pass only a strictly validated canonical
job ID as the template instance. A root-owned, isolated Python executable validates the slot/job
pair and workspace containment again before invoking the fixed Codex command.

The launcher calls `systemctl --no-ask-password --wait start` for the selected fixed instance. It
does not call `systemd-run`, supply an arbitrary command, select a UID/GID, or set a unit property.
The launcher reads the service `Result`, `ExecMainCode`, and `ExecMainStatus` after the unit stops;
the existing workspace `result.json` remains the authoritative worker result protocol.

On the installed systemd 255 and polkit 124, the systemd `StartUnit()` authorization mechanism
provides the `unit` and `verb` action details. The deployment rule therefore allows user `eom`
only the `start` verb for fully anchored EOM worker and probe instance names. It explicitly denies
all other `manage-units` requests by `eom`, including transient units, restart, and arbitrary
services. It does not use authorization caching or execute a helper from polkit. If an operator
cannot demonstrate these details on the installed server, the rule must not be installed; a
separately reviewed root-owned narrow broker is the only fallback.

Doctor and preclaim share a bounded readiness check. For every enabled slot it verifies the exact
root-owned template/helper hashes and starts one fixed `/usr/bin/true` probe. A denial, stale unit,
wrong identity contract, failed probe, or lingering process returns
`WORKER_SYSTEMD_AUTHORIZATION_DENIED` or `WORKER_SYSTEMD_TEMPLATE_INVALID` before a command claim.
No Codex, worker auth, database mutation, NAS access, or workflow event is involved.

## Access patterns and data structures

Slot lookup and expected artifact hashes use immutable maps keyed by the two-digit slot. Job and
unit membership use anchored full-match regular expressions. These operations are O(1) over five
fixed workers. PostgreSQL keeps the ordered command query and `FOR UPDATE SKIP LOCKED` claim;
systemd naming only prevents concurrent activation of the same unit instance.

The five authorization probes are deliberately uncached in V0. They are bounded, local oneshot
operations and preserve correctness when policy or unit state changes. A cache would require an
explicit invalidation/version contract and is not justified by current measurements.

## Sandbox parity

The templates retain the transient unit's `NoNewPrivileges`, strict system protection, read-only
home policy, private temporary directory, NAS/Docker/repository/staging denial, private workspace
and HOME writes, `UMask=0007`, memory/CPU/task limits, and timeout. They additionally fix an empty
capability set and enable kernel/control-group, SUID/SGID, personality, realtime, device, hostname,
clock, and address-family protections that are compatible with Codex network execution. Worker
01 cannot traverse another worker's HOME or workspace through Unix identity or the explicit unit
path restrictions.

## Failure, retry, and cancellation

Authorization or template readiness failure occurs before claim, so attempts, leases, workflow
state, and event history remain unchanged. Once started, a normal worker exit, timeout, missing
result, invalid result, and platform commit failure keep their existing distinct mappings. The V0
runner has no active-worker cancellation use case. It therefore receives no `stop` or `restart`
authorization; the unit's server-side timeout owns termination.

Existing PostgreSQL idempotency and job IDs remain authoritative. Starting an already-active
instance cannot create a second unit, while different job IDs may run concurrently within the
existing worker concurrency controls.

The installed capability assessment used systemd 255, polkit 124, the local
`org.freedesktop.systemd1(5)` and `polkit(8)` manuals, and the distribution's
`/usr/share/doc/polkitd/examples/50-local-allow.rules`, which demonstrates `unit` and `verb` lookup
for `StartUnit()`. Upstream references are the
[systemd manager D-Bus interface](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html)
and the [polkit rules reference](https://polkit.pages.freedesktop.org/polkit/polkit.8.html).

## Alternatives

A broad `manage-units` grant, per-job sudo, a root runner, `CAP_SYS_ADMIN`, and caller-selected
transient properties are rejected because each permits authority outside the fixed worker
contract. A broker is more complex than static templates and is unnecessary while installed
`StartUnit()` unit/verb filtering is demonstrably available; it remains the fail-closed fallback
for systems where that filtering cannot be proven.

## Consequences

Deployment gains root-owned unit, helper, and narrowly scoped polkit artifacts plus negative
authorization tests. Unit updates require an operator install and `daemon-reload`. The runner no
longer depends on transient-unit authorization, stdout piping, or caller-controlled systemd
properties. Historical failed workflows remain immutable and are not retried.
