# CHAT-RAG-2: textbook evidence in conversational answers

Status: implementation plan, 2026-10-09 UTC. User authorized implementation and
requested a goal including operational connection. This is not live acceptance.

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

## Verification/rollout

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
