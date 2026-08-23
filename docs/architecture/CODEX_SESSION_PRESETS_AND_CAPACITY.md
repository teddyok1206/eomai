# Codex Session, Execution Preset, and Worker Capacity Design

Status: Proposed design; no runtime or database implementation is authorized by this document.

Last reviewed: 2026-08-23 UTC

## 1. Decision Summary

EOM keeps Codex execution **fresh, one-shot, and stateless at the conversation level**. A worker
login may persist, but a previous Codex conversation is never the implicit memory of a new item or
the next workflow step.

The stable production contract is:

```text
persistent worker identity and authentication
  + immutable execution preset revision
  + immutable instruction bundle revision
  + immutable reference bundle revisions
  + current workflow's typed input and upstream artifact pointers
  -> fresh one-shot codex exec
  -> schema-validated result artifact revision
```

Users express educational requirements. They do not enter raw model names, reasoning settings,
host filesystem paths, or credentials. An administrator manages Codex account health and publishes
versioned execution presets. The Orchestrator resolves each request to an immutable execution plan
before a worker is claimed.

Worker capacity is managed by a deterministic application service owned by the Orchestrator. It is
not another Codex worker and does not make model-based scheduling decisions. For the current host,
five configured identities remain the hard configured-slot ceiling and three concurrent Codex
processes remain the hard execution ceiling until a measured capacity review approves a change.

## 2. Current Baseline

The current implementation already establishes several correct boundaries:

- five fixed identities: `eom-cdx-01` through `eom-cdx-05`;
- one private `HOME`, `CODEX_HOME`, private group, and workspace root per identity;
- role bindings for authoring, review, image, item management, and support;
- root-owned fixed systemd templates and a root-owned worker executable;
- one-shot `codex exec` with `--ephemeral`, read-only sandboxing, and a JSON output schema;
- `--ignore-user-config`, while authentication still resolves from the fixed `CODEX_HOME`;
- global Codex concurrency configured as three and GPU concurrency as one;
- each systemd worker bounded by `MemoryMax=6G`, `CPUQuota=200%`, `TasksMax=256`, and a 600-second
  start timeout.

Design-time host inventory on 2026-08-23 UTC was 16 logical CPUs, 30 GiB RAM, and 8 GiB swap. This
is evidence for the initial concurrency decision, not a permanent hardware invariant.

The current command does **not** explicitly pin a model, reasoning effort, instruction bundle, or
reference bundle in the per-job execution contract. The current readiness path validates identity,
paths, executable, systemd authorization, and schema resources, but it does not make worker login
health or model compatibility an authoritative pre-claim gate. These are the gaps addressed by this
design.

## 3. Why Fresh Sessions Are the Correct Default

Normal foreground Codex use can retain a session under `CODEX_HOME` and later resume it. EOM does
not use that behavior for production workflows. `--ephemeral` and the absence of `exec resume`
mean that every job starts with a new model context.

This prevents:

- one item's hidden conversation state from contaminating another item;
- stale assumptions from surviving a changed request, Content Pack, schema, or reference;
- slot scheduling from depending on which process or account handled an earlier step;
- an unversioned conversation transcript from becoming an undeclared canonical source;
- replay from silently resolving a different or expired session;
- sensitive prompt or item content from accumulating in reusable session history.

Fresh does not mean context-free. Within one workflow, a later role receives the current request and
validated upstream artifact pointers through the Orchestrator. Continuity is explicit data, not
implicit conversation memory:

```text
fresh authoring run
  -> immutable authoring result revision
fresh image run
  <- current request + pinned authoring pointer
  -> immutable image result revision
fresh review run
  <- current request + pinned authoring/image pointers
  -> immutable review result revision
fresh registration run
  <- all required pinned result pointers
  -> approved Item Revision or a typed failure
```

Production workflow code must not use `codex exec resume`, a most-recent-session alias, a TUI
session ID, or a mutable conversation log. Interactive sessions remain operator-only diagnostics.

## 4. Context Layers

Each run receives five deliberately separate context layers.

### 4.1 Platform instruction bundle

This contains stable execution and safety rules: structured output, tool constraints, trust
boundaries, evidence handling, and failure behavior. It does not contain subject knowledge or a
particular item's answer.

### 4.2 Role instruction bundle

This contains bounded authoring, image, review, registration, or support behavior. It may extend the
platform instruction bundle but cannot override platform security constraints.

### 4.3 Content Pack prompt profile

The existing Content Pack owns domain-specific prompt templates and output schema compatibility.
The new design extends that boundary rather than building a second prompt system.

### 4.4 Reference bundles

Approved curricula, terminology, source material, assessment guidance, and other Markdown inputs are
versioned reference bundles. A reference bundle is a logical entity with immutable revisions and a
typed manifest of artifact pointers. A user never supplies an arbitrary server path.

When no approved reference bundle is required, the request may explicitly permit
`general_model_knowledge`. That mode is recorded as provenance; it is not silently inferred from a
missing path.

### 4.5 Current workflow context

This is the smallest typed payload needed for the current step: item requirements, resolved
decisions, current attempt, upstream artifact pointers, and unresolved review findings. It is not a
copy of previous model transcripts.

## 5. AGENTS.md and Reference Materialization

Codex constructs its instruction chain once at run start. It reads global guidance from
`CODEX_HOME`, then project guidance from the project root down to the current working directory.
Closer files take precedence, and the combined project instructions have a bounded size. Therefore
EOM must not use `AGENTS.md` as a large knowledge store.

The target workspace layout is conceptual and remains private to the selected worker:

```text
<job-workspace>/
  AGENTS.md
  worker-input.json
  worker-result.schema.json
  prompt.txt
  context/
    execution-plan.json
    reference-manifest.json
  references/
    <reference-bundle-id>/
      <pinned revision materialization>
```

The staged `AGENTS.md` is generated deterministically from pinned platform and role instruction
bundle revisions. Its manifest records the source bundle IDs, revision IDs, schema versions, and
SHA-256 values. Reference files are staged read-only from approved artifact revisions after
existence, lifecycle, media type, schema, path containment, non-symlink, and content-hash checks.

Large reference folders are not concatenated into the prompt. The worker receives a bounded typed
manifest and reads only the job-local files needed for the task. The execution evidence records the
bundle revisions made available to the worker. If finer-grained evidence is later required, a
bounded list of actually opened reference members can be derived from supported Codex events; it
must not be guessed from the final answer.

Workspace paths are temporary materialization locations, never identity. A historical workflow pins
bundle revisions and hashes, not `/srv/...` paths.

Official Codex behavior referenced by this design:

- [Configuration precedence](https://learn.chatgpt.com/docs/config-file/config-basic)
- [AGENTS.md discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

## 6. Account and Authentication Control Plane

Authentication and execution policy are separate concerns. A logical Codex account may have one
worker-local authentication installation per authorized slot. Authentication caches are never
shared by symlink, copied from root, committed to Git, stored in PostgreSQL, or exposed to the GUI.

```text
Codex account (non-secret label and policy)
  -> worker auth binding 01 -> worker-private credential store
  -> worker auth binding 02 -> worker-private credential store
  -> ...
```

The administrator-facing account view exposes only sanitized state:

- logical account label;
- authentication method and, when applicable, expected workspace identity;
- slot identity and enabled/draining state;
- `READY`, `STALE`, `AUTH_REQUIRED`, `DEGRADED`, or `DISABLED` health;
- last status check, last successful real job, and consecutive authentication failures;
- installed Codex CLI version;
- latest observed model capability snapshot;
- a re-authentication-required action without any credential value.

The public Scientific Studio must not accept a ChatGPT password, API key, access token, device code,
or `auth.json`. Re-authentication is an operator maintenance flow:

1. mark the slot `DRAINING` so it receives no new lease;
2. allow its current job to reach a terminal state;
3. open a protected terminal as the exact worker identity;
4. run the supported Codex login/device flow without logging credential material;
5. run a sanitized status check;
6. return the binding to `READY` only after the required checks pass.

ChatGPT login is preferred for the existing subscription-based boundary. Adding API-key based model
access would violate the current EOM rule against external LLM APIs and is outside this design.
Where supported, managed Codex configuration should enforce the approved login method and workspace.

Authentication readiness has levels:

1. worker identity, home, and credential-store metadata are valid without reading secret content;
2. `codex login status` succeeds as the worker and reports an allowed method;
3. the account has a recent successful real job with the configured Codex version;
4. an optional usage-consuming canary, if ever introduced, is separately authorized and budgeted.

Level 2 is non-generating but does not prove current model entitlement or remaining usage. EOM must
not report those as known without supported evidence. Official authentication behavior is documented
in [Codex authentication](https://learn.chatgpt.com/docs/auth).

## 7. Capability Inventory and Model Selection

Official model catalogs and account entitlements can change. An advertised model is not necessarily
available to every installed CLI/account combination. EOM therefore separates:

- **published capability:** an administrator-approved model/effort combination;
- **observed capability:** a timestamped result for a worker account and Codex version;
- **resolved execution:** the exact combination pinned to one workflow step;
- **actual evidence:** what the launched command requested and, where supported, what Codex reported.

An execution preset uses an ordered, explicit allowlist rather than a free-form model string. A
resolver pins the actual model before claim. It must never silently substitute “latest” or another
model. An allowed fallback is part of the immutable preset revision and records a stable reason.

The initial effort vocabulary should be restricted to values proven compatible with the installed
Codex CLI and the chosen model. `low`, `medium`, `high`, and `xhigh` are the conservative starting
set. `max` must wait for installed-CLI contract verification. `Ultra` is not enabled: current Codex
documentation describes it as automatic subagent delegation, which changes the execution topology
and requires a separate protocol/security review under EOM's Orchestrator-only coordination rule.

Higher effort is not assumed to be better. Preset publication requires representative item evals
covering educational correctness, answerability, distractor quality, structural validity, latency,
and observed usage. See [Codex model selection](https://learn.chatgpt.com/docs/models).

## 8. Execution Presets

Users select product requirements, not execution internals. Example user-facing choices are:

- subject, topic, item type, and difficulty;
- standard, fast sample, or high-difficulty quality tier;
- equation, table, and generated stimulus requirements;
- approved reference bundle selection or general-model-knowledge mode;
- bounded delivery requirements such as HWPX after approval.

A versioned execution preset maps those requirements to role policies:

```text
ExecutionPresetRevision
  authoring -> model policy + effort + timeout
  image -> model policy + effort + timeout
  review -> model policy + effort + timeout
  item_management -> model policy + effort + timeout
  instruction bundle pointers
  permitted reference bundle classes
  sandbox/tool/network policy
  fallback policy
  compatibility with workflow protocol and Content Pack profile
```

Preset edits create a new immutable revision. Existing workflows keep the old revision. A mutable
“current preset” pointer may select the default for future workflows, but replay and audit always use
the pinned revision.

The initial preset names and model assignments are deliberately not fixed here. They must follow
capability verification and evals. The system can begin with one `standard-item` preset, then add a
fast or high-difficulty preset only when it represents a measured second use case.

## 9. Resolved Execution Plan

Workflow creation resolves the requested product profile to a single immutable plan snapshot. The
snapshot records, per step:

- execution preset logical ID and revision ID;
- workflow definition and role protocol versions;
- exact model and reasoning effort;
- Codex CLI version compatibility requirement;
- selected worker pool and required capabilities, but not a prematurely reserved slot;
- instruction bundle and reference bundle pointers and hashes;
- Content Pack release/profile pointers;
- sandbox, tool, network, timeout, and fallback policy;
- resolution timestamp in UTC and policy resolver version.

The actual worker slot and account binding are recorded when a lease is acquired. Authentication
identity is referenced by a non-secret binding ID. The result evidence records requested execution
parameters and stable failure codes; it does not record chain-of-thought or credential material.

## 10. Capacity Decision for the Current Host

“How many slots exist?” and “how many Codex processes run?” are different questions.

- An idle configured slot mainly costs an OS identity, private home, systemd template, authentication
  lifecycle, and administrative complexity.
- An active Codex process consumes CPU, memory, process count, network capacity, account usage, and
  potentially tool subprocesses.

Current hard limits yield this conservative envelope:

| Item | Per active worker | Three active workers | Host baseline |
| --- | ---: | ---: | ---: |
| CPU quota | 2 logical CPUs | 6 logical CPUs | 16 logical CPUs |
| memory hard cap | 6 GiB | 18 GiB | 30 GiB RAM |
| tasks | 256 | 768 | host/systemd bounded |

Three concurrent workers leave approximately 10 logical CPUs and 12 GiB of physical RAM outside
the summed worker hard caps for PostgreSQL, API, GUI, Observability, runners, filesystem cache, and
operational variance. Four workers could reserve 24 GiB and five could equal the host's physical
RAM, so increasing concurrency without measurement is rejected.

Initial policy:

```text
max_configured_slots = 5
max_active_codex = 3
max_active_per_slot = 1
max_active_gpu = 1
```

The five-slot ceiling is also the current fixed identity/systemd/polkit security contract. Creating
slot 06 is a reviewed deployment change, not a GUI action. More logical roles should first be mapped
onto existing compatible pools rather than creating unbounded Linux users.

No automatic CPU/load or memory-pressure throttling is specified initially because no representative
concurrent benchmark exists. Per-unit cgroup limits plus the hard global cap are the simple safe
starting point. Pressure-aware admission may be added only after measurements define a threshold,
hysteresis, and recovery behavior.

## 11. Worker Capacity Controller

The capacity manager is a deterministic `WorkerCapacityController` application service inside the
Orchestrator boundary. It is not a sixth worker, does not invoke a model, does not hold Codex
credentials, and does not bypass the canonical job queue.

Responsibilities:

- read the immutable/configured capacity policy;
- consider only enabled, role-compatible, capability-compatible, authenticated `READY` slots;
- enforce one active lease per slot and the global/GPU pool ceilings;
- assign slots deterministically from the eligible set;
- mark slots `DRAINING` without killing an active job;
- recover expired leases only after process/unit state reconciliation;
- publish sanitized health and utilization projections;
- fail before claim when the exact preset cannot be satisfied.

It does not:

- keep TUI terminals alive;
- choose educational content or judge model output;
- edit presets or credentials;
- restart, kill, or retry workers automatically;
- silently change a model, effort, reference, or instruction revision;
- write worker results or artifacts to NAS.

## 12. Persistent Model and Data Structures

The following is a logical model; exact SQL requires a separate schema-first design and migration.
Existing `worker_slots` remains authoritative and should be extended rather than replaced by a
parallel registry.

### 12.1 Account and operational state

```text
codex_accounts
  account_id PK
  non_secret_label UNIQUE
  allowed_login_method
  expected_workspace_id nullable
  state

worker_auth_bindings
  binding_id PK
  slot_id FK -> worker_slots UNIQUE
  account_id FK -> codex_accounts
  health_state
  last_checked_at
  last_success_at
  consecutive_failures
  resource_version

codex_auth_health_events
  event_id PK
  binding_id FK
  monotonic_sequence
  observed_at
  prior_state/new_state
  sanitized_reason_code
  UNIQUE(binding_id, monotonic_sequence)
```

No credential value, credential bytes, login URL, device code, or arbitrary credential path is
stored in these rows.

### 12.2 Capabilities and presets

```text
codex_capability_snapshots
  snapshot_id PK
  binding_id FK
  codex_version
  observed_at
  observation_method

codex_model_capabilities
  snapshot_id FK
  model_id
  reasoning_effort
  state
  UNIQUE(snapshot_id, model_id, reasoning_effort)

execution_presets
  preset_id PK
  preset_key UNIQUE
  current_revision_id nullable

execution_preset_revisions
  preset_revision_id PK
  preset_id FK
  revision_number
  state
  schema_version
  content_sha256
  created_at
  UNIQUE(preset_id, revision_number)

preset_role_policies
  preset_revision_id FK
  role
  ordered_model_policy
  reasoning_effort
  timeout_seconds
  instruction_bundle_revision_id FK
  UNIQUE(preset_revision_id, role)
```

Ordered fallback policy should be a small typed immutable value or child relation, not an unbounded
arbitrary JSON object. Capability snapshots are observations with a TTL, not canonical promises.

### 12.3 Instructions, references, plans, and leases

Instruction and reference bundles follow the existing logical entity -> immutable revision ->
component pointers -> artifact revisions -> hashes model. Large Markdown sets stay in artifact
storage, not PostgreSQL.

```text
workflow_execution_plans
  execution_plan_id PK
  workflow_id FK UNIQUE
  preset_revision_id FK
  resolver_version
  resolved_at
  manifest_artifact_revision_id FK
  manifest_sha256

worker_capacity_pools
  pool_id PK
  pool_key UNIQUE
  max_active
  resource_version

worker_slot_leases
  lease_id PK
  pool_id FK
  slot_id FK
  job_id FK UNIQUE
  acquired_at
  expires_at
  released_at nullable
```

Use a partial unique index on `worker_slot_leases(slot_id) WHERE released_at IS NULL` to enforce one
active job per slot. Allocation locks the small capacity-pool row, checks the active lease count,
selects one indexed eligible slot, and inserts the lease in one short transaction. Codex execution
occurs outside the transaction.

Dominant access patterns and structures:

| Access pattern | Structure | Expected cost |
| --- | --- | --- |
| slot lookup | indexed `slot_id` / in-memory map | O(1) map or O(log n) DB |
| capability membership | unique relation / set | O(1) set or indexed lookup |
| role eligibility | indexed role/state query | O(log n + k) |
| ordered pending work | existing indexed DB queue | O(log n), `SKIP LOCKED` |
| one active lease per slot | partial unique index | constraint enforced |
| global admission | one locked pool row plus active lease count | bounded short transaction |
| event history | append-only monotonic sequence | O(log n) append/read |
| reproducible context | immutable manifest pointer | no binary DB copy |

With five initial slots, linear iteration over an already bounded in-memory eligible set is simpler
than a priority-queue framework. A priority scheduler is justified only when there are multiple real
service classes or measured queue pressure.

## 13. Transactions, Failure, Retry, and Idempotency

Execution plan resolution and workflow creation must pin the preset and bundle revisions in the same
application transaction. A mutable current pointer is resolved once; it is never resolved again
during execution.

Lease acquisition is a separate short transaction immediately before claim. Readiness and exact
capability are checked before state consumption. If the account is stale, model unavailable, or
capacity exhausted, the command remains unclaimed or enters a typed waiting condition without a
Codex invocation.

After claim:

- an authentication or model error is a typed terminal job attempt failure;
- a lease is released only after the fixed unit is confirmed terminal;
- no automatic switch to another account/model occurs unless the pinned preset explicitly allows it;
- retries use existing workflow attempt/idempotency rules and create new attempt evidence;
- conversation sessions are never resumed as retry state;
- expired leases require reconciliation against exact systemd unit state before reuse.

## 14. Usage and Observability

The admin projection should show:

- configured, ready, draining, and active slot counts;
- current leases and queue depth by role;
- success/failure/timeout/rate-limit counts by preset revision and model;
- run duration and last successful job per auth binding;
- token/usage metrics only when the installed Codex CLI exposes a supported, sanitized source;
- account quota or remaining allowance as `UNKNOWN` when it cannot be established reliably.

EOM must not scrape private account pages, parse credential files, or estimate subscription limits
and present them as facts. If Codex JSON events provide supported usage metadata, the worker boundary
may extract only the numeric allowlisted fields and must not persist prompts, chain-of-thought, or
unbounded event logs.

Slack development reporting remains unrelated to runtime account or usage observability.

## 15. Administrative and User Interfaces

Keep three separate surfaces:

1. **System / Codex Accounts (ADMIN):** account health, slot binding, drain/enable, re-auth required,
   Codex version, last capability observation.
2. **Execution Preset Library (ADMIN or future dedicated policy role):** draft, validate, release,
   deprecate, compare, and eval evidence. Released revisions are immutable.
3. **New Item Request (EDITOR):** educational requirements and approved product-level preset/quality
   choices only.

The GUI must not provide free-form fields for model IDs, reasoning effort, Linux users, `CODEX_HOME`,
`AGENTS.md` paths, reference directory paths, or fallback model names. An exceptional operator
override, if later required, creates an audited execution-plan revision and requires a reason; it
does not mutate a released preset.

## 16. Security and Dependency Direction

```text
Scientific Studio / CLI
  -> execution policy application service
  -> preset and capacity domain contracts
  -> identifier/value-object packages

Orchestrator infrastructure adapters
  -> PostgreSQL leases
  -> fixed systemd worker launcher
  -> job-local instruction/reference materializer
  -> Codex CLI
```

Domain contracts do not import systemd, subprocess, filesystem, PostgreSQL, Codex, or GUI packages.
Workers neither coordinate nor communicate directly. The Orchestrator stages local inputs and
commits only schema-validated artifacts. Worker homes and authentication remain inaccessible to API,
GUI, Observability, other workers, and NAS.

## 17. Simpler Alternatives and Why They Are Insufficient

| Alternative | Reason rejected |
| --- | --- |
| keep one long-running Codex TUI per slot | process/session liveness becomes hidden workflow state and contaminates items |
| resume the last session for each account | nondeterministic, slot-dependent, and not revision-pinned |
| put model/effort in each worker's `config.toml` | mutable user state; `--ignore-user-config` intentionally prevents it |
| let every user enter model and path settings | bypasses evals, security allowlists, and reproducibility |
| store reference Markdown directly in DB | duplicates artifact content and creates large JSON/text rows |
| add a “manager Codex” to choose workers | spends model usage on deterministic scheduling and violates clear ownership |
| allow unlimited slots but limit active jobs | credential, identity, unit, and operational attack surface still grows unbounded |
| use only a fixed global concurrency integer | does not model per-slot exclusivity, draining, authentication, role, or capability |

The proposed controller is the smallest extension that satisfies the real second use cases of
multiple role-bound slots, account maintenance, and bounded future parallel item production.

## 18. Phased Delivery

This document authorizes no implementation. A future implementation should proceed protocol-first:

1. define JSON Schema 2020-12 contracts for execution preset, instruction/reference pointers,
   resolved execution plan, sanitized account health, and capacity lease views;
2. add future Pydantic models and invariant tests;
3. add immutable preset/bundle persistence and disposable-DB migrations;
4. pass explicit model and effort to the fixed worker executable while retaining
   `--ephemeral --ignore-user-config`;
5. stage and hash job-local `AGENTS.md` and reference manifests;
6. add non-generating auth health and capability observations;
7. add the deterministic capacity controller and lease constraints;
8. expose admin projections and commands without credential handling;
9. run representative preset evals before publishing additional presets;
10. deploy with rollback that preserves current one-shot execution and the five-slot/three-active
    limits.

## 19. Required Tests for a Future Implementation

- every job is a fresh execution and no `resume` path exists;
- model, effort, Codex version, preset revision, instruction revision, and reference revisions are
  pinned and observable;
- old preset and bundle revisions remain byte-identical and replayable;
- missing/stale/unapproved/hash-mismatched bundle pointers fail before Codex invocation;
- arbitrary paths, symlinks, traversal, cross-worker homes, NAS, root auth, and secrets remain denied;
- login health never reads or emits credential contents;
- auth failure before claim does not consume an attempt;
- account failure after claim creates one typed terminal attempt and no silent fallback;
- concurrent claims never exceed three globally, one per slot, or one GPU slot;
- duplicate lease acquisition is rejected by a DB constraint;
- expired lease reconciliation cannot reuse a still-running unit;
- draining prevents new leases and does not kill the active job;
- a released preset cannot be mutated and changing the current pointer does not affect old workflows;
- downstream roles receive only current-workflow typed pointers, never prior conversation state;
- large instruction/reference content is absent from DB rows;
- default non-live tests never invoke Codex or consume account usage.

## 20. Capacity Change Gate

Any request to raise `max_active_codex` above three or configured slots above five requires a new
capacity review containing:

- concurrent representative workload measurements;
- peak and sustained cgroup memory per role;
- CPU, load, I/O, process/task, and swap-pressure measurements;
- API, PostgreSQL, GUI, Observability, and runner latency during the test;
- account concurrency/rate-limit evidence;
- revised failure containment and rollback;
- updates to fixed identities, templates, polkit, readiness, tests, and operations documentation.

Absent that evidence, the safe answer is to queue work rather than create more active workers.
