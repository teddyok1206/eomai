# Knowledge Analysis Batch Execution V1

Status: design approved for implementation

Date: 2026-08-26 UTC

## V1.1 unmapped-range extension

The immutable `knowledge-analysis-batch-request/1.0` contract remains available byte-for-byte and
continues to require at least one curriculum unit key per range. The additive
`knowledge-analysis-batch-request/1.1` contract permits an empty `curriculum_unit_keys` tuple with
one precise meaning: the pinned textbook pages are intentionally not mapped to a curriculum unit
at submission time. Typical examples are covers, front matter, transitions, indexes, and appendices.

The canonical source remains the pinned Educational Document Revision and its resolved Artifact
Revision/hash. Empty keys do not authorize nearest-unit inference, implicit latest-revision lookup,
or omission of pages. They preserve the absence of a reviewed mapping so downstream analysis can
produce independently attributable graph evidence without corrupting curriculum provenance.

Dominant access patterns, normalized rows, indexes, transaction boundaries, runner ownership,
one-attempt behavior, review authorization, and idempotency are unchanged. Validation dispatches
by the explicit request schema version. Public creation emits V1.1; private Catalog transport reads
both V1 and V1.1. This adds no dependency, migration, binary payload, cache, or new cross-service
write path. Filtering unmapped pages was rejected because the product requirement covers every
page; assigning a nearby unit was rejected because it would manufacture canonical data.

## 1. Responsibility and boundary

`KnowledgeAnalysisBatch` is an operator-authorized aggregate for executing a finite, immutable set
of existing single-source Knowledge Analysis requests. It solves one operational problem: a fresh
ADMIN session authorizes the batch once, while a Catalog-owned application runner advances the
already-authorized ranges without manufacturing browser sessions or weakening the existing
15-minute fresh-auth policy.

The batch does not replace the existing single-analysis application service, workflow, worker,
review, or artifact contracts. Every new range still follows:

```text
batch range
  -> KnowledgeAnalysisApplicationService.create
  -> orchestrator workflow
  -> capacity lease
  -> fixed Codex worker
  -> proposal artifact validation
  -> KnowledgeAnalysisApplicationService.reconcile
  -> optional preauthorized review
```

Workers remain isolated, communicate only with the orchestrator, read staged local inputs, and
never write to PostgreSQL or NAS. Only existing orchestrator and Catalog artifact commit boundaries
materialize canonical artifacts.

## 2. Canonical source and immutable identity

The canonical batch request is a schema-valid JSON document normalized into the batch and ordered
range rows, with one SHA-256 over its canonical serialization. The database does not retain a
second arbitrary JSON copy of those rows. The normalized aggregate contains:

- the logical batch ID;
- a pinned released Execution Preset revision and hash;
- a pinned released risk-policy revision and hash;
- the general-knowledge mode;
- the review policy and authorizing operator;
- an ordered tuple of range specifications.

Each range pins one Educational Document revision, physical page bounds, curriculum unit keys, and
an execution mode. Catalog resolves the document revision at batch creation and persists the exact
source Artifact ID, Artifact Revision ID, media/schema identity, and SHA-256. A mutable current
document revision is never resolved during execution.

Identifiers remain distinct:

```text
analysisbatch_<uuid>                logical batch execution
analysisrange_<uuid>                immutable ordered range identity
edudocrev_<uuid>                    immutable Educational Document revision
artifact_<uuid> / rev_<uuid>        canonical source Artifact identity
sha256:<digest>                     immutable source content identity
analysisrun_<uuid>                  one concrete analysis attempt
```

No PDF, page text, image bytes, proposal payload, or worker output is stored in the batch tables.

## 3. Range execution modes

V1 supports two explicit modes:

1. `EXECUTE`: create one new Knowledge Analysis run. An optional predecessor may identify one
   terminal `FAILED`, `REJECTED`, or `CANCELLED` run with identical source, preset, and risk-policy
   dependencies. This is an operator-authorized retry, not an automatic retry.
2. `REUSE_ACCEPTED`: pin one already `ACCEPTED` Knowledge Analysis run whose source range, source
   pointers, preset revision, risk-policy revision, and accepted-result pointers all match. No
   worker executes for this range.

Each `EXECUTE` range has `maximum_attempts=1`. A failed execution moves the range to `FAILED` and
the batch to `BLOCKED`. The V1 runner never submits a second attempt. A later retry requires a new
fresh-auth command or a new batch manifest that explicitly pins the failed predecessor.

## 4. Review authorization

V1 supports `PREAUTHORIZED_APPROVE_VALIDATED` only. At batch creation the fresh ADMIN explicitly
authorizes the Catalog runner to submit an `APPROVE` review on that operator's behalf only when:

- the worker workflow completed successfully;
- proposal schema, pointer, ontology, risk, and artifact validation passed;
- reconcile produced exactly `NEEDS_REVIEW`;
- the range and analysis run still match the immutable batch pointers;
- no prior review exists; and
- the batch remains active and uncompromised.

The authorization record stores operator ID, UTC authorization time, canonical request hash, and
review-policy name. It never stores a session ID, cookie, bearer token, password, or authentication
material. The resulting review remains an ordinary immutable Knowledge Analysis review and records
the authorizing operator. Notes contain the batch and range IDs, not textbook content.

Validation failure, workflow failure, pointer mismatch, stale revision, unknown model capability,
or an unexpected state is never auto-approved.

## 5. Persistent aggregate and state machines

### Batch

```text
QUEUED -> RUNNING -> SUCCEEDED
                  -> BLOCKED
       -> CANCELLED
RUNNING -> CANCELLED
BLOCKED -> CANCELLED
```

`SUCCEEDED` requires every range to be `ACCEPTED`. `BLOCKED` requires at least one `FAILED` range
and prevents claims for later ranges until an explicit future recovery command. V1 intentionally
fails closed instead of continuing past a failure.

### Range

```text
PENDING -> CLAIMED -> SUBMITTED -> ACCEPTED
                  \-> FAILED
PENDING -> ACCEPTED       (validated REUSE_ACCEPTED)
PENDING/CLAIMED/SUBMITTED -> CANCELLED
```

`CLAIMED` has a short database lease. An expired claim may be reclaimed with the same deterministic
range submission key. Idempotent replay can recover a lost create response but cannot create a
second analysis run. `SUBMITTED` stores exactly one `analysis_run_id` and is advanced by observing
that pinned run; it is never resolved by latest-source lookup.

Events are append-only with a monotonic sequence per batch. Event payloads contain only IDs,
states, error codes, hashes, and bounded counters.

## 6. Access patterns and data structures

Dominant operations are:

- batch lookup by ID: primary-key B-tree, `O(log B)`;
- ordered range iteration: unique `(batch_id, ordinal)` B-tree, `O(log R + k)`;
- claim the next eligible range: partial B-tree on `(state, next_action_at, batch_id, ordinal)` with
  `FOR UPDATE SKIP LOCKED`, `O(log R)`;
- find a range by analysis run inside a batch: unique partial `(batch_id, analysis_run_id)` index,
  `O(log R)`;
- source coverage lookup: B-tree on document revision and page bounds, `O(log R + k)`;
- batch event history: unique `(batch_id, sequence)`, `O(log E + k)`.

The ordered manifest is represented as an immutable tuple in contracts and one indexed row per
range in PostgreSQL. A JSON list in one batch row was rejected because it would require repeated
full-document updates, prevent indexed claims, and make concurrent recovery unsafe. A generic DAG
engine was rejected because the workload is a strict FIFO sequence and the existing workflow engine
already owns each individual analysis DAG.

Expected initial scale is fewer than 100 batches and at most 1,000 ranges per batch. Storage is
linear in range count and contains pointer metadata only.

Batch creation keeps a transaction-scoped map keyed by immutable Artifact/Revision/hash tuples.
It parses each Educational Document manifest and rights attestation once per batch instead of once
per page range. The cache never crosses a transaction or execution boundary; each later range
submission resolves and validates its pinned source dependencies again.

## 7. Transaction and concurrency boundaries

Batch creation validates the entire manifest and all pointers before inserting the batch, ranges,
authorization, and initial event in one transaction. A request hash plus API idempotency key makes
replay return the same batch; a changed body fails with an idempotency conflict.
The hash covers the normalized request and operator identity, while the trusted server-side
authorization timestamp is stored separately. This lets a lost-response replay after a new HTTP
request recover the first batch without rewriting its original authorization time.

The runner performs one short action per transaction:

1. claim one range with `SKIP LOCKED` and a lease;
2. call the existing idempotent single-analysis service outside the claim transaction;
3. persist its exact run pointer;
4. on later polls, inspect that run and invoke existing reconcile/review services;
5. persist the range terminal state and append events.

Only one range per batch may be nonterminal beyond `PENDING`, protected by a partial unique index.
The global Knowledge Analysis capacity policy remains authoritative and currently permits one held
analysis lease. The batch runner does not infer capacity from hardware and does not start Codex
directly.

## 8. Dependency direction and ownership

- API contracts define create/read DTOs.
- Catalog contracts define the immutable batch manifest and private application commands.
- Catalog application service owns validation, transactions, idempotency, state transitions, and
  calls to the existing single-analysis service.
- Catalog application runner owns polling and calls the batch application service.
- Application API enforces fresh ADMIN authorization once at create time and calls Catalog through
  the existing private Unix socket.
- Query Adapter exposes read-only batch/range projections.
- Orchestrator and worker packages remain unaware of batches.

Domain contracts do not import SQLAlchemy, sockets, filesystem code, API code, or runner code.

## 9. Failure, retry, and idempotency

- Missing/stale document, Artifact, revision, schema, media type, lifecycle, or hash: reject the
  entire batch before insertion.
- Duplicate or overlapping page coverage for the same document revision: reject the batch.
- Expired runner claim before an analysis pointer exists: reclaim and replay the deterministic
  create key.
- Existing analysis pointer: never submit another create; observe and advance only that run.
- Workflow or validation failure: reconcile the run, mark range `FAILED`, batch `BLOCKED`, preserve
  all evidence, no automatic retry.
- Runner crash after review: deterministic review key and existing review uniqueness make replay
  idempotent.
- Capability/auth observation expiry: the workflow runner periodically renews sanitized local
  auth and CLI capability evidence for enabled idle bindings before it expires. This maintenance
  starts no generating worker, creates no operator command, and stores no browser session, token,
  cookie, or Codex credential. Active leases and pending operator commands take precedence. A real
  login expiry is persisted as `AUTH_REQUIRED`; the next range then fails closed rather than
  fabricating READY evidence. A later operator login is detected by the bounded periodic probe.
- Database or Catalog socket error: retain/reclaim the short action lease; do not fabricate a
  terminal analysis result.

## 10. Security and operational constraints

- Fresh-auth and ADMIN permissions remain required for batch creation.
- No authentication material is persisted in the batch.
- The Catalog runtime receives only the table privileges needed for batch metadata plus its existing
  Knowledge Analysis privileges.
- Network, worker HOME, Codex auth, NAS, and service identities remain unchanged.
- Automatic worker-health maintenance uses the existing fixed non-generating auth probe and
  reviewed CLI capability policy. It refreshes READY evidence five minutes before the 15-minute
  TTL, retries non-ready idle bindings no more often than every five minutes, and never interrupts
  a held lease.
- Slack receives milestone counts and stable error codes only, never textbook or worker content.
- Deployment is additive: migration, source deploy, Catalog runner restart, and API restart. No
  Content Pack, HWPX builder, worker auth, or Node/Kordoc change is involved.

## 11. Required tests

- JSON Schema 2020-12 and Pydantic parity for manifest, commands, and projections.
- Missing/stale document revision, Artifact, media/schema mismatch, and hash mismatch fail closed.
- Duplicate/overlapping ranges and duplicate accepted/predecessor pointers fail.
- Canonical serialization and request hash are deterministic.
- API idempotent replay and changed-body conflict.
- Two-session `SKIP LOCKED` claim yields one owner; expired claim replay creates one analysis run.
- `REUSE_ACCEPTED` validates every pinned dependency and creates no workflow/job.
- Preauthorized review executes only after `NEEDS_REVIEW`; invalid proposals never register accepted
  result pointers.
- Worker failure blocks the batch and creates no retry.
- Crash recovery after create/reconcile/review is idempotent.
- Query plans use the claim and ordered-range indexes.
- Runtime privilege matrices contain only required batch table grants.
- Existing single-analysis API, workflow, Graph publication, HWPX, and historical protocols remain
  unchanged.
- PostgreSQL rows contain no PDF, PNG, HWPX, page text, proposal body, token, session, or password.

## 12. Simpler alternative and why it is insufficient

Repeated browser login plus a `/tmp` loop keeps the current API unchanged, but it makes a 495-range
operation depend on a terminal, sudo timestamp, and a 15-minute interactive session. It has no
durable aggregate, no indexed claim recovery, and no product-visible coverage record. Extending
fresh-auth lifetime or rewriting `authenticated_at` would weaken security. Direct Catalog calls from
an operator script would bypass the API authorization boundary. The bounded persistent batch is the
smallest durable extension that preserves the existing single-analysis and worker architecture.
