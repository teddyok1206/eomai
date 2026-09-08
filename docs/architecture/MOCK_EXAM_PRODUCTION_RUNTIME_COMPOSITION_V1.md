# Mock-exam production runtime composition V1

Status: implemented locally; production execution and deployment intentionally not performed.

## 1. Responsibility and system boundary

The runtime composition joins the existing Application API command/query adapters, Catalog
application client, one-Item workflow coordinator, exact-cohort assembly service, Exam HWPX
service, and atomic checkpoint adapter. The operator CLI authenticates an operator and invokes one
bounded application-service phase. It contains no workflow, selection, review, rating, assembly,
or HWPX business rule. Workers remain behind the orchestrator, cannot call each other, and neither
the CLI nor workers receive NAS or direct database write access.

## 2. Canonical source

The packaged released assembly policy, layout policy, editorial outline, and rating policy are the
canonical static inputs used to derive the self-hashed 25-call production plan. The released risk
policy database row and the execution's pinned preset revision are canonical for analysis and
Graph access-policy pointers. Existing Catalog, workflow, Item, assembly, deliverable, and HWPX
records remain canonical for their own lifecycles. Immutable checkpoint revision JSON files are
canonical for operator-run progress; `current.json` is only their validated compare-and-swap
projection.

## 3. Logical entity and revision model

`production_request_id` names one requested production occurrence. It deterministically maps to
one production execution identity and to one unique `MOCK_EXAM` deliverable key. An execution is
an append-only chain of `execution_revision_id` values and pins the production plan ID/hash. The
deliverable logical ID and its first immutable revision ID remain distinct. Item IDs, Item revision
IDs, assembly revision IDs, HWPX job/artifact revision IDs, and SHA-256 hashes are never collapsed
into filesystem paths or mutable “latest” aliases.

## 4. Required pointers and resolution checks

The release resolver validates the exact released risk-policy revision and content hash. It loads
the exact execution-preset revision pinned by the generation-block resolution and validates preset
identity, state, revision identity/hash, retrieval-policy presence, and admitted corpus. The static
production plan is self-validating and pins assembly/layout/outline/generation-block inputs. Each
application phase rechecks execution ownership and production-plan identity. Graph publication
must present the access-policy revision/hash from that pinned preset. Assembly re-reads the created
deliverable and checks logical ID, key, type, title, edition, lifecycle state, revision ID, and
revision number before returning `MockExamAssemblyIntentV1`.

## 5. Primary access patterns

The operator performs exact lookup by execution ID, ordered phase iteration across 25 positions,
exact lookup by policy or preset revision ID, and idempotent lookup/creation by deterministic
deliverable key. Checkpoint history is append-only; the current revision is one keyed lookup. The
CLI reads only small bounded typed pointer documents and never transports Item content or binary
artifacts.

## 6. Data structures and indexes

The frozen plan and checkpoints use tuples for deterministic position order. Existing coordinator
maps/sets provide constant-time slot, Item revision, review, rating, and cohort membership checks.
Checkpoint paths are keyed by validated execution/revision IDs and protected by one per-execution
file lock. PostgreSQL's unique B-tree constraint on `deliverables.deliverable_key` enforces one
logical deliverable per production request; primary-key and revision indexes resolve the returned
pointers. No new database index or schema is introduced by the composition layer.

## 7. Complexity and expected scale

Each phase reconciles at most 25 Items; ordered traversal is O(25), with O(25) pointer state. Graph
publication is one atomic exact-25 operation. Plan and rating-policy loading occurs once per
composed command runtime. Exact policy/preset reads and current-checkpoint lookup are indexed or
keyed. The composition adds no N+1 query, repeated content hashing, large deep copy, or binary
database value.

## 8. Transaction and concurrency boundary

Catalog, workflow, deliverable, assembly, and HWPX services retain their existing database
transaction boundaries. The CLI never opens a database transaction. Checkpoint creation and
advance use per-execution locks, immutable revision creation, atomic replacement, and
compare-and-swap predecessor checks. The deterministic deliverable key plus database uniqueness
prevents duplicate logical deliverables; a replay revalidates the same first revision before use.
No cross-service distributed transaction is claimed: a failed phase is retried from its last
durable pointers.

## 9. Dependency direction and adapter ownership

`mock_exam_production_cli` depends on the application service and the composition function.
`mock_exam_production_application` owns authorization and use-case sequencing behind narrow ports.
`mock_exam_production_release_resolver` and `mock_exam_production_composition` are infrastructure
adapters that implement those ports using `AppServices`, the Catalog client, Query/Command
adapters, database read models, and Exam HWPX. Domain/contracts do not import infrastructure. The
two-line root CLI registration is the only shared presentation integration point.

## 10. Failure, retry, authorization, and idempotency

Every command authenticates a current access token and constructs an operator `ActorContext`
without granting permissions. Each phase checks its explicit permissions before state-changing
calls; analysis review, Graph publication, and rating require fresh authentication. Executions are
operator-owned. Missing, retired, stale, hash-mismatched, or wrong-scope release pointers fail
closed with stable codes. Replaying a completed/unchanged phase returns the validated checkpoint;
concurrent advances fail compare-and-swap instead of overwriting. Operator files are opened once
with `O_NOFOLLOW`, bounded size, regular-file/single-link validation, and pre/post descriptor
identity checks. The access-token file must be owned by the invoking OS identity and mode `0600`;
errors never echo credentials or supplied content.

## 11. Simpler alternative and why it is insufficient

A shell script that calls internal adapters in sequence would be shorter, but it would duplicate
business rules, lose typed authorization and immutable pointer checks, and make safe replay after
partial progress ambiguous. Adding one large “run everything” API endpoint would also obscure
phase boundaries and create a long-lived failure domain. The small application service plus thin
phase CLI reuses the existing production coordinator and adapters while exposing only the minimum
operator-controlled resume surface.

## Runtime and deployment handoff

Production commands are intended to run as the non-root `eom-api` service identity. The default
checkpoint directory is `/var/lib/eom-api/mock-exam-production`; its parent is already the
systemd-writable state directory. Deployment should create the child directory as `eom-api:eom-api`
with mode `0750` (or allow the service identity to create it) and package the CLI, application,
resolver, composition, coordinator, runner, checkpoint-store, and generation-block-resolver
modules. The runtime must not point the checkpoint option into a Git worktree; the checkpoint
adapter rejects such paths. No secret, input content, checkpoint, or generated HWPX belongs in the
wheel or Git repository.
