# Authenticated API → native reference QUERY preparation

2026-10-15 UTC. Protocol-first source step; no runtime installation/activation.
This connects the existing initial reference selector/atomic admission toward the
ordinary HTTP item flow. It is not completion of the full integration goal.

1. **Responsibility/boundary:** API forwards an already authenticated request to a
   dedicated Orchestrator native owner. Catalog retains source/index verification;
   only Workflow/Orchestrator admits/claims/executes QUERY and commits Artifacts.
2. **Canonical source:** official selected source/report/Graph/policy, immutable
   native controls and the existing Workflow/START/Job/checkpoints. No new queue,
   preparation table, search engine or background principal.
3. **Identity/revision:** operation correlation ID/hash, caller idempotency key,
   native Workflow ID/request hash/context hash remain separate. Native owner
   namespaces the key with the actual captured operator. Its context ID is a
   domain-separated128-bit digest of that same stable scope, not an index/source
   content hash; the full canonical request hash is independently recorded.
4. **Pointers:** wire accepts only exact source revision and Graph/policy pins.
   No actor/roles/session, Artifact paths, model/bundle/space/recipe/resource selector
   or arbitrary native operation. Existing current source/index/member checks apply.
5. **Access:** exact idempotency lookup, one-source capture, at most three view
   namespace reads, original execution poll/claim. No corpus scan in the API.
6. **Structures:** existing indexed queue, unique workflow key, frozen wire DTOs,
   and at most one in-process native driver handle. A local handle is a resource
   observation, not execution authority or a persistent job queue.
7. **Bounds:** request8KiB/reply4KiB; existing Identity challenge/response bounds and
   original10-second capture deadline; finite overall transport. Native calculation
   runs outside HTTP/SQL, under existing resource limits/lease/current fences.
8. **Transactions/concurrency:** same initial preparation/START root. Repeated
   requests reuse original pins/audit. PENDING is an actual persisted Workflow,
   never a completed selection. An active driver does not enqueue another memory
   task; subsequent identical requests inspect/kick the same durable work.
9. **Dependencies/ownership:** domain contracts remain IO-free; API gets a socket
   adapter only, no native engine/model/NAS. The native owner composes the current
   real capture with existing Catalog admission/executor/Runner. No DI framework.
10. **Failure/retry:** timeout is an unknown outcome; do not resubmit with a new key
    or automatically start again. Known initial report/index absence alone is
    UNAVAILABLE; denied/corrupt/revoked pointers remain failures. READY requires
    canonical completed QUERY verification, then Catalog still independently
    validates/publishes the current auxiliary context for item acceptance.
11. **Alternative:** executing inside API/Catalog violates existing privilege and
    storage ownership; synchronous model execution exceeds normal HTTP deadlines.
    A new broker/scheduler/auth cache is unnecessary.

## Authentication exchange

Use the existing bounded length-prefixed EOM3 carrier for three stages on one
accepted Unix connection: preparation request; native-generated genuine Identity1.1
REFERENCE_QUERY challenge / current API RequestContext capture response; final
preparation reply. Existing canonical Identity serializers/parsers are reused.
The native importer must observe the actual installed API PID/UID/GID, code/config/
key-metadata epoch, purpose/nonce/deadline and the held accepted FD. A DTO, role,
UID alone or test callback cannot activate production authority. No password,
bearer or capture is persisted/logged or sent to numerical workers. Preserve
current fresh-auth/expiry/refresh-generation checks; do not extend900-second canary
authority or reinterpret existing capture purposes.

The API client uses RequestContext.owner_capture() from the already authenticated
HTTP request; it does not authenticate a token again or borrow an Actor projection.
Pin the new API client in the provider code witness before activation. The active
9-member compatible canary remains unchanged; new source is a distinct release.
The source witness now has12 members, including the new API client. It cannot
authorize the active older API by omitting that member or normalizing the two
inventories. Compatible API/client and native-owner installation must precede
activation of this new family.

## Socket layout without private-group grants

Planned root-provisioned parent: `/run/eom-reference-query-owner`, owner
eom-workflow-runner, group eom-api, mode2750. The owner binds the fixed socket as
itself; SGID inherits the socket's eom-api group without granting that group to
the owner process. Socket mode0660. Keep the owner's actual primary/supplementary
groups and private staging0700 unchanged. Never grant eom-api membership, read its
secret file, alter CPU worker groups or accept a root-listener UID as a fallback.

Reuse the existing endpoint/carrier with an explicit trusted SGID parent profile
and bounded payload option; existing callers keep0750/default bounds and wire
bytes. Root provisioning, actual inherited-group/secret-denial and real installed
peer verification are separate opt-in privilege gates before activation. This
document is not an installation approval or proof that the socket exists.

## Required tests and remaining activation

Closed schemas/mirrors/hash/JSON Schema2020-12/Pydantic, request/reply pairing,
pending-vs-completed, explicit absence vs failure, no role/path/control injection;
real socket/fragmented frames/bounds/deadlines/disconnect/peer denial; one current
capture and nonce/purpose/hash checks; no SQL before capture; same key/changed
intent/concurrency/partial commit; one native driver and original claim/recovery;
API has no privileged engine/model/source dependency. Synthetic IAM/peer seams
must be reported separately from actual installed verification.

Remaining gates: protected service composition/provisioning, genuine installed
API exchange, existing-item HTTP preparation/poll/replay, private checked plan2.3
handoff, role consumption and full live acceptance. No 25-item/HWPX regeneration
is required for this native preparation boundary.

## Source checkpoint and exact unproven scope

Implemented: closed schema plus byte-identical packaged resource/hash, frozen
Pydantic messages, request/reply hash pairing, one accepted-connection native
handler, a current-RequestContext API client, and explicit bounded/raw-byte EOM3
carrier reuse. Literal bytes reach the Identity parser, so noncanonical capture
data is not silently normalized. The handler sends at most one final reply even
if that write is partial or times out. Neither adapter retries authentication,
reconnects or invokes application work again after an unknown outcome.

Not implemented here: bound preparation application, finite native driver,
listener/service composition, API lifespan/HTTP preparation/poll wiring, root
socket provisioning or actual installed-peer acceptance. The synthetic application
returns PENDING to test transport; it does not prove a real Workflow was created.
No live model execution, database mutation, service restart, credential storage,
authority/expiry extension, new dependency or worker group change occurred.

Verification on2026-10-15 UTC:

- Final shared regression596 PASS in58.49s, including the focused308 PASS. These
  counts overlap and must not be added. Existing httpx/Starlette deprecation warning
  was recorded; no unrelated dependency upgrade was attempted.
- Strict mypy7 production modules PASS; Ruff/format10 Python files PASS.
- Real temporary local sockets and HMAC import are exercised; PID/UID/unit/source
  observations and application are synthetic. Bad peer, capture request hash or
  purpose, wrong challenge, noncanonical request, wrong reply, application failure
  and partial final-write all deny or return failure without duplicate invocation.
- The initial focused run had5 fixture failures: four socketpair context-manager
  usages and one stale expected code-member set. The test setup was corrected;
  production authority checks were not relaxed. The final run includes those cases.
- Existing PostgreSQL preparation/registry results remain prior evidence, not a
  newly executed database/transport or real-user gate. No persistence code/schema
  changed in this checkpoint.

Temporary verification logs:
`/tmp/eom-identity-provider-install.nAaycoDM/query-native-transport-regression-final.log`,
`/tmp/eom-identity-provider-install.nAaycoDM/query-native-transport-shared-regression-final.log`,
and the preserved `query-native-transport-focused-initial.log` in the same workspace.
These logs contain synthetic test diagnostics, not stored credentials or prompts.
