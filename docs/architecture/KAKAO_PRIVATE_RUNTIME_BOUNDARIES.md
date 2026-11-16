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
