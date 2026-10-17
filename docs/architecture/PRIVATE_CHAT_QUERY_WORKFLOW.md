# Private Chat QUERY workflow completion

2026-10-17 UTC. Design before protocol/behavior. This is the missing C4 execution
boundary in the original incremental-RAG goal, not another queue or an activation.

1. Responsibility: admit a distinct fixed private-question application step into
   the existing Runner only after source/claim/control and native admission are
   connected. Define its fixed graph, canonical completion receipt and small step
   output first. The existing Chat owner and Orchestrator retain their authority.
2. Canonical source: the owned immutable user message; existing private execution
   record/result/shard/vector Artifact; original Workflow/step/command allocation.
   Never copy the native input/question into another canonical file or DB field.
3. Identity: preserve Workflow/step, launch Job, Artifact producer Job, receipt
   producer Job and Artifact revision/hash as distinct concepts. Pin the original
   live Chat origin hash separately from the private basis and public query scope.
4. Resolution: supplied closure validation binds actual request/policy/bundle,
   launch, original Chat origin, text-free intent, result and numeric members.
   It checks exact member names/schema/media/raw hashes, shared file-set revision,
   basis and current expectations. It does not prove current authority by itself.
5. Access patterns: fixed two-step DAG and bounded key/hash comparisons. Existing
   unique Workflow/step/attempt and original native Job key remain authoritative.
6. Structures: frozen values and a closed JSON Schema2020-12 resource, registered
   in the existing native resource owner. No table, queue, cache, mutable dispatch
   registry, dependency or generic execution framework is added by this contract.
7. Complexity: O(bounded intent/result metadata), constant graph and member count;
   vectors remain behind their Artifact pointer, not duplicated in the receipt.
8. Transaction: the future submission and RUNNING/allocation commit must preserve
   the existing Workflow→command root fence. Pin the original live origin at that
   boundary; never replace it after expiry, crash or another claim. No SQL root
   spans native work. Completion and replays reauthorize the appropriate live or
   historical owned-source read boundary without reviving expired execution.
9. Dependencies: pure workflow/contracts validate values; existing Orchestrator
   publishes; Runner owns leases/state transitions; infrastructure implements
   current source/Identity/runtime reads. Workers gain no DB/NAS access.
10. Failure/replay: reject cross-family or cross-origin outputs, altered immutable
    pins and malformed nested copies. One native attempt only. An uncertain launch
    retains its original key/history, not another inference or a fabricated success.
11. Simpler alternative: relabeling a private result as the released reference
    application result bypasses its source contract and SQL CHECK. A distinct
    fixed definition/receipt is necessary; copying the entire Runner is not.

The first contract slice deliberately does not enable the compiler's private
dispatch, submit a Workflow, widen the step-result CHECK or create a migration.
Those changes must land with actual source admission/checkpoint execution and
guarded persistence tests. Existing compiler/Runner parsers must still refuse the
private definition until that composition exists. Historical INDEX/reference
schemas, keys, outputs and canonical bytes remain unchanged.

The pure receipt validator takes expected original IDs and origin from its owner,
not from model output. Hash equality or a supplied origin is never a permission
grant. Native result validation reuses the existing private encoder contract; no
tokenizer, scoring, pooling, normalization or binary implementation is introduced.

Required source tests: resource/mirror/hash, strict fixed graph and one attempt,
bool/coercion/extra-field rejection, canonical roundtrip, unvalidated nested model
copies, exact original origin/actor/basis/launch and file-set closure, raw versus
semantic hashes, wrong producer IDs, timestamps, and old parser/compiler rejection.
No model execution or mutating DB test is implied by these pure-value tests.

## Completion publication/read composition — before implementation

Extend the existing `NativeEmbeddingCompletionPublisher`, not a new store. The
private method validates its closed receipt and preallocated identity, constructs
the small output and checks its file-set separation **before publication**. It
then reuses the same protected temporary materialization and existing identified
file-set commit/receipt verification as INDEX/reference. Canonical owner remains
Orchestrator; one local receipt copy exists only at this explicit commit boundary.

The new private key binds original Workflow/step/attempt, not request/origin hashes:
changing immutable intent or claim must conflict with the same original operation,
not allocate another producer through a new key. Existing reference keys/bytes
stay unchanged. Expected work is one indexed unique-key lookup plus one small
receipt file; O(receipt bytes), no corpus/history scan or DB/index/schema migration.
Existing publisher locks/unique constraints and preallocated Job/Artifact identities
own concurrency/recovery. An observation lost after commit requires exact replay,
not model execution, another timestamp or another identity.

Catalog exposes a separate private completion resolver over the existing pinned
Artifact reader. It requires the caller's active nonnested root and no pending
writes; validates exact receipt file set/type/schema/media/raw hash/canonical bytes,
actual approved successful producer and the private output-to-receipt closure;
then verifies the original root is retained. It never resolves an implicit latest
or treats this receipt as current Chat/public-corpus/native admission. Those
checks remain mandatory in the future private owner before execution/delivery.

Existing publisher/reader adapters retain their dependency direction and shared
mechanics; the new values remain pure. No new library, registry or generic
dispatch framework. This publication leaf still cannot submit an unsupported
private Workflow or bypass the old result CHECK. Tests cover actual temporary
file/SQLite readbacks and guarded disposable PostgreSQL concurrent publication,
same-key conflict, interrupted commit and exact replay. Synthetic source/native
fixtures do not establish current permissions or a live Chat tool.

## Contract checkpoint

The distinct packaged schema and frozen definition/receipt/step-output are now
implemented. Schema raw SHA-256:
`694c6043fc7f78f662b01bf05d7d812453efdbdfa400b3b4fcfc85c31f21195a`.
They bind the owner-supplied original origin, actor, basis, request/control/native
launch, text-free execution record and result/shard/binary raw hashes. The three
actual Jobs and the separate receipt versus four-member numeric file sets cannot
be merged. Existing private numeric validation is reused, not reimplemented.

Final related source regression: **402 PASS/74.06s across16 suites**, including
55 new private workflow cases. Earlier50/397 subsets overlap and are not added.
Strict mypy2 production files and Ruff/format3 files PASS. The initial new fixture
failed because it hashed a noncanonical `+00:00` timestamp before the typed UTC
`Z` conversion; the fixture was corrected, not the canonical/hash invariant.

This is **SOURCE_PASS / NOT_INSTALLED / NOT_ACTIVE / C4_NOT_ACCEPTED**. Compiler
and current Runner admission intentionally remain closed; their explicit rejection
is tested. No DB/state/queue or persistence behavior changed, so no mutating DB
test or migration is claimed. No runtime, service, authentication, model or source
policy was changed for this pure contract checkpoint. Actual owner admission,
atomic origin/allocation, completion publication/checkpoint execution and Chat
tool delivery remain necessary, alongside the unchanged full-goal gates.

### Source-candidate packaging

Candidate `fbda1ea7e6df97acbe8c726d2ce0a17ce9351b4c` is committed/pushed and passed
the standard three-wheel build/RECORD gate, without installation or service action.
Dist: `/tmp/eom-api-build/fbda1ea7e6df97acbe8c726d2ce0a17ce9351b4c.Fhla7p/dist`.

- platform raw `35816a9b9a8a226d0dc62d2aa9b6252546ef8c032c57ae4f5e80c0723492dc94`;
- API-contract raw `7d09406e6a9a190db3cfd4863fc06bea4ef6e7aa0fd871c75b5d26c4c8c8f46b`;
- API raw `cf22b0037d2a986cb26d441b0e6364e2fe5323677420c50b45cc3349cc7ec75d`.

An independent Conda `-I -S -B` process imported159 EOM modules exclusively from
the exact platform/contracts archives. It validated definition/receipt/carrier and
all supplied origin/request/native/result associations, and confirmed the compiler
still refuses execution before owner composition. No checkout/test/ML/SQL/HTTP
module or installed EOM fallback was imported. DB/model/activation calls0.
The numerical values and origin are explicitly synthetic, not current authorization.

Proof program and inputs remain under `/tmp/eom-private-query-workflow.Qf8DKy7z`;
proof raw `893533f00c024745ad2b23ea814313a388bed3ccd9f68cfb7c19cf82764bc966`;
synthetic input raw `2da0a8b2f064280b5117c69246f66730a06af3abcca81a1f731315c77ab5082d`.
This closes packaging only; existing operating releases and remaining C4/overall
goal acceptance are unchanged. No new authentication prompt was issued.

## Completion owner implementation — source checkpoint

`NativeEmbeddingCompletionPublisher.publish_private_chat_query` now uses the
existing identified file-set owner and returns the already-defined private output.
Its original key is Workflow/step/attempt only. A changed request, origin, timestamp
or producer cannot escape an existing operation by using a new intent-dependent
key. Output/producer/file-set separation is validated before the commit boundary.
Shared INDEX/reference publication mechanics and their original keys stay unchanged.

`resolve_native_private_chat_query_completion` uses the existing pinned reader in
the caller's clean nonnested root. It reads the exact canonical private receipt,
checks its real successful producer/output association and **revalidates current
provenance before returning**, without rereading large binary data. This is three
bounded indexed metadata reads in the existing reader, not another cache/search
engine. It does not resolve private ownership or public retrieval permissions for
the caller; that remains the actual private owner/admission responsibility.

Final related source regression **397 PASS/86.22s across14 suites**, including24
new completion-publication/read cases and the preceding55 contract cases. Strict
mypy3 production files, Ruff/format5 files, shell syntax and diff checks PASS.
The preliminary141/394 subsets overlap and are not added to this count.

A new negative test first reproduced a late-provenance gap: changing the producer
Job's DB state during materialization was not rejected by the initial read alone.
The new resolver now calls the supported `revalidate_provenance` before delivery.
All three disposable-SQLite corruption variants passed after that change; these
synthetic tamper cases do not claim that approved Artifacts are legally mutable.

The first actual PostgreSQL suite passed54/cleanup, before the additional late
checks. A later run passed55 and failed1/cleanup: its new test tried to modify an
approved Artifact revision. The existing `reject_approved_artifact_mutation`
trigger correctly rejected that test with its original immutable-artifact message.
The fixture now requires SQLSTATE P0001 and that exact guard message, retains the
unchanged readable revision, and separately tests another transaction's producer
state change. No trigger, schema, grant or immutable-history rule was weakened.
Final source-pinned PostgreSQL revalidation passed **56/56, no skips, cleanup
PASS**. Nine new private persistence cases cover concurrent one-producer replay,
lost commit observation, changed immutable inputs/identity at the original key,
late producer-state revocation and the unchanged approved-Artifact trigger.
The native/source values are explicitly synthetic; no operating DB, model launch
or user permission was exercised. Final protected evidence:
`/opt/eom/embedding-benchmark-os-evidence/private-query-completion-accepted-fA7BZQpc`;
test stdout raw SHA-256
`4d33f5bf132c21e2e50143edf37d792972fc22e14f7ed862529998846b0a0444`;
operator helper raw
`a3449e69fa67251c5c4d21489e819d25152fc54e65d8f012592401b8b2243436`.
Earlier54-PASS and55-PASS/1-failure runs and their cleanup evidence remain
preserved, not added to the final test count or reinterpreted as current PASS.

This is not private Workflow submission, result-CHECK admission, actual numerical
execution or Chat tool activation. The old Runner/compiler remains closed, and
no operating service, corpus, original HTTP request, authentication or model
default was changed. Full C1–C5 and CPU/CUDA/default gates remain open.

### Completion owner package verification

Candidate `ab996967616bf1ed84be5e7ed73e154bf81a2d42` passed the standard three-wheel
build and RECORD verification. It was built only, not installed or activated.
Dist: `/tmp/eom-api-build/ab996967616bf1ed84be5e7ed73e154bf81a2d42.NZdqrR/dist`.

- platform raw `7a2d65cc24f89efd139759e65b3155877843abf36e04e5ccd7cfe9edeff5898a`;
- API-contract raw `f0e7f140bde62982175ddef069f78ffc83b223c074dc7885ee2f346de5f2c26a`;
- API raw `8c31ef008c58fa65d2480c67d1c09c514a1249145e43d25a07ba8ead6b61cc19`.

An isolated Conda `-I -S -B` process imported176 EOM modules exclusively from the
exact platform/contracts archives. It exercised the actual new publisher's local
receipt materialization against a clearly synthetic publication port, validated
the exact original typed output and automatic temporary-workspace cleanup, and
imported the Catalog resolver. No checkout/installed-EOM fallback, ML module,
database call, native model execution or runtime activation occurred. This is
not another PostgreSQL gate or actual Artifact publication acceptance.

Proof: `/tmp/eom-private-completion-package.8dTxmLr6/prove_archives.py`, raw
`4852c5a5b32f40ed2e62b637c6cc8283d8049a77e1f9242dfcad828c84a7041a`.
The preceding immutable synthetic values file was reused, not copied. Follow-up
documentation27 PASS includes the24 private unit cases and is not added to397.
No interactive authentication was requested. The user's unattended window is
recorded through2026-10-18 20:01 UTC; it never constitutes login or TTL extension.

## Fixed private CPU execution — design before behavior

The next actual execution prerequisite is a distinct protected CPU entry, not
admission through the released reference QUERY units. Reuse the existing private
input/result schemas, descriptor-only numeric entry, protected handoff primitives
and original INDEX/QUERY CPU-capacity mutex/lifecycle. Keep the reference unit
bytes and its five-member handoff contract unchanged. No new external wire schema
is needed: this is composition of already-defined immutable input/launch values.

Canonical source remains the owned Chat message; the five local control files
are temporary execution materialization, not canonical private-question storage.
Only input.json contains the question, only at the private controller workspace
and root descriptor handoff. Worker namespace receives three fixed descriptors,
not paths, credentials, actor policy or DB/NAS access. Original Job/execution ID,
Workflow/step, launch association, result/shard/binary hashes remain distinct.

Private workspaces and runtime directories, fixed prepare/numeric unit names and
owner environment are separate from reference QUERY. Reconstruct and validate
all five contracts before staging, marking, root transfer or result readback.
Root is checked before reading input; file ownership/mode/symlink/size/canonical
hash checks reuse the existing descriptor primitives. A changed file is rejected,
never overwritten. Result validation binds the exact private input and verifies
the one float32/L2 row before staging the result for Orchestrator publication.

Access is a fixed five-name tuple and one indexed execution directory, O(bounded
input/result bytes + one vector dimension). No DB/schema/index/cache/queue change,
corpus scan, new dependency or broad service authority. The caller must commit
the original origin/command/launch under its SQL fences **before** durable launch
marking. No transaction survives inference. The same existing CPU flock protects
INDEX, reference QUERY, private QUERY and benchmarks; active/orphan unit discovery
must include the private names. A consumed start marker, running/failed/unknown
handle or observation timeout cannot authorize another start or identity.

The typed private adapter is separate because reference rows/input publication
are not private question/intent publication. It reuses shared low-level filesystem,
numeric and lifecycle behavior rather than copying a second queue/Runner or
making mutable strategy registries. Fixed unit templates stay uninstalled until
compatible owner/numerical packages, source admission, policy/ACL and actual-UID
isolation gates are verified. Source tests/synthetic process observations alone
do not activate a Chat tool or establish current user authority. Required tests:
exact/changed controls, owner/root/size/symlink denial, result/hash/vector identity,
resource and mixed-purpose denial, one-start/exact-replay, uncertain/failed
nonrestart, shared capacity and private unit orphan discovery, fixed isolation
templates and original INDEX/reference regression.

### Fixed private CPU source checkpoint

The existing protected root bootstrap and numerical CPU composition now recognize
the explicit `PRIVATE_CHAT_QUERY` owner argument, never a purpose from worker JSON.
Two new fixed private unit templates, five-contract staging/root descriptor transfer,
one-row output validation/materialization and a typed launcher use the existing
handoff primitives, fixed resource checks and shared lifecycle/mutex. The global
active/orphan discovery now includes both private prepare and numeric names.
Reference/INDEX unit bytes and original namespace, hashes, output contracts and
durable dispatch semantics remain unchanged. No model/numerical implementation,
database, queue, protocol, policy permission or dependency was added.

Source regression **494 PASS/86.45s across17 suites** includes the new private
execution tests and original INDEX/reference/owner-release/resource/dependency
gates. One additional handoff→existing Artifact publisher composition case was
then added; the final private suite **46 PASS/26.16s** includes it. Those suites
overlap; do not add their counts. Strict mypy5 production modules, Ruff/format7
files, both fixed systemd unit syntax checks and diff checks PASS.

The first137-case run passed118/failed19. Failures were in new test assumptions:
raw multiline text is escaped in canonical JSON, `CpuHandoffError` is not a
`ValueError`, and the physical start test lacked the required original launch
marker/used the wrong durable dispatch filename. Tests now assert the actual
contract and required marker, without weakening filesystem checks or dispatch
semantics. Extra-row output is rejected by the existing descriptor size guard.
The actual handoff→Artifact composition verifies that only intent/result/shard/
binary are committed through the existing owner; the question input is not in
that file set. That publisher and all native/OS observations are synthetic ports,
not actual user/source/launch authorization or NAS/model acceptance.

This is **SOURCE_PASS / NOT_INSTALLED / NOT_ACTIVE**. No service was stopped,
started or installed; no unit/ACL/polkit/group/credential/default/corpus was changed.
No DB behavior changed in this source slice, so another PostgreSQL run is not
claimed or needed for it. The prior56-case persistence evidence remains scoped
to completion publication/read. Installation must select compatible CPU code and
all controller copies of the shared capacity guard; an old INDEX/QUERY controller
must not race private work using an inventory that predates its unit names.
Current origin/claim-bound private submission/allocation/checkpoints, protected
purpose admission/installation/isolation, numerical execution and Chat tool
delivery remain required; old compiler/Runner admission remains closed.

### Fixed private CPU packaging

Code candidate `db18397e21bf2cda93ce9472bf328e9fcf62d489` passed the standard three-wheel
build/RECORD verification, with no installation or service action. Dist:
`/tmp/eom-api-build/db18397e21bf2cda93ce9472bf328e9fcf62d489.gwSofU/dist`.

- platform raw `361102afaf09c631ad26b081243281d48668d0f00a75ab4b4f88f6f278ae84a6`;
- API-contract raw `42f5799a965144e1a1a18806fb087ddf866a1e24e39826f0f7f4b8b19dc05979`;
- API raw `99a36bb58ca3afcf0725f4fa48307fca44a6661bd54e220403247b8ff6c2b1ab`.

An isolated Conda `-I -S -B` proof loaded176 EOM modules exclusively from the
two exact platform/contracts archives, revalidated synthetic private controls and
the fixed CPU resource profile, staged five real temporary files, replayed them
without inode/byte changes, marked the original launch and checked automatic
temporary cleanup. It also verified the separate private unit names and explicit
numerical purpose dispatch. No checkout/installed-EOM fallback, test/ML module,
DB/native model call, OS-unit observation or runtime activation occurred.
The temporary owner's current UID/GID is explicitly synthetic, not an installed
private controller identity. An archive/import proof is not an isolation grant.

Proof `/tmp/eom-private-cpu-package.793r6xri/prove_archives.py`, raw
`a071be42c6516ddc4a5782a0c28b24580eacae20243d051beddd5deb5b24a06c`.
The prior pinned synthetic values were reused without copying; their controls
were adjusted only in memory to the existing fixed CPU resource contract.
Final documentation/dependency9 PASS overlaps the494-case inventory. No new
interactive authentication was requested; no operating pin was changed.

## Original private Job checkpoint history — design before protocol

1. Boundary: persist four original private phases in existing append-only Job
   events, not another execution queue/table or authorization cache. Existing
   Workflow→command→Job lock order remains the caller's responsibility.
2. Canonical source: the original owned message and captured Chat origin; exact
   private request/launch, allocated producers, observed fixed private units and
   existing numeric/receipt Artifact pointers. No question text or vector bytes
   enter the history. Capture the full text-free origin once at ALLOCATION;
   every later phase and reconstructed receipt reuse that exact original pin.
3. IDs: native launch Job, numeric Artifact producer and receipt producer stay
   separate. Workflow/step/command and current root are not interchangeable with
   an origin hash or an Artifact revision. No new identity on replay/recovery.
4. Resolution: a closed2020-12 schema precedes models/storage. Validate phase and
   hash, original purpose/launch/control/basis/actor, monotonic unit chronology,
   exact private template hashes, four-member numeric file-set closure and exact
   reconstructed receipt/output. Actual current Chat/public-source/native checks
   remain mandatory upstream; a checkpoint is not an execution permission.
5. Access: one indexed original launch lookup and bounded ordered event lookup
   by Job ID/sequence. Four phases form a contiguous immutable prefix.
6. Structures: existing unique launch key and Job event monotonic sequence;
   fixed transition table, frozen typed phase payloads and tuple history.
7. Complexity: O(four bounded metadata frames), no corpus scan or N+1. Existing
   Job-key/event indexes suffice; no DB migration/index/large-value storage.
8. Transactions: allocation and original step-start share the caller root. Each
   append takes the existing Job lock, validates the entire original prefix and
   commits its state/event together. No SQL root crosses file commit or inference.
9. Ownership: pure workflow values own semantic closure; Orchestrator owns
   Job/event storage. Extract only the shared existing reference/private event
   persistence mechanics; retain typed public reference wrappers and exact legacy
   keys/bytes/protocol IDs/errors. Domain imports no infrastructure.
10. Replay: same record is idempotent; changed origin/producers/time/output at a
    used phase conflicts. Reordered/skipped/mixed phases and foreign terminal
    state fail closed. Known physical failure is preserved, not retried; a timeout
    is uncertain, never FAILED or a fresh launch by assumption.
11. Alternative: relabeling private results as reference violates its closed
    schemas. Copying a second Job state machine duplicates lock/protocol/event
    checks. Shared existing storage with typed purpose-specific validation is
    smaller and preserves one transition owner. No mutable plugin registry.

Tests must cover strict/mirrored packaged schemas, every contiguous prefix,
forged model copies, origin/actor/basis/producer/template/file/hash/order changes,
root/rollback, concurrent exact append, conflict and failure-preserving replay in
guarded disposable PostgreSQL. Reference1.0/1.1 bytes and behavior stay unchanged.
This still does not open compiler/result-CHECK admission or install a private
unit; source/claim-bound Runner execution and current authorization are separate.

### Original private history implementation and guarded persistence

The separate packaged checkpoint schema now has raw SHA-256
`52b9d892e9010a923ed287163d60030113f2f03dc19fc79c1f26902e7187ae3f`.
Pure typed history reconstructs the exact receipt from original allocation/origin,
fixed private unit observation and four-member intent/result/shard/binary pointers.
The existing private launcher now emits the typed successful-unit observation,
checking distinct ordered invocations, stable boot and exact private template pins.
It does not derive successful execution from result bytes or start a new unit.

`NativeQueryCheckpointStore` extracts the existing Job lock/protocol/event/state
mechanics for reference and private queries. The original public reference wrapper
retains its typed API/errors, keys and protocol identities; reference1.0/1.1 schema
bytes and private runner/completion schemas are unchanged. The private wrapper uses
the same store with distinct family validation/protocol/events. There is one fixed
transition table, not a second state machine/queue. Reads use the original Job key
and existing `(job_id, sequence)` unique B-tree, ordered and bounded to five rows:
four valid phases or evidence of excess history. Foreign-purpose events are not
silently filtered away. A source SQL-operation test verifies the exact indexed
predicate/order and five-row cap; no new index/cache/migration is needed.

Final related source regression **466 PASS/251.51s across16 suites**, including
original reference execution/admission/submission/completion and private metadata,
actual local SQLite root/rollback/conflict, private handoff and package/dependency
tests. Earlier116/139/subsets overlap and are not summed. Strict mypy7 production
files, Ruff/format11 files, shell/diff checks PASS.

The first new tests exposed fixture errors, not relaxed invariants: hashing an
illegal float before parsing, sealing a `+00:00` timestamp before typed `Z`
conversion, and treating the existing publisher factory's tuple as its publisher.
They were corrected before the final suite; canonical integer-only JSON and UTC
hashing, root and immutable-prefix rules remain unchanged. One mistyped regression
filename caused a no-tests-run invocation and was corrected, not counted as PASS.

The supported guarded `embedding-stage-tests` purpose now includes six private
checkpoint cases. The actual disposable PostgreSQL gate passed **219/219, no
skips, cleanup PASS**, covering the existing213-case cohort plus concurrent exact
private append, one original phase event, exact replay, caller rollback, changed
origin conflict, nested-root refusal and failure-preserving terminal replay.
Synthetic numerical fixtures were resealed and checked against the actual private
receipt contract; they are not current Chat/IAM/native execution evidence.
Production DB/model/service/activation calls0. Protected evidence:
`/opt/eom/embedding-benchmark-os-evidence/private-query-checkpoints-IljUOOv7`;
operator helper raw
`d9a9978a4e946a6b25f947aead96852415b809d925b2895a9cb4367a165017cc`;
test stdout raw
`9ca60bd1596738209c3970a5db7befaa660f40609dad1868c63ad81a4abf0ea5`.
Forty-six exact source/script/test files were pinned throughout that finite gate;
no interactive authentication, retry, production row repair or new model run.

This closes the private original-Job history storage prerequisite, not C4 or the
full goal. Origin/source/claim-bound actual Runner submission/allocation/execution,
private-purpose installation/isolation, current public corpus delivery and Chat
tool activation remain OPEN. The compiler/result CHECK remains intentionally
closed; operating CPU/QUERY/INDEX selections and original HTTP request are intact.

### Original private history package verification

Code candidate `9e96ab1d2e121bea9fcbf535a545df129bfd4e01` passed standard three-wheel
build/RECORD verification without installation or service action. Dist:
`/tmp/eom-api-build/9e96ab1d2e121bea9fcbf535a545df129bfd4e01.jJkT7O/dist`.

- platform raw `6e92546314648e16fcfaa6eec72ea3ec5b7061e205525568ac8d1a21cc01206f`;
- API-contract raw `3b87c8dd44e52c6697751fd9b402f16a0352cd19d139d34b502eb850c09ad6ee`;
- API raw `57dc5dfa162efa10f0ad12f945ff6a2cba0404e50f3620e5b6b83d64b83bf15d`.

The isolated Conda `-I -S -B` proof imported182 EOM modules only from the exact
platform/contracts archives, reconstructed all four synthetic private checkpoints
and their receipt/output, validated every contiguous prefix and imported both
typed coordinator adapters/shared store and fixed private observation adapter.
It made no DB/model/unit-observation/activation call and imported no checkout,
installed EOM fallback, tests or optional ML module. Current source/Chat/native
authorization remains unproven; this is package closure, not another live gate.

Proof: `/tmp/eom-private-checkpoint-package.prmVCKZA/prove_archives.py`, raw
`0daa4a8c3643fcb917f27d1a3ded9421ae6c0954c17bfacd6bb3afde6aec044f`.
The prior pinned synthetic metadata file was reused without copying. Final
documentation/dependency9 PASS overlaps the466-case inventory, not an additional
aggregate. No new authentication prompt or operating selection occurred.

## Actual private executor composition

1. Runner composes the existing current Chat/source/command owner, fixed private
   CPU launcher, shared original-Job checkpoint store and existing publications.
   No parallel queue, storage owner, worker protocol or generic plugin engine.
2. Canonical sources are the immutable submitted origin, exact request/controls,
   original launch and four-phase Job history; local workspace bytes are staging.
3. Native Job, numerical publication producer and receipt producer stay distinct;
   recovery reuses their original allocated identities and source commit.
4. Current source/input is reconstructed under the original Job/query IDs. The
   existing Catalog private numeric/receipt readers check member/revision/media/
   hash/lifecycle/producer closure; the command owner supplies actual permission.
5. Lookups use Workflow/step keys and a bounded five-event original history, not
   scans or a second request tracker. Every replay reauthorizes current sources.
6. Reuse frozen typed checkpoints and manifests; pending is a small internal
   original-launch observation, never a Role/Codex result or retry grant.
7. Metadata/vector checks are bounded O(bytes + dimension), plus the existing
   authorized public scope. Actual model cost is measured separately; no new ML
   dependency or question copy/public enrollment is introduced.
8. Step/allocation commit precedes physical work; no SQL root survives inference
   or unit observation. Commit PUBLISHED before the receipt owner's independent
   commit, then validate and append COMPLETED in the current fenced root.
9. Pure contracts stay below adapters. Runner orchestrates owners; only the
   existing Orchestrator publisher commits validated bytes. Workers still have
   no DB/NAS/network/peer channel.
10. BUSY/UNCERTAIN retains the original prefix. A known failure stays failed;
    lost observations/commits recover by exact checkpoint/publication replay,
    never another Job/key/model run. Completed reads do not require old units.
11. A receipt-only shortcut would omit physical/source provenance; treating the
    question as a reference Item would lie about authority. Reuse the existing
    storage, fixed lifecycle and file readers while preserving distinct private
    source and receipt types. No released schema/migration is changed here.

This implements the actual executor composition before opening compiler, result
CHECK, async routing or Chat tools. Those remain required activation prerequisites.

## Executor source verification 2026-10-17

Concrete source composition now joins the original current-source owner, fixed
private-purpose launcher, existing Job checkpoint adapter, numerical publisher,
receipt publisher and canonical readers. It does not open production admission.

`tests/unit/test_private_chat_query_native_executor.py`:23 PASS, including
four commit-boundary crashes/replay, no SQL root during numerical work/observation,
original launch and producer reuse, known-failure preservation, BUSY/UNCERTAIN,
late permission withdrawal, changed canonical bytes, rollback, exact purpose,
root/engine rejection and completed reads without surviving original units.
Canonical temporary SQL Jobs/Artifacts and files are real; Chat/IAM/public scope,
Workflow/step views, fixed-unit observations and numerical backend are explicitly
synthetic. Tests do not relax the closed compiler or private application-step CHECK.

Final focused inventories are167 PASS/six suites and122 PASS/four suites (the
execution-contract suite overlaps; do not add the counts). The latter includes
the six dependency/large-binary-DB checks and five new redacted raw-parser cases.
Strict typing seven source modules; Ruff/format ten source/test files; diff check
PASS. Initial draft-fixture failures used the older non-fixed resource profile
and wrong checkpoint state/field names; corrected fixtures honor existing fixed
resources and `SUCCEEDED`/`record_type`, with no production rule relaxation.

No PostgreSQL composition claim for this new executor yet; earlier guarded
storage/owner tests do not prove it. No operating DB mutation, model inference,
protected install, private-unit activation or authentication prompt was made in
this source gate. Original HTTP delivery, async ADVANCE lineage, immutable-context
terminal, private CHECK/compiler/routing and genuine Chat delivery remain OPEN.

## Private terminal and asynchronous continuation boundary

The existing Runner remains the sole command/step state owner. Terminal completion
reuses `native_step_completion`, not a second completion service. Its legacy INDEX
and reference final-pointer behavior stays unchanged. Private submission context
is the immutable original source, never a result cache: private terminal success
must leave its exact bytes untouched. The successful private application step,
receipt producer and existing terminal step/history carry the final result.

Required pointers are the original Workflow/step/attempt, canonical receipt and
origin/request controls. The purpose executor reauthorizes current Chat/public
sources and canonical bytes in the caller's fenced root before every completion
or completed replay; the common terminal helper checks identity, closed original
context and terminal shape without inventing authority. Lookups remain indexed
by Workflow/step with bounded history; O(1) metadata state work, no new table or
large payload. The existing Workflow→command lock order, transaction rollback and
append-only events apply. No source/runtime/network adapter enters contracts.

An asynchronous continuation must use the existing ADVANCE command with its exact
step pointer, original actor and purpose-specific source/key. It must prove the
original successful parent command and its allocated nonfailed private execution;
an arbitrary ADVANCE or expired command cannot create a replacement original Job.
One supported continuation per parent key is sufficient; no new retry queue or
worker protocol is needed. Source/lease failures remain failures, not auth refresh.

Opening private compiler/step CHECK/claim routing requires a separate tested
successor and actual release. This source terminal extension alone grants none of
them. Copying a final pointer into private runtime context would violate its
closed contract and existing immutable-origin trigger, so it is not a fallback.

### Guarded executor test correction and terminal source checkpoint

First guarded composition run retained at
`/opt/eom/embedding-benchmark-os-evidence/private-executor-MBLaPcc8`:
244 PASS/1 FAIL, no skips, cleanup PASS; helper raw
`5d1ac294f116c818eb242cb164ccfa977bf5a2172b26f64c042a2df5f4eb5e29`,
test stdout raw `c71377204b59698bcabf3fe88ba6fb2b021a7b5fd9fe8c2fde1e78a589979f30`.
Do not relabel this first run PASS. Its failed expectation incorrectly required a
previously calculated private question vector to fail whenever the public scope
became empty **between requests**. Such a vector contains only the question, not
public document content. Current reauthorization may legitimately produce an
empty candidate scope without recomputing the question or retaining public access.

The corrected inventory separately asserts that empty newly authorized scope,
and rejects a **within-root** public withdrawal between capture and final private
authorization. No production source/permission rule was relaxed to fix the test.
This is not an excuse to return previously authorized document candidates.

The existing common terminal helper now supports the private purpose without
changing its closed submission context. Seven new synthetic terminal cases cover
exact context preservation, replay/current callback, bad origin/actor/request/
extra final pointer and terminal shape. Final source108 PASS/six suites (including
those7, six dependency and five harness cases); separate execution/source-owner51
PASS overlaps historical inventories. Strict10/Ruff/format15 PASS. An initial
terminal mock incorrectly forwarded the repository-only `max_attempts` argument
to an ORM row; it was corrected without changing repository/model constraints.

Latest exact95-pin successor at
`/opt/eom/embedding-benchmark-os-evidence/private-executor-final-y6cLrgey` completed:
**246 PASS/no skips/cleanup PASS**, including11 private composition cases. Helper
raw `2888b03f857a4e31a771769a07e02380e7ddac5f27c68cf15f3bd92bd9186f97`;
test stdout raw `12fabc13c7a8ac6ac5422e0e9cf08da441c3576b6787ccb678b289894d190121`.
Final source108 PASS and strict10/Ruff/format15 above cover this source snapshot.
Published controls/registered index/Job/event/Artifact SQL and files are actual;
Chat/IAM/public population/Workflow views/unit observations/numerics are synthetic.
The fixture's between-request scope is demonstrably empty; within-request late
withdrawal refuses delivery. No production admission is inferred from either test.

Original failed evidence and both completed cleanups are preserved. No operating
DB/model/installation/private claim or Chat tool activation occurs in either gate.
Actual private Workflow SQL terminal admission, async routing and consumer delivery
are still required. Operating migration remains the last verified0055; source
head0056 is unchanged and no new migration is introduced here.

## Original continuation and queue-family integration

1. Existing Runner repository owns FIFO selection/claim; the private owner owns
   current source/Chat authority. A separate PRIVATE_CHAT_QUERY family prevents
   private or malformed markers from falling into ROLE, INDEX or reference QUERY.
2. Canonical continuation proof is the original Workflow/START, immutable origin,
   original native launch/checkpoints and current actor; queued metadata alone
   grants nothing. Native/result/source hashes keep their separate meanings.
3. Existing ADVANCE payload contains exactly its original step-run ID. Its trusted
   pending key binds that step and the predecessor command, not another model run.
4. Current and predecessor command payload/source/actor/fingerprint must match;
   predecessor must be SUCCEEDED. The original successful START and original
   launch/generation are also checked. A pending parent never grants its child.
5. Access is bounded PK lookups plus the existing original Job's bounded history;
   no recursive chain scan, new queue, event tracker, cache or question copy.
6. Existing command unique key, Workflow→command locks, lease generations and
   original native allocation own concurrency. One pending child per parent key.
7. Catalog/current identity and physical launcher admission stay separate from
   candidate projection. Reclaim/replay reauthorize, never reuse an old grant.
8. Private submission context remains immutable. Failed original history cannot
   be replaced through a fresh continuation or another key; uncertainty retains
   the same original launch and one physical attempt.
9. Purpose-owner interfaces live above contracts and below Runner composition;
   repository must not import the concrete owner that itself uses repository.
10. This uses existing closed request/ADVANCE contracts. No released schema or DB
    migration changes here; private definition/result admission remains closed
    until complete Runner/step support is tested. No operating activation follows.
11. Treating private markers as generic INDEX is simpler but routes a user's
    question through the wrong authority. Parent-key-only checks without original
    source/START/launch closure are likewise insufficient.

### Continuation/step source checkpoint

The working tree now has the private queue-family quarantine, typed owner port,
original START/ADVANCE linkage and a private Runner step/terminal use case. The
existing Runner default remains the prior three families; it explicitly refuses
private execution until complete composition/admission is offered. At this exact
database-gate snapshot the compiler, private SQL result CHECK, definition admission
and operating release remained closed. Separate subsequent compiler staging is
recorded below; it is not inferred from this gate.

Source244 PASS/11 suites includes20 original-lineage,12 routing and16 private-step
cases, existing native/role/preclaim regressions and six dependency checks. Those
subsets overlap this inventory, not additional aggregate counts. Six separate
harness cases also PASS. Strict6/Ruff/format12 PASS. Step progression includes
source resolution before state writes, atomic initial allocation, no SQL through
execution, immutable context, original-history pending checks and actor/result/
rollback negatives. Its owner/step/physical seams are synthetic; no actual private
Workflow admission or execution is inferred.

First dual DB gate retained at
`/opt/eom/embedding-benchmark-os-evidence/private-lineage-sVZncBXF`:
embedding81 PASS/cleanup PASS; stage233 PASS/16 FAIL/cleanup PASS. All16 failures
were in the empty-history/inactive-definition migration fixture after three new
continuation fixtures had committed declared private Workflows. Reordering alone
is insufficient: the migration fixture also commits an intentionally inactive
different definition. Do not delete/rewrite immutable history or loosen guards.

The correction puts continuation/declared-owner cases in the existing embedding
owner-purpose DB; empty-history migration cases remain in the separate stage DB.
A source harness test pins that separation. This introduces neither a testing
purpose nor another queue/framework. The exact104-pin successor at
`/opt/eom/embedding-benchmark-os-evidence/private-lineage-final-0b3I53Ri` completed
with84 PASS and246 PASS in separate fresh databases, zero skips and both cleanups
PASS; independently read back2026-10-17 23:30 UTC. Source files were held unchanged
through termination. Cohort stdout raw hashes:

- embedding84: `e60d04899056d8832d32bb61156657661fbef8f14c315a88e7dd8a25c4024ff6`.
- stage246: `911d1ad6c8da6791d5fa2ddba0b8f7c12fe290b7f617e7d22543de47fc5906d6`.

Helper raw `174cff705eae6ad57b7fd00d59db73813e8164975288e976bd92d7d68fb01013`.
Earlier failure and both cleanups remain preserved. No production DB, model,
installation, API or Chat tool activation occurs in these gates.

### Fixed private compiler staging — after the guarded snapshot

The compiler now accepts only the existing closed private1.3 graph and calculates
its own canonical hash and `private-chat-query/1.0` execution protocol. Revalidation
rejects unvalidated model copies, altered purpose/role/attempt/terminal/extra
authority. Definition import can stage it inactive and report the correct protocol;
it does not add the key to static admission or enable Runner's private family.
No released schema bytes, role capabilities, SQL CHECK, migration, execution policy
or operating installation changed. Existing native INDEX/reference and role paths
keep their semantics.

This compiler work was first tested in a detached development worktree while the
104-pin PostgreSQL gate was still using main's frozen inputs:127 tests/5 suites,
strict4/Ruff/format6 PASS. Main changes were applied only after that gate terminated.
The PostgreSQL evidence above therefore covers its earlier exact snapshot, not an
unexecuted combined compiler/persistence gate. Combined main source regression:
371 PASS/16 suites, strict8/Ruff/format17/bash syntax/diff PASS. That inventory
includes the earlier244 and compiler/workflow cases plus the separate harness;
overlapping historical counts must not be summed into additional coverage.
Real private owner/executor composition,
supported submission/claim/advance and application-step persistence admission are
still needed before deployment; C4 and the original full goal remain OPEN.

## Next complete admission boundary

The next change must join compiler, private application-step persistence and
actual Runner composition before offering new work. Closed private1.3 definition
and native request/receipt schemas already exist; do not change their bytes or
reuse reference/index purpose identifiers. Compiler support alone does not admit
new jobs. The exact key/version/protocol admission entry is added only with the
paired owner/executor, submission, claim, advance and terminal paths tested.

Canonical source remains immutable Workflow definition/request/context and its
original native Job history. Existing IDs/member pointers and hashes are reused;
no new queue, registry, worker protocol, storage format or binary DB column.
Dominant operations stay indexed FIFO/PK/step lookups and bounded original history.
The private step CHECK successor permits only the exact private application key,
schema, role-null and attempt1 tuple, preserving the existing null/legacy branches.
Its downgrade refuses retained private step history before DDL instead of changing
rows. Existing Workflow→command locking, unique step/key constraints and the
private context immutability/turn index remain authoritative.

Repository/Runner owns state transitions, while current Catalog/Chat and physical
launch stay at their independent adapters. Current authority is rechecked before
and after mutations; no SQL root crosses numerical work. Existing definitions
and failed histories keep their meaning, and pending reobservations reuse the
same allocation. A generic-role or INDEX fallback would violate those boundaries;
hand-creating private rows outside supported submission would skip concurrency
and source checks. Staged compiler/persistence support remains source-only until
the compatible installed composition and actual release gates are satisfied.

### Explicit Runner composition before admission

The next Runner change uses its existing constructor and native transaction
adapter, not a separate scheduler. Private owner/executor ports must be paired;
explicit private-only processing requires both and cannot borrow role/INDEX/
reference ports. The existing default family selection stays unchanged. Candidate
readiness uses the exact private request and its physical adapter; claim keeps
static admission and current-source/lease checks separate. Loaded private graphs
dispatch only to the private step/terminal use case, with original request/actor/
command identity checked before progression. Current source errors are mapped to
stable redacted workflow errors, not question content or adapter tracebacks.

The existing Workflow→command short-root fence is reused for every private
mutation and lease renewal; numerical execution stays outside SQL roots. Replay,
pending, failure history and immutable context use the existing private owner and
step implementation. Dominant access patterns remain PK/FIFO/step-map and bounded
original Job history; no DB schema/index, queue, protocol or mutable registry is
added by this composition. Static admission/private SQL CHECK and actual installed
configuration remain closed pending their paired changes and verification.

#### Runner source verification —2026-10-17

Explicit paired ports are now passed through production composition and exact
claim, readiness and private mutation roots. The private graph dispatches to its
own application/terminal use case and preserves original context on replay. The
private-only constructor does not create a Codex role executor; old default family
selection is unchanged. An unavailable private candidate does not starve ready
existing INDEX work, and private data under a public family cannot borrow its
readiness/authority. Original FAILED/CANCELLED work is not revived.

Combined final source417 PASS/18 suites, strict4/Ruff/format4/diff PASS includes31
new Runner cases. Earlier144/six-suite and prior371 inventories overlap; they are
not additional coverage. The draft119 PASS/8 FAIL is preserved in the test record:
six new readiness fixtures used a plain Mock as a context manager, and two old
constructor-bypassing fixtures omitted the new explicitly initialized None ports.
Only fixture context/initialization was corrected, not source or lease rules.

The test runs real Runner dispatch, private step/terminal orchestration and command
state transitions, but SQL roots, current IAM/Chat/source and physical executor
seams are synthetic. It is not actual PostgreSQL private-step, protected-runtime
or user-tool acceptance. No migration, DB CHECK, definition admission, source/
execution policy, model, operating service, login or runtime activation changed.
Actual supported atomic submission, private step CHECK successor and installed
private owner/executor/tool composition remain required; the full goal is OPEN.

#### Runner archive verification

Source candidate `5484e83004883a886d0b37794aac58f269f01fab` (tree
`ad41d361f93a0f3d31bde8d0ab31e8ddbd5bda52`) passed the standard three-wheel build
and RECORD gate. Build-only output:
`/tmp/eom-api-build/5484e83004883a886d0b37794aac58f269f01fab.eOrcAG/dist`.

- platform raw `3abc6a56765cfa1069f68bb749db0a43af4de6d5a166bb3f0a563af8fe4495cc`;
- API-contract raw `a4df5477295d7ea64bfcc9d4f2f15598d55c0ea6ec1dc9cdd77ee3dfbae0a308`;
- API raw `584003b80954fe30a32aed2e7c4030df9e56242060a6e8b3d719f3190c207e30`.

Separate explicit Conda `-I -S -B` archive-only proof imported395 EOM modules
exclusively from the exact platform/contracts archives, including Runner, production
composition and private owner/executor/step adapters. It compiled the synthetic
fixed1.3 graph, verified paired-port signatures/unchanged default families and
retained closed private definition admission. No tests/checkout/installed EOM or
optional ML fallback was imported; DB/model/unit observations/activation calls0.
This verifies package dependency closure, not actual private submission or runtime
authority. Proof script:
`/tmp/eom-private-runner-package.PyGehQxA/prove_runner_archives.py`, raw
`14ef637595e5b1dd02814a91e52bdbf4a0cf1dcd3ba0a69c5170ecc5446046f1`.
