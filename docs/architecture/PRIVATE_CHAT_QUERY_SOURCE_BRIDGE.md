# Live Chat question source bridge

2026-10-17 UTC. Design before protocol/behavior. Not native execution admission.

1. Boundary: the existing Chat owner is `eom-general-chat`; the fixed numerical
   QUERY controller is `eom-workflow-runner`. Reuse the owner RPC transport with a
   separate read-only endpoint/profile. Do not give either worker DB/NAS/sudo,
   reuse a human password/token or broaden the existing API endpoint's peers.
2. Canonical source: existing conversation owner, active turn/claim/capacity and
   immutable user-message, prepared input and dispatch Artifacts. A supplied
   ticket/hash alone proves none of these facts.
3. Identity: one closed source-read family with MATERIALIZE_LIVE_CHAT_QUERY and
   AUTHORIZE_LIVE_CHAT_QUERY. Origin pins the derived actor, runtime, exact ticket,
   prepared-input/dispatch members and private basis; identity and semantic hashes
   remain separate. No caller/model-supplied actor or role is accepted.
4. Resolution: initial and fresh final live-claim checks; canonical prepared input
   and dispatch/ticket/policy closure; owned-message/hash resolution; exact last
   user text equality. Late owner/claim/pointer changes fail before disclosure.
5. Access patterns: indexed capacity/turn/conversation/actor lookups and bounded
   exact Artifact reads, not a history/corpus scan. Reuse the current tool-actor
   guard and canonical execution reader rather than duplicating claim semantics.
6. Structures: frozen origin/projection, closed commands/replies and existing
   bounded socket pool. No new table/index/cache/queue, mutable authority registry
   or source binding. Share the canonical worker-ticket schema, not another copy.
7. Complexity: O(indexed lookups + bounded canonical input/dispatch/question bytes).
   Each call is read-only, with no encode, Job allocation or Artifact publication.
   Authorization replies return metadata only; question text is temporary input
   materialization exclusively to the trusted controller, never public evidence.
8. Concurrency: existing capacity→turn locks and short transactions before/after
   IO. No SQL transaction spans Artifact IO. Do not renew an expired claim, use
   recovery as live authority, retarget a turn or retry numerical work on timeout.
9. Dependencies: Catalog/protocol own values; Chat application owns private-source
   resolution; its existing socket adapter owns peer checks/framing. Canonical
   worker-ticket resource is exposed through its protocol owner for composition.
   No infrastructure dependency is introduced into contracts.
10. Failure: exact current RUNNING claim required; mismatched ticket/policy/runtime,
    changed pointers/text, revoked actor, missing/corrupt members and invalid
    protocol fail with stable content-free codes. Failed replies disclose neither
    origin nor text. Read requests have no side effects and no automatic retry.
11. Alternative: numeric execution in the Chat owner violates its OS/runtime
    separation; accepting metadata as a grant bypasses actual ownership; giving the
    controller the existing API socket expands unrelated mutation capabilities.
    A distinct read-only profile on the existing server preserves all three limits.

The existing API listener remains unchanged. The private profile must admit only
the fixed QUERY controller peer, reject all ordinary owner/API messages and remain
default-off. Its separate fixed socket requires explicit protected provisioning;
do not add workers to groups or silently relax socket metadata to enable it.

This is source materialization/reauthorization, not a user session, Graph/source
retrieval grant, native policy/lease, actual execution or approval. The numerical
owner must still bind the origin into its original work, enforce public Catalog
permissions/Graph/policy/index pins and native-purpose admission. Historical reads
remain on the existing owned-conversation boundary; this endpoint cannot turn a
completed/expired turn into new execution authority.

## Verified source checkpoint — 2026-10-17 UTC

SOURCE_PASS / DISPOSABLE_DB_PASS / NOT_COMPOSED / NOT_INSTALLED / NOT_ACTIVE.
The application reader, closed read contracts, fixed-peer client and mutually
exclusive source profile of the existing RPC server are implemented. The existing
API listener and owner main composition are unchanged. No source socket, service,
OS group, database grant, migration, model run or consumer activation was added.

- Focused source/transport/legacy/contract/dependency regressions: **145 PASS**.
  These include real local Unix framing and kernel peer checks with synthetic
  source metadata, not production source permissions or numeric execution.
- Strict type checks: **9 source files PASS**; Ruff, format and shell syntax PASS.
- Existing guarded `chat-tests` purpose, extended by five source tests: **64 PASS**
  against actual disposable PostgreSQL. Current actor revocation before/during
  file reads, claim expiry, terminal-history rejection and unchanged row/Artifact/
  Job/expiry state were checked. Catalog retrieval and model ports remain synthetic.
- Exact Artifact substitution test first reproduced a real reader gap: identical
  canonical bytes/hash from another revision were accepted. The shared execution
  reader now validates the original Artifact ID, revision, member, media and hash
  plus the canonical schema family before reading. The family map is owned once
  by protocol and reused by the actual Artifact resolver and reader.
- The first disposable run recorded 60 passing cases, four failures and five
  teardown errors. The first new read test passed, but its generic V1 teardown
  tried to resume V4 work with a different policy. The new fixture now closes its
  own work via supported completion with its original pinned identity. No runtime
  policy/state invariant was weakened; the failure logs remain preserved.
- Both disposable databases were removed through the guarded marker/manifest
  cleanup. Original failed test evidence is retained at
  `/opt/eom/embedding-benchmark-os-evidence/private-query-source-kiQKW44H`.
  Final evidence is retained at
  `/opt/eom/embedding-benchmark-os-evidence/private-query-source-final-M3L3qU0u`;
  operator raw SHA-256 `13a6cd01e1dbbe5cba8abe4a850037bd971da22972208599d6ed83cb2c58b1cc`,
  final test stdout raw SHA-256
  `6e4f516b86db9c7f9d040d0e227848668dce5a66f5b9d3ea127392c2d049c212`.

Remaining: protected source socket provisioning/default-off main composition;
original-work numeric admission and purpose/lease binding; actual private QUERY
execution, canonical context delivery, worker tool/history integration and bounded
installed/live acceptance. This checkpoint does not close C4, other consumers,
CPU/CUDA comparison or the full incremental-RAG goal. The separate original HTTP
canary still reported LOGIN at 14:05 UTC; this source gate did not use or replace
that human session or submit another HTTP preparation request.
