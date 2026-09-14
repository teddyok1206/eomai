# ADR 0088: Catalog-owned mock-exam assembly boundary

## Status

Accepted for implementation.

## Responsibility and canonical source

The Catalog service owns mock-exam candidate resolution, immutable review evidence, Item component
dereferencing, assembly planning, and released assembly persistence. The Application API owns only
authentication, authorization, HTTP/idempotency presentation, and orchestration. Assembly plans and
manifests remain canonical typed Catalog values; the private Unix-socket response is a validated
materialization, not a second source of truth.

The old Application API adapters constructed `MockExamAssemblyService` directly. That required the
API database role to read Catalog-only tables and would also require the API process to traverse NAS,
contradicting its runtime-isolation contract. Adding either privilege would widen the wrong trust
boundary and still leave the other dependency broken.

## Protocol, pointers, and resolution checks

A new immutable Catalog application request/response schema family carries four discriminated
operations: preview a plan, create an explicit assembly, create a planned assembly, and inspect an
immutable assembly revision. Requests contain the existing typed policy, Graph, cohort, deliverable,
placement, actor, and expected-plan pointers. Responses contain exactly one existing typed assembly
plan or manifest. Both peers validate JSON Schema 2020-12 and Pydantic models, and the Catalog service
continues to validate all logical IDs, revision IDs, schemas, media types, lifecycle states, member
hashes, and canonical NAS locations before returning a value.

## Access patterns, structures, scale, and indexes

The dominant operations are indexed key lookup and one bounded exact-cohort resolution of 25 Item
revisions. Existing SQL `IN` queries and maps/sets keep joins, uniqueness checks, and pointer lookup
O(n) time and O(n) temporary space for n <= 25; assembly revision inspection is O(1) indexed lookup.
No binary or large result is stored in PostgreSQL or copied through the API. The bounded JSON socket
message carries pointer-rich plan/manifest metadata only. Existing foreign keys, unique aggregate
keys, and Item/review/Graph indexes remain authoritative; no new database structure is required.

The dedicated Catalog runtime role must read the complete bounded assembly projection: the pinned
Graph and curriculum rows, Item/review/Artifact pointers, immutable deliverable and assembly
aggregates, and both the current `usage_records` history and its legacy `usage_records_v1`
predecessor. The current usage table is read-only at this boundary. A focused privilege-contract
test keeps this complete read set and the smaller Form/Assembly write set aligned with repository
queries, so a new query cannot be fixed by widening Application API access or an ad hoc live grant.

## Transaction, concurrency, retry, and failure

Preview is read-only. Creation stays inside the Catalog service's existing transaction and aggregate
locks, with deterministic revision identity providing idempotent replay. The API idempotency record
continues to wrap public create calls, while the production coordinator pins the plan before creation
and reuses its deterministic operation key. A bounded assembly-specific socket timeout covers the
25-member validation workload; unknown transport outcomes remain retryable and are resolved by the
same immutable inputs. Schema errors, missing pointers, stale revisions, hash mismatches, permission
errors, or ambiguous responses fail closed with stable Catalog/application errors.

The pinned Deliverable and Deliverable Revision are validated with ordinary indexed reads. They are
not mutable assembly aggregates, and the Catalog runtime role intentionally has no UPDATE privilege
on them. Locking starts at the Form/Assembly aggregate owned by this use case; deterministic IDs,
unique keys, foreign keys, and those aggregate locks protect concurrent creation and replay.

## Dependency direction and simpler alternative

API interfaces call an application adapter implementing the private Catalog contract; the Catalog
application server composes the infrastructure service that owns PostgreSQL and NAS. Contract models
do not import either infrastructure implementation, and workers are not involved. Granting Catalog
table `SELECT` or NAS traversal to the API role would be a smaller edit but violates least privilege,
duplicates the service boundary, and merely moves the failure to the next dereference. A second
assembly framework or subprocess bridge is unnecessary because the existing authenticated Unix
socket already owns analogous Catalog operations.
