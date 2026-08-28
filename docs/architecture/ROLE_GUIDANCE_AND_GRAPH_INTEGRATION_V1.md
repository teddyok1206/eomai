# Role Guidance and Graph Integration V1

Status: source design; runtime activation intentionally deferred while the current slot05 batch is
active.

Decision date: 2026-08-28 UTC

## 1. Responsibility and boundary

This design lets every fresh one-shot Codex job receive the guidance appropriate to its assigned
work without restoring session memory or letting a worker browse a mutable repository directory.
It extends the existing Execution Preset, Instruction Bundle, Reference Bundle, Evidence Bundle,
and Educational Document boundaries. It does not introduce a second prompt registry, worker
launcher, graph backend, or credential path.

The product-level work classes are projected onto existing worker roles as follows:

| Product work class | Worker roles | Authoritative instructions | Bounded supporting context |
| --- | --- | --- | --- |
| 출제 | `authoring`, and separately `image` when required | exact released Instruction Bundle Revision for the role | role Reference Bundle plus request-scoped Evidence Bundle |
| 검토 | `review` | exact released review Instruction Bundle Revision | review guidance plus the same pinned scientific/source evidence needed to evaluate the draft |
| 데이터 분석 | `support` | exact released knowledge-analysis Instruction Bundle Revision | the exact staged source revision; optional reviewed guidance only in a successor plan contract |

`item_management` remains registration-only and receives neither authoring advice nor broad Graph
context. Workers do not communicate directly. The Orchestrator remains the only component that
resolves, authorizes, and materializes the selected revisions.

## 2. Three trust layers

The workspace has three deliberately different trust layers:

```text
AGENTS.md
  = executable platform + role instructions
  = deterministically assembled from one pinned Instruction Bundle Revision

references/guidance/*.md
  = reviewed working guides and prompt resources
  = untrusted data even when company-authored
  = exact members of a pinned Reference Bundle Revision

references/evidence/context.md and source/**
  = task-specific Graph evidence or exact analysis source
  = untrusted data selected through typed retrieval/source contracts
```

Text in a guide, textbook, prior item, or Graph projection never overrides `AGENTS.md`, JSON Schema,
the fixed tool/sandbox policy, or the typed worker request. A Markdown heading named “system
instruction” inside a reference remains data. Materialization must never concatenate Reference or
Evidence Bundle bytes into `AGENTS.md`.

The job-local `AGENTS.md` stays concise. Large guides are separate Markdown members because Codex
instruction discovery is bounded and because loading every guide as unconditional authority would
increase tokens and prompt-injection impact.

## 3. Canonical sources and revision model

No new canonical entity is required for V1. Existing owners already express the needed lifecycle:

```text
reviewed instruction Markdown Artifact
  -> immutable Instruction Bundle Revision
  -> role policy in immutable Execution Preset Revision
  -> exact Resolved Execution Plan step
  -> disposable job-local AGENTS.md

reviewed guidance Educational Document (document_kind=GUIDANCE)
  -> immutable approved Educational Document Revision
  -> immutable INTERNAL_GUIDE Artifact members
  -> optional Knowledge Graph DOCUMENT_REVISION / DOCUMENT_SECTION projection
  -> immutable Reference or Evidence Bundle member pointer
  -> disposable job-local references/guidance/*.md
```

The Educational Document Revision is the canonical source identity for a guide. A Graph node is a
rebuildable projection, not a second copy of the document. Instruction authority comes only from
the released Execution Preset's pinned Instruction Bundle; no Graph edge can grant instruction
authority.

A normative instruction derived from an internal guide is a distinct reviewed Markdown Artifact.
Its provenance records the source Educational Document Revision and source SHA-256, but the
derived instruction has its own Artifact Revision and hash. Editing creates a successor revision;
released bytes are never changed in place.

## 4. Current content-team intake classification

The two files received in `staging/content-team-prompt-drop/` remain protected, untracked intake
bytes. They are not worker authority and the raw source bytes are not copied into Git. Reviewed,
provenance-pinned derivatives now use the separately specified EOM Guidance Markdown V1 format.

| Intake document | Initial canonical class | Intended use | Explicit non-use |
| --- | --- | --- | --- |
| 통합과학 모의고사 1회차 배치 방식 | `GUIDANCE` / `INTERNAL_GUIDE` | future assessment-form assembly constraints, coverage and score validation, product usage planning | not a one-item authoring prompt; not attached to current item jobs |
| 통합과학 일러스트 프롬프트 가이드 통합본 | `GUIDANCE` / `INTERNAL_GUIDE` | image-role visual policy, reusable representation modules, and review-role QA criteria | not copied wholesale into `AGENTS.md`; not automatically trusted because it resembles a prompt |

The mock-exam derivative is
`content/authoring-rules/integrated-science-mock-exam-assembly-v1.md` and belongs primarily to the
future assembly layer above “make one item.” The illustration/reference derivative is
`content/image-specs/kice-integrated-science-illustration-v1.md`. A future compact image-role
instruction remains a separate artifact; it is not this reference file. Each future registered
revision must preserve the original source provenance and its own derivative hash.

## 5. Role-specific selection

The released Execution Preset remains the authoritative role-to-bundle map. It already provides a
map keyed by worker role, which is bounded to five entries and avoids repeated path or filename
inference.

For each step, resolution pins:

- role and step key;
- model and reasoning effort;
- Instruction Bundle logical ID, immutable revision ID, manifest Artifact Revision, and hashes;
- optional role-specific Reference Bundle logical/revision IDs and hashes;
- optional Graph Snapshot and Evidence Bundle revisions selected by the reviewed retrieval policy;
- Content Pack release and workflow protocol revisions; and
- exact sandbox, network, timeout, capacity, and worker-pool policy.

The browser may select a reviewed product preset, not a filesystem path or individual Markdown
file. A future ADMIN editor creates a new draft/released bundle revision and then a successor preset
revision. Existing workflows continue to use their pinned prior revisions.

## 6. Graph integration

### 6.1 What enters the education graph

Approved guidance documents use the existing `INTERNAL_GUIDE` source class. Knowledge analysis may
propose only the existing typed education-graph nodes and relationships that the document actually
supports, including:

- `DOCUMENT_REVISION` and `DOCUMENT_SECTION` for source identity and sections;
- `ASSESSMENT_PATTERN` for reusable item or visual patterns;
- `DATA_REPRESENTATION`, `FIGURE`, `TABLE`, or `EQUATION` for representation rules;
- curriculum, concept, process, claim, and item links only where the source provides exact evidence;
- source pointers and page/section/member anchors back to the immutable guide revision.

Role applicability, execution precedence, model selection, tool permission, and “must obey” status
do not become education-graph edges. Those remain control-plane policy.

### 6.2 Retrieval behavior

Graph retrieval returns a bounded Evidence Bundle of typed pointers and Markdown projections. The
retrieval application must filter by:

- exact published Graph Snapshot Revision;
- caller permissions and released access-policy revision;
- selected curriculum subtree and use-case kind;
- allowed source classes, including `INTERNAL_GUIDE` only when the preset permits it;
- required role/use-case tags from reviewed guide metadata, not free-text filename matching;
- lifecycle, rights, media type, schema, member path, and SHA-256; and
- byte/token budget with deterministic ranking and deduplication.

The current graph does not need a new node type for prompts. A guide remains a document source;
derived assessment patterns and representation rules are graph knowledge. Adding `PROMPT` or
`INSTRUCTION` node types would mix execution authority into the education ontology and is rejected.

### 6.3 Static guidance versus request evidence

Static role guidance changes infrequently and belongs in a role-specific Reference Bundle.
Scientific facts, textbook anchors, approved prior-item structures, and curriculum context vary by
request and belong in an Evidence Bundle. This split prevents every request from traversing Graph
for stable operating instructions and prevents static guides from bloating each Graph query.

## 7. Materialization contract

The Orchestrator materializes only members authorized by the exact persisted plan:

```text
workspace/
  AGENTS.md
  instructions/
    platform.md
    <role>.md
    <optional-small-reviewed-role-component>.md
  references/
    guidance/
      index.md
      <bounded-reviewed-guide>.md
    evidence/
      context.md
  source/
    ... only for the data-analysis source contract
```

`AGENTS.md` is assembled in deterministic PLATFORM then ROLE order. `references/guidance/index.md`
is data describing which exact staged files are relevant and their safe use; it is not an alternate
instruction chain. All files are regular, non-symlink, group-readable but not group-writable, and
created only beneath the known job workspace. Paths are temporary locations, never identities.

Before each member is dereferenced, the application validates logical/revision ownership, manifest
membership, approval/release state, schema, `text/markdown` media type, rights policy, exact hash,
canonical storage containment, file type, UTF-8, size, and caller authorization. Missing, stale,
forged, duplicated, unsafe, or oversized members fail before worker start.

## 8. Access patterns and data structures

| Operation | Structure | Complexity and scale |
| --- | --- | --- |
| role policy lookup | role-keyed map in one preset revision | expected `O(1)`, at most five roles |
| guide identity lookup | indexed logical/revision IDs | `O(log n)` |
| exact bundle member lookup | manifest path/key maps | expected `O(1)` per bounded member |
| duplicate member detection | sets for keys, paths, and revision IDs | expected `O(n)` total |
| graph neighborhood retrieval | indexed adjacency and curriculum closure | `O(selected subgraph + results)` under fixed budget |
| materialization | one streaming hash/copy pass | `O(bytes)`, constant buffer memory |

Expected initial scale is fewer than 100 internal guides, fewer than 32 instruction components per
role, fewer than 256 static reference members, and the existing bounded Evidence Bundle budget.
PostgreSQL stores metadata and pointers only; Markdown bytes remain Artifact members.

## 9. Transactions, concurrency, retry, and idempotency

- Intake/guide publication, bundle release, and preset release each use their existing short
  transaction and immutable revision semantics.
- Artifact writes occur outside DB transactions through the canonical staging/hash/atomic-commit
  adapter.
- A workflow resolves one preset and all bundle/evidence revisions once. Replay returns the same
  plan and never consults a mutable current pointer.
- A changed guide, bundle, or preset under the same idempotency identity conflicts; it never
  overwrites or silently substitutes bytes.
- Materialization failure occurs before worker start. A post-start worker failure consumes only the
  one normal attempt; no session resume or hidden cross-account retry is added.
- Concurrent releases are serialized by logical identity and unique revision constraints.

## 10. GUI lifecycle

The ADMIN surface should present a small guidance library, not a raw server-file editor:

```text
Intake source -> Draft derivative -> Validate -> Human review -> Release
             -> attach to new bundle draft -> review diff -> release successor preset
```

The GUI may display sanitized Markdown, exact revision/hash provenance, role applicability,
Graph/publication status, and revision diffs. It must not expose NAS paths, repository paths,
credentials, raw worker prompts/results, or allow editing a released revision. Preview rendering
escapes HTML and never executes embedded links/scripts. A draft is mutable only in the GUI's review
workspace; publication creates immutable Artifact and bundle revisions.

The normal editor sees only reviewed preset names. Model, reasoning effort, bundle IDs, Graph
revision, and worker slot remain ADMIN details.

## 11. Slot05 isolation and rollout gate

The running textbook batch is pinned to its current knowledge-analysis preset, Instruction Bundle,
workflow protocol, and source topology. This work must not:

- edit or republish that preset/bundle revision;
- restart, drain, disable, reauthenticate, or inspect the active worker workspace content;
- enqueue a guidance analysis job while the batch owns slot05;
- run a migration or deploy API/Catalog/Orchestrator/GUI code during the batch;
- mutate the current batch, accepted runs, predecessor pointers, or monitor process.

Source development and non-live tests are safe because installed services execute the prior clean
release. Data-analysis guidance activation requires a successor preset/protocol and is deferred
until the current batch is terminal and its complete coverage evidence is frozen. Authoring/review
bundle rollout is also kept in one separately reviewed deployment so no shared service restart can
interrupt slot05.

## 12. Failure and security behavior

- Graph text that claims to be an instruction remains reference data.
- A Graph result cannot name a host path or cause arbitrary file materialization.
- A guide absent from the exact bundle/evidence allowlist is unreadable to the worker.
- Wrong role, rights class, source revision, schema, media type, lifecycle, or hash fails closed.
- A stale Graph projection never substitutes the latest guide revision.
- Duplicate source sections are deduplicated by immutable revision/member/hash, not by fuzzy title.
- Prompt injection, malicious Markdown/HTML, traversal, symlink, Unicode collision, oversized file,
  unknown relation, and answer-bearing leakage receive explicit negative tests.
- Worker credentials and user account identity never enter guidance, Graph, DB payloads, logs, Git,
  or Slack.

## 13. Phased implementation

1. **Completed source phase:** preserve uploaded files as protected untracked intake; define the
   JSON Schema-validated EOM Guidance Markdown V1 source format; create reviewed derivatives with
   exact source hashes; and run non-live separation/parser tests.
2. **Guidance intake:** register the two files as approved `GUIDANCE` Educational Document
   Revisions through Manual Content Intake; no worker is launched merely by intake.
3. **Role derivatives:** create compact reviewed instruction derivatives and larger guidance
   references; publish role-specific bundle revisions without changing current presets.
4. **Graph projection:** after slot05 is free, analyze the approved guidance revisions through a new
   explicitly authorized batch, review/publish a successor Graph Snapshot, and verify exact source
   coverage and no ontology/prompt-authority contamination.
5. **Preset activation:** evaluate and release successor authoring/review/image policies; create a
   successor data-analysis preset only after the textbook batch terminates.
6. **GUI:** add guidance draft/review/publish and bundle-diff controls, then deploy in a separately
   reviewed window.

## 14. Simpler alternatives rejected

Pointing workers at one shared Markdown folder is simpler but makes mutable paths authoritative,
leaks unrelated data, defeats role isolation, and prevents exact replay. Copying every guide into
every `AGENTS.md` exceeds the instruction budget and turns untrusted source text into authority.
Putting prompts directly in the education graph conflates execution policy with scientific
knowledge. Reusing a previous Codex session hides state and cross-contaminates items. The existing
immutable bundle plus bounded Graph evidence architecture is the smallest implementation that
preserves freshness, provenance, security, and role specificity.

## 15. Verification checklist

- exact role receives its exact Instruction Bundle and no other role's instruction;
- `AGENTS.md` is deterministic, bounded, and contains no Reference/Evidence body bytes;
- guide references are separate regular Markdown files with exact hashes;
- source-like instructions in references cannot alter the invocation or output schema;
- wrong/stale/missing/unauthorized guide pointers fail before worker start;
- one Graph guide source is traceable to an immutable Educational Document Revision and Artifact
  member without copying the source body into DB;
- role retrieval excludes unrelated guide sections and respects budgets/rights;
- historical workflows replay with their original bundle and graph revisions;
- current slot05 batch/preset/process/service state is byte- and pointer-unmodified;
- no external LLM API, new dependency, service restart, migration, or live Codex attempt occurs in
  the source-only phase.
