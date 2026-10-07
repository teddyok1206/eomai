# ADR0212: General chat with dedicated, resident capacity

Status: implementation in progress, 2026-10-07 UTC. No runtime activation yet.

## Boundary and canonical source

Scientific Studio adds `일반 → ChatGPT`. This is an EOM conversation surface
powered through Codex, not an embedded ChatGPT website or a new billed LLM API.
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

## Incremental delivery plan (not a runtime completion claim)

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
