# Kakao private runtime — capture and manual lease boundary

Status: source-only contracts and deterministic tests. This note does not activate a
collector, authorize a user, install VNC, select Kakao DOM controls, or deploy remote access.
This implementation covers the remote lease/profile rules and deterministic gateway
lifetime in specification §§6 and 11. Capture command/result contracts described below
are design constraints for a separate follow-up, not implemented contracts in this slice.
Existing Studio/BFF/API/Catalog/Orchestrator ownership remains unchanged.

## Ownership, identity and pointers

- Catalog owns source bindings, current authorization, durable run/attempt claims and
  manual leases. Identity's actual operator and API session are checked afresh; browser
  fields, worker output and previously cached roles are not authority.
- Future capture commands must pin command/task/attempt, binding, profile, browser execution,
  fence, capability revision and adapter release. Capture results repeat those pins
  and reference only bounded task-local members with hashes/media/sizes.
- The capture worker receives no Studio session, DB/NAS location or authority claim.
  Orchestrator validates current fence and source access before existing Artifact
  publication. A successful local capture is not a published Artifact.
- Remote lease identity and gateway epoch are distinct. A renewal increments its
  grant revision without replacing issued-at, absolute deadline or profile fence.
  The gateway receives only the lease/epoch/deadline grant, never an operator token,
  Identity session, profile path or arbitrary upstream.

## Access patterns and structures

Each active profile has one browser owner and at most one manual gateway lease.
Runtime rules use frozen values and an explicit allowed-transition table; lookups and
lease checks are O(1). Future capture output uniqueness uses sets and one pass, O(n) time
and O(n) memory under explicit member/byte limits. Active connection termination is
the fixed gateway owner's responsibility, not a new shared queue or worker registry.
No database schema, cache, external endpoint or dependency is added by this slice.

## Atomicity and recovery

Durable claim/CAS transactions remain in Catalog. Pure validators cannot replace
database exclusion, OS profile locking, process-stop observations or authenticated IPC.
Expiry alone cannot authorize a takeover. A new browser fence requires an exact prior
browser execution stop receipt, released profile lock, and (for AUTO interruption)
committed checkpoint. Leaving MANUAL additionally requires confirmed gateway stop.
Unknown process state fails closed. Login-button clicks and expired viewers never
implicitly authorize automatic collection.

Remote admission requires current ACTIVE operator/session, ADMIN, remote permission,
matching source owner/binding/profile, exact manual runtime fence and an unexpired
lease. Private authorization is GET-only. WebSocket access uses one fixed path and
exact expected HTTPS Origin/HTTP-1.1 upgrade; static assets use an installed allowlist,
not user paths. Query/fragment credentials and static-asset upgrades are rejected.
The initial contract fixes a 30-second grant, 20-minute absolute limit, and at most
5 seconds between the owner's fresh authorization observation and its use. These
are source policy choices, not measured operational guarantees or a permission cache.

The gateway lifetime helper checks both UTC and monotonic deadlines, so moving the
wall clock backward does not prolong control. Renewals cannot revive expiry or extend
the original absolute limit. Revocation first closes admission and requests shutdown
of the whole gateway (including established connections/children); it remains STOPPING
until the injected owner adapter confirms closure. Failed stop attempts are not success.
The helper cannot renew itself or alter the browser/profile lifecycle.
The shutdown callback must be bounded and must not re-enter the lifetime helper: calls
are serialized with a local lock so renewals cannot race with irreversible revocation.
This helper still requires the gateway supervisor's periodic watchdog; it does not
start its own timer or substitute for the independently supervised process-stop owner.

## Verification and remaining operational gates

Synthetic tests cover schema mirrors, strict input, identity/fence mismatch, deny-by-default,
owner/session/role/permission changes, exact expiry, stale renewal, absolute limit,
clock rollback, shutdown failure/retry, and profile takeover without confirmed stop.
Local connected-stream tests check EOF after the supplied gateway shutdown callback;
they do not prove a deployed WebSocket/RFB path or systemd cgroup cleanup.

Real activation still requires current-Identity integration, authenticated private grant
transport, dedicated UID/profile/UDS permissions, pinned binaries, Caddy forward-auth,
real WSS/RFB termination tests, browser close/flush and fixed-unit stop confirmation.
No raw VNC TCP fallback, no session token in URLs, no reuse of Codex profiles, and no
NAS access for workers are introduced. The simpler alternative—one mutable boolean
or an expiry check only at initial handshake—is insufficient because it cannot revoke
already connected viewers or prevent concurrent profile use after a stale lease.

## Next owner slice: durable first-login manual sessions (design, not activation)

This defines the smallest persisted owner before requesting Kakao login. Source now
implements `kakao_manual.py`, `kakao_manual_models.py`, `kakao_manual_service.py` and
migration `20261116_0083`; public/runtime integration is a separate boundary. This is not
operational activation. The predecessor is the owner-private binding/student/room work,
not a fabricated accepted capture.

### Bootstrap authority and fixed profile assignment

Current code has only DRAFT/RETIRED bindings. A DRAFT owned by the authenticated operator
must be eligible for first login without pretending the channel is ACTIVE or its
capability is verified. `CurrentRemoteAuthority.source_active` currently has no production
producer; its pure rule only checks an eligibility boolean. The source-only owner defines
that boolean as **binding currently permits this manual-login operation**:
non-retired owned binding, current ADMIN + `kakao_archive:remote`, current Identity
session, matching installed profile assignment and available protected remote runtime.
It must not mean `binding.state == ACTIVE`, successful Kakao authentication, verified
channel or collection authority. `source_access` still enforces the actual owner scope.
Collection authorization remains separate and requires its own observed capability.
This is an explicit producer definition, not a change to the existing wire schema.

The MVP has one fixed logical profile and fixed browser/gateway units. Persist its exact
`owner_operator_id + source_binding_id` assignment; do not reuse it for another owner
or binding just because no browser is running. First assignment requires the protected
installer/runtime's **never used, fresh profile** evidence, then an atomic one-time claim
by the actual binding owner. Existing nonempty/unknown profile state cannot be adopted
through the public start command. An already assigned profile cannot be reassigned by
starting another lease; a later reset/transfer is a separate reviewed operation that
first closes processes and handles retained credentials. Paths are installed constants,
not public arguments or browser-supplied identity.

### Minimum records and public values

Use three small Catalog-owned tables for this manual-only vertical slice:

1. `kakao_profile_runtime`: one fixed slot key, profile ID, immutable owner/binding
   assignment, current mode/fence/gateway epoch, current manual intent pointer and
   resource version. Unique slot/profile and composite owner/binding FKs provide O(1)
   exclusive claim. AUTO must later acquire this **same row/gate**; no second AUTO lock.
   This slice rejects unsupported AUTO transition, rather than inventing an AUTO job.
2. `kakao_manual_sessions`: lease/intent ID, owner/binding/profile/API session pins,
   browser run ID and command hash, fence/gateway epochs, PREPARING/ACTIVE/STOPPING/
   ENDED/ERROR phase, UTC request/authorization/expiry/absolute-expiry timestamps,
   grant revision, bounded failure/outcome code, and exact start/stop observation fields.
   Pin the current dispatch boot ID before launch; store observed InvocationID and
   PID/start-monotonic only after observation. Cgroup/unit identity remains installed
   runtime configuration. Pre-READY stays representable without a fake successful handle.
   Each new intent has its own row, preserving failed attempts and previous handles.
   This is the current manual execution record, not a generic second job system.
3. `kakao_remote_commands`: owner/scope/idempotency key + canonical request hash,
   command action, intent/result revision and small exact result fields. This keeps
   repeated START/RENEW/END replies stable even after subsequent renewals or termination.
   No credentials, browser cookie, source content, screenshots or arbitrary JSON body.

The profile row's current pointer and each session's profile/owner/binding must agree by
composite FK. Retain completed/failed session rows; use current pointer plus short row
lock for exclusivity, not a scan of all history. The fixed-profile gate is O(1);
lease/command-key lookup uses unique B-trees, O(log L + log C), with only one lease/command
mutated. This slice reads a lease by exact identity, without a history-list feature.
No separate grant table or event bus: the receipt already retains issued grant revisions.

Public commands are START(binding), RENEW(lease, expected grant revision), END(lease,
expected session revision), each with existing idempotency and CSRF handling. The API
derives operator/API session from `RequestContext.actor()`; clients cannot set a profile,
fence, role, runtime handle, duration or upstream. READ returns phase, safe reason,
expires/absolute deadline and ready flag; only ACTIVE has the fixed same-origin remote
URL. PREPARING is a real accepted intent, not a ready remote session. The internal gateway
receives existing `GatewayLeaseGrant`, without API/Studio credentials. GET authorization
only validates existing state and never starts, renews or retries anything.
Lease reads/renewals/replays require the exact pinned API session as well as the owner.
A new login cannot reuse an old key to revive a prior session's lease; the owner cleanup
path can still terminate that prior intent after current-Identity expiry/revocation.

### Transaction and external execution sequence

1. Reauthorize through current Identity and binding owner, acquire command-key and
   profile row locks, reject another current holder, reserve intent/run/lease IDs and
   the next fence. Commit PREPARING and the exact command before external execution.
   The 20-minute absolute deadline is fixed from this initial intent and never reset.
2. Outside the DB transaction, the existing fixed browser adapter validates installed
   pins, current intent and real profile exclusion, then stages/starts the same run.
   Record `start requested` separately from the observed `BrowserRunHandle`. No long
   systemctl, browser launch, file hashing or network call occurs under a DB row lock.
3. In a new short transaction, recheck current actor/session/binding/profile fence and
   record the exact browser handle. Only then prepare a 30-second gateway grant, capped
   by the original absolute deadline. Start the fixed gateway outside the transaction.
4. Reobserve both exact runtimes and the lease deadline, reauthorize, and commit ACTIVE
   under the same intent/fence. Before this commit, public admission stays denied even
   if a gateway process exists. A successful browser process alone is not remote READY.
5. UI heartbeat about every 10 seconds calls RENEW. Re-read current Identity, exact
   session, binding/profile and runtime state; call existing `renew_remote_lease` and
   commit the next grant revision + command receipt before delivering it. Grant delivery
   failure cannot extend control: reconcile that same issued grant or let it expire.
   Same-key replay returns the prior reply without adding another 30 seconds.
6. END, expiry, logout/revocation or runtime loss first closes admission in a short
   transaction. Outside it, stop gateway/viewers, then close/flush browser and verify
   exact cgroup/profile-lock release. Only confirmed closure clears the profile holder.
   Keep the failure/outcome reason after closure; do not turn a failed start into success.

Remote polling requires fresh real authorization, not a cached ADMIN label. The owner
tick uses stored actor/session references only to **look up** current Identity; they are
not a bearer credential or permission to impersonate an authenticated request. If the
owner/API is down, grant renewal stops and the gateway's existing monotonic/UTC watchdog
closes established connections. A valid session alone cannot revive an expired lease.
No automatic AUTO resume is included in this first-login slice.
The existing pure handoff forbids MANUAL → MANUAL and `ProfileFence` does not represent
STOPPED. Repeated login therefore closes the old MANUAL fence into the durable STOPPED
gate first, then starts a newly authorized MANUAL intent with a larger fence. Do not
weaken the existing handoff rule to skip confirmed stop or reuse a prior browser run.

### Pre-READY failure, reboot and reconciliation

The current browser adapter can observe the same successfully started run, but a staged
dispatch that failed before READY has no successful `BrowserRunHandle`; current `start`
also intentionally refuses a history marker as first use. Therefore persistence alone
is insufficient: implement a narrow **observation-only pre-READY closure** adapter before
exposing START. It must pin the original intent/fence/command digest and boot identity,
inspect the protected staged input and trusted fixed unit/cgroup, and either recover
the exact running handle or return verified closure/explicit UNKNOWN. It never calls
start, deletes history markers, removes Chromium locks or fabricates a ready handle.

Reboot likewise needs an explicit closure observation: boot changed plus trusted current
unit inactive, gateway/browser cgroups closed and real profile exclusion verified under
the control lock. A boot change alone is not sufficient; unrelated new processes may
already exist. Record `REBOOT_UNCLEAN` and do not claim profile flush or AUTO checkpoint.
After verified closure, a fresh currently authorized manual intent may use a new fence;
an uncertain predecessor remains ERROR and blocks takeover. Existing `_same_execution`
checks must not be weakened to accept any boot/PID merely to make recovery pass.

Required disposable/concurrency tests: same-key START and lost replies create one
intent/run; competing START has one holder; stale RENEW/END and old gateway epochs are
rejected; replay never extends deadlines; revoked/expired sessions and foreign owners
lose access; DRAFT login is allowed but channel/capability stay unverified; pre-READY
failure and reboot preserve history and require physical closure before reuse. Protected
runtime tests must still prove actual gateway EOF, profile exclusion, permissions and
fixed-unit child cleanup. None of the source tests substitute for that operational gate.

## Manual runtime composition and proxy admission (next source slice)

This slice composes existing boundaries, not a new execution framework. Catalog remains
the durable owner; fixed browser/gateway adapters own OS I/O. A bounded coordinator reads
the one profile's current lease by indexed key, advances PREPARING → ACTIVE or tears down
STOPPING/ERROR, and uses existing public service transitions. No worker, AI queue or
long database transaction is introduced. A dedicated bounded owner loop must not hold
the unrelated Catalog application loop during systemd waits.

Canonical input is the accepted manual intent, with its exact run/fence/boot/command
hash; OS state is an observation, never an alternative lease. Prior execution lookup is
by the same profile and predecessor fence, not arbitrary latest. O(log L) indexed lease
lookup and O(1) profile/OS checks are sufficient. No copied profile or stored process
output is needed. Current service CAS and OS control locks protect concurrent handlers.
No new table or queue is expected; any necessary contract addition precedes behavior.

An un-staged intent, a staged command with uncertain dispatch, a running execution and
an observed closed execution are distinct. Lost replies observe the original identity
before any further side effect. Browser readiness precedes a fresh gateway grant;
ACTIVE requires both real observations. END/revocation/expiry denies admission first,
closes the gateway's existing viewers, then stops the browser and verifies cgroups plus
profile lock release. Failure history is retained. The coordinator never renews a grant
on its own: only an authorized UI heartbeat can extend it within the original deadline.

Proxy admission is a separate read-only operation in the existing manual RPC family.
The API passes its real actor/session; Catalog checks current owner, binding, MANUAL
fence, active unexpired lease and installed runtime observation. It returns only the
existing bounded session view, never VNC/password/profile data. A history GET is not
enough: it may legitimately show a stale ACTIVE row before reconciliation. Admission
therefore fails closed on runtime, authority or concurrent revision changes without
launching, renewing or retrying an execution.

The existing BFF WebSession gains only a server-side lease/binding pointer from a
validated START/read response. It is not authority; every private asset/WebSocket
handshake reuses the API admission and normal token-refresh lock. No URL bearer or
separate session store is introduced. Old/late responses must not overwrite a newer
pointer; END clears only the same pointer. Missing/expired session denies access.

Caddy must overwrite forwarded method/URI metadata, prevent direct public access to
the admission endpoint, and strip cookie/authorization before the private gateway.
Only fixed noVNC paths and the exact WebSocket path/method/same-origin handshake are
allowed. A successful BFF admission is empty 204; uncertainty is never HTTP 200 false.
This source work does not enable remoteViewEnabled or reload production Caddy.

Tests cover shutdown and restart at dispatch/ready/publication boundaries, same-key
replay and no autonomous renewal, revoked/current owner sessions, old or concurrent
lease pointers, wrong origin/paths/upgrade, and actual HTTP status semantics. New
service transitions are additionally checked in disposable PostgreSQL. Reusing a
cached ACTIVE UI flag would be simpler but permits obsolete access; implementing a
second authorization framework is unnecessary because these checks already have owners.

The optional owner composition is disabled by default. `EOM_KAKAO_MANUAL_MODE=ENABLED`
also requires exact protected profile/template/driver/supervisor pins; absent pins do not
activate partial behavior. `EOM_KAKAO_INITIAL_PROFILE_MANIFEST_SHA256` identifies the
original empty-profile installation receipt, not a later package-upgrade manifest.
Disabled composition imports neither optional runtime code nor the Kakao worker wheel.

A start timeout followed by the same staged command, boot and trusted unit's pending
Job/activating state remains WAITING. It observes that original run, without relaunch,
until actual readiness, terminal failure or the accepted lease deadline. Physical
closure of a failed unit is not first-use proof or historical success. Ordinary expiry
uses the existing gateway stop path with the explicit `EXPIRED` reason; it introduces
neither an extra delay nor a new grant. Gateway/viewer closure still precedes browser
shutdown and real profile-lock release.

After an authorized heartbeat commits a new grant revision, private proxy admission
may briefly fail closed until the bounded owner loop publishes that exact revision to
the gateway. This is intentional: no adapter substitutes the old window, creates a
new deadline or hides the gap with a general retry. Read-only admission re-observes OS
identity outside DB locks and then rechecks current authority and the same revision.
Parallel noVNC assets and heartbeat probes share one runtime wrapper's bounded (2-second
acquisition) observation mutex, avoiding read/read contention on the existing OS control
locks. Each call still obtains fresh evidence; this is not an authorization cache, an OS
write-lock replacement or an unbounded wait. Failure to acquire remains explicit denial.

### Compatible migration admission

Kakao storage adds migrations 0080–0083 after the deployed 0079 baseline. Extend the
existing protected release operator with context/admission 1.25 and exact 0079 → 0083
upgrade plus 0083 verification. Do not reinterpret 1.24 or permit an arbitrary head/range.
The existing source/wheel/tree hashes, root-private staging and role reconciliation
remain the authority; this adds no DB values, queue or deployment service. The callback
checks the predecessor, runs the existing Alembic chain once and verifies the target;
same-context replay at 0083 does not rerun migration. Concurrent/timeout outcomes require
actual revision observation before any retry, as in the existing operator contract.

Only the new release's deployment verification selects 0083. Historical source/release
manifests and all older callbacks remain unchanged. Source tests cover wrong predecessor,
wrong context/head, same-key installation replay and schema byte/hash preservation;
the Alembic chain itself is already exercised in disposable PostgreSQL. Actual deployment
still requires the compatible installed API/Web/Catalog set and optional runtime wheels.

The activated Catalog owner and Web transport require the small pure Kakao contracts
wheel. Context 1.25 therefore pins it as a fourth exact wheel (`kakao_contracts`), while
all preceding context families retain exactly their original three wheels. Browser,
gateway and PDF runtime dependencies do not enter the API environment. The unreleased
pure contracts support jsonschema 4.25.1–4.26.x; the dedicated runtime still pins 4.25.1
and the API keeps its existing 4.26.0. Installing an incompatible wheel with `--no-deps`
and ignoring `pip check` is not a deployment strategy.

### BFF proxy implementation boundary

The optional source Caddy snippet `config/caddy/kakao-remote.caddy` is not imported by
the operational Caddyfile. It denies public access to the authorization endpoint,
overwrites the original request metadata, admits only HTTP 204, and strips Studio
credentials before the fixed gateway UDS. Its expanded forward-auth form follows
[Caddy's documented authorization pre-check](https://caddyserver.com/docs/caddyfile/directives/forward_auth)
and [response interception rules](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#intercepting-responses).

The Web wheel depends on the pure `eom-kakao-archive-contracts` package solely to share
fixed-path/Origin/WebSocket transport validation; it does not construct authority or
runtime evidence. An absent installed transport policy denies proxy admission
until the installed noVNC inventory supplies an exact immutable path allowlist and
expected HTTPS origin. The UI starts disabled and reads only the presentation boolean; its
iframe target is the fixed `/studio/admin/remote/vnc.html`, not a directory or query URL.

Each in-memory WebSession stores only a frozen lease/binding/version/time pointer and
a local response generation. START/read results are validated by the existing gateway.
Replayed START receipts resolve the current read before changing that pointer. A late
response cannot replace a newer pointer, END clears only its matching pointer, and
session eviction/logout/expiry invalidates outstanding pointer updates. Admission
rechecks the same pointer after API authorization, so a simultaneous END/logout cannot
accept a stale in-flight response. No lease, credentials or private content is persisted
in browser storage, forwarded to VNC, or added to URLs.

### Installed Web presentation configuration

Web's existing frozen configuration optionally contains the validated transport policy
(exact HTTPS origin and installed noVNC static-path set). Omitted configuration keeps
remote admission disabled; enabling requires Secure cookies and an allowed public host.
An authenticated read returns only `kakao-remote-presentation/1.0` and one enabled boolean.
This is presentation configuration, not lease authority, runtime health or permission to
start a process. It performs no storage, worker, DB or network work. The existing manual
controller loads it when opened and ignores responses after owner/view changes. An iframe
still requires the separate ACTIVE/ready/current lease; every asset and WebSocket request
still uses actual API/Catalog admission. No paths, policy, credential or origin inventory
are exposed in the presentation reply. A static JavaScript flag alone was insufficient
because the same installed Web wheel must remain usable with the optional runtime disabled.

### Web offline dependency closure

The Web build/install scripts own dependency materialization, not runtime admission.
The existing `infra/conda/eom-web.requirements.lock` pins the complete Web distribution
set, including the small pure Kakao contracts wheel and jsonschema's five-distribution
closure. Existing Web dependency versions are unchanged. Browser/gateway/PDF packages
and their dependencies never enter Web. Local EOM wheels come from the same source
commit; third-party wheels are downloaded only during the unprivileged build stage.

A standard pip requirements file records the exact distribution/version and one SHA-256
per wheel. Its separately approved SHA pins the entire closure, while source commit and
Web wheel SHA remain separate identities. The verifier uses a keyed distribution map,
rejects duplicate/missing/extra wheels, and performs bounded O(total wheel bytes) reads.
No DB, persistent queue or new wire protocol is introduced.

Before privileged pip execution, the installer copies and verifies all approved bytes
into a fresh root-private staging directory. Offline `--no-index --require-hashes`
installation uses this protected set with dependency resolution enabled. A missing
dependency cannot fall back to an index or the build interpreter. Both build simulation
and installer preflight use an empty venv without system site packages; actual Web app
and contract imports plus `pip check` must pass before the target environment is touched.
An interrupted installation remains an explicit deployment failure, not an automatic
retry or service restart. Existing compatible-release scheduling and rollback apply.
The former single-wheel `--no-deps` installation was insufficient because API's richer
build environment hid missing jsonschema dependencies in the isolated Web environment.

The privileged installer itself runs from the existing reviewed root-private release
source snapshot, not a developer checkout or a standalone copied shell script. Preserve
`scripts/web_gui/{install_release.sh,wheel_closure.py}` and
`infra/conda/eom-web.requirements.lock` in that snapshot. The operator independently
checks the installer SHA before Bash starts; the installer checks root ownership,
non-writable/non-symlink ancestors and independently approved helper/pin-lock SHA values
before executing the helper. Build output reports these three hashes. No new release
operator callback or authentication authority is added. A changed helper or lock needs
a freshly reviewed bundle, not an override flag.
