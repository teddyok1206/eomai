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
