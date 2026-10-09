# CHAT-RAG-2 installed checkpoint and bounded canary failure

As of 2026-10-09 06:21 UTC. The goal remains ACTIVE; this is **not**
successful live textbook-answer acceptance.

- API/Catalog/shared runners, chat owner/worker and Web installed source
  `c2ce4fbfca0bc0a1b072d8ea57f852fa4300f41a`. Web installed RECORD verifies
  44 runtime files. The normal API release pipeline passed metadata, existing
  migration head `20261008_0049`, role admission and real API OS isolation.
- Chat protocol 4 explicitly pins released retrieval policy
  `accessrev_4f62f8b4c4544443a9d0a809dd1c0bb9`, hash
  `sha256:bf35bc53cd756efdff81fe4154a639968083b5d91932bdc09deaa439b32fcbc0`.
  Same Codex model `gpt-6.1-sol`, CLI 0.160.0 and enrolled dedicated identity.
  Source-derived owner/worker OS isolation PASS; native calls during install 0.
  Existing six-slot settings/auth, DB schema and historical rows were unchanged.
- Before rollout: 18 completed chat receipt identities/hashes captured; chat
  capacity unclaimed, held workflow leases 0. Three nonterminal September job
  records were classified as history, not repaired or marked successful.
- Verified retained API rollback wheel set:
  `/tmp/eom-api-build/7fb311fbfab683f9b3cf4cea123812e1f4e62591.0VRKuh/dist`.
  Its three wheel hashes match the preceding deployment record. Retained Web
  rollback source `926f3791677ddea13ef56204305127e2aa612241`, wheel SHA
  `bca90348c2f09fd358ceadf17481152189013d749794040d37805f4aaf9d2289`.
  Prior chat nonsecret model configuration SHA
  `sha256:cee8de0ae1f45b0041c4f896852035e63ba4ddbeb4a57977c0152cc82ad54fcc`.
  Protected predecessor-unit/config checks passed before atomic replacements.

## First actual canary

One model submission through authenticated HTTPS, conversation
`chat_77a99837ed12820effc6b3978f679e4c`, turn
`chatturn_d5823e787bfa66e0f13df6f76b0f4519`.

Canonical outcome is FAILED / `CODEX_PROTOCOL_INVALID`, not accepted answer.
Its validated result is Artifact `artifact_61a94be3fb204663892114d3f56efa7a`,
revision `rev_62b6ee8cac41461d87697d754bf99201`, member `chat/evidence.json`,
SHA `sha256:25b6e690fa290b9e3b41385eb8f158a4de4da365fc7c456d8ec3d64eaf5ae9f6`.

One canonical RAG tool record was preserved: SUCCEEDED, three textbook sources.
Thus Catalog retrieval/publication worked; this does **not** prove a successful
native answer or diagnose the subsequent failure. Safe native metadata locates
the last event at `item/tool/call`. No generation replay, failed-history rewrite,
new role grant, direct DB mutation, GPU or HWPX execution occurred.

Two earlier browser attempts ended before any model submission. They are HTTP/UI
checks, not extra inference attempts. One reproducible UI race was identified:
New Conversation can invalidate an initial slot-read epoch and strand Send.
The existing read-only refresh owns the fix; a deferred-response regression
first failed and then passed. Entire Web suite: **281 PASS**.

Next: install the small tested UI fix and safe closed tool-failure diagnostics;
use a separately counted bounded canary to locate the failed boundary. Do not
publish prompts, raw native frames, arguments, error bodies or model reasoning
in logs/Git/Slack. Follow-up/pinned-evidence/historical-receipt live gates remain
pending until actual success.
