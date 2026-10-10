# Authorized snapshot to staged experiment

Status: **SOURCE_PROPOSAL**. This note authorizes no installation, production
read, model invocation or Artifact publication. It composes the existing
snapshot and experiment contracts without changing their bytes or meanings.

1. **Responsibility/boundary.** A small Orchestrator application use case asks
   an injected supported Catalog snapshot read port to prepare/read the exact
   population and assembles the existing experiment request. A separate call
   reauthorizes that exact assembly immediately before an authorized commit.
   The caller supplies its actual authenticated operator context; workers never
   receive DB, NAS or transport authority. This is not another search engine.
2. **Canonical source.** Catalog's current authorization and exact accepted
   source/report/profile values are authoritative. A local assembly, hash,
   producer-admission label or cached authorization reply is not a credential.
3. **Identity/revision.** Retain the prepared header, complete index, exact
   Graph/policy/projection/view and model pins, immutable experiment IDs, request
   SHA and independent source/profile/entry/baseline hashes. Never follow latest.
4. **Resolution checks.** Reparse every request/reply through the released
   schema/model validators. Check phase, actual actor, full index membership,
   complete record coverage, duplicate records, profile/source/count/hash
   closure and exact query/baseline closure before assembling the experiment.
   Reauthorize the full entry and baseline sets, not just selected queries.
5. **Access patterns.** Stable ordered chunk iteration and keyed exact lookup,
   complete-set membership/deduplication, one deterministic assembly and final
   authorization. Missing-report sources stay in the denominator; they cannot
   be selected as an encodable query.
6. **Structures/indexes.** Reuse existing immutable tuple/index contracts and
   map/set lookups. No DB table, queue, snapshot cache, new index or raw-vector
   persistence. Keep the pure use case independent of filesystem/SQL/HTTP.
7. **Scale/complexity.** At most 1,024 sources, 16 queries and existing 64 MiB
   input limit. Track accumulated encoded bytes while receiving chunks and
   validate final canonical request bytes before any materialization. Chunk
   count/bytes retain their existing limits. Owner reconstruction remains
   O(chunks × population), explicitly unoptimized pending a real measurement;
   local merge is O(N log N) for canonical ordering and O(N) space.
8. **Transaction/concurrency.** Each read is independent current authorization
   plus frozen-header equality, not a distributed transaction. This use case
   performs no DB mutation, file write, model launch or Artifact commit. The
   existing owner performs protected local staging and validated commit later.
9. **Dependency/ownership.** Orchestrator application code depends on existing
   public Catalog contracts and an injected read protocol, not Catalog private
   adapters or Application API internals. Filesystem, transport, authentication,
   model execution and Artifact publication stay in their existing owners.
10. **Failure/retry/idempotency.** Do not accept partial/duplicate/out-of-order
    coverage, missing query reports, mismatched pins or malformed replies. Only
    an explicit read-only chunk-budget error may split that same selected chunk;
    a one-record overflow fails without truncation. Authorization, revocation,
    transport and unknown errors are not retried with another actor/policy/key.
    A pre-execution authorization reply must not substitute for post-execution
    reauthorization. Preserve historical evidence and never call a partial
    subset the full corpus.
11. **Simpler alternative.** Manually copying JSON is shorter but cannot protect
    full-index/chunk closure or mandatory final authorization consistently. A
    single pure assembly use case over the supported read port closes that gap
    without another maintenance API, authentication framework or registry.

Source tests use fake owner ports only: exact complete assembly, missing-report
denominator, query absence, duplicate/foreign chunks, changed actor/header,
current revocation, wrong phase/hash, bounded budget splitting, one-entry
overflow, no implicit retry and final reauthorization. These tests do not prove
that an operator is authenticated, a live snapshot is accessible, the model is
installed or that a committed result has passed human transfer review.

## Source implementation evidence

The approved pure boundary is implemented in
`services/orchestrator/eom_orchestrator/inference_transfer_snapshot_staging.py`.
Its frozen actor context is a caller-captured value, **not a credential**. The
injected supported owner adapter retains actual authentication and maps stable
failures to the application-owned `SnapshotReadFailure`; arbitrary exception
text cannot authorize chunk splitting.

`stage_snapshot_experiment` performs exact PREPARE and ordered complete READ
assembly only. It does not cache an AUTHORIZE reply. The separate
`reauthorize_staged_experiment` call always asks the current owner again after
model execution and before publication. A result labelled
`AUTHORIZED_CURRENT_READ` remains a current-read observation, not a durable ACL
or a commit token. The later commit owner must retain its own transaction fence.

Accumulated canonical reply bytes and final canonical experiment bytes both
respect the selected existing input budget (at most 64 MiB). The complete compact
index and all sources retain missing-report denominator entries. The local merge
is O(N log N); reusing the existing full-index validator on each chunk also costs
O(chunks × N), in addition to the owner's independent reconstruction. No new
cache or optimized authorization shortcut was introduced.

Source verification: 38 focused fake-owner tests PASS; together with the existing
snapshot, binding and experiment contracts, 141 tests PASS. Explicit `eom-core`
strict mypy, Ruff and formatter checks PASS. No production snapshot, model run,
filesystem staging, installation, activation or Artifact commit was performed.

## Protected local execution and owner publication extension

Status: **APPROVED SOURCE IMPLEMENTATION SCOPE / NOT ACTIVATED**. This extension
changes neither snapshot nor experiment schemas. It introduces no public API,
SQL state, queue, model registry or durable authorization token.

1. **Responsibility/boundary.** One Orchestrator application leaf composes the
   existing pure snapshot stage, a protected local workspace, an injected CPU
   execution port, existing result validators, final snapshot reauthorization
   and an injected owner publication port. The filesystem and publication
   adapters own their side effects; contracts still do not import them.
2. **Canonical source.** Catalog's exact current source resolution is authoritative
   before and after execution. `request.json` and local completion observations
   are temporary materialization, not an access grant. The existing commit owner
   creates the sole canonical published result member and Artifact manifest.
3. **Identity/revision.** Preserve experiment logical/revision IDs, an explicit
   execution ID, request/result semantic hashes, snapshot header/index/source
   closure, exact model/view pins and independent member/manifest hashes.
   A raw result-member SHA is not its `result_sha256` semantic self-hash.
4. **Resolution checks.** Reuse the released schema/model/result validators.
   Input is canonical JSON within its chosen budget and the 64 MiB ceiling;
   result is a regular bounded local member with exact execution/request/model/
   view identities. Require actual pinned-model provenance for publication;
   `TEST_ONLY` diagnostics are not publishable real-model evidence. Check private
   ownership, mode, no symlink/hardlink, FD epochs and named inode identity.
5. **Access patterns.** One exact workspace lookup, exclusive input/launch
   creation, bounded ordered reads, known-completion replay and final exact
   full-population authorization. No corpus lookup or numerical work is added
   to this leaf; the existing CPU harness owns encode-once-per-view behavior.
6. **Structures/indexes.** Reuse frozen existing JSON contracts and small typed
   execution values. A private exclusive launch sentinel and a completion hash
   observe this one local handoff only; they are not another persistent job
   registry. Fixed explicit member names distinguish input, output and completion.
7. **Scale/complexity.** Input/result I/O is O(bytes), bounded to 64 MiB per JSON
   member. There is one temporary canonical input and a separate validated
   publication materialization boundary; no vectors, duplicated corpus cache or
   binary DB value is introduced. Count/thread budgets do not promise OS wall-time
   or RSS isolation. The actual isolated CPU launch adapter remains a separate gate.
8. **Transaction/concurrency.** `O_EXCL` admits one launch for an execution ID.
   Concurrent/uncertain work is not resubmitted. A known local completed output
   may be validated and republished under the same owner idempotency key after
   fresh source authorization. Existing file-set publisher advisory locking,
   immutable Artifact/Job identity and partial-publication recovery remain the
   sole commit authority, not a distributed transaction with Catalog or CPU.
9. **Dependencies/ownership.** The application uses small CPU-run and owner-commit
   ports. A single-result adapter may reuse existing `ControlFileSetPublisher`:
   the smaller `ControlArtifactPublisher` 2 MiB ceiling is insufficient for some
   allowed 1,024-profile result shapes. This adds no dependency and changes no
   predecessor publisher meaning. Actual transport authentication stays in the
   supported snapshot adapter; nominal actor/model/path values are not authority.
10. **Failure/retry/idempotency.** Source revocation after CPU completion prevents
    publication. A timeout, unknown process outcome, incomplete write or invalid
    result never triggers another model call automatically. Preserve local
    evidence and report a stable limitation. Retry uses the same execution/input
    identity; only a known completed, exact validated result can reach commit.
    Publication retry reauthorizes again before the existing owner replay.
11. **Simpler alternative.** Calling the offline CLI and publishing its JSON
    directly would omit protected input/result closure, exact execution replay
    and post-model source authorization. This bounded leaf closes those gaps
    without a new executor framework, state machine, queue or vector database.

The injected CPU port must execute the existing offline harness in an explicitly
reviewed compatible environment and report known terminal completion; it must
not treat a timeout as a failed/no-op submission. This source scope does not
provide an unsandboxed subprocess fallback, create an embedding worker account,
install the harness/model or claim a protected isolated launcher is operational.
Missing execution/publication ports fail explicitly. Tests use fake CPU/commit
ports and temporary private local files only, not real model/source/publication
acceptance or human transfer-quality evidence.

### Protected execution source evidence

Status: **SOURCE_IMPLEMENTED / INSTALLED CPU LAUNCH AND PUBLICATION NOT_RUN**.
The public composition is
`inference_transfer_experiment_artifacts.compose_inference_transfer_experiment`;
its application is `InferenceTransferExperimentExecution.execute`. The caller
supplies the supported authenticated snapshot adapter, existing owner publisher,
reviewed installed source commit, private local root and isolated CPU run port.
Composition itself creates no credential, SQL connection, worker account or
model process. Missing CPU/publication ports fail before source or file work.

The protected workspace checks canonical input before launch and again after
the CPU returns. Raw output must be canonical JSON, optionally followed by the
single newline written by the existing offline CLI. Duplicate JSON members,
unsafe file ownership/modes/links, growth, FD changes and replacement of a named
inode are rejected. Result/request/model/view/execution pins are checked using
the unchanged released validators; no schema successor or claim of current
authorization is inserted into the harness output. The publication adapter uses
the registered `eom://schemas/knowledge/item-inference-transfer-experiment/1.0`
schema (request/result oneOf), not an invented result-only schema URI.

The standalone CPU CLI now accepts optional `--execution-id`; exact format is
validated before input/model access. Omitting it retains the previous random-ID
behavior. An installed launch adapter must pass the owner-pinned execution ID;
this CLI option is not an installed launcher or an activation grant. Token
overflow and `INSUFFICIENT_ENCODING_COVERAGE` remain explicit diagnostics, not
quality success or permission to truncate a view.

A local completion hash is created only after canonical publication bytes have
been materialized. Known-completed replay validates that exact output, then
reauthorizes the complete source population and calls the existing owner under
the same idempotency key without another CPU launch. Timeout, late output after
an uncertain launch, malformed results and partial writes never auto-resubmit.
Commit failure is reported as uncertain, preserving both completed evidence and
the existing owner key rather than assuming that no Artifact was committed.

Temporary workspace observations must not be erased before supported owner
reconciliation. Recovery after deleting the whole workspace is **not supported**
by this source leaf; it cannot discover prior execution from a new empty folder
and does not claim durable exactly-once scheduling. Rollback stops composing the
optional execution port and retains local evidence and existing canonical
Artifacts. Final source reauthorization immediately precedes owner publication
but is not a distributed transaction or durable ACL token.

Focused fake-CPU/owner and offline-CLI source tests: **73 PASS**. Combined pure
snapshot staging, execution, CLI, experiment and experiment-contract regression:
**164 PASS**. Explicit `eom-core` strict mypy for the four new source modules and
CLI, Ruff, formatter and diff checks PASS. These tests use temporary private
local files and fake responses (including explicitly labelled synthetic model
response fixtures), not actual numerical inference, PostgreSQL, NAS or live
authentication. The actual protected CPU launch identity/runtime, installed
authenticated composition and real owner publication remain **NOT_RUN**;
human transfer quality remains **NOT_EVALUATED**.
