# Private Chat QUERY preparation and finite drive

## Acknowledged original continuation — 2026-10-18 design before behavior

1. Extend the existing private preparation application/client, not a queue or a
   new wire version. PREPARE remains explicit admission/drive; READ stays strictly
   read-only. An acknowledged PENDING Workflow may have received BUSY, so it does
   not prove a physical execution is alive.
2. Canonical state is the original unique-origin Workflow, its validated START,
   current live Chat origin/Identity and immutable selected request/controls.
3. Reuse that exact request/origin/Workflow ID. No tool-sequence key, new Workflow,
   command, query execution or latest index is allocated by continuation.
4. Existing closed V1 schema/Pydantic request/reply checks and correlation hashes
   remain unchanged. The client may explicitly continue only a validated PENDING
   acknowledgement; returned non-null Workflow IDs must match that original.
5. Reuse the Runner's current atomic native claim and exact checkpoint admission.
   A drive offer is not permission to compute. Existing linked recovery may
   observe/advance RUNNING work without a new Job or physical launch; do not
   duplicate that state machine in this application or infer authority from idle.
6. Use the existing indexed original/command lookups and single finite handle,
   O(1) additional metadata. No schema/migration/query/index/cache or retained
   authority is introduced by this client seam.
7. Close the admission transaction before offering the existing single driver.
   A competing offer coalesces; actual atomic claim/current fences remain required
   even after a stale observation. Never invoke a model under a source-read root.
8. Client read uses READ only. Explicit continuation sends the exact same PREPARE
   once after known PENDING, not a hidden retry inside read. Timeout/disconnect,
   FAILED/UNAVAILABLE or wrong original never triggers another request.
9. Runner infrastructure owns durable eligibility; Orchestrator client owns wire
   acknowledgement/identity validation. Workers gain no new tool or authority.
10. BUSY preserves the original and permits a later explicit bounded continuation.
    Unknown transport outcome triggers no automatic request. Any later explicit
    drive still uses the original lease/checkpoint recovery boundary; no lease
    reset, new identity or reinterpretation of failed history is permitted.
11. A new drive message/queue is unnecessary because PREPARE already owns original
    admission. Hiding PREPARE in a read is unsafe; an unstarted-only parallel rule
    would incorrectly prevent supported original RUNNING/checkpoint continuation.
    Returning BUSY as permanent failure would abandon an otherwise valid original.

The consumer must still bound its own wait/progress loop and report unresolved
PENDING honestly. This seam does not activate Chat delivery or admit native work.

The concrete owner wait use case uses the existing stop Event/current worker
deadline, capped at180s and12 progress rounds (maximum25 RPCs,5s interruptible
spacing). It reserves the full20s one-shot RPC bound before every call, including
after a delayed wake-up. It returns the actual last PENDING at its bound; it never
converts that into EMPTY/READY, starts another Thread/queue, stores authority or
holds SQL roots. Initial admission and explicit continuation are PREPARE; every
observation is READ. Any transport/validation error propagates immediately with
no subsequent call. Later broker/provenance/current-source delivery remains a
separate integration, not implied by this local use case.

### Implemented continuation and final source verification

`PrivateChatQueryPrepareClient.read_original` makes exactly one READ; explicit
`continue_pending_original` validates a PREPARE/PENDING acknowledgement and sends
the exact same PREPARE bytes once. Both reject a returned different non-null
Workflow ID. Missing/revoked/failed replies and unknown transport errors never
cause fallback requests. `wait_for_original_private_chat_query` supplies the
bounded/interruptible owner wait described above, returning actual canonical
READY or unresolved PENDING without inventing empty results.

Related nine suites **207 PASS /99.50s, no skips**; the initial105 overlap and
are not added counts. Cases include real temporary kernel-peer/Unix exchanges,
an actual shared Thread occupied by reference work then driving one original
private Workflow after release, same-original coalescence and read-only behavior.
Runner/model/source bodies remain declared fixtures. Fake-clock tests prove
25-call/180s bounds, delayed-wakeup checks, stop, exact request bytes and immediate
termination on unknown outcomes. Existing native executor/step/Runner tests cover
their own original checkpoint fences; this is not a new actual model or DB gate.

An exploratory unstarted-only application predicate was rejected before merge:
it would incorrectly block existing RUNNING/checkpoint continuation and duplicate
the Runner's authoritative admission. Its trial73 PASS/5 FAIL also exposed that
the declared application fixture has no step table. The trial predicate/query
and fixture edits were removed, restoring byte-identical application, domain,
SQL, state, lease and persistence code. Final207 prove existing RUNNING behavior
is preserved. No production safeguard was relaxed to hide that trial.

Frozen private prepare1.0 source/mirror raw9af37ac1dab5062183336016d1522a0e167fe165b592abfc244ee8b689487656
and worker V4/tool2/origin1 bytes are unchanged. No schema version, dependency,
queue, database, native admission or operating default was added/changed. The
previous121-case real PostgreSQL proof remains its historical data-layer scope.
The new client/wait use case is not wired into the operating Chat broker yet;
canonical provenance, truthful bounded candidate filtering and live delivery
remain required. Existing passive owner3b0626ac and running services are intact.

### Committed package candidate — 2026-10-18 04:54 UTC

Code `48d28c2a2c879d118f294794c124804f3e8572c4` is pushed. Strict typing2,
Ruff/format4, diff and separate-process client/completion imports without
torch/transformers/sentence-transformers/numpy PASS. Standard three-wheel/RECORD/
installed simulation PASS; exact client/completion modules and unchanged packaged
private prepare1.0 schema match source inside the platform ZIP.
Build directory:
`/tmp/eom-api-build/48d28c2a2c879d118f294794c124804f3e8572c4.nkvNmb/dist`.
Platform raw1dcc9841da9ef90702ddac364fbd0751b330fcf9afd6aaf2218d35157a86f9cd;
API contracts raw47de20c7f244ab3c5250c5729e193f457983cc403bb9f2bc3135f8a9f643e454;
API raw814cd45b1b958ac85bdc933727f528f53af486fbd22e53f7267ab2dc261c027e.

This client-only candidate is NOT_INSTALLED/NOT_ACTIVE; the prior passive QUERY
composition3b0626ac is not replaced merely to add an unused Chat-side helper.
No production DB/schema/state/claim/runtime/unit/policy/default change or manual
model/GPU/HTTP replay occurred. Background INDEX remains separately observed on
the thirty-minute schedule. Full consumer/coverage/six-actual-run/default/rollback
gates remain OPEN; the next boundary is canonical provenance and real Chat use.

Design before behavior, 2026-10-18 UTC. Continues
[initial private context selection](PRIVATE_CHAT_CONTEXT_PREPARATION.md).

1. Responsibility: join the existing initial-selection/atomic Workflow+START use
   case, dedicated private Runner and canonical completed-context reader. This is
   the missing owner application before a Chat tool can await/use a private query.
2. Canonical source is the exact live V4 Chat origin, immutable original private
   Workflow request, selected controls/index and existing result/receipt Artifacts.
   A supplied actor ID, old turn or prior success is never authority.
3. Preserve original turn/claim/worker-input hash/basis, request/index/Graph/policy
   and execution identities. Repeat prepare uses the existing unique origin key;
   no tool-sequence key or substitute approved Item is allocated.
4. Inputs and context results already have closed JSON Schema2020-12/Pydantic
   contracts. The application result is a frozen owner-local value, not a new
   worker/API wire contract. No V4/tool2 bytes or prompt meaning change here.
5. Access: one indexed origin lookup, bounded command failure existence lookup,
   exact canonical result read and fixed Workflow drive. No conversation scan.
6. Reuse the existing single finite Thread handle for reference and private QUERY,
   with separate explicit offer methods and concrete family/actor/owner guards.
   One private invocation cannot overlap a reference invocation in that handle.
   Keep the old public reference driver import as a compatibility alias, not a
   second queue/registry/pool or arbitrary runner callback.
7. Complexity: O(log W + log C + C_workflow) workflow/command selection plus existing bounded
   index/context resolution; one active handle and O(1) drive metadata. No new
   DB/index/cache/migration, retained authority or persistent text.
8. Commit the original Workflow+START transaction before any drive offer or
   completed-context read. Never run a model while holding that admission root.
   A busy driver preserves the existing pending Workflow; no new identity/retry.
9. Runner infrastructure composes the Catalog/source interfaces and existing
   domain Workflow. Domain/schema packages remain infrastructure-free. Orchestrator
   still owns Artifact publication; Chat/native workers get no DB/NAS access.
10. PENDING, initial INDEX_NOT_PREPARED, terminal execution failure and invalid/
    revoked canonical reads remain distinct. READY requires the existing actual
    canonical reader plus current private/public reauthorization; a COMPLETED row
    alone is insufficient. Errors are content-free; unknown failure never becomes
    new model work. Stop offers/drain only the actual original handle on close.
11. Copying the reference driver would create independent unsupervised execution
    handles. Reusing its reference-only admission would fabricate authority.
    Sharing only the finite handle and keeping two explicit validated entrypoints
    is the smaller correct boundary.

This does not activate private admission, install migration0057, publish policy,
launch a model, change a Chat worker protocol or silently change TOPIC/RECENT/EXAM
search behavior. Semantic delivery must still retain provenance and distinguish
PENDING from unavailable/failed work. Reordering six legacy cards is not full
private candidate retrieval. Actual fresh-user and C1–C5/device gates remain open.

## Implemented ownership boundary

`NativePrivateChatQueryPreparation` commits the supported initial selection and
original Workflow/START before offering its dedicated Runner or opening canonical
result-read roots. A current `COMPLETED` row is only a reason to invoke the existing
private canonical reader/service; it cannot create READY without validated query
execution and current private/public/producer authorization. A failed or unavailable
canonical read is never repaired with another query. Initial index absence remains
the existing distinct `PrivateChatQueryPreparationUnavailable` exception.

The immutable owner-local result preserves the original request/origin and actual
context, not a second persisted payload. Revalidated context equality is canonical
value equality, not Python object identity. Queue actor selection is not permission:
the actual `OperatorAuthorizationFence` public protocol remains authoritative and
does not need a caller-invented `capture` attribute. The application rechecks its
exact owner/executor/driver composition before every use.

`NativeQueryPrepareDriver` shares the original one-handle lifecycle across two
explicit guarded offers. Cross-family calls cannot coalesce even if supplied the
same Workflow ID. The old reference import is an explicit compatibility alias;
its public offer stays reference-only. Shared composition guards/value types are
separate from both applications, so loading the driver does not load the private
context application or create an import cycle. A child interruption remains
UNAVAILABLE, with no process-wide exception-hook disclosure or automatic retry.

Tests distinguish real Thread handles/SQL roots/local canonical files from mocked
source admission, Identity and native/canonical result ports. The staged PostgreSQL
fixture explicitly admits its declared private definition; production admission
stays FALSE. New application cases must prove cross-connection commit visibility,
one original Workflow/START on replay, late-denial preservation and failed-history
preservation. No source test or this declared fixture proves installed private
worker/tool delivery. No schema bytes, migration or dependency changed.

The failed-command existence read uses the existing indexed
`WorkflowCommandRecord.workflow_id` column, then checks the small original
Workflow's command set before LIMIT1. Initial origin lookup uses the existing
unique Workflow idempotency key. No new global scan or index is introduced.

## Source checkpoint and preserved failures

Final related23 suites **597 PASS /289.38s, no skips**; strict mypy5 production
modules, Ruff/format9 and diff checks PASS. An actual separate-process import
verified the shared/legacy driver alias without ML or the private context
application being loaded. Positive admission/Chat/Identity/native results in
these source tests remain synthetic; real Thread handles and SQL root behavior
are distinguished from operating model/consumer acceptance.

The first broad run was590 PASS/1 FAIL: a test incorrectly required the same
Python context object after schema revalidation. It now checks the unchanged
canonical value rather than weakening validation. An earlier invalid synthetic
service-ID fixture was corrected to the official local-indexing identifier.
The public Identity protocol has no `capture` field; composition therefore uses
queue selection only, and the actual existing Identity/source fences still decide
authority. No capture object was fabricated. Two child-interruption tests failed
before the finite driver recorded UNAVAILABLE without invoking the exception hook;
both passed after that fix. Earlier29/54/57 focused cases overlap this final597.

The first guarded147-pin PostgreSQL gate, `private-prepare-Tx4CEHDY`, preserved
100 PASS/3 FAIL and successful cleanup. All three new tests had reached their
post-commit independent-connection observer, which mistakenly expected START
instead of the existing official START_WORKFLOW enum value. Independent protected
readback proved that exact assertion failure and removal of disposable state
`/tmp/eom-api-testdb-20261018023314_46c642c1`. Test-only enum correction does not
change production workflow state, admission, commands or immutable history.
Original failed stdout raw3c7c26c1adb0d50c6e7a348f30416d230064992fcaecbd909d5f1d0a65fd7096
and protected evidence remain at
`/opt/eom/embedding-benchmark-os-evidence/private-prepare-Tx4CEHDY`.
The distinct `private-prepare-8gABET14` gate is the explicit developer re-execution
after that fixture correction, not an automatic retry or live query resubmission.

## Final disposable PostgreSQL verification — 2026-10-18 02:46 UTC

The distinct147-pin `private-prepare-8gABET14` gate passed **103/103, no skips**,
including the three new application cases. Independent protected readback matched
the exact test stdout, all current source pins, real read-only inspection at
source migration0057/other connections0, and successful supported cleanup. Exact
disposable state `/tmp/eom-api-testdb-20261018023958_5640889b` no longer exists.
Both finite root1446697/wrapper1446689 are terminal. The prior failed100/3 gate
and its diagnostics remain preserved, not rewritten or counted as103 PASS.

Evidence:
`/opt/eom/embedding-benchmark-os-evidence/private-prepare-8gABET14`;
root helper raw62bafecced1fb2ce515c283d1117dcac7923ec4126c7ff0f7027148758b88619;
test stdout rawe4f502baca5017cd34150ffcbe56b9aba1240170ef632b2dc0c0e7ba579757b4;
independent observer rawcde3fa20ae737072357e1d7226d83cf3e03ed25e7c797d14ec00109e02c01965.
Local bounded preparation/readback is `/tmp/eom-private-prepare-db.8gABET14`.

SQL/registered files/Workflow/START persistence are real in this disposable
database; Chat/Identity/source populations and native numerical execution remain
declared fixtures. Model runs0, production DB/privilege/admission changes0. Operating
migration remains last verified0055, not this test database's0057. No current service,
slot, numerical prefix or CPU default changed, and no login was requested.

Still required: actual private policy/admission and protected owner composition,
an internal prepare/read transport and actual Chat delivery with canonical
auxiliary provenance/async handling. Existing multi-member control file sets and
the Chat resolver may allow an owner-only provenance companion beside the frozen
tool2 record; verify full producer/permission/replay closure before choosing that
design. Do not invent an implicit audit registry, silently repurpose TOPIC or
change frozen worker/Origin bytes just to get a passing fixture. C1–C5, full
coverage and six real CPU/CUDA/default/rollback gates remain OPEN.

## Read-only continuation before transport wiring

The eventual internal prepare/read protocol needs two separate use cases. A
poll/read must not call prepare again: even an idempotent prepare can offer
pending work to the finite driver. Add an explicit owner-local read which uses
the same unique origin-key lookup, preserved request and current Chat/Identity
authorization, then the same canonical completed-result reader. Missing original
work is NOT_PREPARED; pending is PENDING, never EMPTY. No initial index-head
selection, Workflow/START insertion, claim renewal or drive offer occurs on read.

The original request selection is a small frozen typed value shared with prepare,
not a second persistent record. Indexed lookup is O(log W), failed-command
existence remains bounded by the original Workflow, and completed file/context
checks retain their existing bounds. No DB/schema/wire/dependency change is
needed for this application seam. A new internal wire contract still requires
JSON Schema before transport behavior; this local seam does not activate one.
The simpler alternative (polling prepare) is insufficient because it can start
pending numerical work and conflates observation with side effects. Authenticated
private source access remains live-turn-only; an ended/revoked claim is not made
readable by retaining an earlier successful response.

## Internal preparation exchange — design before JSON Schema

The new owner-only request carries a revalidated original private origin, exact
Graph/access-policy pins, a correlation ID and semantic request hash. It has two
explicit actions: PREPARE_PRIVATE_CHAT_QUERY and READ_PRIVATE_CHAT_QUERY. No text,
credentials, requested actor/role, external path, numerical config, index-head
override or caller-chosen idempotency key is accepted. The embedded origin's
actor is an assertion to reauthorize, not a grant. The trusted Chat owner selects
the original prepared turn's Graph/policy; workers cannot call this endpoint.

The QUERY adapter derives one stable context request ID from the original origin
hash, uses its configured corpus/namespace/spaces/limits, and delegates to the
existing prepare or strictly read-only application. Both paths enforce current
original ownership and actual operator fences. READY carries the exact canonical
private context; PENDING has no context, UNAVAILABLE distinguishes initial index
absence/read-before-prepare, and FAILED preserves explicit terminal/authorization
errors. Replies bind action/correlation/request hash/origin and all context scope
pins. Numerical scores are auxiliary, never source citations or approval.

Use the existing bounded canonical JSON Unix framing and kernel Chat-owner peer,
one request/application invocation/final reply, no automatic transport retry.
The protected QUERY socket's future owner/profile installation is separate from
adding these messages. API/reference human-capture transport stays unchanged;
no worker peer, fake human session or session capture fallback is added. Socket
timeout means unknown original outcome, not NOT_PREPARED or a new key. A reply
does not authorize later use; the consumer must still perform current source and
original claim checks before returning cards/citations. Tests must distinguish
real local sockets/SQL from declared Chat, Identity and numerical fixtures.

This adds one packaged schema resource with its canonical source file and its
intentional wheel copy, not duplicate runtime payload storage. No new queue,
DB table/migration, dependency, model default or activation is introduced. The
remaining protected composition, provenance companion, filtering and async/tool
delivery gates remain required; a source exchange is not C4 live acceptance.

## Implemented internal exchange and read behavior

`system-rag-private-chat-query-prepare/1.0` is the new closed2020-12 resource.
Its packaged copy is intentionally byte-identical and pinned by the Catalog
resource inventory. The old V4 Chat input/result, ToolRecord2 and Origin1.0 remain
unchanged. Request32KiB/reply640KiB limits cover original metadata and the existing
bounded private context, not question/binary duplication.

`NativePrivateChatQueryPrepareDispatch` translates only the two explicit actions
to the existing application. Context request identity is deterministically derived
from the original origin hash; changing RPC correlation does not allocate another
original query. Full original hash still backs the unique Workflow lookup. Owner
configuration alone supplies corpus, namespace, spaces, source classes and bounds;
Graph/access-policy pins come from the trusted original Chat preparation and are
reauthorized by the existing source owners. READY verifies the canonical context
and exact question-basis/Graph/policy/context-identity closure.

`PrivateChatQueryPrepareClient` requires an explicit protected owner endpoint;
there is no default installed endpoint, API-key path or automatic activation.
`handle_private_chat_query_prepare_connection` uses the existing EOF-delimited,
canonical JSON framing, actual kernel Chat-owner UID and one final bounded reply.
It is not the EOM3 worker streaming carrier. An invalid/unauthorized frame invokes
no application; a failure after application entry remains unknown and cannot cause
another model invocation or a fabricated NOT_PREPARED. The future finite host and
protected owner composition still have to activate this adapter explicitly.

Read-only selection authorizes the actual operator and live original Chat even
when no original Workflow exists. Pending reads return only owned execution status;
READY additionally uses the existing canonical current-public-source/producer read.
Neither read selects a newer index, submits START, renews a claim or offers the
driver. A revoked/ended claim is explicit failure rather than an empty answer.

Preserved development failures: the first30-case exchange run had26 PASS/4 fixture
setup errors (missing required listener backlog); the second27 PASS/3 FAIL exposed
a real adapter mismatch between EOF client framing and EOM3 stream handling. Both
ends now use the same existing EOF carrier; no framing check or timeout was relaxed.
The next exchange run passed30/30. Later matrix/resource/consumer regressions are
recorded separately, not inferred from this focused result. Strict typing initially
found an untyped known-absence error code; both fixed-code exceptions now use their
exact Literal types rather than a cast or broader error-code contract.

### Verified composition discovery for the next delivery step

The existing resident calls `execution.prepare` before `worker.answer`; prepare
commits RUNNING and the exact request/dispatch pointers before returning. Its
independent heartbeat thread is already running at that point. A future bounded
pre-model preparation can therefore verify a genuinely live original turn; it
must still respect the original hard claim/answer deadline, not extend it or
publish a guessed worker-start receipt. Cold numerical work can exceed one20s
RPC: use explicit READ on the same original after acknowledged PENDING; never
turn a timed-out PREPARE into absence or submit a replacement. Which user intent
should incur this work and the pending tool/UI meaning remain delivery design,
not permission to run a private query for every greeting.

The existing official `PostgresOperatorAuthorizationFence` supports current
target-row/permission fencing without minting a human session; the actual Chat
source RPC independently authenticates live original ownership. This is the
appropriate existing seam to evaluate for protected private-owner composition,
not a fabricated `AuthenticatedOperatorSession` or an ADMIN capture borrowed
from the reference/API path. Actual role pin, installed routine/privilege/current
configuration and source-policy checks are still mandatory. This discovery does
not install that composition or change either authentication contract.

Concrete composition subsequently confirmed that adapter's caller-role check is
Catalog-only, whereas the native QUERY controller is pinned to `eom_app`. Do not
configure/patch that restricted adapter to accept QUERY. The Identity-owned
table-owner alternative and live-original factory are documented in
[installed-owner composition](PRIVATE_CHAT_QUERY_INSTALLED_OWNER_COMPOSITION.md).
Neither alternative grants a human capture, changes HTTP freshness or turns an
old login into current authentication.

The original origin-key lookup now also reuses the existing full
`validate_private_chat_query_workflow_submission` definition/row/fingerprint
validator for both read and prepare replay, rather than trusting stored state.
Canonical READY additionally uses the existing deeper reader. Source fixtures
explicitly declare their unattached-row seam; actual disposable PostgreSQL cases
exercise the full validator. Attempted changes to definition hash, request
fingerprint and request payload are first rejected by the existing PostgreSQL
immutability triggers; after rollback the same original remains readable. Source
tests separately prove propagation of the full row validator's rejection. No
trigger is disabled to manufacture corruption. Static private admission remains FALSE. The original
fresh-auth HTTP observer remains waiting, not retried.

PENDING is durable admission, **not proof that a finite driver is currently
alive**: the shared handle can have returned BUSY or UNAVAILABLE. Before live
delivery, close that liveness case through an explicit supported same-original
drive/reconcile decision, respecting current claim and native checkpoint state.
READ itself must stay side-effect-free. Do not invent a second memory queue,
poll PREPARE as if it were read-only, reset an uncertain original, or assume that
READ alone will cause a busy original to start after another request finishes.

## Current source checkpoint and preserved disposable runs

Final related28 suites **741 PASS /304.51s, no skips**, strict typing7 production
modules and Ruff/format11 Python files PASS. Focused108 are included, not added
to741. An earlier740 run preceded the full original-row validator reuse and is
preserved as historical scope, not latest-source acceptance. Actual separate
process imports of the new contract/client/transport/dispatch loaded no torch,
transformers, sentence-transformers or numpy. No wire predecessor was edited.

The first155-pin disposable gate `private-read-tfekGGID` passed107/107 and cleanup.
Independent protected readback matched all then-current pins and confirmed source
migration0057, read-only inspection/other connections0 and removal of exact state
`/tmp/eom-api-testdb-20261018030256_dbad06d8`. This predates the full original-row
validator reuse. Evidence:
`/opt/eom/embedding-benchmark-os-evidence/private-read-tfekGGID`;
test stdout raw4efbdfdece19cbbe560c8aae44f11dc6a3d2d5c5d9ad7ea3cbb67a8b37030fa2;
root helper raw2fa2da708f3e63d9663add847f6ccc407c8aecc85a0d213655b848fc4f1538bf;
independent observer rawd6cef5e23b461d3f2db7510cf821989966e0ac6e9a3f43a86fcf770e9fa15037.

The next155-pin gate `private-read-os78dGDZ` preserved107 PASS/3 FAIL and successful
cleanup. The three test fixtures wrongly expected immutable PostgreSQL snapshots
to accept corruption. Existing `reject_workflow_snapshot_mutation` and
`reject_private_chat_query_origin_mutation` correctly rejected those writes before
application read. Independent protected diagnostics confirmed those exact errors
and removal of state `/tmp/eom-api-testdb-20261018030912_ffbd27e4`.
Evidence: `/opt/eom/embedding-benchmark-os-evidence/private-read-os78dGDZ`;
test stdout raw581b5ecca436cda73f13399d57417bdd7c0e7d11c54c800655c6ffca97d24dce;
root helper rawfe092059f521655ee6232071487b6f3afb0497313aeb094e5a6ecdb4b2da6d23;
diagnostic observer raw78844d6a0b07cc762b085887b899557fa0311bebd1ef0475824f30f24a9d8ab9.

Only those test expectations were corrected: assert PostgreSQL rejects mutation,
rolls back, and the original read returns the same pending work without a drive
offer. No trigger, privilege, production source rule or failed history was changed.
The distinct `private-read-JZuabQEP` gate is the deliberate developer validation
after this fixture correction, not an automatic workflow/model retry. All source
and SQL source/Identity/native fixture scope remains explicit; operating private
admission is FALSE and the full goal/C1–C5/device gates remain open.

### Final155-pin PostgreSQL readback — 2026-10-18 03:22 UTC

`private-read-JZuabQEP` passed **110/110, no skips** with supported cleanup.
Independent protected readback matched all155 then-current source/test/schema/
script pins, exact test stdout, read-only disposable inspection at migration0057
and other connections0. Exact state
`/tmp/eom-api-testdb-20261018031607_76dc225c` is absent; original wrapper1469947
is terminal. Earlier107 PASS and107/3 failed gates remain separate historical
evidence, not counted toward110 or rewritten as success.

Evidence: `/opt/eom/embedding-benchmark-os-evidence/private-read-JZuabQEP`;
test stdout raw92dee4332c070170009810e4d33ec7024d5e0c913e4d5de7ee83fcb48c25dab2;
root helper rawb50148dd76250860f8ef6fe60683d2ccaba808a9a3075218e4db59c85188668a;
independent observer raw4b911b63d6f8b296a47b07485f333a67107f57b1e5aeb378280d31f106a8a5ec.
SQL rows/registered files/original Workflow and DB immutability are real in this
disposable test; Chat, Identity/source populations and numerical work are declared
fixtures. Operating migration remains last verified0055. Model/GPU/HTTP replay0,
production DB/role/runtime/default/admission changes0; no interactive login.

### Published package candidate — NOT_INSTALLED

Code candidate `c9927f57f8ae76916c23a973323a75f360100d4f` is pushed. Standard
build-only three-wheel/RECORD/installed-simulation verification PASS; all seven
changed production Python modules and the packaged schema (eight members) match
the exact selected source bytes inside the platform wheel.
Build directory:
`/tmp/eom-api-build/c9927f57f8ae76916c23a973323a75f360100d4f.VfeX2d/dist`.
Platform rawf1c2b8ce6ef9fdfab4fb7a94897f35ba881591a3d0274cf4f2219b8adc5e480d;
API contracts rawde196c637df34b99db454174155c9a43822aceaec37e5242715663a9b1a721fc;
API raw993673bc69fdc0ef07bb00c249c60a9a2d917490456276ea5089ddc175cebd30.
This does not install the private host, policy/admission, migration0057 or a Chat
tool consumer. Existing operating services/default/policies remain unchanged.

## Published candidate and package evidence

Code candidate `16b021b25cc2408521f682e7b12fb1b77ccc3852` is pushed. Standard
build-only three-wheel/RECORD/installed-simulation verification PASS; all five
changed production modules in the platform wheel match the selected source bytes.
Build directory:
`/tmp/eom-api-build/16b021b25cc2408521f682e7b12fb1b77ccc3852.T2wQTy/dist`.
Platform raw25d9fc5b38aed74a9d07ee8aa2c3a2c53d910bc162c7d60d7b490b6a5a87e0c5;
API contracts rawc05103df64a904f6b1b834c8d533e52c757307f66e485efab3e7fde3fa217c7b.
This is a developer package candidate, NOT protected installation/activation.
The earlier actual c6c01fe7 root CUDA capture remains separate historical evidence.
