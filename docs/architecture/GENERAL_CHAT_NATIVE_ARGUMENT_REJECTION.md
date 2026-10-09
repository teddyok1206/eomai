# General chat: rejected arguments are not a poisoned native session

## Evidence and scope

On 2026-10-09 a V4 follow-up failed with `CODEX_PROTOCOL_INVALID` at
`ARGUMENTS`, before any accepted tool record, although its prepared request
contained three pinned RAG sources. Rejected arguments are intentionally not
retained, so the particular invalid field cannot be reconstructed. This is not
evidence that those sources were missing or that Catalog failed.

The pinned Codex App Server 0.160.0 dynamic-tool response supports
`contentItems` and a boolean `success`. A rejected tool execution can therefore
return `success=false` without reporting a broken JSON-RPC transport. See the
[official dynamic-tool sequence](https://learn.chatgpt.com/docs/app-server).

## Boundary and invariants

- Only JSON Schema/Pydantic **argument parsing** failures in the V4 native
  adapter are recoverable. They become a typed local exception before the
  Orchestrator broker is called. Validation is not weakened or normalized.
- A correctly matched native tool request receives a fixed, text-only failed
  tool response. The model may correct its input or answer from prepared
  sources **inside the same turn**. There is no new submission, claim, model
  turn, automatic replay or change to failed historical turns.
- Namespace, request/call/thread/turn identity, unsupported tools, tool budget,
  broker failures, reply/hash/ticket/transcript errors and final answer/citation
  errors remain fatal. V1-V3 behavior is unchanged.
- The existing native call-ID map/set counts every attempt, including rejected
  arguments, against the seven-call ceiling. Accepted tool records alone
  describe actual authorized broker executions; a rejection creates no
  canonical tool record, evidence, source key or NAS write.
- Lookup and deduplication remain O(1) per native call, with at most seven
  entries. Canonical inputs, immutable output pointers and accepted tool
  records retain their existing schemas and pins. No DB, queue, protocol
  version, worker permission or dependency changes are needed.
- Logs contain a fixed rejection category only, not arguments, validation
  exception bodies, conversation/source text or native frames.

The native adapter owns transport behavior; the protocol package still owns
input constraints, and the Orchestrator broker owns authorized reads. A
prompt-only patch cannot distinguish input rejection from protocol poisoning.
Catching all `ValueError` or all tool exceptions would incorrectly hide trust
boundary violations. The typed exception is raised only by the narrow parser.

## Verification and rollout

Regression cases must cover schema and cross-field rejection, correction and
prepared-source reuse, one native turn, all rejected attempts counted, forged
identities and malformed broker replies remaining fatal, and unchanged V3.
Use the existing compatible API/chat release path without redeploying unrelated
Web assets or regenerating user content. Preserve the terminal failed user turn;
the user can submit a new follow-up after the repaired runtime is ready.
