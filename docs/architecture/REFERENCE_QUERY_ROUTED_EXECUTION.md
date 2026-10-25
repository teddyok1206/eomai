# Routed reference QUERY execution

2026-10-25 UTC. Continuation of the approved GPU-preferred goal. No unrelated
review findings or new search engine are in scope.

1. Responsibility: compose the existing original-selection admission, parent
   route, QUERY START/Runner, finite GPU group and fixed CPU launcher. Neither
   numerical workers nor the transport implement scheduling or persistence.
2. Canonical source: the actual operator and released Catalog policy resolve
   pinned Graph, accepted analysis/profile and exact CPU/CUDA index revisions.
   Each device's complete population must match before a routed selection.
3. Identity: the existing preparation manifest pins one original parent. Child
   Workflow keys derive from its immutable ID and ordinal. No new identity is
   issued on a timeout or replay, and old FAILED records remain FAILED.
4. Resolution: every operation reauthorizes the genuine captured operator and
   checks all canonical policy/bundle/source/index hashes. A route to CPU requires
   the original real PRE_EXECUTION BUSY/NOT_STARTED observation, not an exception.
5. Access: one indexed parent lookup, keyed ordinal membership and ordered child
   iteration; at most 32 anchors. No full corpus scan for identity lookup.
6. Structures: tuples for original order, maps for child IDs, a finite Condition
   barrier for collecting prepared inputs, existing append-only parent/Workflow
   histories for persistent state. No extra queue or mutable permission cache.
7. Complexity: O(anchors + native inputs) preparation/binding; numerical cost is
   separate. Keep file bytes only at the existing staging/validation/commit
   boundaries. Share small immutable values instead of copying full results.
8. Transactions: current source/claim roots close before a barrier or inference.
   Existing official START and native allocation remain atomic in their owners.
   GPU children share the current finite channel. CPU fallback gathers the
   existing fixed-CPU prepared inputs, canonically binds all original children,
   then uses the unchanged numerical launcher. After a restart, an already-bound
   child validates its exact original binding and current lease without waiting
   for already-completed siblings to rejoin.
9. Dependencies: application owns composition and barriers; Catalog resolves
   sources; Orchestrator persists validated metadata/Artifacts; fixed infrastructure
   owns CPU/systemd/GPU. Domain/schema packages do not import those adapters.
10. Failure/replay: completed GPU children are read through existing canonical
    completion owners, never by reviving an old root. An allocated but unconfirmed
    GPU invocation stays pending for supported reconciliation. CPU pending work
    retains its original key/launch and actual capacity rules. No authority/hash/
    partial-execution error triggers fallback. All barriers are bounded and wake
    on failure; no worker-to-worker communication is introduced.
11. Alternatives: re-running old `prepare()` would select latest index revisions;
    reimplementing the CPU executor would fork its mature checkpoint/recovery
    rules. Instead add a small typed CPU execution strategy at the existing
    adapter boundary and share the same pure QUERY batch-binding constructor.

## Transport boundary

The old reply requires a real Workflow ID for PENDING. Routed preparation can
validly exist before physical allocation chooses a device and before child START.
Do not fabricate Workflow IDs or quietly weaken the released reply. A versioned
opt-in reply must explicitly identify preparation-stage pending and the original
small preparation pointer. Define its JSON Schema first and update receivers
before activation. Existing CPU1/2 and private-chat behavior remain compatible.

## Gates

Pure binding and current-route tests; simultaneous barrier join, interrupted and
already-bound replay; unchanged fixed-CPU execution regressions; disposable
PostgreSQL atomic START/claim/bind/rollback; installed wheel and dependency
checks. Live CUDA, actual kernel BUSY-to-CPU, unchanged image allocation, paired
coverage, throughput, default and rollback remain separate acceptance evidence.
Source tests alone do not close the GPU goal or permit the post-checkpoint review.

## Shared application/source checkpoint — 2026-10-25 UTC

The CPU adapter is a small typed strategy around the existing fixed launcher,
not a copied QUERY executor. The finite CPU barrier uses original indexed parent
history, binds input order before models, and uses explicit per-child fenced
transactions when another Runner leads. Already-bound replay does not wait for
completed siblings. Current source denial/interruption wakes all pending joins.
The original CUDA binding bytes, current-child authorization, purpose-only Runner
composition and canonical completed-read owner are shared rather than forked.
The original CPU constructor/public entry and document CPU-route error stay compatible.

- Fixed CPU execution regression: 32 PASS,79.19 seconds (r2 native-strategy log).
- Shared binding/source/CPU adapter/dependency tests: 33 PASS,26.54 seconds.
- Existing current-session runtime/private-chat/completed-read composition:
  59 PASS,107.14 seconds. These overlapping suites are not summed as unique tests.
- Guarded disposable PostgreSQL: new CPU barrier/current source denial/expired
  gather/already-bound replay/explicit cross-thread original lease/interrupted
  bind rollback plus existing document fallback and finite CUDA Runner/publication
  recovery: 23 PASS,273.40 seconds, cleanup EXIT0 (`r53`). Root/IAM/numerics are
  explicitly synthetic leaves. Earlier `r52`15 PASS is preserved, not added to23.
- Strict mypy twelve production modules and scoped Ruff checks PASS.

Initial `r50` selected a nonexistent test path and ran no tests; cleanup passed.
`r51` reused one synthetic batch ID across unrelated fixtures, correctly causing
five conflicts. The fixture now assigns an ID once per independent case and
preserves it for every replay. No production invariant/dialect guard was relaxed.

The routed execution/transport wrapper and live query acceptance remain pending.
On future intake, verify both device-index populations and graph epochs explicitly;
a GPU-only latest index must not be treated as a ready CPU fallback or silently
intersected with an older CPU population. Full default activation still depends
on the approved exact-pair/current-source boundary.

## Actual INDEX rollout, not QUERY acceptance

Metadata/source and root controller release `8b0ddddeddfb95462d06c2d76d9849240dac0110`
is active for the existing mixed+legacy three-view scopes (six namespaces), maximum
16 targets. Service revision `localindexservicerev_1ae620ab1c7846f29083b60edd974849`,
invocation `73d378f5b6df4369b87adbe198917409`. The qualified numerical prefix, API,
Web and installed CPU/private QUERY selections are unchanged. The previous four
INDEX/controller configuration files and original service reference are retained
for explicit rollback under `/var/lib/eom-gpu-full-index-8b0dddde/backup` and its plan.

The first mixed CONTENT_ONLY Workflow completed, followed by CONCRETE_FACETS;
METADATA_ONLY was running in the next read-only observation. A metadata refresh
may select one already available witness: BATCH_COMPLETED or a target bound of16
does not alone prove sixteen model forwards or full paired coverage. Numerical
and per-namespace population evidence are still required. Evidence:
`/tmp/eom-full-index-activation-20261025.log` EXIT0 and
`/tmp/eom-full-index-observation-20261025-r2.{json,status}` EXIT0.
