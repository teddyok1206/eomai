# ADR0212: General chat with dedicated, resident capacity

Status: implementation in progress, 2026-10-07 UTC. No runtime activation yet.
Activation gate: `AUTH_ROUTE_REVIEW_REQUIRED` (2026-10-07 13:45 UTC).
Current user-authorized access scope: **all authenticated EOM users**. The later
instruction `그렇게 하지말고 그냥 다 쓸 수 있게 해` supersedes the interim
personal-only answer. No selected-login binding is required or implemented.

## Boundary and canonical source

Scientific Studio adds `일반 → ChatGPT`. This is an EOM conversation surface,
not an embedded ChatGPT website. The initially investigated Codex-managed
ChatGPT authentication route is an unactivated candidate, not authorization
for a shared hosted product; see the authentication gate below. Do not replace
it with an external LLM API or billed API key without an explicit scope decision.
OpenAI Docs' [App Server](https://learn.chatgpt.com/docs/app-server) documents
threads, turns and message events. Reuse the existing isolated Codex execution
and authentication adapters; do not copy the operator's/root's credentials.

General chat is not customer support, document review or item authoring. Its
dedicated `chat` capacity must not consume slots01..06, borrow their leases,
increase their concurrency ceiling or silently fall back to their accounts.
An idle resident service makes no inference calls. READY means actual admitted
runtime availability, not an unconditional green UI badge. Runtime failure must
remain visible. A resident slot is not a perpetual generation/goal loop.

The API owns authenticated commands and queries; an Orchestrator application
port owns execution, validation and canonical transcript Artifacts. Workers see
staged bounded context, never DB/NAS, other users' conversations or credentials.
The Web BFF only proxies the API. No direct browser/Web-to-Codex invocation.

## Identity and resolution

Conversation logical ID, turn ID and sequence are separate from transcript
Artifact ID/revision/hash. Persist per-user ownership, ordered turn metadata,
states, pinned transcript pointers and concurrency/idempotency receipts in DB;
long transcripts and generated files belong in the Artifact store, not Git/DB.
Do not use localStorage as canonical history or resume a native Codex thread
provided by a browser. Resolve owner, lifecycle, schema, media and hash before
building worker context. No silent latest-revision substitution.

## Access patterns, transactions and failure

Conversation reads are indexed `(owner_id, updated_at, conversation_id)` cursor
queries and primary-key lookups; history is append-only ordered turn metadata.
Bounded pages (<=50) and contexts avoid unbounded materialization/N+1 queries.
Conversation serialization uses optimistic revision plus a unique active-turn
constraint; dedicated capacity has one atomic claim/lease across all users.
Submission and its queue receipt share a transaction. Owner-scoped idempotency
replays the same intent, including after uncertain HTTP outcomes. Reusing a key
with different input or revision is an explicit conflict, not another generation.

Different users may queue fairly; a conversation permits only one active turn.
Completion/cancellation must compare the exact claim identity. Restart must
reconcile an unknown active turn rather than automatically resubmit it. An
interrupted/failed response is not a completed assistant message. Immutable
failed history is retained. Do not leak raw worker failures or tool arguments.

Dependency direction: Web → API use case → Orchestrator application port →
domain/contracts; infrastructure implements the port. A parallel queue or a
general-purpose agent framework is not justified. First define schemas, DTOs,
conversation guards and authenticated UI; the executable owner/worker boundary,
DB migration, isolated dedicated identity, auth and deployment remain separate
gates and must be tested before activation. Until they are ready, return a typed
UNAVAILABLE status and reject writes; never fabricate answers or availability.

## UX and acceptance

New conversation, server-backed history, multiline composer, Enter to send /
Shift+Enter newline, code blocks/copy, real pending/error state and safe retry.
Do not interpret model HTML. Clear selected history and timers on session/owner
change. Late replies cannot replace the currently selected conversation.
The chat slot remains visible on the chat page, separate from the six-slot work
monitor. Streaming must display actual model events, not simulated typewriter
text. Initial non-streaming completion is explicitly distinguishable.

Existing support behavior/protocols and production slots remain unchanged.
ChatGPT parity for search, uploads, voice, image generation and native tools is
not implied by a text-chat surface; each requires its own authorized boundary.
No new dependency is required for the first implementation slice.

## Scope correction and resident-loop design

The latest instruction preserves per-user transcript privacy but allows every
active authenticated operator to submit to the one dedicated FIFO. Do not add a
personal-operator allowlist, first-caller binding or administrator-only exception.
The interim personal-access implementation was uncommitted and withdrawn; its
test counts do not certify the current source. This user access decision does not
claim new vendor eligibility, change billing or authorize credential copying.
Source/runtime integration development continues independently of that question.

The resident application coordinates the existing execution service and a bounded
worker port using the already defined turn-input/result1.0 contracts. It does not
spawn Codex inside the trusted Artifact owner or introduce a second queue. DB turn
metadata and pinned transcript Artifacts remain canonical; logical conversation,
turn and claim IDs and exact request SHA are validated before dispatch/admission.

Primary operations are singleton capacity lookup, indexed FIFO claim and ordered
immutable context. One execution loop and one heartbeat monitor use O(1) runtime
state; one bounded request/result is materialized at the existing worker boundary.
The existing singleton lock/lease and per-conversation unique active-turn index
retain cross-user concurrency control. No schema, index or migration is added.

Only admitted worker capacity is announced. Heartbeats continue while a known
claimed turn drains during shutdown; shutdown stops new claims, not publication
of an already known result. Withdrawal expires only this runtime's heartbeat,
never its active claim, lease, turn, historical result or another runtime. Unknown
worker/transport outcomes stop dispatch and require reconciliation: neither a
fabricated failed/successful result nor automatic model retry is permitted.

Dependency direction remains resident application → execution/worker ports →
existing contracts; storage and isolated native execution remain adapters. Every
claimed request/result is schema/hash/claim validated. The simpler synchronous
poll loop cannot maintain truthful availability during a long answer, while a
generic scheduler/retry framework would duplicate existing ownership. Worker
admission and DB operations must be bounded by their adapters; the heartbeat
monitor does not invoke or retry generation. Installed composition, worker RPC,
durable recovery, policy provenance, isolation and real inference remain separate
uncompleted gates, not claims made by this source slice.

## Incremental delivery plan (not a runtime completion claim)

### Private worker handoff design (source integration after resident loop)

Responsibility: Orchestrator is the only worker caller and canonical commit owner.
A private worker endpoint accepts admission probes, one exact turn execution and
read-only result recovery. No worker-to-worker, API-to-worker, DB or NAS access.
Native handles/account details are never on this protocol. The canonical source
remains the registered input/result Artifact; local worker handoff files are
bounded staging, not a second transcript store or an authoritative queue.

Conversation/turn/claim identities and canonical request SHA are pinned separately
from worker boot identity and the small immutable execution-policy value (model,
native profile, prompt revision/SHA). An admission change cannot silently select
another model/process. JSON Schema2020-12 precedes the new strict frozen messages;
existing public/owner/turn1.0 schema bytes remain unchanged. Owner-side canonical
policy provenance is still required before runtime activation; wire attestation
alone is not historical provenance or hosted-auth eligibility.

Access is O(1) exact-claim filename lookup; a process lock plus exclusive marker
creation prevents duplicate execution. Bounded inputs/results use O(context+reply)
materialization only at the existing worker boundary. No queue scan, new DB table,
index, framework or dependency. A private700 local directory is opened no-follow;
all leaves are validated IDs, file identity/ownership/type/mode/size are checked,
pending metadata is immutable and final output is published without overwriting.

The immutable pending marker precedes model invocation. A completed exact result
may be replayed/read without inference. A pending marker without a valid result
means UNKNOWN and requires reconciliation, never permission to regenerate. Crash
or fsync/transport ambiguity does not erase the marker, change historical status,
fabricate an answer or allocate another claim. Hash/claim/policy conflicts fail
explicitly. Local outputs do not contain user transcript copies, credentials,
native reasoning or raw errors. The result response is validated by Orchestrator
before canonical publication.

Dependency direction: protocol values → application handoff → worker/local-file
and Unix-socket adapters. Reuse the existing strict bounded socket framing and
SO_PEERCRED/mode checks. The endpoint permits only the trusted owner UID. Probes
and lookups remain possible during execution; one bounded execution lock admits
only one model turn. An unverified reboot/policy change stops new dispatch.
The simpler blind synchronous socket retry can generate twice after timeout;
another persistent scheduler duplicates the existing indexed claim owner.

### Canonical dispatch provenance (after private worker integration)

Orchestrator pins one small dispatch manifest per claimed turn before RUNNING or
worker invocation. Its canonical Artifact binds the existing input member pointer,
conversation/turn/claim and request SHA to the owner runtime, admitted worker boot
and frozen model/native-profile/prompt revision/SHA. Policy is an inline immutable
value, not a new independently versioned entity/registry. No input transcript is
copied into this manifest. Existing turn input/result and public/RPC schemas stay
unchanged; define a new dispatch1.0 JSON Schema before its implementation.

Add only the manifest Artifact/revision/SHA pointer to the existing turn metadata
using successor migration0049. Composite RESTRICT FK and all-or-none checks guard
pointer integrity. A separate DB trigger forbids replacing a pinned dispatch and
requires it for new RUNNING transitions/inserts. Predecessor terminal history may
retain no dispatch; do not invent historical model evidence or rewrite it. Legacy
non-terminal work without provenance cannot silently use a current policy.

Dominant access: exact turn/claim PK lookup and bounded two-member resolution, not
queue iteration. Existing B-tree PK/FK identities suffice; no new index, cache or
table. Cost is O(log N) metadata plus O(input bytes) at the already-defined prepare
boundary; dispatch bytes are constant-sized. Expected scale remains thousands of
turns and one global dedicated active claim. No binary/transcript/model response
is placed in a DB row, and canonical policy hashes are not cached separately.

Reuse the existing idempotent Artifact commit owner and independent publication
pool. Publish immutable input/dispatch before the exact capacity→turn transaction
pins both pointers and changes CLAIMED→RUNNING. Interrupted publication can leave
registered evidence, not permission to execute; replay uses the same claim/intent.
Replay resolves stored pointers and compares the full pinned execution identity;
no implicit latest, changed boot/model/prompt, or new identity can replace it.
Completion/recovery resolve the original manifest and input, not current policy.

Neutral protocol values and evidence validation remain below the application;
DB/Artifact/native/Unix-socket operations stay in existing adapters. A socket policy
SHA alone is simpler but disappears after process restart and does not establish
historical provenance. A second runtime-policy registry or repeated transcript
copy would add independent lifecycles without a required access pattern. No new
dependency, queue, existing-slot change or production migration is implied by
source/disposable acceptance of this design.

Expired recovery is a separate Orchestrator use case, not a new claim or lease
extension. Lock the capacity/turn, require the exact original runtime/turn/claim,
an unchanged lease and withdrawn/expired owner heartbeat, and resolve original dispatch
and input before admitting an exact known terminal worker result. Reuse the normal
COMMITTING journal/Artifact publication/final transition with this explicit guard.
Absent/unknown output, live owner, different claim/hash or historical terminal
conflict never grants recovery or fresh inference. Read-only worker RESULT lookup
uses the historical ticket policy SHA, even after a configured policy change;
PROBE/EXECUTE still require the actual current policy and admitted boot. Completing
the old claim releases capacity only after canonical publication. A known result
need not wait for lease expiry, but recovery never extends it or grants another
model invocation; unknown results stay fenced, including after expiry. New runtime
admission remains a later, separately verified action. No automatic unknown-turn
retry, failed-history rewrite, direct repair UPDATE or fresh identity is provided.

0. Establish a supported authentication route for the actual deployment and user
   scope before inference or runtime activation. UI/persistence/private owner RPC
   verification is independent of this vendor eligibility gate; enrollment alone
   cannot close it. Do not silently substitute a personal-only prototype for the
   requested multi-user company feature.
1. Public JSON Schema2020-12, frozen API/Web mirrors, independent read/write RBAC,
   authenticated CSRF-protected BFF, closed OpenAPI/package inventory and chat UI.
   No inference during this slice; absence of an admitted owner returns503.
2. Add the Orchestrator-owned conversation/turn metadata and immutable transcript
   pointers, owner-scoped idempotent receipt and indexed atomic claims. Define the
   worker input/result schemas before implementing its behavior. Test using a
   disposable PostgreSQL database, including concurrent submits and completion
   claims; never store answer/transcript bodies in DB.
3. Add an isolated `eom-cdx-chat` identity and a resident execution service, separate
   from the existing six-slot policy. Bound context per turn, suppress all local
   privileged/tool access, validate exact thread/turn/claim and final-answer events.
   Account enrollment is operator-owned; root/main Codex auth is never copied.
4. Verify installed capability/config/identity isolation and add the API composition
   binding. Deploy the compatible API/Web/Orchestrator set and the necessary additive
   migration. Exercise a real first question and follow-up, two authenticated owners,
   service restart/unknown execution, and independent existing-six-slot regression.
5. Report real readiness, outputs and pending visual review. Only then close the goal.

First-slice tests do **not** demonstrate persisted user isolation, model generation,
resident execution, live availability, streaming or migration deployment. Those
are separate required exit checks in steps2–4. Native schema generation from the
installed `codex-cli0.160.0` is read-only capability research, not a model run.

## Persistence implementation decision (step2)

Orchestrator owns three metadata tables: conversations, turns and the singleton
dedicated capacity record. The turn table is the indexed FIFO work queue, not a
second generic queue framework. Operators are tombstoned by Identity; owner FK
uses RESTRICT. API presentation contracts re-export neutral protocol models, so
Orchestrator does not depend on the API implementation or its distribution.

Canonical message bodies are immutable control-owned execution evidence JSON,
published with the existing resumable ControlArtifactPublisher. This reuses its
Job/Artifact commit boundary; no chat adapter writes NAS independently. DB stores
only pinned member identity/revision/schema/media/hash and bounded context pointer
lists. User and assistant bodies never enter conversation/turn rows. Materialize
one bounded history page/context through the shared indexed snapshot resolver.

Create and submit use scoped advisory intent locks plus uniqueness constraints.
Replay is checked before resource-version guards. Submission locks its owner-
verified conversation, reserves two monotonic sequences, publishes the user
evidence idempotently, then atomically stores the pointer and QUEUED receipt.
Publication recovery reuses the same deterministic intent/turn identity; an
orphan registered Artifact after interruption is evidence, not runnable work.
One partial unique index admits one active turn per conversation. FIFO claim
locks capacity before a queued turn; completion locks capacity, then turn and
conversation. Submission never acquires capacity while holding conversation.

Capacity heartbeat/identity admission is separate from claim expiry. Expired or
unknown execution stays unavailable until explicit reconciliation: no automatic
new inference or lease takeover. COMMITTING represents validated final output
being published; replay pins the same request/result hash. Completion checks the
exact runtime/turn/claim and increments the conversation revision. Terminal turn
history, input identity and accepted output pointers are DB-trigger protected.

Expected scale: thousands of per-user conversations/turns. PK/member lookup and
cursor pages use B-tree indexes, O(log N + page); work selection uses a partial
FIFO index; history/context bounded to 50 turns/40 messages. Transcripts remain
linear in selected bytes, with one batched metadata query, no N+1 or persistent
byte cache. Failure codes are bounded, not raw worker output. No dependency or
existing six-slot policy/schema change is required. A JSONB transcript in DB or
using slots01..06 would be simpler but violates storage and capacity ownership.

Use one injected chat evidence adapter per resident owner process, with an
independent two-connection publication pool and an instance-local publication
lock. A publisher holds an advisory connection while committing on a second
connection. Sharing the metadata pool would let concurrent submit transactions
consume every connection and block the publication needed to release them.
The 20-intent saturation test covers this resource deadlock boundary. These are
two pools to the same canonical DB, not another database, cache or queue.

## Native execution adapter decision (step3)

The dedicated worker adapter implements the already released staged turn input /
result contracts. Codex JSON-RPC is a vendor adapter, not another public EOM queue
or registry. Pinned profile `codex-app-server/0.160.0/environment-free/1.0` uses the
installed CLI's actual experimental schema for explicit empty environments. No
external LLM API, added dependency or six-slot protocol change is introduced.

Canonical context remains the Orchestrator's validated Artifact snapshot. Each
turn starts an ephemeral native thread, injects preceding user/assistant messages
with their original roles, then submits only the newest user message. Native IDs
are local handles, never owner/Conversation IDs or persisted history pointers.
Thread/turn identity and empty native history are checked before accepting output.
This adapter neither queries DB, dispatches another worker nor writes NAS.

Actual v0.160 normalizes `unified_exec` back to true despite a user-config false
override. The matching official implementation gates shell registration on
`shell_tool` and environment availability; applying a patch also requires an
environment. Therefore do not pretend that the backend flag itself is disabled.
Use supported `environments=[]` on both thread and turn, empty runtime roots and
dynamic tools, disabled shell/browser/image/plugin/MCP/agent/goal features, and
fixed read-only/no-network/never-approve policy. Never alter system-wide Codex
requirements or the existing slots to achieve a private chat policy. References:
[managed feature normalization](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core/src/config/managed_features.rs),
[tool registration](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/core/src/tools/spec_plan.rs),
[explicit environment selection](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server-protocol/src/protocol/v2/thread.rs).

The subprocess adapter permits only UID/GID `eom-cdx-chat`, its own700-mode home,
root-installed640-mode empty configuration, fixed environment/CLI and a root-owned
empty workspace. A read-only config mount is mandatory: root ownership alone does
not prevent rename in a worker-owned directory. Effective CLI version/features,
native config and ChatGPT account type must pass admission. Existing worker or
operator authentication is never borrowed. UID/config checks are not a substitute
for the **still-required live service isolation negatives** before activation.

Access is serial JSON-RPC with exact integer request IDs, bounded FIFO pre-response
events, O(1) handle/item lookups and <=32MiB/50,000 events per turn; one line<=1MiB.
Stdio reads/writes are nonblocking with deadlines, rejecting duplicate JSON keys,
nonfinite values, invalid encoding and EOF. Retired handles are bounded to256;
renew the native process between turns when that bound is reached. Late housekeeping
for a known retired handle is ignored; late message content is never accepted.

Only exact-thread/turn `final_answer` items and a successful native terminal event
produce SUCCEEDED. Commentary, reasoning, deltas, failed/interrupted turns and
tool events are not completed answers. Actual model deltas are validated but are
not yet exposed as browser streaming; the UI currently shows pending→completion.
Any uncertain/error/tool boundary closes the process and produces pinned FAILED
evidence, never an automatic generation retry or partial-answer promotion.

`scripts/chat/provision_worker_identity.sh COMMIT` prepares only the dedicated
locked Linux account/home/root-owned configuration after clean pinned-source
checks. It does not copy credentials, start a service, migrate DB, amend groups of
existing workers, or claim readiness. Existing conflicting paths/configuration fail
explicitly. Resident worker/owner RPC, service isolation, enrollment, API composition
and coordinated deployment remain required successor work, not fulfilled by this
provisioning helper or adapter source tests.

## Private owner RPC and resident composition

The API's existing GeneralChatOwner port is implemented by a private Unix-socket
client; only authenticated API calls may supply an actor ID. The resident
Orchestrator owns the existing conversation/turn/capacity tables and Artifact
adapter. Its worker port is separate, never reachable by the browser/API. An API
process that directly constructs the DB/NAS transcript owner would be simpler but
would cross the established persistence/commit responsibility boundary.

Define JSON Schema2020-12 request/reply envelopes before adapters. Reuse the
canonical public view definitions through an offline schema registry rather than
inventing different conversation shapes. Requests carry a correlation ID and a
discriminated typed command; replies preserve the exact ID/action and bounded
typed projection or stable error. Conversation/turn/revision/hash remain the
canonical identities, not socket paths or correlation IDs. The authoritative
operator and conversation owner checks remain in their existing services.

Access patterns are one indexed owner query/command per connection, cursor history
pages and the existing indexed FIFO queue. Single-connection framing and bounded
concurrency avoid unbounded threads/JSON/logs. Requests<=256KiB and projected
replies<=16MiB accommodate existing bounded views without duplicating binary data.
The server uses fixed peer UIDs; clients check socket/parent metadata and connected
peer credentials. Each side uses a deadline and validates both schema and model.
There is no native generation, DB transaction or new queue inside the API client.

Business transactions and idempotency remain in the conversation owner. Socket
disconnect/timeout does not prove a write was unprocessed; clients never issue a
second mutation with a new key or hide a failure as success. Unknown/malformed
replies fail explicitly. General chat is optional until its dedicated runtime is
admitted, and absence of its socket must not break other product workflows.

Resident composition has separate trusted-owner and unprivileged-worker identities.
Only the owner can commit validated evidence; the worker reads staged input and
returns local results. Runtime/model/prompt policy evidence must be pinned for each
claim before inference. Owner restart must reconcile persisted worker/result evidence
and never re-run uncertain generation. DB/schema changes are not needed for this
owner RPC slice; service setup, protected policy provenance and recovery remain
distinct required runtime gates before availability or completion is claimed.

Operator enrollment uses the documented [device-code authentication](https://learn.chatgpt.com/docs/auth)
through `scripts/chat/enroll_worker_account.sh COMMIT`, in an interactive terminal
under the dedicated worker UID and cleared environment. Existing credentials are
not overwritten, imported or printed; the browser challenge stays in the operator
terminal and is never captured as development evidence. Enrollment is a bounded
login operation, not model execution or service activation. Unavailable device
login requires an explicit operator decision; no credential-copy/API-key fallback.

## Authentication deployment gate — official documentation discovery

As of2026-10-07 13:45 UTC, the official
[App Server authentication guidance](https://learn.chatgpt.com/docs/app-server)
states that existing authentication may continue for local/open-source apps,
but has not been permitted for commercial or hosted services. EOM's intended
shared company-server chat is not demonstrated to qualify for the local-app
case. This is a deployment-classification uncertainty, not evidence that current
EOM production performed an unauthorized chat inference: none has occurred.

The official [Sign in with ChatGPT documentation](https://developers.openai.com/siwc/token-sharing-open-source)
describes optional access to an eligible user's own plan, user/workspace-bound
registration and host identity. It directs paid/remotely hosted applications to
an interest form; documentation availability does not prove EOM's eligibility.
Its [self-hosted VM guide](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
preserves the same user/workspace in local enrollment and VM operation. It does
not establish permission to expose one operator's plan to all company accounts.
The [SIWC native App Server guide](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)
uses an OAuth token-backed Responses provider and different authentication/
renewal configuration from the source-verified managed-login profile above.

Therefore shared-service activation and real model calls remain on hold pending
deployment eligibility and an explicit user decision about scope/authentication.
Do not treat dedicated Linux identity, sudo authorization, browser device login,
or existing native adapter tests as that decision. Do not register an OAuth app,
submit a partner form, transfer credentials, introduce an external inference API,
or share one plan between company users as an implicit implementation step.

Preserve existing source tests, transcripts/contracts and independent capacity
design. A supported successor authentication adapter, if authorized, must pin its
own runtime profile and owner/renewal boundary; never relabel managed-auth test
evidence as SIWC/live eligibility. GPU work and production slots01–06 stay untouched.

### Alternative credentials reviewed, not adopted

The official [Codex access-token guide](https://learn.chatgpt.com/docs/enterprise/access-tokens)
also describes workspace-bound credentials for trusted local CLI/App Server
automation, currently supported in Business/Enterprise workspaces. It is not
proof that this EOM shared chatbot qualifies or that the operator has such a
workspace. Do not inspect another account's credentials or enroll a new plan to
resolve that unknown. Ask for the current plan/workspace and deployment scope.

The official [service-account guide](https://learn.chatgpt.com/docs/enterprise/service-accounts)
describes separate non-human identities for organizational automation, available
only on pay-as-you-go plans. This is not an implicit substitute for the requested
subscription-capacity route. Account creation, plan changes, costs and related
credential setup require a separate explicit decision; none was performed.
