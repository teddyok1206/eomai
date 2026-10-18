# CHAT-RAG-2: textbook evidence in conversational answers

Status: compatible operational connection and bounded actual HTTPS/native/canonical
acceptance PASS, 2026-10-09 UTC. Textbook analysis informed an initial answer and
an exact-evidence follow-up; source cards and prior completed history were verified.
Installed pins, failures, call accounting and limits are in the
[live acceptance](../status/GENERAL_CHAT_TEXTBOOK_RAG_ACCEPTANCE_2026-10-09.md).
The checkpoints below preserve their original narrower evidence, not a claim of
educational-quality approval or access expansion.

## Design boundary (required design procedure)

1. Responsibility: add one bounded `retrieve_eom_knowledge` native read tool to
   the existing dedicated chat. Orchestrator owns execution/evidence publication;
   Catalog owns retrieval, source authorization and materialization.
2. Canonical source: the same published Education Graph, released retrieval
   access policy and accepted source analyses used by item authoring. Reuse
   `KnowledgeRetrievalApplicationService` selection and source resolvers, not a
   second search engine, vector store or whole-book prompt dump.
3. Identity: additive chat turn/worker/dispatch V4, read-tool record V2 and
   grounding view V2. Released V1–V3, historical model prompts, receipt bytes and
   recorded tool transcripts remain readable and unchanged.
4. Pointers: exact Graph revision/hash, access-policy revision/hash, source logical
   identity/revision/member/hash, accepted analysis result and excerpt/anchor
   pointers. Textbook references are not fabricated Item references. Each source
   distinguishes approved analysis text from a verbatim original-page quote.
5. Access patterns: indexed lexical term→stable topic lookup; existing bounded
   multihop retrieval; keyed immutable analysis/member lookup; batched source
   authorization; append-only tool receipts and exact-pin follow-up.
6. Structures/indexes: existing term/snapshot/analysis indexes, maps for identity
   checks, sets for uniqueness and tuples for ranked immutable output. No DB
   schema, queue, registry or new dependencies are planned.
7. Scale/complexity: retain up to four Item searches/one Item read and add at most
   two bounded RAG reads per turn (seven total native calls). At most three RAG
   sources, 32 graph nodes, 4,000 estimated retrieval tokens; combined prepared
   Item/RAG context remains bounded. Lookup is indexed O(log N + postings), with
   the existing bounded candidate/traversal policy; LIMIT is not a query-plan proof.
8. Transactions/concurrency: one existing chat claim/ticket and authenticated
   owner-initiated worker connection. Read-only repeatable-read Catalog projection;
   actor/claim checked before and after retrieval, and on admission/history/reuse.
   Only Orchestrator publishes the validated immutable tool result to NAS.
9. Dependency direction: contracts → application ports → Catalog/native adapters.
   Workers receive bounded sources only: no DB, NAS, unrestricted socket, shell,
   internet or mutation capability. AGENTS.md is guidance, not an access grant or
   a replacement for the frozen runtime prompt.
10. Failure/retry: explicit EMPTY/FORBIDDEN/UNAVAILABLE/stale/hash/anchor errors.
    A failed read supplies no partial evidence; never switch to latest, invent a
    source, relabel model knowledge as textbook evidence or retry generation on an
    uncertain transport. Follow-up reauthorizes exact sources without new retrieval.
11. Simpler alternative: merely mention textbooks in a prompt or AGENTS.md does
    not provide model-visible evidence. Inserting documents into Item-only fields
    corrupts source identity. Extend the existing protocol/adapter boundary instead.

## Authority and scope

Keep the released authoring retrieval policy and actual actor permissions. Do not
grant all chat users unrestricted textbook access, impersonate WORKER/ADMIN, or
accept role/permission/policy claims from model tool arguments. Discovery itself
must authorize before exposing source metadata. Any missing permission or retired
source is an explicit limitation, while ordinary chat and existing Item reads remain.

## Native and output contracts

Use the already pinned native `dynamicTools` / `item/tool/call` integration and
direct-tool exposure configuration; do not enable more native capabilities.
Official interface: <https://learn.chatgpt.com/docs/app-server>.

Existing Item citations keep S1–S9. Separate R1–R3 sources expose source class,
human-readable title and checked page/anchor location, plus immutable source and
analysis identities internally. New grounding views render document references
without routing them to Item Preview. Existing S buttons continue to open exact
Item revisions. Cite only sources actually read in this turn or explicitly pinned
for its follow-up. A model inference and general knowledge remain separately marked.

Each subsequent RAG read extends the exact existing R-source prefix. It cannot
retarget R1, remove its limitation or silently switch Graph/policy. The same domain
rule validates Catalog replies and canonical transcript replay. Intake references
retain source-file and Artifact revision identity without exposing internal batch
identity in source cards. Context metadata is bounded to 32,000 bytes, source text
to 8,000 UTF-8 bytes (4,000 existing estimated tokens); combined prepared Item/RAG
materialization is bounded to 128,000 bytes.

## Contract foundation checkpoint

JSON Schema 2020-12 was defined independently of runtime models, through
`scripts/contracts/generate_general_chat_rag_schemas.py`, then mirrored into the
protocol wheel resources. Frozen Pydantic source/context, V4 turn/result, mixed
Item/RAG tool transcript, citation receipt and view models now enforce the rules.
All 28 predecessor schema bytes remain unchanged (aggregate SHA
`cadfcf5b94725568a201b1f1627f0d0ee8c3abb519d00b4e1232f27398a3cb6e`).
The existing Item offered-reference rule and section support rule are reused,
not copied into another search or state-machine framework. Offline validators
share one immutable parsed schema registry; a counted-read regression checks that
the five schema resources are parsed once, not once per definition.

At this historical contract-foundation checkpoint, `AGENTS.md` records supported
RAG use, installed-tool availability, exact-pinned
follow-up and honest source classification. It does not grant access or turn on a
planned native tool. Actual Catalog actor/source authorization, read-only retrieval,
native duplex integration, source-card rendering, disposable persistence tests,
compatible installation and live textbook answers are **not yet accepted**.

## Catalog read-path checkpoint

The next source checkpoint adds `ChatRagResolutionService` and the private
`CHAT_RAG` Catalog operation. Actual actor/role/permissions are resolved before
discovery, under a read-only repeatable-read transaction. Korean terms use the
existing immutable lexical index to select real authoring topic keys. Public
read-only methods reuse authoring candidate/source resolution and the existing
Graph publisher's accepted-analysis/receipt/member validator; they do not create
an Evidence Bundle, registry row or Artifact. Run/Artifact/job metadata and
source-card titles are batched; three Graph reference checks use two queries.

Chat pins use the existing **snapshot SHA**, not the separate manifest-file SHA.
Both are checked against the exact immutable manifest. At most three distinct
source/range references are materialized, with the policy's smaller node/source/
claim/context budgets respected conservatively. Deterministic UTF-8 prefixes are
explicitly approved analysis, never page quotations or pixel inspection. Follow-up
reauthorizes the exact text, source, accepted result, normalized member, Graph
anchors, titles and locations. Source keys and prior limitations remain stable.

Source-side read-only production diagnostics retrieved three textbook analyses
and reauthorized identical context; the indexed term query used the existing
term/source/node indexes. This is **not installed Catalog/native/UI acceptance**.
No model/GPU/HWPX execution, DB mutation, Artifact publication, migration, policy
grant or service restart occurred. Detailed evidence and remaining gates:
`docs/status/GENERAL_CHAT_RAG_CATALOG_CHECKPOINT_2026-10-09.md`.

## Verification/rollout

### Owner admission and history resolution

The existing owner resolves each turn into one frozen value (user message,
prepared request, admitted answer, resolved Item context and resolved RAG context).
This replaces positional history tuples rather than adding a second history
store. Canonical inputs/results and all tool records are materialized in bounded
batches; maps keyed by immutable snapshot/revision or context hash deduplicate
authorization. Every distinct RAG context is reauthorized through Catalog before
history display, follow-up preparation and successful final admission. A revoked
historical source is an explicit error, not a silently shortened conversation.

V4 is opt-in through an exact released access-policy revision/hash in the owner
configuration and an explicit worker protocol selection. Without this setting,
V3 remains the default. Initial RAG permission denial may leave ordinary chat and
Item tools available, but an invalid requested pin or revoked prepared evidence
must not be downgraded to a fresh/latest scope. Follow-up uses its prior Graph and
policy even when the current configured policy changes. No DB schema, history
backfill, new message Artifact family or role grants are required.

The supported V1–V4 readers live in `general_chat_turn_contracts`; legacy V1–V3
readers retain their original semantics. The unchanged ticket value is extracted
into `general_chat_ticket`, explicitly reexported by the old module, so the new
turn/tool/envelope dependency graph stays acyclic. Native V4 uses the existing
duplex worker transport and canonical handoff/recovery mechanism. New R source
cards pass through typed owner/API/BFF contracts and render as document-analysis
cards, never fabricated Item links. The Web mirror contains only presentation
fields and bounds; Catalog remains the authority for provenance and access rules.

Staging keeps both chat services stopped. Activation uses an exact policy and
worker protocol pin; nonsecret model configuration advances only from its supplied
predecessor hash, and changed units only from the named predecessor source bytes.
Protected credentials, worker authentication and conversation history are untouched.
An explicit model-configuration SHA CAS may select source/similarity flags while
the exact installed runtime commit remains unchanged. This config-only path must
verify the existing release pin and both source-pinned unit bytes, preserve the
parsed model/RAG policy/native CLI identity, and reject missing or foreign targets.
It neither advances/recreates release.env nor repins a CLI or changes a unit.
The existing compatibility/installed-release, stopped-service, configuration CAS
and source-endpoint preflight checks remain required; stopped state and the same
release pin are rechecked before mutation. File selection is bounded O(1) work,
not a new authority or activation protocol. Treating this as a release advance
rejects a valid equal predecessor; using CLI pin-only mode would incorrectly try
to substitute a different selection operation. No model call or authentication
transfer is involved, and ordinary startup/current authorization gates still apply.
Source/disposable evidence and the then-pending live gates are recorded in
`docs/status/GENERAL_CHAT_RAG_NATIVE_CHECKPOINT_2026-10-09.md`.

The current HTTP owner boundary has one finite 50-second deadline for all seven
chat-owner operations, covering the existing authoritative 45-second RPC. Other
API and Catalog-search limits stay unchanged. A timed-out write is not proof of
nonprocessing: use the same conversation/request identity for supported lookup or
idempotent replay, never a replacement generation. The accepted follow-up's lost
HTTP response was recovered by read-only display of its already-completed turn.

- Define JSON Schema 2020-12 before runtime behavior; mirror bundled schemas and
  frozen Pydantic contracts. Test released V1–V3 byte preservation.
- Test actual-role authorization, no metadata leakage, stale/retired policy/source,
  source/analysis/hash/anchor mismatch, bounded reads, canonical manifests,
  idempotency, claim identity, forged receipts and exact-source follow-up.
- Reuse authoring retrieval regression/query-plan tests and add guarded disposable
  persistence/native-duplex/history tests, including Item/RAG interleaving.
- Ruff/formatter/mypy, source and browser/BFF compatibility gates before commit.
- Compatible installed API/Catalog/chat/Web release plus rollback; no migration.
  Actual authenticated conversation must cite textbook analysis/page evidence and
  retain its exact source on follow-up. Keep educational quality separate.
- Record tested/installed pins, model-call accounting, corpus scope and unknowns;
  report important milestones only. Goal completion requires live evidence, not
  source PASS or an AGENTS.md sentence alone.
