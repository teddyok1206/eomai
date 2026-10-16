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
