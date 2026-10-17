# Owned Chat query basis for auxiliary similarity

2026-10-16 UTC. Protocol-first implementation boundary; **NOT_ACTIVE**.
This is one concrete part of the original [five-consumer plan](SYSTEM_RAG_SIMILARITY_CONTEXT_IMPLEMENTATION_BOUNDARY.md#3-query-basis-by-consumer--all-five-remain-required),
not a substitute for authenticated C1, variation/authoring/review integration or
the required CPU/CUDA comparison. It does not activate a Chat tool or query worker.

## Responsibility and canonical source

The current similarity request accepts an approved reference Item only. Chat terms
or an arbitrary reference cannot truthfully stand in for the user's actual question.
Add one closed `system-rag-private-chat-query-basis/1.0` value, before behavior.
Do not add speculative authoring/draft variants to an unused generic union.

Canonical source is the existing Orchestrator-published user-message Artifact and
the existing owned conversation/turn relationship. Support only registered stored
message schemas1.0 and2.0, with exact `chat/evidence.json`, JSON media and raw SHA.
The logical conversation and turn, immutable Artifact/revision/member, raw message
hash, exact projected-text hash and basis semantic hash remain separate.
No new message copy, revision table, source enrollment or public index binding.

The fixed recipe uses **only the exact user text**. Preserve spaces, numbers,
negation, units and Unicode; do not inject assistant replies, previous turns,
grounding selections or the model's inferred solution. Empty/NUL/oversized text
fails. Text length follows the existing16000-character submission limit. Query
token overflow remains a later explicit encoder failure, never silent truncation.
There is no approved Item, accepted solution report or Evidence claim on this value.

## Authority and resolution

The existing conversation owner resolves a single turn using its public repository
and Artifact read ports. Actor identity comes from existing authenticated owner
composition, not the basis/model. Before reading, require an active actor and exact
conversation ownership, then an indexed turn lookup belonging to that conversation.
Resolve the registered schema family; verify pointer/schema/media/member/raw hash,
canonical bytes, conversation/turn/user role and projected text. Read one member,
not the whole conversation or assistant output.

After materialization, use a **new** read snapshot to recheck active actor,
ownership and the original immutable message pointer. A stale repeatable-read
transaction is not a revocation fence. Missing/other-owner turns share the existing
NOT_FOUND error; revoked actor, malformed/dangling/hash/schema content fail explicitly.
No source-role impersonation, ADMIN grant, direct Catalog DB read or worker NAS read.

This read does not authorize retrieval against the public corpus. Actual query
admission and result delivery must still enforce the same operator/session and
released purpose policy, exact Graph/index/model/recipe pins and current source
permissions. Follow-ups reauthorize the exact original basis, not latest. Future
query publication must recheck this private source again. A returned text projection
is temporary bounded owner materialization, not a persistent cache.

## Access patterns, concurrency and failure

Use existing PK/index lookups: operator, owned conversation and turn, then exactly
one Artifact member. Work is O(index lookups + message bytes), bounded256000 bytes;
space is one bounded message and its text. No history scan, N+1, new index/migration,
queue, transaction mutation, cache or registry. Existing read snapshots own DB
consistency; no DB transaction remains open during Artifact materialization.
The second snapshot closes revocation/pointer races at this read boundary.

Contract/domain imports remain pure; Orchestrator application owns authorization
and its existing repository/evidence adapters. New basis DTO has no actor, role,
path, answer, model or authority fields. No dependency is added. Errors do not
contain private text. Repeating a read derives identical bytes/hash without a Job,
claim, Artifact commit or encoder launch. Failure does not retry/re-key/alter a turn.

The simpler approved-reference route remains useful when labelled as such, but is
insufficient for semantic search of the actual question. A new database or full
copy of chat history is unnecessary because immutable message evidence already exists.

## Tests and remaining connection

Test schema/Pydantic raw-value closure, canonical/hash determinism, forbidden extras,
supported stored-message families, wrong role/conversation/turn, raw hash mismatch,
empty/NUL/oversized text, copied/constructed invalid values, no ML/infra imports in
contracts, and pointer-oriented output. Owner tests must exercise missing/foreign
turns, inactive actor, pointer/ownership revocation between reads, exact replay,
one-member materialization and absence of DB/Artifact changes. Persistence fixtures
are permitted only through the guarded disposable PostgreSQL route.

Remaining, not implied by basis validation: private-basis similarity context and
read DTO successor, actual production QUERY/session admission, fixed native request
derivation, public corpus reauthorization, owned-turn tool/worker delivery and
operating activation. Existing approved-anchor schemas and native numerical
contracts are not widened by this leaf.

## Source checkpoint —2026-10-16 UTC

Implemented one concrete closed basis and the optional
`general_chat_similarity_basis.read_owned_private_chat_query` owner application.
The only input bytes come from the existing Chat Artifact port after owner/turn
checks; message family resolution is checked against the original immutable hint.
The result carries a small basis plus one temporary text projection. It performs
no publication, enrollment, claim or encoder call and exposes no HTTP/worker tool.

Canonical schema and package mirror raw:
`589521cd1ed918569c41f149eb224376172c493a97b00b256c39cbfa5367b145`.
Existing approved-reference schemas, numeric modules, runtime configs, source
policies and deployed services are unchanged. No new dependency or DB migration.

Source regression across new contract/owner reads, old context/query contracts,
Chat owner, schema resources, original design and layer/version checks:220 PASS
in18.60s. Focused74 overlaps and is not added. Strict mypy2, Ruff/format7 files,
shell syntax, repository boundary and diff checks PASS.

Actual disposable PostgreSQL head0055 and existing Chat publication/ownership
integration:59 PASS in19.27s, including five new cases covering both message
families, exact replay without Job/Artifact/turn mutation, indexed turn reads,
foreign/missing turns and actor revocation committed during materialization.
The first run had two assertion failures because the test assumed an explicit
`app.` SQL qualifier while the existing repository uses its protected search path;
the test now inspects the actual SQLAlchemy Select/table, preserving the required
PK predicate and four lookup count. Production authorization/read rules were not
weakened. Both observations are retained, not rewritten as an initial PASS.

Guarded test DB:`/tmp/eom-api-testdb-20261016112100_d26cd21a`; its existing
`chat-tests` purpose includes the new suite. Logs are bounded operator evidence
under`/tmp/eom-cpu-host-successor-Z1YMaK2I/private-chat-query-*`. These fixtures
use local synthetic artifacts and zero model inference, not real-user/RAG acceptance.
Operating C1 authentication, all consumer activations, coverage and CPU/CUDA gates
remain open; this leaf is **SOURCE_PASS / NOT_ACTIVE / C4_NOT_ACCEPTED**.

Candidate`f92b6db93573e3ed1ae24a22af020885f379ecf3` subsequently passed the existing
three-wheel build/RECORD/contract inventory. A separate isolated two-wheel proof
imported190 EOM modules **only from the exact platform/API-contract archives**,
without checkout or installed-prefix fallback. Both message families and the new
resource/model roundtrip passed; optional ML imports, DB/model/activation calls0.
Platform raw:`66ceac1681ebe149ddcee89b6f4ad61ddba222d4ed0a6c909b788cef31a516cd`;
API-contract raw:`28c5d41dc1f3eadf16a6819ec2fece0e68c4308e5c513c4d6cf86f620a30632d`.
Build path:`/tmp/eom-api-build/f92b6db93573e3ed1ae24a22af020885f379ecf3.rsDamC/dist`.
The guarded disposable database/roles were removed successfully; no operating DB
was a test target. This candidate was not installed or activated, and existing
INDEX/QUERY/API/Catalog releases were left unchanged.

## Next boundary: distinct private-query numerical input/result

The released approved-reference input/result must not be relabelled to accept a
private question merely because their numerical fields look compatible. Add a
closed `embedding-private-chat-query/1.0` input/result schema before behavior.
One input pins the exact private basis, parent context-request hash, complementary
QUERY/DOCUMENT spaces, **document** projection recipe, one CONTENT_ONLY text row
and configured batch/thread recipe. One result pins those identities and one
normal validated QUERY shard. The document recipe describes the candidate index;
it is not a claim that a user question has an accepted solution report.

Use the existing generic row/space/shard value objects and the SAME numerical
backend check, one `backend.encode(..., purpose="QUERY")` and float32 packer.
Do not implement a second tokenizer, pooling, prefix or normalization algorithm.
One actual row retains the configured batch size (for example4), not batch1.
The private basis hashes raw UTF-8 text; the existing encoding identity hashes the
canonical JSON string. Keep those distinct hash domains and test their closure.
The source owner checks that its exact question agrees with both, without trimming,
summarizing, generating facets or adding assistant/history text.

The preparation function accepts an already owned projection and an exact pinned
CONTENT_ONLY index selection. Reject absent index, invalid/copied basis, changed
text and unoffered view locally. Actual backend model/runtime/batch/thread closure
is checked before and after encoding. Canonical index/space/document-recipe
resolution remains the owner's mandatory check, not something a pure builder can
prove from a pointer alone.
The parent context hash is an association, not proof that the parent exists or is
authorized. Actual private-context/Workflow admission must resolve/revalidate that
parent and its operator/session/purpose before staging or launching this envelope.
Neither DTO parsing nor a synthetic backend call supplies that missing authority.

Ownership and source/Artifact identities remain with the existing Orchestrator;
native code receives a bounded temporary text materialization and returns local
binary/metadata only. No DB, source binding, index mutation, persistent private
query cache or new queue. Operations are one key/hash check, one text-row projection
and one bounded sequential numeric pack; metadata work O(text bytes + dimension),
neural encode cost is separately measured. Existing locks/leases/commit and later
admission own execution concurrency/idempotency, not this pure leaf.

The old reference parsers/worker entry continue to reject this distinct schema.
No CLI/installed unit/owner will execute it until a compatible private-purpose
successor explicitly admits it; no old approved-reference policy is widened.
Tests cover exact typed/hash/row closure, strict predecessor rejection, genuine
QUERY purpose, actual backend mismatch before/after encode, row count and malformed
vector failures, deterministic binary/hash, safe errors and no DB/ML imports.
This is a necessary internal execution boundary, not C4 operating acceptance.

The source-only native library connects that distinct envelope to the existing
protected three-FD handoff: one bounded canonical input, initially empty separated
result/vector descriptors, input/output epoch checks, binary fsync before result,
and the same stdlib-first UID/profile/capability guard. Share canonical input reading
across the real INDEX/reference/private cases instead of copying the parser. Do not
add a generic dispatch registry or a request-selected executable/path/purpose switch.
No production main, fixed unit, launcher or policy grants private-query admission.

### Numerical/FD library source checkpoint

The distinct `embedding-private-chat-query/1.0` schema and byte-identical package
mirror are pinned raw:
`50feda7efee0617663def17ab3684afba2580769c1a6454518d042520f75b75b`.
The owned projection now builds the exact input, and the existing encoder adapter
returns a dedicated private result through its SAME backend verification and shard
packer. Existing numeric module implementations (float32 codec, host L2 and offline
encoder) are unchanged; native prefix/config/space was not replaced or activated.

The source private library writes only inherited local descriptors, with binary
fsync before canonical result. INDEX/reference/private readers now share the
bounded canonical parser; source-specific schemas remain strict. Old reference
parsers AND the old reference FD entry reject the private envelope before backend
construction. Its separate entry uses the same stdlib-first actual identity guard;
no CLI mode, installed unit, native session capture or source policy was added.

Combined regression:441 PASS in23.67s across15 suites, covering the new private
contract/projection/numerics/FD leaf, previous Chat basis, INDEX/reference encoders,
FD/identity controls, schema resources, common context, reference preparation, Chat
owner, original-design/layer checks and README/version documentation. Focused222
overlaps and is not added. Strict mypy6, Ruff/format11 files, repository/diff checks
PASS. Synthetic backends and explicitly synthetic UID captures supply test data;
real temporary FDs exercise input/output modes/epochs, duplicate JSON, wrong
protocol, mutated input, binary order and descriptor cleanup. These are NOT actual
model/GPU, root-unit, session/policy or private-context acceptance tests.

The earlier59 guarded PostgreSQL ownership-read cases remain historical evidence
for that unchanged read behavior. No DB/state/queue/persistence behavior changed in
this numerical/FD leaf, so no mutating DB test was rerun or skipped as a fake PASS.
No new dependency, public corpus entry, query cache or production mutation occurred.
Bounded source/test logs:`private-chat-query-encoding-focused.log`,
`private-chat-numeric-library-{regression,type,boundaries}.log` in the existing
temporary operator directory. Full goal/C4 remain **NOT_COMPLETE / NOT_ACTIVE**.

Candidate`1cfe5686d1bea78a66e5611fe4ac74540872a2a2` passed three-wheel build,
RECORD and contract inventory. Exact platform raw:
`fa5d4bffd988d85b8ed69673394a8e1da76445ef07c0b0b92ad864c1aa1929a4`;
API-contract raw:`2928b36c752c8a11a3d184ceaf2e61a538bf5c47b417562f7d9bcc699920cde2`.
The new code remains uninstalled; older operating INDEX/reference services retain
their exact source/config/permissions and do not accept private-question input.

Independent isolated proof imported200 EOM modules from those two exact archives,
with no checkout/installed-prefix runtime fallback. Explicit checkout test fixtures
provided only synthetic input/backend data. One synthetic QUERY encode passed
private input/result/shard/binary closure; real model/DB/activation calls and optional
ML imports0. Packaged private library entries/resources are present. This does not
prove actual UID/unit/source admission or a usable Chat tool.
Evidence:`private-chat-numeric-library-release-build.log` and
`private-chat-numeric-library-owner-pair-proof.log` in the existing temporary directory.

Actual Workflow connection also has an explicit remaining persistence boundary:
the current `workflow_step_runs` CHECK admits only the released INDEX/reference
application result schemas. A private result must not be mislabeled as one of them.
Before admitting a private Workflow, define its exact context/policy/check/output
successors and corresponding guarded migration through the existing Runner queue.
No CHECK, DB head, runtime or source policy was changed by this source library.

## Private similarity context and common candidate composition

Define a distinct closed `system-rag-private-chat-similarity/1.0` request/context
before its read behavior. Request pins the private basis, Graph/policy and one
CONTENT_ONLY index/recipe, source classes, maximum sources and top-k. No actor,
raw question/history, fake approved anchor or unsupported metadata filter enters
the wire. A private numeric input must derive from THIS exact parent, basis and
index selection, not an arbitrary parent hash. Existing reference schemas stay strict.

The result carries approved candidate pointers and independent vector observations
only; it does not fabricate a Graph Evidence receipt or an approved-left-profile
model comparison. Existing GraphRAG/textbook tools keep their separate evidence.
All authorized documents may be scored, including1024: there is no approved query
Item to subtract. Coverage inherits the existing denominator rules with this one
explicit scored-count successor. Missing public reports, missing vectors and
bounded population remain separate. Mandatory limitations identify the single
private message, auxiliary-not-Evidence and not-equality/approval score meaning.

The common Catalog application reuses official registry read DTOs, source-binding
closure and the existing exact float ranking function. Extract the current
document-read check behind a small typed scope Protocol for both real consumers,
not a second search engine or public/private fake-anchor conversion. Owner ports
must supply actual owned-message projection, current authorized population,
committed private QUERY and exact index rows; absence fails closed. Reauthorize
both private basis and full public population immediately before result delivery.
The read is not publication, enrollment, execution admission or an authority cache.

Use maps by source/profile/encoding and one bounded O(Nd + N log N) exact ranking pass. Result
order uses full precision with the existing tie rule; rounded millionths are
display only. Scope hash and ordered source/profile sets are deterministic. No
new queue/cache/table or DB write; future private Workflow CHECK/migration remains
an explicit separate dependency. Orchestrator owns private source materialization
and Artifact commit, Catalog owns current source/index authorization, pure contracts
own exact values, and adapters implement those interfaces. Fake ports in unit
tests never establish operating permission/source/native acceptance.

Tests must cover single/all1024 candidates without false self-exclusion, partial
coverage and unavailable/no-query states; stale/foreign basis/index/QUERY/hash;
full precision ranking; last-moment revocation with zero candidate/count leakage;
forbidden fields/old parser rejection and exact parent-to-native derivation.
This stage remains uninstalled until actual owner/session/policy/Workflow wiring
and appropriate real-source/isolated-DB gates are verified.

### Context/composer source checkpoint —2026-10-16 UTC

Implemented the distinct request/result schema, private application read ports and
candidate composer. Canonical schema and package mirror are byte-identical, raw:
`884bc8b9d873746ffea5cfb5042859a61eaa5942a8f488f4fc3d2d76db14d586`.
The owned query builder now accepts this typed parent rather than a free parent
hash/selection pair. It rejects a changed private basis before numerical execution.
No released predecessor schema bytes or native policy/configuration changed.

Both actual source implementations use one extracted source/profile/report and
document-binding/index validator. The approved-reference use case retains its
anchor exclusion, Graph channel, purpose restrictions and output meaning. The
private composer includes every authorized binding, uses the same exact floating
ranking and only emits CONTENT_ONLY vector observations. It requires explicit
owner ports for owned-message resolution, official population/index reads,
committed private QUERY result and fresh private/public reauthorization. This is
not an implemented production adapter or a default grant to read private Chat.

Combined source regression:516 PASS in46.04s across17 suites. New private context
suite48 PASS in13.89s includes a synthetic1,024-binding composition with one reused
immutable encoding row, deterministic rank/ties, exact replay, explicit unavailable
index/query/overflow, missing reports versus missing vectors, empty/truncated
scope, stale/duplicate preparation, native/result/shard/raw-hash association,
foreign/duplicate index reads and late authority revocation with no disclosed
counts/candidates/execution. Fixture-local fabricated owner values test application
composition only, never actual source authorization or registration. The earlier
89-case focused subset and79-case legacy regression overlap; do not add them.

Strict mypy6 source modules, Ruff/format13 files, original-design/previous-version
and layer checks, repository boundary and diff checks PASS. The first focused run
was41 PASS/1 FAIL because a fixture still expected only ValueError after the typed
parent began rejecting an invalid view at JSON Schema validation. The test now
accepts that stricter SchemaError too; no validator was weakened. Initial type
annotation/format findings were corrected before the final gates. Logs are retained
under the existing temporary operator directory as`private-context-*`.

No DB schema/state/queue/persistence or production/runtime behavior changed;
previous guarded59 PostgreSQL ownership-read cases remain historical evidence,
not a new DB test execution. New dependency, production model/HTTP submission,
Artifact commit and activation counts are all0 for this source change. Existing
INDEX/QUERY/API/Catalog services remain on their independent installed releases.
Remaining: private Workflow context/policy/result CHECK and actual admission,
Orchestrator/Catalog/session adapters, native execution, tool delivery, installed
release and real-source acceptance. Full goal/C4 remain**NOT_COMPLETE/NOT_ACTIVE**.

Candidate`324bb973e8ecc56f8417690f7a96a8310933ca52` passed the standard
three-wheel build, RECORD and contract inventory. Platform raw:
`3699b276c942086cd5d599984b141fda97723c8e6cf8d79b2144f634a75cba37`;
API-contract raw:`870bd72daba496ad33a70dbd2576b5559125ed80777f4111fd174eeab39141ec`.
Build path:`/tmp/eom-api-build/324bb973e8ecc56f8417690f7a96a8310933ca52.MgZDms/dist`.

An isolated two-wheel proof imported211 EOM runtime modules exclusively from those
exact archives, rejecting checkout or installed-prefix fallback. Explicit synthetic
test fixtures supplied input/backend/owner values only. Two synthetic QUERY calls
in total covered the prior numerical leaf and one private context with all three
candidate sources; request/result/member/binary closure and serialized roundtrip
passed. Real model/DB/HTTP/activation calls and optional ML imports0. Package proof
does not authorize a real private source or native unit. Evidence logs:
`private-context-release-build.log` and`private-context-archive-proof.log` in the
existing temporary operator directory. No installed service changed.

## Private execution intent and control closure — before implementation

1. Boundary: connect the owned-message projection to a distinct private QUERY
   execution intent. Reuse the existing Orchestrator preparation function, native
   numerical contract and shared runtime/resource values; do not borrow an
   approved-reference execution policy or add another search/queue framework.
2. Canonical source: the immutable owned user-message basis and exact private
   context request. This step validates supplied values, not current ownership,
   session, Graph permission or installed-runtime admission.
3. Identity: add closed private-chat-query-workflow-request/1.0 and
   private-chat-query-execution-policy/1.0. Keep original request, context, basis,
   policy semantic hashes and policy member raw hash separate. Existing reference
   request/policy/schema bytes and meaning remain unchanged.
4. Resolution: require one CONTENT_ONLY pinned index, exact QUERY/DOCUMENT spaces,
   document recipe, storage partition, model/runtime bundle and resource recipe.
   Validate native input against this exact parent and private basis, including
   batch/thread settings, before any later dispatch.
5. Access pattern: bounded typed key/hash equality and one owned text projection;
   no corpus scan, DB query, Artifact read/write or network operation is added.
6. Structure: frozen values and the existing packaged schema registry. No table,
   cache, index, mutable registry, migration or authority field from the model.
7. Complexity: O(context metadata + bounded question bytes), one native row and
   at most64KiB execution metadata. No claim of measured inference improvement.
8. Concurrency: existing owner/claim/lease/atomic allocation remains the future
   admission boundary; this pure preparation cannot submit, retry or allocate.
9. Ownership: workflow/contracts own closure; Orchestrator prepares native input.
   Share runtime-bundle numerical closure with the real approved-reference path
   through one pure function, not cross-imported infrastructure or a fake anchor.
10. Failure: malformed/cross-bound values fail before preparation returns. A
    copied private basis, changed recipe/partition/model/runtime, policy pointer
    or resource setting cannot reuse another execution. Errors contain no text.
    Current authority must still be rechecked by the eventual admitted owner.
11. Simpler alternative: passing free batch/thread parameters or a bare parent
    hash loses the execution-policy association; relabeling a reference policy
    contradicts its source contract. This narrow typed preparation closes that
    association without prematurely admitting an unsupported Runner result.

This stage does **not** admit the new Workflow, widen the existing step-result
CHECK, select a runtime, publish a private result or expose a Chat tool. Actual
admission/receipt/atomic allocation/native execution and current-user delivery
remain necessary before C4 can be marked active. They will use the existing
Runner/Orchestrator boundary; no rejected old result is reinterpreted as private.

### Execution-intent source checkpoint —2026-10-17 UTC

The closed intent/control schema and byte-identical packaged resource are pinned
raw `b1a2d42eb5d7ed9ce8b6447e7524a90121820961a22882d5b91f331312609a6f`.
The existing Orchestrator question preparation now has a typed selected-control
entry, sharing numerical runtime-bundle closure with the approved-reference
implementation. Batch/thread values come from those controls, not free caller
parameters. A separate supplied-native-input validator binds the exact parent,
private basis, document recipe and partition; malformed native errors suppress
JSON Schema's default representation of the private question.

Final related regression:701 PASS/36.35s across18 suites, strict mypy5 production
modules and Ruff/format6 paths PASS. These are source/synthetic-pointer tests, not
current-user ownership, real corpus/model, protected unit or operating acceptance.
No DB/state/queue/persistence behavior changed; no new migration or mutating DB
test ran. Earlier guarded59 ownership-read tests remain historical evidence only.

Initial new tests exposed fixture assumptions about the frozen recipe fields and
the stricter SchemaError type; fixtures were corrected without weakening parsers.
The wider run also exposed the existing benchmark control entry in the original
four-member DOCUMENT inventory (present before this change). Both benchmark and
private resources now have distinct named entries in the SAME registry; the
unchanged old-inventory tests pass without assertion changes. Existing benchmark
schema bytes/hash and its supported parser remain unchanged. No mutable registry,
new search framework, optional dependency or public authority override was added.

Status: **SOURCE_PASS / NOT_INSTALLED / NOT_ACTIVE / C4_NOT_ACCEPTED**. Actual
private Workflow admission/result CHECK, publication receipt, atomic allocation,
native execution and Chat tool delivery remain open. No old reference policy,
selected runtime, model default, original request/key or authentication changed.

Candidate `aeab2d78ba6363f88c1422f2e756ddc76d4b46b8` is committed/pushed and
passed the standard three-wheel build/RECORD gate. Retained dist:
`/tmp/eom-api-build/aeab2d78ba6363f88c1422f2e756ddc76d4b46b8.UBkghP/dist`.
Platform raw `20f33053cc6155bc50d39001d6f0cf4b6f49e59a8338b376652e8c1f33248089`;
API-contract raw `5cbcc2a12aa47c193972b4695269a4292ddb72d95a4a41a6f53f5a565b8e5722`;
API raw `2ea6b7b0841607149a4494af59c827b5f41673c5c4ed46066dd366274827f19c`.

An independent Conda `-I -S -B` process imported195 EOM modules exclusively from
the exact platform/API-contract archives. It validated the new schema/resource,
private intent→native preparation equality, shared legacy-reference closure and
unchanged original DOCUMENT inventory. Test/checkout/optional-ML imports0; actual
DB/model/activation calls0. Synthetic input was staged separately, pinned raw
`68fae22f427ec6144976142de16b467622e7c83be965c1594d18de47727b8810`.
The read-only proof and staged input remain under
`/tmp/eom-private-query-intent.gyMCBX4F`; they are not source/IAM/native acceptance.
No protected prefix, service, policy, original request or selected device changed.
