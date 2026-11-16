# Kakao browser profile and process boundary

Status: source-only fixed-unit gate and local subprocess tests. No browser, VNC,
account, selector, remote gateway, collection run or service is activated here.

## Narrow ownership

Catalog still owns current operator authorization, claim/fence, checkpoint and mode
transition rules. Orchestrator starts/stops exactly `eom-kakao-browser.service`.
The separate `eom-kakao-archive-collector` wheel supervises one installed driver;
it has no Catalog/DB/NAS imports. The offline PDF worker has no browser dependency.
Both AUTO and MANUAL use this same service and the same real nonblocking flock.
This is not a scheduler and does not infer permission from a lease timeout.

The existing `kakao-profile-fence/1.0` JSON Schema is the only input protocol here.
The owner stages it at `/var/lib/eom-kakao-runtime/browser/request.json`, with
`eom-catalog-manager:eom-kakao` ownership and mode 0640 under a protected 2750 owner
directory (setgid supplies browser read access without adding it to core groups).
It contains logical profile/run identity, increasing fence and mode, not credentials,
roles, URLs, arbitrary argv, browser paths or instructions to access another profile.
The supervisor validates it, snapshots its exact bytes once into its private runtime,
and passes that snapshot to the fixed installed driver. The original run record stays
with its existing owner; the mutable input filename is never execution identity.
The fixed start helper holds the control flock while checking prior process closure,
creating an exclusive per-run input, and atomically replacing this small current input.
A durable first-use marker prevents an inactive/reset unit from being mistaken for a
never-used profile. Existing run input is observe-only, never automatically rerun.

## OS exclusion and lifetime

`/var/lib/eom-kakao/profile` is browser-owned 0700. A precreated browser-owned 0600
`/var/lib/eom-kakao/profile.lock` is held by the supervisor, not just briefly probed.
The parent is root-owned 0710, group `eom-kakao`, so the worker cannot replace a live
lock inode. This tightens the specification's illustrative parent-directory ownership
without giving the gateway access to profile bytes. No `SingletonLock` is removed.

The supervisor acquires the lock before spawning the driver, retains it through
shutdown, and only emits systemd READY after acquisition and process creation. READY
means process ownership, not Kakao login/channel/collection success. Driver output is
not journaled. SIGTERM asks the driver to close/flush; a bounded grace period is followed
by killing the still-owned driver. Systemd `KillMode=mixed` additionally closes the whole service
cgroup, including descendants that escaped that process group. `Restart=no` prevents
an unexpected exit or stale claim from implicitly restarting a browser.

The owner serializes start/stop with a local control flock in addition to the existing
DB claim. A recorded run pins boot ID, systemd InvocationID, main process/start timestamp,
fixed cgroup and the command digest. Stop is accepted only after reading actual systemd
state and the recorded cgroup's `cgroup.events`: no main/control process and no populated
cgroup (or the verified original cgroup has disappeared). Reboot, another invocation,
malformed/inaccessible observations and lingering descendants are UNKNOWN, not STOPPED.
A worker boolean or expired lease is not stop proof. Cgroup closure closes the old
supervisor's lock descriptor; the next supervisor must still acquire the real flock and
fails if any unrelated process holds it. A new start rechecks closure, not a cached receipt.
The observation preserves systemd result and main exit code/status; forced termination
is explicitly nonzero. Physical closure is not a claim that the driver flushed data or
committed a checkpoint. The owner must treat that distinction in its existing recovery flow.

Mode changes must also satisfy the existing pure handoff rule: AUTO checkpoint before
MANUAL, gateway/established-viewer stop before leaving MANUAL, and fresh authorization
before AUTO. Those are mandatory caller responsibilities; this OS adapter does not
invent checkpoint or gateway success.

## Access pattern, errors and simplest alternative

One profile/unit is the MVP boundary. All operations are O(1), with bounded small
descriptor reads and one indexed owner claim, not process-list scans or a new registry.
Only the fixed local input and private snapshot are materialized. No DB/binary storage
or cross-service schema is added. Interrupted bytes and prior failed records remain.
Start timeout is uncertain and is never retried automatically; the owner can observe
the same run. Stop timeout is followed by an actual closure observation, never a second
blind start. Driver, unit and interpreter are pinned root-installed artifacts.

A DB lease alone or a flock released when only the main PID dies is insufficient:
Chromium descendants may still own the profile. Separate AUTO/MANUAL units would create
another race; one unit plus exact cgroup closure is the simpler supported boundary.

## Remaining installation and driver gates

- Install the collector/contract wheels in a dedicated explicit Conda environment and
  verify wheel RECORD, root-owned interpreter, entrypoint, unit and driver SHA.
- Implement/install `eom-kakao-browser-driver --request <fixed private snapshot>
  --profile <fixed profile>` separately. It must keep its browser/Xvnc children in this
  cgroup, handle SIGTERM by closing/flush, never daemonize, and never start without the
  supervisor. Playwright, Chromium and TigerVNC are not added or guessed by this slice.
- Create dedicated users/groups, root-protected paths, fixed command/control files and
  optional narrow systemd authorization through the existing installer boundary.
- Verify actual Chromium sandbox and browser egress, no raw VNC TCP, protected Xauthority,
  current gateway lease and whole-cgroup forced shutdown in the protected environment.
- Wire current owner claim/checkpoint/gateway checks and persist the exact run handle.
- Add owner reconciliation for a staged dispatch that failed before supervisor READY:
  the input/history is preserved but no successful run handle exists. This state is
  explicitly blocked from blind replay/first-use; never delete the marker to bypass it.

Local tests prove real flock exclusion and subprocess lifetime plus deterministic
systemd/cgroup observation cases. They do not claim a privileged systemd sandbox,
real remote browser, Kakao capability or operating release passed.

Source verification: 61 focused local tests passed, including actual subprocess flock
contention and bounded forced termination; Ruff and strict mypy passed. Unit syntax
inspection currently fails because the dedicated Conda interpreter is not installed,
not because an installed browser sandbox was tested. The worker dependency set contains
only the pure contract wheel; PDF/browser engines are not pulled into each other.
Normal stop-handler failure remains a nonzero process exit. A default SIGTERM death
is explicitly unclean; neither is converted to success merely because stop was requested.
