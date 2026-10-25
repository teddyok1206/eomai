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

### Completed Catalog reads must select the original device too

Pre-activation review found that installed Catalog completed-result reads still
pin only CPU native controls. Merely activating routed QUERY would therefore
compute CUDA results which the existing Item/read/publication path rejects. Add
an opt-in reader-configuration3 wrapper around the unchanged CPU reader1/2 plus
exact CUDA document space/native-policy/bundle pointers. Define the closed JSON
Schema first. Old configurations and original CPU/private history remain valid.

The installed Catalog owns both read-only device configurations. After actual
operator fencing and exact completed-Workflow selection, choose the matching
owner from that stored original request's device, never a caller-supplied device
or latest index. Canonical policy/bundle validation and every current source,
permission, Artifact/hash and completed-output check still apply. A missing
device configuration fails explicitly; it is not a fallback or a compute grant.
The shared completed-reader constructor also serves Item publication and stored
authoring/review materialization, preventing parallel per-consumer rules.

Use two bounded immutable configuration values and O(1) device selection; no DB
schema/index/cache/queue, new worker permission or CUDA import in Catalog. The
original completion key/revision/hash remains unchanged across replay. Startup
validates both canonical controls; each read retains its current authorization
transaction. Preserve failed history and CPU rollback selections. Allowing the
old CPU owner to trust an arbitrary stored CUDA policy would silently broaden a
released boundary, so explicit installed successor selection is required.

### Metadata-only INDEX publication before physical allocation

The 2026-10-25 live INDEX trace exposed a costly ownership mismatch: refreshing
membership from already committed numerical rows acquired a physical GPU even
though the common executor correctly performed no forward. Keep the existing
preparation, source admission, atomic START, Runner and index publication owner;
send an explicitly observed membership refresh to a compute-forbidden execution
adapter before constructing a physical batch parent. Its exact original request
and runtime controls are pinned, and any request for numerical execution fails
closed. It neither reports GPU BUSY nor creates a CPU fallback or GPU compute
receipt. Current source/permission/hash checks and immutable vector space remain.

Use the existing reconciliation idempotency key to recover that same queued
publication after interruption. Numerical routed jobs retain their original batch
key and allocation/recovery path. Key comparison is O(1), membership publication
keeps the existing bounded O(n + artifact bytes) registry/manifest work; no new
schema, queue, index, cache or persistence model is introduced. Preparation and
START remain separate authorization roots. Disposable DB tests must cover same
key concurrency/replay, interruption and preserved terminal history. A second
metadata pipeline or weakening source validation would duplicate the owner and
is not an acceptable alternative. The change does not stop active GPU work.

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

### Standby source rollout and metadata-publication correction — 2026-10-25 UTC

Source `91a8894ea530189795cfdc5bc28efe86339c89a8` is installed and active for
the six existing INDEX namespaces, maximum16. Invocation
`6211aa1136d54e1791e337893394c5dd`, started12:19:13 UTC. The preceding source
finished its current work normally before the successor was activated. The first
drain checker incorrectly counted historical RemainAfterExit active/exited units
as live work and stopped before activation. Its failure is preserved; the resumed
read-only check verified process0, no held native FDs and no original nonterminal
Workflow before selecting the successor. No numerical unit was forcibly killed.
Evidence: `/tmp/eom-standby-index-activation-20261025-91a8894e-r2.log`, EXIT0.
API/Web/CPU-private QUERY and qualified numerical prefixes stayed unchanged.

The subsequent source correction routes explicitly observed membership refreshes
through the existing atomic reconciliation START/Runner and canonical completed
reader, using a compute-forbidden adapter instead of a physical GPU allocation.
The original reconciliation key also identifies interrupted metadata work. Failed
history is returned unchanged; successful replay checks its actual registered
completion and does not claim or compute again. This is metadata publication,
not GPU success or GPU-unavailable CPU fallback. Numerical discovery still uses
the original routed batch key and physical allocation.

- Focused adapter/namespace/reconciliation/executor/runtime tests:91 PASS,
  30.47seconds (`/tmp/eom-membership-publication-focused-20261025-r2.log`).
- Disposable PostgreSQL:28 PASS,280.41seconds, cleanup EXIT0 (r60), including
  independent-root submission of the same retained preparation, reauthorization
  after interruption and membership publication/crash recovery with numerical
  execution forbidden. IAM/model leaves remain explicitly synthetic; this is
  not a live CUDA or human-session acceptance.
- Strict mypy3 production modules and scoped Ruff PASS. No new dependency,
  schema, migration, persistent queue or cache was introduced.
- Dependency/current-source/CUDA-CPU adapter and QUERY-runtime regression:
  36 PASS,21.98seconds (`/tmp/eom-membership-publication-boundaries-20261025-r2.log`).
  The initial command named a nonexistent test file and ran no tests; that
  invocation log is preserved separately and is not counted as acceptance.

These source tests do not complete full paired coverage, actual GPU QUERY,
GPU-default/fallback or rollback acceptance. The externally supplied12+4 static
review remains unopened until the full GPU goal and live release checkpoint.

### Completed-read device successor source evidence

The closed reader configuration3.0 has canonical/resource mirror SHA
`b3cb23f75186fbc219bf0c5c11bcda218197e954e2a541e73205f2ffc2307f53`.
It explicitly wraps unchanged reader1/2 CPU controls and separate CUDA space,
native policy and bundle pointers. The nested family is a discriminated union;
unknown/extra authority fields, ambiguous bytes and missing/mismatched controls
are rejected, not interpreted as CPU fallback. Protected runtime composition
validates canonical policy/bundle bytes before constructing two read-only owners.

The common completed-reader constructor selects from the original stored request
for direct reads, Item context publication and stored authoring/review reads.
The standalone read service selects the same device owner before resolving exact
index revisions. It never widens a CPU native-policy pin or chooses latest.

- Source/legacy/mixed/runtime/common reader/dependency regression:123 PASS,
  117.04seconds (`/tmp/eom-gpu-completed-reader-regression-20261025-r3.log`).
- Final closed configuration/model-copy negatives:16 PASS,6.99seconds
  (`/tmp/eom-gpu-completed-reader-contracts-20261025-r4.log`); these overlap the
  larger suite and are not summed as unique tests. Strict mypy5 modules PASS.
- Disposable PostgreSQL r61:2 PASS,69.83seconds, cleanup EXIT0. The new actual
  Runner/publication case reads two original CUDA children through a CPU+CUDA
  Catalog reader, replays concurrently without another dispatch and denies
  revoked current authority. The existing paired-parent Runner replay also PASS.
  Root/IAM/numerics remain explicitly synthetic; no live GPU acceptance is claimed.
- The existing unstarted-cancellation suite was correctly skipped17 cases in r61
  because its additional opt-in was missing. It was then run explicitly against
  another disposable DB in r62:17 PASS,8.92seconds, cleanup EXIT0. This covers
  cancellation/claim races, interruption rollback, exact replay, owner checks,
  started work refusal and one immutable cancellation receipt.

Initial reader runs exposed a missing mixed-type import and a nondiscriminated
nested union whose external schema exceptions did not choose the right branch.
Both are corrected; failed logs are retained. Predecessor schemas and production
validation/authority were not relaxed. The reader successor is not yet installed
or activated and does not itself complete the GPU goal.

### Actual membership-only INDEX successor activation

At12:58 UTC the installed INDEX source became
`ca0beb2c5502117949eca1a823f83d358022a00b`, service revision
`localindexservicerev_084877747e944cf2855f2b66484c256a`, invocation
`ca583a2b415d4582a4fedeefedcb4207`, maximum16 in the same six namespaces.
The numerical prefixes and API/Web/CPU-private QUERY remained unchanged.
Evidence: `/tmp/eom-membership-index-activation-20261025-ca0beb2c-r2.log`, EXIT0.

The preceding source completed its current GPU work normally but its standby
discovery had queued one still-unclaimed CPU request before observing shutdown.
The first drain correctly refused activation with that nonterminal row present.
Read-only classification proved REQUESTED/PENDING, attempts/generation0,
no lease, no step and no failure. After r62's disposable concurrency/replay tests,
the existing public owner-maintenance use case cancelled exactly that unstarted
request, retaining its original request/key and append-only receipt. No direct
row repair, scientific content deletion or failed-to-success transition occurred.
The two original completed GPU Workflow metadata and the original failed64
Workflow metadata were unchanged before/after. Same-command replay returned the
exact receipt `d8714ea81bac6b64a88b0ef28432e0a267126ed65bc6c1a7978f734c0c78135b`.
The final check found zero preceding nonterminal Workflows and zero held GPU FDs
before the staged successor was selected. Previous configuration and service
reference remain in `/var/lib/eom-gpu-standby-index-ca0beb2c/backup` and its plan.

The source process had reached its1GiB cgroup ceiling, but observed cumulative
memory stall was only0.35seconds and current pressure0; this is not evidence that
memory pressure caused the long reconciliation. No active memory cap was changed.
Reconciliation wall time includes source/control validation, publication and CPU
standby discovery and is not a numerical GPU-forward timing or throughput claim.

### Compatible receiver rollout and retained-handle correction — 2026-10-25 UTC

API/platform/Web, the CPU/private QUERY provider and the Catalog dual-device
reader were installed from `06b5d0e9`. Official API RECORD/isolation and Web
service-identity integrity passed; HTTPS readiness returned200. GPU-default
QUERY and authenticated numerical acceptance are still pending. The initial
QUERY-selector guard omitted the reviewed prepare/3.0 client delta; the exact
one-member old/new hashes were checked against the source diff and six pure
selector tests passed before the supported selection continued. Initial
read-only preflight/selector/startup-health failures remain recorded, not PASS.

During this rollout PID1 renumbered its retained GPU-lock descriptor from278
to3249. The original GPU worker actually ended successfully; its root controller
then failed because retained-resource validation incorrectly equated a historic
descriptor number with physical identity. Supported read-only terminal
observation reproduced that failure. A separate public terminal-resource read
proved the same device nodes, lease parent/file epochs, exact unit FD store and
exclusive kernel flock remained held. The original INDEX service stopped and
its sixteen encodings remain unpublished; it must not be reported as continuous
or accepted numerical completion. No old failure or worker outcome is rewritten.

The correction keeps the original frozen observation and re-resolves the exact
unit's unique retained open description. Descriptor numbers are local handles;
the canonical physical identity is the protected lease/device epoch plus actual
exclusive kernel flock and unit FD-store membership. Missing/duplicate/lost or
different resources remain explicit errors. This is a local observer correction,
not a new GPU lock, permission grant or numerical runtime. Core reproduction
failed before the correction; relocated-handle and negative physical-fence
regressions protect the change. Runtime cutovers must additionally avoid an
in-flight control transaction until this corrected owner is installed.

The exact same-inode descriptor relocation regression failed on the predecessor.
Corrected retained-resource/lifetime/failure-reconciliation/owner-proxy/unit-policy
regressions:277 PASS,32.74seconds
(`/tmp/eom-pid1-fd-relocation-regression-20261025-r3.log`). Strict mypy for the
observer and scoped Ruff/format/diff checks passed. The first invocation selected
a nonexistent test path and ran zero tests; the second retained an obsolete
descriptor-number negative fixture (276 PASS,1 failure). Both logs are retained.

#### Unpublished-success maintenance boundary

The original worker exited `SUCCEEDED` but its source-owner publication never
completed. The old recovery/1.0 proves a failed numerical unit; using it here
would falsify history. Add an explicit recovery/2.0 maintenance message instead.
Responsibility stays with the existing root/schema-owner recovery application;
the canonical facts are the original protected successful retirement and the
separately failed original root-controller invocation. Pin allocation, numeric
and controller invocation, parent plan, Workflow/request/command/generation and
retirement raw SHA. Resolve exact files, outcome, unit policy, empty cgroups,
zero retained descriptors and immutable epochs; a DTO is never authority.

Only the expired, allocated, still-unpublished Workflow/launch/encoding rows can
close as an application failure with a distinct `RESULT_UNPUBLISHED` code.
Numerical `SUCCEEDED`, controller `FAILED`, historical failures and original
output bytes remain unchanged; no successful completion receipt is fabricated.
The existing bounded explicit encoding-producer successor can then retry an
unpublished failed producer under fresh service/source authority. It must not
reuse these uncommitted vectors or treat this as a GPU-BUSY fallback.

Access is indexed identity lookup plus ordered row locking and append-only
events, O(encodings), bounded1024; no new table/index, queue or binary DB value.
Physical retirement is an existing separate root effect; metadata recovery is
one short NOWAIT transaction with rollback on late physical/source mismatch.
The existing application owns transitions, the existing Orchestrator storage
owns events/retry edges, and the root adapter owns OS proof. Exact replay returns
the original failed receipt; it never repeats compute, retirement or publication.
The simpler alternatives—calling the old failed-unit proof, accepting local
files as canonical success or submitting a new identity while the old producer
is still RUNNING—violate outcome, publication or concurrency invariants.

Recovery/2.0's mirrored schema SHA is
`996997c8b36626556cda4b2b7e63d1b8d004e8d9ca87aef0b465f06d9e4d5746`.
The two concrete failure dispositions share the existing Workflow/native/encoding
maintenance transaction and bounded retry graph, with distinct events and codes.
An indexed original-receipt publication-intent guard refuses both complete and
incomplete existing publication, so valid canonical completion is never failed.
No released recovery/1.0 schema or original numerical checkpoint was rewritten.

Focused contract/retirement/coordinator/reservation regressions140 PASS,45.95s;
related routed-execution/publication/dependency regressions87 PASS,55.31s.
Disposable PostgreSQL r64:49 PASS,49.21s and cleanup EXIT0, covering both failure
dispositions, concurrent exact recovery, late-proof rollback, fresh-lease and
foreign-owner refusal, original identity/history, concurrent single successor,
same-request replay, and existing/incomplete publication refusal. These suites
overlap; OS/source admission in the DB cases is explicitly synthetic. Strict
mypy7 modules passed. Initial fixture/float-construction failures are retained.

Actual physical retirement used installed metadata source `129ff5dd` and the
existing original-terminal application, without model execution or Workflow DB
changes. The original numeric success and failed controller remain recorded;
held descriptors1→0. Evidence:
`/tmp/eom-pid1-lease-retirement-20261025-129ff5dd.log`, EXIT0; original retirement
raw SHA `94405a21f6dc2d7713c89b1ffb93f3fca3174c6c5cac9980a8f93708c989104b`.
The unpublished Workflow still needs the tested recovery/2.0 installed owner
before supported metadata closure and successor-runtime activation. GPU-default
QUERY, exact full paired corpus and the overall goal are not complete.

The first installed recovery/2.0 read-only preparation stopped before any DB
mutation with `INSTALLED_RUNTIME_REPEATED_BYTE_READ`: its exit fence attempted
to capture the same protected launch/allocation bytes twice. The reader now
captures those immutable bytes/epochs once, retains a small typed controller
observation, and re-observes only actual unit/PID/store/cgroup state at exit.
It neither adds a cache nor weakens the protected file owner. Actual temporary
protected-file read-once/late-tamper coverage plus the outcome-reader/contracts:
42 PASS,18.47s; strict mypy and scoped lint/format passed. Initial filesystem
fixture permissions were corrected to0700/0600, not relaxed in production.
Evidence: `/tmp/eom-unpublished-protected-snapshot-20261025-r3.log`.

### Original unpublished recovery and restored physical-owner alignment

The installed recovery/2.0 application from `04e36bbe` closed only the expired,
unpublished Workflow `workflow_aaeda70eab6c4bf7a1650c5fb7c72b02` as application
`FAILED/EMBEDDING_NATIVE_RESULT_UNPUBLISHED`. Its16 encoding producers closed
under the same disposition. The original numerical `SUCCEEDED`, root-controller
`FAILED`, planning history and older failed/completed Workflows stayed unchanged.
Exact command replay returned the same receipt without a model execution.
Evidence: `/tmp/eom-unpublished-recovery-install-20261025-04e36bbe.log`, EXIT0.

The same source became the INDEX/root-controller metadata owner and the explicit
image/trainer retained-resource guardian owner. Only the latter's two entry
installation values and matching configuration owner value changed; its19
numerical templates, worker bootstrap, models and device pins stayed unchanged.
Guardian/retained-resource regression302 PASS and pure selection4 PASS do not
claim an actual image-generation or trainer numerical run. API/Web/Catalog and
CPU/private QUERY remained the compatible `06b5d0e9` release. CPU/CUDA numerical
prefixes, Graph, migration and embedding-space identities stayed unchanged.
Evidence: `/tmp/eom-restored-index-activation-20261025-04e36bbe-r2.log`, EXIT0;
backups `/var/lib/eom-gpu-standby-index-04e36bbe` and
`/var/lib/eom-image-retained-owner-04e36bbe`.

Four other-revision nonterminal historical Workflows were classified and retained,
not silently counted as current executable work or marked successful. The current
queue predicate includes the exact service reference. A read-only inspection of
the old CUDA CONCRETE Workflow `workflow_b1c0a4cd2f8b4447a17df277d28c2a4f`
found no attached encoding association or exact BOUND parent; that stale row alone
does not justify a state-machine patch, fabricated retirement or failure repair.

### Bounded work-size correction after measured control-budget exhaustion

The restored INDEX invocation `d2fcb43fc95e45bca317640ebc18dc21` ended at
14:35:40 UTC with `EMBEDDING_BENCHMARK_CHANNEL_EXPIRED`. This was not GPU
unavailability: its16-row numerical worker actually succeeded, wrote65536 vector
bytes at14:34:29, and retired with zero retained descriptors at14:34:59. The root
controller subsequently failed before canonical publication. Preserve those
distinct facts; raw local vectors are not canonical accepted output.

Measured source-stage totals for this invocation:106 current resolutions,
246617 milliseconds combined, including candidate admission145217ms and profile
resolution46572ms. Preparation and final settlement share the original240-second
control allowance; numerical time remains separately bounded180 seconds. A full
16-row group therefore exhausted the420-second original channel. Logs:
`/tmp/eom-current-index-expiry-20261025-r2.json` and the original unit journal.

Use the existing owner5.0 `maximum_targets` setting to split subsequent groups
into8 targets. This is an operational work-size selection, not a new queue,
schema, service identity, source policy, permission cache or numerical runtime.
Keep both logical projections and all six namespaces; change only the two group
work-size values. In particular, do not renew the failed original deadline,
increase the pinned numerical budget or requalify a new embedding space merely
to accommodate metadata overhead. Existing grants remain unchanged upper bounds.

Canonical inputs remain pinned approved sources and controls. Access remains the
existing indexed queue/unique encoding reservation plus ordered finite batches,
O(targets) metadata;8 reduces per-root source work and trades some model-loading
amortization for completion headroom. No binary copy, DB schema or new index is
needed. The root-managed owner-selection file is captured at service startup,
outside the runtime-identity hash cycle; every new request pins its actual plan.
Change it only while the service and physical resource owners are stopped,
after the old unpublished Workflow is officially recovered with its original
retirement proof and expired command lease. Compare exact predecessor bytes and
epochs, save a recoverable backup, then replace that one selection and restart
the same installed service. No model/source/user authority comes from the file.

The previous16-row selection is the rollback target; already committed vectors
and all original failed records remain. Source/config tests alone do not show
that8 rows will finish: require an actual registered completion before declaring
the work-size experiment successful. A fresh failure remains explicit, never a
CPU fallback or silent re-key. GPU-default QUERY, complete exact device pairs,
authenticated multi-query/fallback acceptance and the post-checkpoint review are
still pending. The external12+4 review document remains unopened.

The expired16-row Workflow `workflow_2b164211a28d423a8239855f0badf9cf`
subsequently closed through the installed recovery/2.0 application, with16
encoding failures, exact replay PASS and no new numerical execution. Original
retirement SHA `ea6d9cd1ce1f3fc7f87b833965056aa8ee1413c465f3917102627e69e80bc0fe`
pins numerical invocation `134f32e8fb0542a587b1b2d1d01977ae`; original failed
controller invocation `2f69fde2f3844555a027fa09cc44f171` remains failed.
Recovery command SHA `4ce150f6c114e21df451041944fdfd3e6ee15ab5cae7d7c9a18188d39c00145d`.

The owner-selection before/after raw hashes are respectively
`e8c26f1f264384464dd7227bd479a95489df554c04d8323e86eab1b2b970924a` /
`7bbd9b6a657eb19c8f74723b0dc1600c61f273e98dea2b54138d1a7247fae71f`;
backup and selection receipt: `/var/lib/eom-index-eight-04e36bbe`.
INDEX restarted at14:51 UTC, invocation `6e792281a46a420898cdece549539ef7`,
PID227907. No daemon reload, numerical-prefix change, service/grant revision,
API/Web/QUERY restart or authentication change accompanied this selection.
Evidence: `/tmp/eom-index-eight-started-20261025-r2.log`, EXIT0.
The first operational selection stopped before file replacement because its
diagnostic used an assumed actor JSON key. It was corrected to the existing
public version-aware service-reference resolver; it did not repeat recovery or
alter rows. The original failed invocation and operator error logs are retained.

Pure work-size/configuration/unchanged lifetime/namespace tests64 PASS,13.26s;
the final two operational selection helpers11 PASS,7.40s, scoped Ruff/format
PASS. No core code, schema or persistence behavior changed in this selection,
so the prior recovery disposable-PostgreSQL evidence remains applicable; these
new helper tests are not described as additional live or DB-concurrency tests.

An unselected QUERY3 candidate was also validated against canonical published
CPU/CUDA native policies and routing controls using installed SDK04. Its API
provider remains the actual06 release; both public/mixed owners select04 and
private chat keeps the unchanged CPU base, with its existing pin rebound to the
new CPU base bytes, **not** to the routed wrapper bytes. Unit isolation and64-task/
1GiB bounds are preserved. Candidate generation and pure six-case selection
tests do not constitute activation, paired coverage or numerical acceptance.
Evidence: `/tmp/eom-routed-query-candidate-20261025-r1.log`, EXIT0;
candidate/rollback set `/var/lib/eom-query-routed-selection-04e36bbe`.
Slack milestone `devreport_57b7011f14f64ece931547a55a4bbbaa` reports ACTIVE,
not completion. The user-supplied post-checkpoint review and README cleanup are
still untouched.
