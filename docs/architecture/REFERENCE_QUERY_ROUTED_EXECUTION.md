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

The concrete successor is prepare request/reply3.0. Old single requests keep
their bytes; an explicitly selected routed owner can return reply3.0, bound to
the exact original request family. Request3.0 is a finite1–16 envelope of the
existing single requests, not a recursive request, source authority or queue.
Reply3.0 carries the small preparation pointer, parent hash, selected device and
ordered per-child Workflow/selection pointers. Before physical allocation it
can truthfully be PENDING without a Workflow. The API/Web reference-start reply
therefore needs an additive successor for preparation-stage pending; version1
remains closed. Receivers precede activation. Private chat is not routed here.

One existing service-owned finite driver handle runs the routed batch; it does
not retain an unbounded task/capture registry. Same-key observation reauthorizes
the actual operator and original pins. A busy handle leaves original preparation
pending, not failed or re-keyed. HTTP timeout does not submit a new logical request.

The source parent contract can represent32 anchors, but this first installed
transport intentionally caps16. Each child needs a Runner plus heartbeat thread;
32 would exceed the existing64-task metadata service once its supervisor,
driver and socket handlers are included. Retain64 tasks/1GiB and the numerical
deadline; split larger caller cohorts into separate finite intents. The two
existing fixed control/work-batch staging directories are the only additional
writable service paths. Read-only layout/mount preflight runs before admitting
a human operation. Do not grant the metadata service GPU devices or model imports.

### Continuous exact-pair coverage

The routed INDEX coordinator previously discovered new work only through its
CUDA namespace. Its CPU runner could drain old work, but never discover new
standby coverage. After a confirmed completed GPU child, and when GPU discovery
has no numerical work, invoke the existing CPU reconciliation facade to enqueue
bounded missing CPU bindings. The existing CPU Runner drains them on its normal
next turn. This is explicit standby-index maintenance, **not** a claim that GPU
was BUSY or a CPU fallback result. No new policy, queue, schema or identity is
invented for this already-supported CPU indexing use case. Both current service
grants still apply. GPU execution stays the primary numerical discovery path.
Incomplete pairs stay unavailable to new routed queries until both full target
populations match; existing pinned query history remains readable by its owner.

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

At this shared-code checkpoint the routed wrapper/transport was still pending;
its successor source progress is recorded below. Live query acceptance remains pending.
On future intake, verify both device-index populations and graph epochs explicitly;
a GPU-only latest index must not be treated as a ready CPU fallback or silently
intersected with an older CPU population. Full default activation still depends
on the approved exact-pair/current-source boundary.

### Routed receiver/application source checkpoint

The successor preparation3.0, finite1–16 request envelope, truthful pre-Workflow
reply and API/Web reference-start2.0 pending adapter are implemented. The original
single requests and reply1/2, accepted Item command, CPU launcher and private-chat
selection remain compatible. The installed entry explicitly opts into owner3.0;
the original configuration decoders remain closed. One existing finite driver
handle is shared, without another queue, background authentication cache or
numerical import in the metadata owner.

Source evidence (overlapping suites, not summed):

- HTTP/socket/current-capture plus application/family/configuration:89 PASS.
- API/Web/schema/release alignment and current-session/private runtime:105 PASS.
- Receiver/package/dependency focused regression:115 PASS.
- Final focused message/current capture/API/Web pending adapter:81 PASS before
  the final additive authority-denial negative; rerun recorded separately.
- Strict mypy23 production modules, scoped Ruff/format and diff checks PASS.
- Disposable PostgreSQL r54:12 PASS,26.86seconds, cleanup EXIT0, including
  concurrent re-observation of allocated-but-unknown original requests.
- Disposable PostgreSQL r55:49 PASS,237.78seconds, cleanup EXIT0, covering existing
  atomic preparation, finite CUDA Runner/publication recovery and CPU service
  reconciliation. Its numerical/root/IAM leaves are synthetic.

The new source is not itself an installed QUERY release or GPU-default approval.
Cold unknown CUDA work still stays pending for supported reconciliation; no
fresh root/CPU permission is inferred. Completed outputs reauthorize through the
canonical completion reader without a redundant submission-resolution pass.
Actual INDEX source/policy pins remain8b0dddde until a safe drained rollout.

The additional paired-parent1.2 PostgreSQL execution/completion/exact replay
case passed in37.13seconds, cleanup EXIT0 (r59). Its initial synthetic conversion
omitted source classes/used overlapping dummy index IDs; r56 used the deliberately
closed1.0 key helper, r57 retained OPTIONAL vectors, and r58 retained scalar-fixture
row views different from the selected index views. Fixtures now faithfully use
the public family helper, REQUIRED vectors and exactly selected views.
Predecessor or successor validation was not relaxed. Those failed test logs remain.

Final focused receiver/finite carrier/current-session runtime/namespace staging/
API/Web/OpenAPI tests after the16-child cap and two fixed writable paths:
155 PASS,41.06seconds. Earlier overlapping suites remain historical evidence, not
additional unique tests. Real numerical GPU QUERY/default/rollback is still pending.

### Coverage is a live preparation gate

The11:28:45 UTC technical metadata audit found the following current binding
counts on the current Graph. This is not canonical human-authorized pair
resolution or permission to narrow/intersect the corpus:

| Projection | View | CPU | CUDA |
|---|---|---:|---:|
| mixed2.0 | CONTENT_ONLY |521|1|
| mixed2.0 | CONCRETE_FACETS |457|117|
| mixed2.0 | METADATA_ONLY |521|16|
| legacy1.0 ALL_ADMITTED | CONTENT_ONLY |520|17|
| legacy1.0 ALL_ADMITTED | CONCRETE_FACETS |457|117|
| legacy1.0 ALL_ADMITTED | METADATA_ONLY |520|no current index|

Eligible source metadata reports546, not a promise that all546 have every
accepted report/view. Different view availability and missing reports are
explicit. Exact CPU/CUDA source/profile/input target equality is required per
view. Ordinary installed CPU queries remain available while coverage catches up.
Evidence: /tmp/eom-current-index-pair-metadata-20261025-r1.json, EXIT0.

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
