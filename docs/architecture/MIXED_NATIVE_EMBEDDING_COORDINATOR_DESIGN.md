# Mixed native coordinator continuation

2026-10-19 UTC. Source-only continuation of the mixed native carrier design;
not an installed owner, current source permission or physical execution proof.

1. Responsibility: connect exact request2/intent2 to the existing four-phase
   Orchestrator coordinator, without a second state machine or scheduler.
2. Canonical source: original protected-owner request, original Job/event intent,
   immutable allocation, actual registry command/result and receipt carrier.
3. Identity: checkpoint2 is independent from checkpoint1. Native metadata Job2
   uses ownership2's exact protocol/hash; computational encoding Job/input/result1
   and their original allocations remain unchanged, including borrowed history1.
4. Pointers: source-plan2, registered index/command/result2 and receipt/output2
   retain their exact raw/semantic hashes. No retagging old values or latest lookup.
5. Access: one exact Job key, ordered Job events and bounded four-record replay.
   Actual owner/source/lease fences precede this continuation read/append.
6. Structures: separate frozen checkpoint2 and payloads, shared original producer
   allocation and small pure order/identity/time checks. Existing Job state/event
   table and fixed transition mapping are authoritative; no new queue/DB/schema.
7. Complexity: O(4) metadata reads/validation and fixed16KiB checkpoint frames.
   No source text, vectors, numeric rows or credential copies are carried here.
8. Concurrency: the actual non-savepoint owner root and existing Job row lock
   serialize append. Same checkpoint replays; changed/foreign/skipped records fail.
9. Dependency: Workflow pure contracts validate schema first; Orchestrator owns
   Job reads/writes. Shared supported request/intent protocol selection is pure,
   not a caller-selected validator or a grant. No runner/repository changes here.
10. Failure: wrong request/intent/protocol/hash/phase/producer/time/result/output
    cannot advance. Failed/cancelled original Job outcomes remain visible; no new
    keys or allocations are created on reentry or borrowed from another family.
11. Alternative: widening checkpoint1 or labelling intent2 as encoding-job1 would
    redefine immutable history. Duplicating the coordinator would split one real
    state machine. Add only an explicit metadata2 branch to the existing owner.
