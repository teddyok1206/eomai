# Codex runtime update and execution compatibility

Status: implementation decision, 2026-10-10 UTC. This is not a claim of live acceptance.

## Responsibility and boundary

Codex advertisement, operator admission, actual execution, and content quality are different
claims. Native `model/list` remains an observation, and existing preset `NON_LIVE` validation
remains an argument/contract test. Neither is renamed to an inference acceptance test.

The Orchestrator owns a maintenance-only compatibility use case. It checks the installed
CLI surface, reports the latest stable official distribution without installing it, and
sequentially submits small synthetic structured-output/vision probes through the existing
fixed worker adapter. The CLI validates presentation input and calls that use case. Workers
return local results; only the existing Orchestrator Artifact publisher commits evidence.
No external LLM API, copied authentication, new queue, service, or DB migration is needed.

## Canonical sources and identities

The root-owned CLI and fixed worker executable are the runtime sources. Each report pins
their version/hashes, the compatibility contract hash, and the source release commit.
An immutable request has a `codexcompat_` run ID and ordered `compatcase_` case IDs. Each
case pins slot, account binding/resource version and immutable assignment revision, model,
and existing reasoning-effort enum.
A worker execution has its own `job_` ID; it is not an invented production execution plan.
The additive `codex-compatibility-invocation/1.0` contract is separate from the unchanged
resolved-plan `codex-invocation/1.0` contract. Invocation, request, and result hashes remain
separate from all logical and revision IDs.

The canonical report is an approved Artifact revision published by the existing control
file-set use case. Installing a capability policy resolves that exact typed member pointer,
checks schema/media/hash/lifecycle and successful publication, then checks current runtime
identity and freshness. A local JSON file or self-calculated hash is not an admission receipt.

## Access patterns, structures, and scale

A request contains at most 64 ordered cases and a matching model-call budget. Frozen typed
tuples preserve order; sets reject duplicate IDs and model/effort/binding triples in O(n).
Runtime identity is hashed once per epoch and checked before subsequent launches. Results
are bounded small JSON; raw logs and binary inputs stay in existing local staging and are
not stored in DB rows or Git. Existing indexed binding, Job, Artifact, lease, and publication
lookups are reused. No new persistent derived cache/index is introduced.

## Concurrency and maintenance

Unknown models cannot pass ordinary production admission before being tested. Therefore
this operation has separate, explicitly diagnostic authority and only runs in a quiescent
maintenance window. It does not broaden the production allowlist to obtain a worker lease.

Before any call, the fence holds the existing PostgreSQL host-capacity advisory lock at
session scope (short read transactions, not a long transaction). Production Codex producer
units must be stopped, held/reconciling worker leases and executable jobs/control commands
must be absent, and fixed worker/helper units plus the independent general-chat claim must
be quiescent. The fence is checked before every launch; probes are sequential. It refuses
busy systems instead of stopping an active job or guessing whether a timeout completed.
Service stop/start belongs to the reviewed operator maintenance wrapper, not domain logic.

The existing fixed worker unit timeout remains its documented upper bound. A probe uses a
tiny deterministic task, but expected short latency is not a new timeout guarantee. A
runtime/fence mismatch stops new launches and retains the existing checkpoints without
claiming a completed report. A conclusive probe failure records FAIL and remaining NOT_RUN.

## Failure, replay, and publication

The request is durably staged before inference. Each case gets an immutable execution ID
and a start marker before launch, then a validated checkpoint after completion. Exact run
replay must reuse completed checkpoints; a started case without a conclusive result is an
explicit uncertain execution and must not automatically launch again. Failed executions
remain failures. A new approved diagnostic run may be requested separately.

Tiny tasks test strict model/effort invocation, sandbox flags, valid structured JSON, an
unconstrained arithmetic answer, and interpretation of a staged synthetic PNG. The expected
answers are not forced by the output schema. PASS means those execution checks passed for
that binding/runtime/pair, not full authoring/review quality or provider-model identity.

Policy admission is a separate root operation. Only pairs passed by the required authoring
and review bindings on the exact current CLI/worker/contract may enter the existing
protected capability policy. Existing presets, Workflows, Content Packs, defaults and
historical pins do not change. Unsupported reasoning efforts remain observation-only.
The previous policy is recoverably retained; no raw DB UPDATE or historical rewrite occurs.
Admission reauthorizes the exact immutable assignment; a normal observation may advance
the mutable resource version, but cannot transfer evidence to another account assignment.

## Six-slot admission successor V3 (2026-10-10)

Responsibility remains Orchestrator evidence admission and the protected root policy
installer. V2 admitted only slots 01/02; even explicit successful 03–06 probes could not
authorize those roles after a CLI change. Merely running more probes or retaining stale
global pairs is insufficient. V3 is a new policy contract, not a reinterpretation of V2.
The existing Worker Registry owns one immutable fixed-host layout; inventory validation
and V3 policy role checks use that same public role map. Schema mirror parity tests protect
the necessarily repeated wire enum/role constraints without changing inventory V2 bytes.

The canonical source is the existing committed report V1 Artifact/member. Logical binding
and immutable assignment revision remain distinct from slot identity and mutable resource
version. V3 scoped pins add the exact fixed slot and role to binding/assignment pins:
01 authoring, 02 review, 03 image, 04 item_management, 05/06 support. Report/request V1 and
released policy V1/V2 bytes remain unchanged. Existing approved member resolution validates
publication, lifecycle, schema, media, hashes, runtime and freshness before rendering.

Dominant access patterns are six indexed slot/binding lookups in one query, set intersection
for author/review pairs, and keyed aggregation of per-binding successful pairs. Every
requested case must resolve to its current exact binding/assignment and a non-regressed
resource version; mismatches are errors, not silently discarded rows. Slots 01/02 retain
their paired-PASS candidate invariant. Slots 03–06 admit only their own actual PASS pairs.
Model/effort pairs sharing the same binding scope are grouped deterministically without
introducing an untested model/effort/binding Cartesian product. Aggregation/storage is
O(cases + entries), with O(entries log entries) canonical sorting, bounded by 64 cases,
six slots and 32 policy entries; no DB schema, index or cache is added.

Snapshot observation reauthorizes V3 binding slot, role and assignment, and repeats exact
runtime checks before writing. Its automatic refresh preflight uses the same rule before
persisting READY. V1/V2 loader and snapshot meanings stay intact. Existing final transaction
and root install-time pointer/runtime rechecks remain the concurrency boundary. An
observation-only resource-version advance is allowed; reassignment does not inherit proof.
The compatible unchanged-runtime legacy global baseline may remain, but a changed runtime
drops global baseline pairs, and old scoped entries are never carried forward as fresh
evidence. Failures preserve predecessor policies and immutable reports; identical evidence
renders identical bytes and root installation retains existing replay/rollback behavior.

The CLI remains presentation-only and calls application services; policy/schema types do
not add worker orchestration, a queue, direct NAS access or a new authority source. Actual
execution budget and source/runtime pins remain explicit. Coverage of all requested six
slots is not full product acceptance: active role/default pairs must actually be admitted,
the probe checks are synthetic, and the separate General Chat app-server/account path is
not tested by this operation. Neither CLI updates nor model/default changes are automatic.

### Explicit bounded selection matrix

`codex-compatibility-matrix/1.0` is an additive presentation contract containing only
ordered slot/model/existing-effort selections. A frozen tuple preserves selected order;
a set rejects duplicate triples in O(n), with at most 64 selections. It contains no
operator, account, binding, assignment, revision, hash or execution authority. Preparation
resolves all selected current bindings in one indexed query and produces the unchanged
immutable request V1 with server-owned pins. Inference, replay, maintenance and publication
continue through the existing use case. Matrix bytes are untrusted bounded private input,
not an admission receipt, copied report, new queue or database aggregate.

A deliberately nonrectangular matrix can test seven models × three efforts on authoring
and review (42 cases), plus only the actual baseline Terra × three efforts on slots 03–06
(12 cases), totalling 54 instead of a 126-case full Cartesian product. This is a budget
example, not a claim of actual PASS or an automatic production default change. Actual
approved selections and their report pins define scope; General Chat remains separate.

## Update checking and rollout

Distribution discovery is a bounded, fixed HTTPS request to official `@openai/codex` npm
metadata. It ignores ambient proxies/npm configuration and refuses redirects, malformed
metadata, prerelease guesses, and oversized responses. An unavailable check is UNKNOWN.
Never invoke `codex update` as a supposed check-only operation: it can install an update.

An operator installs an approved CLI release during normal maintenance, runs this same
compatibility operation, and admits passed pairs. A changed CLI or worker hash invalidates
old admission evidence; exact-runtime mismatch remains fail-closed. This is
on-demand maintenance, not a background auto-updater or a replacement for release rollout.

The shared installation also serves the independently enrolled General Chat app-server.
Its additive policy/dispatch V5 pins the explicitly selected CLI version and launcher/native
hashes using the existing protected chat model environment. The version-neutral adapter
profile maps to unchanged protocol-4 transport/turn/tool/result contracts; it does not
rewrite V1–V4, widen RAG policy, enroll an account, or change production defaults.
The shared protected CLI identity adapter hashes once per startup epoch and checks metadata
before subsequent launches/admission. Runtime selection and byte observation are separate;
startup cannot automatically adopt a changed executable, even at the same version.

Six-worker report/V3 admission does not substitute for actual authenticated chat text and
official-RAG-tool canaries. A shared package replacement therefore keeps producers stopped
through exact-runtime proof and admission, then restores only the approved originally active
capacity. Compatible future CLI releases require new explicit pins and fresh checks, not a
source-level version-number edit; changed native behavior requires reviewed successor work.
See [General Chat runtime evolution](GENERAL_CHAT_CODEX_RUNTIME_EVOLUTION.md) and the
[coordinated upgrade runbook](../operations/CODEX_RUNTIME_COMPATIBILITY_RUNBOOK.md#coordinated-shared-cli-upgrade).
These are source/operation contracts; live acceptance must record actual runtime evidence.

## Simpler alternatives rejected

Appending every advertised model to the YAML confuses discovery with execution. Reusing
legacy `Orchestrator.submit` bypasses shared capacity and does not pin model/effort. Adding
an asynchronous compatibility command/queue would require new concurrency accounting and
persistent state without a current product requirement. The maintenance-only use case
reuses existing ownership and fixed worker boundaries with the smallest additive protocol.

## Required acceptance

Schema/Pydantic parity, immutable predecessor fixtures, invocation dual-file rejection,
hash/path/permission negatives, maintenance/host-lock contention, checkpoint replay and
uncertain-launch rejection, bounded update discovery, Artifact resolution/admission, and
installed-wheel/helper identity tests are required. Actual inference is opt-in and has its
own explicit call count; no source test consumes model usage. Runtime PASS and any future
educational evaluation are reported independently.

## Native output-schema projection (2026-10-10)

The first native diagnostic rejected the generated output schema because `schema_version`
had no explicit `type`. The released V1 contract already requires every field and restricts
that value by a string constant, and the two shape fields by string enums. The generation
adapter adds `type: string` to only those three fields in a copied schema, alongside the
existing per-case identity constants. This is an equivalent string restriction, not a
canonical contract change or a supplied task answer. Released V1 bytes/hashes, the worker
helper and canonical result validation remain unchanged; no general conversion layer is
introduced.

The failed run and its attempted-call/NOT_RUN ledger remain immutable. After releasing the
adapter fix, a separately approved new bounded request is required; the old failed case
must not be replayed as a new model call. Source tests cover explicit native types, complete
required-field coverage, canonical immutability and unchanged constant/enum rejection.

## Historical child-job quiescence (2026-10-10)

Live preflight found two CLAIMED/RUNNING child Job records whose canonical step and parent
were already FAILED/CANCELLED. They are not successful executions and their rows/events
must remain unchanged. Age, known IDs, and missing leases alone are not quiescence proof.
The Workflow owner exits on those unsuccessful terminal parents; its special untouched
QUEUED recovery is still executable and must always block diagnostics.

The maintenance adapter may classify only CLAIMED/RUNNING records as sealed history when
an exact request workflow/step pointer resolves, every linked step and parent is
FAILED/CANCELLED, and no linked parent has a PENDING/LEASED/PROCESSING command. A missing,
dangling, successful, or mixed link remains busy. The global held-lease and fixed-unit
absence checks remain mandatory, and all producers are stopped under the same host lock
before inference. Classification is read-only, not a reconciliation or state transition.

Use the already composed SQLAlchemy table registry, as the existing lease boundary does;
do not import Workflow Runner implementation into Orchestrator. Correlated EXISTS/NOT
EXISTS use the existing platform_job_id and workflow_id B-tree indexes rather than one
query per Job. Scale and storage are unchanged; no migration, cache, duplicate state enum,
or job repair queue is introduced. The simpler status-only filter incorrectly blocks
sealed historical children; ignoring all children of terminal parents would incorrectly
admit recoverable QUEUED work. Tests preserve original rows and cover every negative link,
active command, worker/lease guard, and the QUEUED recovery boundary.
