# ADR 0101: Graph verification planning and bounded review escalation

- Status: Accepted
- Date: 2026-09-21

## Context

The released independent item review (`workflow-role/1.23.0`, `review-result@11.0`) binds one
review to the immutable authoring Artifact, Evidence Bundle V5, Graph Snapshot, solution reports,
and exact draft leaves. It can return repairable findings to authoring at most three times. It does
not yet make four useful review tactics explicit and auditable:

1. plan the exact scientific, answer, curriculum, originality, and visual targets before reaching a
   final verdict;
2. inspect visual material before text-dependent conclusions when an item has images;
3. preserve suspected problems as candidates and explicitly confirm or demote them instead of
   turning every observation into a blocking finding; and
4. route uncertain or structurally complex cases through one stronger independent review pass.

The future textbook-PDF review product will need analogous verification targets and candidate
dispositions. That future product must not be implemented by making item review a generic plugin or
by letting workers call each other.

## Decision

### Boundary and responsibility

Add a successor item-review family:

- `workflow-role/1.24.0` and role results `@12.0`;
- additive public request schema `workflow-start/3.0` for workflow definition `1.13.0`;
- `independent-item-review/2.0` inside `review-result@12.0`;
- `workflow-review-escalation-directive/1.0` authored only by the workflow application;
- a successor resolved execution plan that pins both the ordinary and escalated model candidates
  for the single logical `review` step; and
- a successor workflow/Content Pack/control release. Released V11/V1.23 bytes and behavior remain
  immutable.

The review worker still has no orchestration, persistence, Graph-query, or NAS authority. It reads
the staged immutable request, authoring result, images, Evidence manifest/context, and control
references, then returns one structured result. The orchestrator validates and commits the result.

### Canonical source and pointers

The canonical review inputs are:

```text
Workflow request + immutable authoring revision
  + pinned Graph Snapshot
  + pinned Evidence Bundle manifest/context
  + immutable solution-report pointers
  + optional generated-image Artifact revisions
```

Review verification targets select Evidence IDs already present in the pinned bundle. Review never
silently queries the mutable current Graph or substitutes a newer bundle after workflow start. A
target that cannot be supported by the pinned bundle is marked `INSUFFICIENT`; it is not filled from
general knowledge and it contributes to escalation.

The escalation directive pins the first review Artifact pointer, the reviewed authoring pointer,
the exact next attempt, bounded reason codes, structural complexity score, and its own canonical
SHA-256. The second review receives the immutable first result only through that orchestrator-owned
directive. Direct worker-to-worker communication is impossible.

### Review structures and access patterns

The dominant operations are bounded ordered iteration, key lookup, membership, and deduplication:

- ordered verification targets and candidate findings use immutable tuples;
- target/candidate/Evidence identity resolution uses dictionaries keyed by ID;
- duplicate paths, IDs, and reasons use sets;
- Graph evidence membership is checked against the manifest map in `O(E + T + C)` time; and
- review history remains append-only by workflow step attempt.

Expected scale is at most 64 evidence entries, 32 verification targets, 32 candidate findings, and
one escalation per review cycle. No new database table or index is required. Existing unique
workflow step-attempt, job idempotency, lease, Artifact revision, and event sequence constraints
remain authoritative.

### Verification planning and image-first review

Every review returns a bounded verification plan covering answer derivation, each choice, optional
statements, explanation, curriculum scope, originality, and every authored visual relation.
Graph-grounded targets select exact Evidence IDs and source-class expectations. A visual item must
declare `VISUAL_FIRST` and place its first verification target on the visual relation. A nonvisual
item declares `CONTENT_FIRST`.

This is an auditable plan and concise conclusion record, not hidden chain-of-thought. Free-form
reasoning transcripts are forbidden.

### Candidate re-verification and demotion

A suspected defect is first represented as a candidate with exact draft paths and Evidence IDs. Its
closed disposition is `CONFIRMED`, `DEMOTED`, or `UNCERTAIN`.

- only `CONFIRMED` candidates may appear as blocking review findings;
- `DEMOTED` candidates are retained for audit but cannot block or drive authoring rework; and
- `UNCERTAIN` candidates require escalation and cannot survive the escalated result.

The application recomputes these invariants. A worker cannot promote or suppress a blocking finding
by making inconsistent copies in different fields.

### Bounded stronger review

The ordinary and escalated candidates are both pinned in the execution plan. Escalation is required
when the application-recomputed policy observes at least one of:

- an uncertain candidate;
- insufficient evidence for a required scientific/answer/curriculum target;
- a confirmed visual-risk candidate;
- any confirmed content candidate that must be independently rechecked before rework; or
- structural complexity at or above the reviewed threshold.

The first successful review Artifact is committed, then atomically superseded by exactly one new
attempt of the same logical `review` step. The second attempt uses only the plan-pinned escalated
candidate, receives the source review through the directive, and must close every source candidate.
It cannot request another escalation. Only the final active review result may drive bounded
authoring rework, human approval, registration, and the trusted Evidence receipt pair.

Pre-commit infrastructure retry is not an escalation and preserves whichever primary/escalated tier
was already selected. Escalation count is independent of the maximum three authoring rework cycles;
each fresh review cycle may have at most one escalation.

### Transactions, failure, retry, and idempotency

The source review commit and the scheduling decision are reconciled in the workflow runner's fenced
transaction. A repeated command adopts the existing exact successor attempt. Different source
pointers, reason sets, model pins, or decision hashes fail closed. Capacity queues and leases remain
unchanged; the final review still uses the review pool.

Missing/stale Artifact revisions, wrong result schemas, Graph/Evidence drift, candidate mismatch,
an unavailable escalated capability, or an invalid directive are stable failures. They never fall
back to a weaker model, mutable latest revision, general knowledge, direct DB repair, or a second
unbounded retry.

### Dependency direction and future PDF review

JSON Schemas and frozen value models define the protocol. Domain validation computes review
invariants. Workflow and Catalog application services own classification, scheduling, and pointer
resolution. PostgreSQL, filesystem/NAS, Codex execution, and Graph storage remain adapters.

Future PDF review may reuse the small value semantics of verification targets and candidate
dispositions in a distinct document-review contract. It must define its own source-page pointers,
OCR/image inputs, workflow, results, and acceptance rules. Item review does not become a generic
review framework in advance.

## Simpler alternative rejected

Prompt-only instructions on the V11 reviewer are insufficient: target coverage, false-positive
demotion, Evidence selection, and escalation would not be machine-verifiable. Always running an
`xhigh` reviewer is simpler but wastes scarce capacity and does not preserve why escalation was
needed. Adding a second permanent review role or a direct reviewer-to-reviewer channel duplicates
profiles/capacity and violates the orchestrator boundary. Querying the mutable current Graph after
authoring would weaken reproducibility. The bounded same-step successor attempt is the smallest
implementation that preserves all invariants.

## Consequences

- Review becomes more expensive only for policy-selected cases.
- The result contract is larger, but all collections remain bounded and ID-oriented.
- Existing V11 workflows and accepted Items remain replayable byte-for-byte.
- A later PDF reviewer can reuse the proven concepts without sharing item-specific schemas or
  infrastructure internals.
