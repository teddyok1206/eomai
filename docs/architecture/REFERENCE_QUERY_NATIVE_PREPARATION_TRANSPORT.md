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

## Bound application/driver implementation decision

The next application binds a genuine captured owner, exact native executor and
QUERY-only Runner. Trusted composition supplies the policy-derived query/document
spaces; the wire never selects them. Owner configuration plus fixed three views,
OPTIONAL mode/top8/maximum1024 are fed to the existing initial-selection use case.
The native key uses a full domain-separated SHA of actual operator/original key;
the context logical ID uses a separately domain-separated128-bit digest. Changed
source/Graph/policy under that key is a conflict, not a new execution.

Admission/replay and terminal read stay in one caller root. Known report/index
absence rolls back without queue work. COMPLETED alone is insufficient: the
existing canonical completed QUERY reader must verify source and result/receipt
members before READY. Failed/cancelled Workflow or command history is preserved
and returned as failure, not restarted by this adapter. A completed canonical
read does not need a live command lease and does not invoke the driver.

Only after commit may the shared driver offer exactly `runner.run_once(workflow)`
on one non-daemon thread. No thread pool/backlog/poll loop or second queue is
introduced. Existing native unit deadlines and Runner claim/lease/current fences
bound that invocation; this is not a new840-second authority grant. Pending/busy
work remains durable for the same-key HTTP poll, which may offer the original
Workflow again through supported claim/recovery. A physical timeout is never a
new-key or model-restart permission. An active handle is reused without replacing
its capture; the Thread releases its runner/capture arguments when it exits.
Driver observations use the actual thread handle and redacted outcome only;
they are not persisted authority, workflow status or proof of completion.
The finite-drive port belongs to the preparation application; the Thread adapter
depends on that public application boundary, not the reverse. Trusted service
composition must share one driver across current-capture application instances.

Access remains exact unique key/PK and per-Workflow indexed command existence,
plus bounded current source reads. Memory is O(1) driver handles and the existing
bounded request/read materialization; database metadata stays pointer-only. No
schema/migration/new dependency or change to historical artifacts is needed.

## Transport-only source checkpoint and exact unproven scope (6bad5a4a)

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

## Package gate

Candidate `6bad5a4aae97c209550febc9c1430d6ac588b21b`, tree
`27f263d6de10a26f7f56bb42138e7e4e7c1acb63`: complete three-wheel build and RECORD
verification PASS. Dist:
`/tmp/eom-api-build/6bad5a4aae97c209550febc9c1430d6ac588b21b.W9KBoA/dist`.

Isolated `python -I -B` checks PASS with only the selected archives: owner pair
(platform/API-contracts) and full trio including the API client. Checkout imports,
installed-prefix fallback and numerical-library imports were forbidden. Changed
source/resource-byte closure is19 members for the pair,20 with the API client.
Provider inventory is12; this is not an observation or installation of the live
provider/client family. No model, database or authentication was invoked.

Wheel SHA-256 values:

- platform: `9bc2d0d503c63c2ce451f70783a1ce3c58e7a1800710167e3ba9038eafcf225b`
- API contracts: `9e54971012e21cfcb53519cb09d088c03c9b0851ffb0a150b67e31b77bf47f61`
- application API: `a3c83e45b07fcbdb81fff5da86bfd083446d9620761333202d24c784dc00d945`

The initial archive probe looked for Catalog contracts in the API-contracts wheel;
the established build owns those members in the platform wheel. The probe was
corrected to that actual ownership, without adding an ambient/fallback import or
rebuilding/modifying any wheel. Both failed probe logs are preserved alongside
the passing `query-native-transport-owner-pair-package-final.log` and
`query-native-transport-api-package-final.log`. Active services and the original
QUERY recovery handle were not changed by this package gate.

## Native preparation application and finite driver checkpoint

The bound `NativeReferenceQueryPreparation` now implements the existing prepare
port. It derives caller scope from the genuine captured owner, constructs the
fixed initial selection and reuses the supported canonical admission/replay root.
PENDING has the real original Workflow ID; FAILED/CANCELLED history never invokes
the driver; unrelated human-approval stages fail explicitly. READY is constructed
only after the concrete canonical completed QUERY reader has returned in that
same root. It does not replace Catalog current-context publication/ranking.

`ReferenceQueryPrepareDriver` implements the application-owned finite-drive port.
It runs exactly one original-Workflow `runner.run_once` per offer on at most one
live non-daemon Thread. Same active Workflow reuses that handle; other work returns
BUSY without a memory backlog. A failed start or invocation is a redacted local
observation, not a DB state repair/retry. The actual Thread handle, rather than an
early IDLE flag, controls admission. Python Thread releases its runner/capture
arguments at exit. Required QUERY-only family/actual operator/engine/owner/executor
composition is checked before dispatch; actual claim and source authority are
still revalidated by the existing Runner.

Verification2026-10-15 UTC:

- Focused application/driver23 PASS in8.90s, strict mypy9 production modules PASS,
  Ruff/format6 changed Python files and shell parse PASS.
- Guarded disposable PostgreSQL stage102 PASS in91.88s, including12 new application
  cases. Actual Workflow/START commit-before-offer, same-key replay and simultaneous
  first admission, changed source/Graph/policy, absence without work, late current
  denial/full rollback and terminal-state-without-canonical-result are covered.
- The shared test DB was inspected before and after: exact disposable identity,
  migration20261014_0055, read-only inspection, zero other connections. No production
  DB was a pytest target and no new migration was needed.
- IAM/source/driver observations are synthetic in this PostgreSQL gate. Temporary
  real control/Artifact bytes and actual transactions do not establish installed
  API identity, actual numerical inference or production activation.
- Initial fixture failures are preserved: JSON Schema exception type, missing
  imported guarded-engine fixture, and an invalid step-state name used as a
  Workflow state. The DB correctly rejected that last injection; the fixture now
  uses the actual unrelated AWAITING_HUMAN_APPROVAL Workflow state. No schema,
  constraint, authority check or historical result was weakened to pass tests.

Logs in the existing temporary verification workspace include
`query-native-prepare-application-focused-final.log` and
`query-native-prepare-application-postgres-final-reviewed.log`. The earlier runs
remain separate, not overwritten or counted as new runtime acceptance.

Still unimplemented/unactivated: protected listener/runtime composition and socket
provisioning, actual installed API/client exchange, ordinary HTTP preparation/poll,
private checked plan2.3 consumption, and remaining role/consumer/GPU acceptance.
The current original QUERY/auth handle is unchanged. Coverage is still2/520; CPU
default and the safely drained indexing service are unchanged. This source step
does not close the full goal or consume a new live-model execution.
