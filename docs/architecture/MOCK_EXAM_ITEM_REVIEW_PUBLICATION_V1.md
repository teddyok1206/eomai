# Mock-exam Item review eligibility and publication v1

## 1. Responsibility and system boundary

The Catalog application service owns two operations. `INSPECT_MOCK_EXAM_REVIEW_ELIGIBILITY`
validates a content-team workflow and returns the same exact review evidence both before and after
human approval. Its atomic approval state distinguishes pending evidence from the approved human
identity and timestamp. `PUBLISH_MOCK_EXAM_ITEM_REVIEW` appends one immutable A/B/C rating only
after that workflow has been approved, completed, and registered as its exact current V2 Item revision.
Workers do not publish ratings, write Catalog tables, or write NAS artifacts.

## 2. Canonical source

Before approval, the canonical source is the immutable authoring/image/review artifact chain plus
the pending workflow approval snapshot. After approval, the canonical rating source is one
`mock-exam-item-review-decision/1.0` artifact. It pins the source review pointer, approval,
workflow, Item revision, explicit operator-selected rating, released rating policy, idempotency
hash, and decision time. `ItemReviewRecord` is the indexed pointer projection and never duplicates
the review result or decision payload.

## 3. Logical entity and revision model

The evidence chain is:

```text
fresh production-plan workflow
  -> immutable authoring revision
  -> optional immutable image revision (or pinned SKIPPED branch)
  -> immutable review revision
  -> human approval snapshot
  -> current APPROVED Item revision + V2 content component
  -> immutable review-decision artifact revision
  -> append-only ItemReviewRecord
```

Logical artifact IDs, artifact revision IDs, Item revision IDs, workflow IDs, record IDs, and
SHA-256 values remain distinct. The publication command requires both `item_revision_id` and
`expected_workflow_id`; it never resolves an implicit latest workflow. Only `CREATE_ITEM`
content-team requests carrying a self-hashed mock-exam slot are admitted, excluding legacy,
revised, and general generated Items.

## 4. Required pointers and resolution checks

Eligibility resolves the exact workflow definition and hash, request hash, production-plan slot,
active authoring/image/review steps, step input pointer lists, role-worker inputs, jobs, approved
artifacts/revisions, manifests, physical members, media/schema identities, SHA-256 values, parsed
role results, human gate, and approval lock version. A pending result requires null reviewer/time;
an approved result requires the exact human reviewer/time and the same gate inputs. The image branch
must be either one exact SKIPPED step for zero IMAGE slots or one succeeded image result covering
every IMAGE ordinal.

Publication repeats the same chain resolution, then requires a completed workflow, an
unsuperseded succeeded registration step, the exact current active APPROVED Item revision, one V2
content component byte-equal to the authoring draft, zero blocking findings, and one successful
human approval by the supplied operator. Decision artifacts are resolved through fixed type,
member name, JSON media type, schema reference, manifest hash, member hash, protocol revision,
request/result projection, JSON Schema, Pydantic identity checks, and self-hash. Missing, stale,
dangling, superseded, unapproved, mismatched, or physically altered pointers fail explicitly.

## 5. Primary access patterns

The hot paths are exact primary-key/foreign-key lookup, one Item-revision membership lookup, a
bounded lookup of active workflow step attempts, one review per Item-revision lookup, and one
immutable member read. Eligibility is read-only. Publication performs append-only history plus
idempotent artifact commit. No unbounded graph traversal or large payload scan occurs.

## 6. Data structures and indexes

Small immutable tuples preserve upstream pointer order; dictionaries provide artifact/member key
lookups; sets detect duplicate identities; typed Pydantic models replace arbitrary JSON. Existing
primary keys cover workflow, step, job, artifact, revision, approval, Item, and review-record
identity. Existing B-tree indexes on `item_revisions.workflow_id`,
`workflow_step_runs.workflow_id`, `approval_requests.workflow_id`, and
`item_review_records.item_revision_id` support the bounded queries. The deterministic review
record primary key provides exact replay collision protection. No new table or migration is
required because the Catalog service is the sole writer and locks the parent Item row before its
one-current-review check.

## 7. Expected scale and complexity

A workflow has at most four attempts per configured step and at most twenty findings. Database
lookups are index-backed O(log n); all in-memory validation is O(s + f), where `s` is the bounded
number of step attempts and `f <= 20`. Memory is O(f) plus one bounded role-result payload. Review
results are capped at 256 KiB and other role results/Item content at 4 MiB.

## 8. Transaction and concurrency boundary

Eligibility uses one read session and changes no state. Its result includes workflow and approval
lock versions so the approval command can reject a stale pending snapshot. The same query remains
valid through APPROVED, REGISTERING, and COMPLETED states and returns the exact approved gate, so a
coordinator does not need a second private database reader after approval.

Publication first locks the parent Item/current revision, resolves all evidence, and checks for an
existing review. It then commits the deterministic decision artifact at the artifact adapter's
idempotent transaction boundary. A second transaction re-locks the Item, re-resolves the full
chain, verifies that the decision is unchanged, verifies the committed artifact, and appends the
record. Concurrent different keys serialize on the Item row; the loser observes the existing
decision and receives `ITEM_REVIEW_ALREADY_PUBLISHED`. Concurrent exact replays additionally
converge on the deterministic record ID and artifact idempotency key.

An artifact committed before a stale second transaction is an unreferenced immutable artifact,
not a competing rating; retry resolves the same artifact. It can be found later by its deterministic
artifact job idempotency key.

## 9. Dependency direction and adapter ownership

JSON Schemas and Pydantic DTOs live in `eom_catalog_contracts`. The Catalog application service
owns orchestration and transaction boundaries. `ItemReviewArtifactStore` is the narrow adapter
interface; `CatalogArtifactService` owns PostgreSQL/NAS materialization. The private Catalog Unix
socket and Application API only validate/dispatch typed operations. Domain contracts do not import
SQLAlchemy, filesystem, socket, or API modules.

## 10. Failure, retry, and idempotency behavior

Every validation failure uses a stable content-free code. Pointer/hash/schema failures never fall
back to a latest revision. Blocking findings produce a schema-valid ineligible inspection result;
publication rejects them. Rating is never inferred from model output or review text: the caller
must explicitly provide A, B, or C (the production coordinator selects C), and the canonical
decision self-hash binds it.

The review record ID is derived from a scoped SHA-256 of the caller key. Exact retries require the
same workflow, Item, rating, reviewer, policy, evidence, decision artifact, and severity projection;
otherwise they fail with an idempotency conflict. A different key cannot replace an existing
rating. Artifact commit uses a deterministic key scoped to that review record.

## 11. Simpler alternative and why it is insufficient

Pointing `ItemReviewRecord` directly at the worker `REVIEW_REPORT` is simpler, but that artifact
does not contain the human A/B/C decision and therefore cannot protect the rating from row drift.
Storing the rating only in JSONB has the same provenance gap. Trusting workflow state without
dereferencing author/image/review inputs permits stale or unrelated artifacts. Resolving “latest”
breaks reproducibility. A canonical self-hashed decision artifact plus a small indexed pointer row
is the smallest design that protects the complete operator decision and remains replayable.
