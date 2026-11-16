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

`/var/lib/eom-kakao/profile` is browser-owned 0700. A precreated browser-owned 0640
`/var/lib/eom-kakao/profile.lock` is held by the supervisor, not just briefly probed.
The parent is root-owned 0750, group `eom-kakao-control`, so the worker cannot replace a live
lock inode. This tightens the specification's illustrative parent-directory ownership
without giving the gateway access to profile bytes. Group read is required by the
descriptor-based O_RDONLY directory walk; execute-only 0710 would reject that walk.
Only the browser and Catalog owner belong to the control group. Catalog can hold a
Linux LOCK_EX on an O_RDONLY lock FD without changing file bytes; its ability to probe
exclusion gives it no access to the browser-owned 0700 profile. Real subprocess tests
confirm this read-only-FD exclusion. Catalog's currently running process gets the new
supplementary group only on a later compatible owner activation.
No `SingletonLock` is removed.

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
- Install and verify the source-implemented MANUAL driver below:
  `eom-kakao-browser-driver --request <fixed private snapshot> --profile <fixed profile>`.
  Its browser/Xvnc children stay in this cgroup and close on SIGTERM. Playwright,
  Chromium and TigerVNC are not installed or activated by this source implementation.
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

## MANUAL driver source contract

The fixed driver consumes the same validated ProfileFence snapshot; no new browser
request schema or caller authority field is added. It supports MANUAL only. AUTO returns
an explicit unavailable error until the collection adapter is implemented, not an idle
browser falsely reported as collection. It issues no automatic navigation (a new profile
starts blank; retained browser session tabs remain browser-managed) and uses no Kakao
selectors, login actions, guessed channel URL, OCR or model calls.

The dedicated collector's optional `manual-browser` extra pins `playwright==1.65.2`.
This is an isolated runtime dependency, not an API/renderer dependency or installation
approval. The publisher's [1.65.2 release](https://pypi.org/project/playwright/1.65.2/)
was checked, and the bundle's browser is installed only beneath
`/opt/eom/kakao-browser/playwright-1.65.2`. The exact release's Chromium and fixed
`/usr/bin/Xtigervnc` executable hashes must match the root-owned, read-only
`/etc/eom/kakao-browser-driver.env`, with exactly `EOM_KAKAO_XVNC_SHA256` and
`EOM_KAKAO_CHROMIUM_SHA256`. This small static install configuration contains neither
paths supplied by the user nor credentials. Ubuntu Noble's
[package inventory](https://packages.ubuntu.com/noble/amd64/tigervnc-standalone-server/filelist)
confirms the executable name; installed help/version/UDS behavior still require validation.

The driver requires preprovisioned browser-owned mode0600
`/var/lib/eom-kakao/vnc.passwd` and `/run/eom-kakao-private/Xauthority`. It never creates,
resets, logs or returns either credential. Xvnc runs on fixed display `:94`, with
`-nolisten tcp`, `-rfbport -1`, VncAuth and permissioned
`/run/eom-kakao-vnc/vnc.sock`. A pre-existing socket, X lock or X socket is an explicit
reconciliation requirement, never permission to unlink it. The fixed profile remains
0700 and must be under the supervisor's real lock in the same fixed systemd cgroup.

Playwright launches the persistent context headed, explicitly setting
`chromium_sandbox=True` ([official API](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context)).
No `--no-sandbox`, tracing, HAR, screenshots, video or credential argv/environment is
introduced. stdout/stderr from browser/Xvnc remain suppressed. The loop observes child
failure and context closure. SIGTERM first closes the context, then its Playwright
connection, then Xvnc, with bounded waits below the supervisor's grace budget. Failure
to close, failed child exit or forced termination stays nonzero. Systemd remains the
final whole-cgroup owner; a local mock does not prove deployed Chromium sandbox behavior.

Access is O(1) for fixed input/paths and bounded streaming executable hashing at the
explicit launch-validation boundary. The driver neither polls DB nor stores a second
collection state machine. No credentials or browser processes are generated in source
tests; anonymous subprocesses and launcher fakes validate arguments, shutdown and errors.

Source verification on 2026-11-16: MANUAL driver and browser runtime focused tests
passed together (104 cases), including actual SIGTERM handler execution and ordered
context/transport/display shutdown. Ruff, formatting and strict mypy passed. A fresh
non-editable collector/contract wheel installation in a temporary verification directory
passed module-byte comparison, wheel RECORD integrity, installed schema lookup and
the secret-safe driver entrypoint. No Playwright dependency, Chromium, TigerVNC, account,
credential or production service was installed or activated by those checks.

## Protected installation preparation (2026-11-16, not activated)

Responsibility is a fixed three-runtime stage/verify command, not a package manager or
release service. `scripts/kakao/install_runtime.py` consumes a reviewed root-private
`runtime-install-v1.schema.json` manifest plus exactly three units, one polkit rule and
one tmpfiles rule. Source commit, byte-tree SHA, unit SHA and renderer release identity
remain separate. The source tree and manifest are installation inputs, never UI authority.
It checks root-owned read-only ancestors, contained links and complete byte-tree hashes
before importing any new runtime. It uses stdlib only and requires an explicitly selected
protected Conda Python with `-I -S -B`; the mutable API interpreter is not a root bootstrap.

The fixed prefixes are `/opt/eom/conda/envs/eom-kakao-browser`, `eom-kakao-remote`, and
`eom-kakao-pdf`. The former `/srv/eom` proposal is rejected: its current ancestors are
root:eom whereas the reused native runtime validator requires root:root. Existing `/srv`
ownership is not changed. Python 3.12.13 and each prefix's full dependency closure are
reviewed before fingerprint admission; pins include contracts0.1.0/pydantic2.13.4/
jsonschema4.25.1, browser Playwright1.65.2, gateway websockify0.13.0, and PDF PyMuPDF1.26.7/
Pillow11.3.0. The exact Chromium and noVNC1.6.0 trees are separately SHA-pinned.

The unreleased pure contract wheel supports jsonschema>=4.25.1,<4.27 so it can also
be consumed by the existing API's pinned4.26.0 without downgrading that runtime.
This package compatibility range does not loosen dedicated runtime admission:
browser/remote/PDF installation manifests still require jsonschema4.25.1. Both
concrete versions must pass the same capture/remote/render contract regression suite
in independent temporary environments. Web currently has no jsonschema installation;
its reviewed dependency release must include the pure wheel and a hash-pinned
validator dependency closure. Do not vendor these contracts into the platform wheel
or satisfy the new dependency with an unrecorded runtime pip install.

Read-only host inventory: Ubuntu24.04.4/systemd255/Caddy2.11.4; all Kakao units/users/groups
are absent. Apt simulation (not installation) for TigerVNC1.13.1+dfsg-2build2 adds only
`tigervnc-standalone-server`, `tigervnc-tools`, `tigervnc-common` and
`libfile-readbackwards-perl=1.06-2`; zero upgrade/removal. `xauth` already exists.
Distro noVNC1.3.0 and websockify0.10.0 do not satisfy the pinned gateway and are not
fallbacks. Existing root-owned NotoSansCJKkr-Regular.otf has SHA
`6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a`; renderer materializes
that font through its ordinary exact-input contract rather than installing another font.

The installer creates only dedicated nologin identities and fixed directories/empty locks.
Browser/remote/render never join sudo/docker/eom/caddy. Remote gets only its proxy/VNC/grant
groups; Catalog writes inputs, remote reads its bounded grant, and render sees only attempt
bind mounts. Fixed lookup maps and sorted immutable inventories make checks O(files+bytes),
not DB queries. One root installation flock excludes concurrent stage. Existing exact bytes
are replay; a changed existing target fails without overwriting it. Partial newly-created
paths are retained for operator reconciliation; no failed receipt is changed to success.

Stage does **not** start/enable services, reload systemd, alter Caddy or groups of existing
Caddy, create credentials, download packages, run pip, or mutate DB/NAS. Only the fixed
Catalog owner gains the new control-lock read group; it never gains VNC/profile access.
A missing runtime
or asset is an explicit preflight failure; missing credentials is a separate NOT_PROVISIONED
activation gate. `verify` means installed files/identities match, never browser/login READY.
Unit reload is deferred to a release window because systemd's global reload epoch affects
running GPU pin checks. Caddy currently proxies `/studio/*` to Web; reviewed remote-route
authorization and the proxy-group membership require a separate compatible activation.

The existing installers are intentionally **not** a generic callable for Kakao:
`scripts/embedding/install_index_runtime.sh fingerprint CPU_INDEX_FP32` and
`fingerprint CUDA_INDEX_FP32` accept only those fixed numerical profiles;
`install_experiment_runtime.sh` publishes only its fixed experiment prefix. Do not invent
a KAKAO profile argument or broaden numerical locks. Reuse their proven preparation
sequence: unprivileged explicit Conda build at the final dedicated prefix, independently
approved fingerprint, fresh root-controlled inode copy with links/ownership not preserved,
full hash/contained-link/mode check, then replace only that dedicated prefix before execution.
The narrow fixed-three-prefix publisher still needs an explicit implementation before live
installation; this stage/verify script does not pretend to perform it. Inputs needed are
reviewed source commit, three runtime byte-tree hashes, Chromium/noVNC tree hashes, exact
five payload hashes, and renderer release SHA. Existing operator scripts supply no secret
material to this manifest. The protected launcher/helper must be independently SHA-checked
**before** executing them; a script's self-check cannot protect its first instruction.

The actual stage CLI (after an operator independently stages/hashes the helper, manifest,
and five payloads beneath root-private storage) is:

```text
/opt/eom/conda/envs/eom-embedding-index-cpu/bin/python -I -S -B \
  <root-private-install_runtime.py> preflight|stage|verify \
  --manifest <root-private-manifest.json> \
  --manifest-sha256 sha256:<independently-approved-64hex> \
  --payload <root-private-directory-containing-exactly-five-payloads>
```

This reuses the protected Conda interpreter read-only, not its numerical workload,
packages, configuration, admission or worker. All three commands are root-only. The
five named payloads are the browser/remote/PDF units, `46-eom-kakao-runtime.rules`, and
`eom-kakao-runtime.conf`; filenames and destinations are closed maps. There is no shell,
arbitrary action or service-start argument. `stage` uses a separate fixed installation
flock; active Kakao units or queued systemd jobs block it. The operator must also stop
Kakao application admission through the owner before the installation window. No
application-state quiescence is inferred from systemd alone.

The manifest's explicit `profile_id` is bound once in
`/var/lib/eom-kakao-runtime/fresh-profile.json` (root:root0644). Schema
`schemas/kakao-archive/fresh-profile-v1.schema.json` pins device/inode/mtime_ns/ctime_ns
of the newly created, actually empty 0700 profile plus the install manifest SHA.
An existing profile without that receipt is reconcile-required. Replay preserves the
original receipt even if the profile later changes; it does not recertify it as empty.
`install_manifest_sha256` belongs to that **initial** installation, not a subsequent
runtime upgrade. A newer runtime manifest does not overwrite or invalidate the old
initial pin; owner observation intentionally uses the original receipt identity.
Catalog must compare current stat, no-history, unit/cgroup closure and real lock exclusion
before first-use observation. The installer never returns profile_empty=True.

Rollback before activation means leave units stopped and keep profiles, staged inputs and
failed records; restore only an exact prior compatible runtime/unit set during a stopped
window. No recursive uninstall, user deletion, apt downgrade, profile reset or generic
systemctl authorization is added. A generic installer or executing Conda/pip as root would
be broader and less auditable than this fixed boundary.

## Shared API release dependency closure

The API/Catalog owner needs the pure Kakao contracts, but not Playwright, websockify,
Pillow or the PDF worker. The existing API builder therefore builds four independent
wheels from one Git archive: platform, API contracts, application API and Kakao contracts.
The release operator's 1.25 context pins the fourth wheel as `kakao_contracts`; it does
not vendor that package into platform or resolve a floating dependency during install.

Dominant operations are one keyed wheel inventory and ordered byte/RECORD verification:
O(number of members + payload bytes), with no DB or worker changes. The pure wheel's
complete package inventory, metadata and schema bytes must match the same release archive
and canonical schemas. The existing temporary non-editable installation imports its
actual Catalog consumer before acceptance. The captured four-wheel hashes/inodes are
rechecked immediately before and after install and recorded together for compatible rollback.

`verify_release_wheel_records.py` retains the historical three-wheel default and narrow
owner-pair/platform-only modes. Only the explicit `--kakao-release` mode accepts exactly
the new four-distribution set; it never silently accepts three. This avoids reinterpreting
archived release evidence. The simpler alternative, an unpinned `pip install` of the pure
package, would bypass source identity, offline installation and rollback closure.
The normal clean-commit gate remains mandatory. A dirty-tree temporary build used during
development is explicitly a test fixture, not a release candidate or deployment approval.

### Initial fixed-prefix publication

`scripts/kakao/publish_runtime.py` owns only the five fixed runtime/asset paths above.
Its publication plan pins the existing install-manifest SHA and the complete installed
distribution-name/version map for each role; it does not duplicate the install manifest's
payload hashes or introduce another runtime registry. Approved hashes are operator
inputs, never inferred as approval from mutable builder output. `prepare` creates only
empty directories for the existing unprivileged `eom` builder. Conda/pip run separately
as that builder at the final absolute prefixes; `/tmp` test environments are not moved
into production prefixes.

Access is a bounded sorted tree walk (O(files log files + bytes)), exact role/package
maps and membership sets. Publication serializes on the existing install flock and
requires stopped Kakao units/jobs. All five candidates are copied into new root-owned
inodes in root-private quarantine before any target changes. Descriptor-relative,
no-follow copying rejects special files, escaping links, unsafe modes and changing
members. Source hard links are not retained. The protected snapshots must match the
independently reviewed tree hashes before their original builder directories are moved
to private retained backups and the snapshots take the fixed names.

Only after fixed-path publication may a candidate interpreter execute, with `-I -S -B`
and a clean environment. It verifies its exact Python prefix/version, installed package
lock and actual dependency closure. This preserves Conda's absolute-prefix behavior and
does not execute editable source, pip installation or post-link code as root. The helper
and reused installer are independently hash-checked root-private files before execution.
Bootstrap is the already protected Python 3.12.13 interpreter; no optional package is
needed to parse the plan or copy candidates.

This is initial-only, not an upgrade or rollback framework. Existing root-owned targets
require the exact completed publication receipt and read-only verification; mixed or
interrupted states are reconcile-required. A failure retains quarantine, builder backups
and the phase receipt without automatic retry, deletion or service activation. Actual
identities, units, credentials and proxy activation remain the existing separate installer
and owner boundaries. Synthetic copy/closure tests do not certify a live installation.

The root-private CLI is `publish_runtime.py prepare|fingerprint|publish|verify
--installer <root-private-install_runtime.py> --installer-sha256 sha256:<reviewed-hash>`.
`publish`/`verify` additionally require `--manifest <root-private-publication-plan.json>`,
`--manifest-sha256 sha256:<reviewed-plan-hash>` and `--install-manifest
<root-private-existing-install-manifest.json>`. Invoke it with the same protected
Python 3.12.13 `-I -S -B` bootstrap as the installer. The `eom` builder uses `umask 022`
for its separate final-prefix preparation; the publisher never runs Conda or pip.
`fingerprint` reports candidate byte hashes, not an approval. Complete role locks must
come from the final built wheels, not the earlier temporary dependency-preparation run.

All targets must share the quarantine filesystem so rename is atomic per target. The
five-target sequence is deliberately not advertised as one atomic transaction: a stopped
window and retained per-target phase evidence make partial publication explicit. No
candidate interpreter runs until all five snapshots are protected at their final paths;
tree bytes are checked again after the read-only probes. No auth/profile file is copied.
