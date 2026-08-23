# Codex Execution Resolution and Job-Local Materialization

Status: Phase 3 source design

Last reviewed: 2026-08-23 UTC

## Responsibility and boundary

The Orchestrator application layer resolves one released Execution Preset into one immutable
Resolved Execution Plan before a workflow job is claimed. The filesystem adapter then materializes
only the selected, approved Markdown members into the already isolated job workspace. The fixed
worker executable consumes one bounded invocation descriptor and starts one fresh Codex process.

The resolver does not inspect credentials or host paths. The materializer does not select a model,
change a plan, query for a latest revision, write NAS, or commit an Artifact. Workers remain unable
to address PostgreSQL or NAS and never communicate with another worker.

## Canonical sources and identity

- the released Execution Preset Revision is the selection policy;
- the Resolved Execution Plan is the immutable per-workflow selection record;
- Instruction and Reference Bundle Revisions identify their exact manifest and members;
- Artifact Revision plus member SHA-256 is the canonical byte source;
- `AGENTS.md`, `instructions/`, and `references/` are disposable job-local materializations only.

Logical IDs, revision IDs, Artifact IDs, Artifact Revision IDs, and SHA-256 values remain separate.
No filesystem path is persisted as identity or accepted from an execution preset.

## Required pointers and resolution checks

Every selected bundle and member is revalidated at materialization time for logical/revision
ownership, `RELEASED`/approved lifecycle, schema, `text/markdown` media type, manifest membership,
expected SHA-256, explicit caller authorization, canonical NAS containment, regular-file type, and
absence of symlinks in every path component. Missing, stale, unauthorized, unsafe, oversized, or
non-UTF-8 members fail before a worker unit is started.

The job-local relative paths are normalized contract values beneath `instructions/` or
`references/`. Creation uses exclusive, non-following file descriptors and exact final modes. A
deterministic `AGENTS.md` is assembled in `PLATFORM`, then `ROLE`, then relative-path order. At
least one platform and one role instruction component is required.

## Access patterns and data structures

| Operation | Structure | Complexity |
| --- | --- | --- |
| current preset lookup | unique indexed key and current-revision FK | `O(log n)` |
| role policy selection | role-keyed map over at most five policies | `O(r)` bounded |
| step resolution | ordered tuple plus role map | `O(s)` |
| duplicate path/member detection | set | expected `O(n)` |
| bundle/member lookup | primary/unique DB keys and manifest map | `O(log n) + O(m)` bounded |
| byte validation/copy | one streaming SHA-256 pass | `O(bytes)`, constant buffer memory |

The configured scale is at most 64 plan steps, 32 instruction members, 256 reference members, 2
MiB per Markdown member, and 32 MiB per job-local bundle materialization. These bounds prevent a
small control record from becoming an unbounded filesystem operation.

## Transaction and concurrency boundary

Plan resolution and insertion occur in one short transaction. Existing per-workflow uniqueness
makes replay idempotent and prevents two different plans from being attached to the same workflow.
No file I/O or Codex execution occurs in that transaction.

Workspace creation and materialization occur after validation but before worker claim consumption.
Job directories and files use exclusive creation; any pre-existing target, symlink, or hash drift
fails closed. Codex runs outside all DB transactions. Job state and append-only event data record
only IDs, hashes, selected model/effort, installed CLI version when observed, exit code, and stable
outcome code—not credentials, chain-of-thought, full logs, or source content.

## Dependency direction and adapter ownership

`eom_workflow` owns the immutable control contracts. `eom_orchestrator.control_service` owns
selection and plan persistence. `eom_orchestrator.execution_materializer` is the NAS-to-workspace
infrastructure adapter. `eom_orchestrator.worker` composes the prepared workspace with the fixed
systemd worker. The root-installed `worker_exec.py` validates the local invocation descriptor and
translates only its exact model and reasoning-effort values into Codex CLI arguments.

## Failure, retry, and idempotency

- resolution failures occur before claim and do not consume an attempt;
- materialization failures occur before systemd start and use stable, sanitized boundary codes;
- after claim, auth/model/process failures terminalize exactly one attempt;
- there is no latest-revision substitution, session resume, model substitution, cross-account
  retry, or automatic re-submission;
- a repeated resolution for the same workflow returns only the byte-identical persisted plan;
- workspace cleanup targets only the exact disposable job directory after durable evidence exists.

## Simpler alternative considered

Passing repository paths or copying a whole reference tree into every worker would be simpler, but
would make mutable paths authoritative, expand untrusted input, defeat exact replay, and expose
unrelated content. Letting each worker read a global `AGENTS.md` or its user configuration would
also reintroduce hidden mutable state. Exact immutable pointers plus bounded job-local
materialization are therefore the smallest design that preserves reproducibility and isolation.
