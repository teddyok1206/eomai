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
