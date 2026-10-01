# ADR 0162: Module boundary enforcement and workflow schema cache

## Context

The repository has explicit dependency-direction rules, but the existing automated boundary test
covered only selected packages. A repository-wide AST audit found no infrastructure dependency in
contract/domain packages and no service-to-application dependency. It also found one existing
strongly connected component containing Catalog, Identity, Orchestrator, and Workflow Runner. Those
packages share SQLAlchemy metadata and atomic transactions; treating them as independently deployed
services would be inaccurate.

The audit also measured repeated workflow role schema materialization. A single public load cost
7.629 ms for authoring input 1.24, 35.642 ms for authoring result 12, and 63.863 ms for knowledge
proposal result 10 on the reviewed source environment. Validation repeatedly parsed, checked, and
inlined the same immutable wheel resources.

## Decision

Enforce the lower-layer boundary for every discovered `packages/*/eom_*` package and prohibit every
service from importing an application entrypoint. Build a first-party adjacency map in tests and
compute strongly connected components in O(V + E). A cycle may not include a package, app, or any
service outside the reviewed runtime composition cluster. This is a regression fence, not a claim
that the existing cluster is ideal.

Move HMAC cursor serialization and the immutable page result value from the SQL query adapter into
the DB-independent pagination module. The old query-adapter import remains a compatibility re-export.

Cache canonical workflow role schemas by exact `(role, protocol_version)` or `schema_id`. The key
space is the finite checked-in mapping. The first access still reads the package resource and runs
JSON Schema 2020-12 and reference-closure checks. Internal validation reads the cached canonical
dict; public loaders return a deep copy so a caller cannot mutate shared validation state.

## Boundaries and data structures

- Canonical sources remain wheel-owned JSON Schema resources and their checked-in hashes.
- No logical ID, revision ID, Artifact pointer, schema identity, DB row, or wire message changes.
- Cache lookup is expected O(1); retained space is O(R), where R is the finite number of admitted and
  historical role schema identities.
- The import graph is a test-only adjacency map of sets. Tarjan traversal is O(V + E) and adds no
  runtime dependency.
- Cursor encode/decode remains O(n) in the bounded cursor payload and preserves the exact HMAC bytes.
- No transaction, concurrency, retry, idempotency, NAS, or worker boundary changes.

## Performance result

The same 20-call measurement after the change produced 0.051 ms, 0.284 ms, and 0.837 ms per public
load respectively. This removes repeated parse/inlining work without adding a request-time network
hop or DB query. Public-copy isolation and exact cursor compatibility are covered by focused tests.

## Rejected alternatives

Splitting every large file by line count would create wrappers without clearer ownership and could
duplicate version registries. Decomposing the four-package runtime cluster in this change would put
shared commit and claim transactions at risk without an isolated persistence port or recovery proof.
Returning the cached mutable schema directly would be faster but would allow one caller to corrupt
subsequent validation. Keeping repeated schema parsing avoids retained memory but wastes measurable
CPU on immutable inputs. These alternatives are rejected.
