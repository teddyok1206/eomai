# Fixed benchmark checkpoint/ACK channel

2026-10-12 UTC. Source implementation boundary, not runtime or benchmark acceptance.
The canonical benchmark1.0 schema already defines the exact1/21-message phase program.
This note defines only its bounded local transport, not a command server or another queue.

1. **Responsibility:** the Catalog transport adapts one admitted AF_UNIX stream. Worker sends
   checkpoints and waits; owner validates local vectors/current authority and acknowledges.
   Orchestrator alone admits the launch and publishes results. No worker-to-worker communication.
2. **Canonical source:** the existing immutable invocation and checkpoint/ACK values are used
   unchanged. A completed transcript is small session evidence, not a copied vector file set.
3. **Identity:** bind execution ID, invocation SHA, ordinal and each checkpoint SHA. Actual peer
   PID/UID/GID and socket inode are observed independently; a parsed invocation grants nothing.
4. **Resolution:** require exact AF_UNIX/SOCK_STREAM, live held socket identity and expected
   SO_PEERCRED. A mandatory caller-supplied peer fence additionally checks the admitted process/
   starttime/unit/cgroup association. No default fence or request-selected path/peer authority.
5. **Access:** one ordered duplex exchange, bounded read/write, exact expected-sequence lookup;
   one outstanding checkpoint per side. No history scan, reconnect or transport replay.
6. **Structures:** fixed state counter plus one pending typed checkpoint, tuples at transcript
   completion, one length-prefixed frame. Domain association rules stay in existing contracts.
7. **Bounds:** four-byte big-endian length then canonical UTF-8 JSON,1..64KiB per frame. Reject
   announced overflow before allocation. One absolute monotonic deadline, no read/chunk timeout
   resets; caller supplies a remaining unit deadline≤180s. Memory O(frame+21 metadata records).
8. **Concurrency:** one thread uses each endpoint. Nonblocking per-call socket flags avoid
   changing a shared descriptor's blocking mode. Require Python socket timeout `None` or `0.0`
   before and after every peer fence/IO: a positive timeout invokes CPython's own pre-select
   even with `MSG_DONTWAIT` and can exceed the absolute deadline. Reject rather than change
   this shared mode. No SQL transaction spans socket waits/inference.
9. **Dependencies:** no third-party dependency. Existing contract parsing/serialization and
   checkpoint/ACK association validators are shared with the full session validator. Application
   owners inject transports; numerical backend/worker receives no DB/NAS/auth/token data.
10. **Failure:** EOF, malformed/noncanonical frame, wrong peer/epoch/phase/hash, deadline or owner
    continuation failure invalidates and closes only this owned endpoint. No retry/fallback. The
    owner reconciles the original launch/capacity; channel close is not process/device cleanup.
11. **Simpler alternative:** EOF-delimited one-message chat transport cannot represent21
    checkpoints; final process exit cannot measure cold separately from warm/query. A bounded
    fixed channel is sufficient, without a generic broker, arbitrary dispatch or new schema.

The owner endpoint requires a second mandatory continuation fence before every ACK. It receives
the exact checkpoint; for QUERY_PREPARED, the owner starts its wall clock before fresh source/
session/command authorization. For ready phases it validates the closed member/bytes and stops
the appropriate clock before ACK. These real callbacks and vector/unit/device checks are not
implemented by the framing adapter and cannot be replaced with saved actor IDs or a successful
DTO. Synthetic tests use explicitly synthetic fences, never installed/source acceptance.

Proposed source: additive pure association helpers in the existing benchmark contract module;
`eom_catalog_service.embedding_benchmark_channel` with worker/owner endpoints composed over one
private bounded frame adapter; focused contract/session/socket tests. Historical schema bytes,
index3FD behavior, backend/model factory, old transport and deployed units remain unchanged.
Actual protected endpoint creation, exact peer/unit association and both real continuation
callbacks must be composed before native benchmark admission. A source transcript does not
prove that an actual CPU/GPU launch, cold/warm timing or authorized query ran.
