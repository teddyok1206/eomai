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

## Update checking and rollout

Distribution discovery is a bounded, fixed HTTPS request to official `@openai/codex` npm
metadata. It ignores ambient proxies/npm configuration and refuses redirects, malformed
metadata, prerelease guesses, and oversized responses. An unavailable check is UNKNOWN.
Never invoke `codex update` as a supposed check-only operation: it can install an update.

An operator installs an approved CLI release during normal maintenance, runs this same
compatibility operation, and admits passed pairs. A changed CLI or worker hash invalidates
old admission evidence; existing expected-version mismatch remains fail-closed. This is
on-demand maintenance, not a background auto-updater or a replacement for release rollout.

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
