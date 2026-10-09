# General chat argument rejection repair — 2026-10-09 UTC

## Incident and classification

The reported follow-up `chatturn_16a88ee2f43f9f1ac330fff3c59bbbd4`
terminated with `CODEX_PROTOCOL_INVALID`. Its committed request already
contained three RAG sources, and its result contained zero accepted tool
records. Bounded canonical pointer/schema/hash validation passed. Closed native
diagnostics located the failure at tool `ARGUMENTS`, before broker dispatch.

The exact rejected field is **not recoverable**: raw rejected model arguments
are deliberately neither published nor logged. Synthetic cross-field validation
reproduced the same failure boundary. This is not evidence of missing textbooks,
a Catalog outage, or a mere HTTP timeout.

## Repair

Installed API/shared platform/chat source:
`d32f3ba75bc7a0b34305204d3dba43a009e99617`.
Compatible Web remains `c0558ecfe534e40c3ee91ea4fd9b099afa14ec34`;
no unrelated Web redeployment was necessary.

The [design](../architecture/GENERAL_CHAT_NATIVE_ARGUMENT_REJECTION.md)
separates malformed V4 tool **arguments** from corrupted protocol/trust state.
Schema/Pydantic parsing rejection returns a fixed text-only native tool response
with `success=false`. The same model turn may correct its input or use its
prepared evidence. It cannot turn rejection into an authorized read.

All attempts, including rejected ones, count against the existing native seven
call ceiling. Thread/turn/call/request identity, namespace, unsupported tools,
broker/reply/hash/transcript failures and final citation admission remain
fail-closed. Released schema bytes and V1-V3 semantics are unchanged. No new
dependency, DB migration, queue, grant, worker capability or external API exists.

V4 RAG prompt SHA:
`sha256:9ece0408f054fca7cf86299ed2a5a264c611d5e69bc82de0c1cfceb0c21b1977`.
Worker policy SHA:
`sha256:6c2b02c7fcb795ca24393fe67e08874b090407140b674976f01bf80201441f73`.
Existing Graph/access-policy pins, model `gpt-6.1-sol`, CLI 0.160.0 and separate
chat capacity are preserved; the other six slots are unchanged.

## Source and installed validation

- Final coherent regression: **1,013 PASS, 0 SKIP** across chat unit tests,
  Catalog RAG resolution, dependency boundaries, API chat/knowledge and all Web
  tests. One existing third-party Starlette/httpx deprecation warning remains.
- Focused native RAG suite: **47 PASS**, included above. Cases cover schema and
  cross-field rejection for all three tools, same-turn correction/source reuse,
  seven/eight rejected attempts, forged native identities remaining fatal,
  broker schema failure remaining fatal, and real duplex/handoff replay without
  a second generation after input rejection.
- Ruff format/lint, focused strict mypy, schema-generator checks and diff checks
  PASS. No DB persistence boundary changed; the prior 52-test disposable DB
  acceptance remains historical evidence, not a newly executed test.
- Normal release wheel/RECORD/migration and API runtime-isolation verification
  PASS. Migration remains `20261008_0049`; chat activation reports READY and API
  readiness is READY. API, Web, chat owner/worker and Catalog are active.
- Immediately before the canary, read-only comparison preserved all **21**
  pre-existing COMPLETED turn receipts and the user's exact FAILED
  request/result/claim hashes. Active chat turns and held chat capacity were zero.
- Compatible rollback wheel set retained at
  `/tmp/eom-api-build/1ec04c62f092d02e350395690d5a6291ec7b1352.iVhdxL/dist`;
  the new installed release record is
  `/var/lib/eom-api/deployments/d32f3ba75bc7a0b34305204d3dba43a009e99617.json`.

## Actual HTTPS follow-up

One bounded follow-up was submitted through the real admin's existing test
conversation, not the affected user's identity or conversation:

- Conversation: `chat_9b8ee37be1f7701405e64630b2b15433`.
- New turn: `chatturn_bcae8b38e733dd8d85d8bba71ddb7ce1`.
- Browser run: 08:02:53–08:03:51 UTC, admission HTTP 202, terminal COMPLETED.
- Exactly **one** model submission; no uncertain replay or automatic generation
  retry. Prepared RAG context is exactly the previous resolved context, three
  TEXTBOOK sources; accepted new tool records: zero.
- Canonical input/result/dispatch pointers, identities, hashes and citation
  receipt PASS. Citation receipt SHA:
  `sha256:66f0e0108f33fa490ec239a107cee3c3e6304297048fb26e043529d07a6d5473`.
- Two cited source cards and the new Markdown answer rendered; browser errors:
  zero. This is not human educational/visual approval.

Invalid-input continuation was explicitly exercised in synthetic native/duplex
tests. The live canary verifies actual deployment and prepared-source follow-up;
no malformed request was deliberately injected into production.

The original failed receipt remains FAILED. The user may send a new follow-up
after refresh; no DB/history repair, replacement conversation, Item generation,
GPU invocation or HWPX build was performed. This is a focused repair after the
textbook-RAG goal's completion, not a recreated long-running goal.

Private bounded incident evidence and test logs:
`/tmp/eom-chat-failure.oORTkK`. Generated artifacts, credentials and conversation
content are not committed to Git or sent to Slack.
