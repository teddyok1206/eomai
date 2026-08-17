# Agent Rules

These rules apply to all future Codex and automation work in `/home/eom/EOM`.

1. Never modify `/home/eom/EOMIS`.
2. Treat `/home/eom/EOM` as a separate Git repository with separate history.
3. Use protocol-first development. Define JSON Schema before worker behavior.
4. Validate agent messages with JSON Schema 2020-12 and future Pydantic models.
5. Do not let workers communicate directly with each other.
6. Route all worker work through the orchestrator.
7. Do not let workers write to NAS. Workers read staged local inputs and submit local results.
8. Only the orchestrator commits validated artifacts to NAS.
9. Never commit secrets, tokens, credentials, `.env` files, Codex auth, SSH keys, or database passwords.
10. Preserve logical ID, revision ID, and SHA-256 content hash as separate immutable concepts.
11. Treat every external file as untrusted input.
12. Use explicit Conda environments. Do not rely on an ambient Python.
13. Apply formatter, linter, type checker, and focused tests before merging core code.
14. Do not merge core protocol, storage, state-machine, or worker changes without tests.
15. Document the reason for every new dependency.
16. Use UTC for system timestamps.
17. Use Asia/Seoul only for user-facing display.
18. Do not put generated artifacts directly into Git.
19. Store HWPX, PNG, AI, PDF, long logs, and backups in NAS with manifests.
20. Do not use port 8000 for new EOM services. The reserved API bind is `127.0.0.1:8765`.
21. Do not use external LLM APIs.
22. Do not copy root Codex auth to workers.
23. Do not add worker users to sudo, Docker, or the `eom` group.

## Development Progress Reporting

- When the development reporter is enabled, send reports only at important milestones.
- The Slack development reporter is not a production runtime feature.
- Slack failure must not block development, tests, commits, or runtime workflows.
- Never send secrets, full diffs, full logs, worker prompts or results, or item content to Slack.
- Keep routine reporting milestone-based and avoid excessive messages.
- Report `BLOCKED` and `COMPLETED` milestones immediately.

## Pointer-Oriented Data and Artifact Design

In these rules, a pointer is a validated identity or reference. It is not a C or C++ raw memory
pointer and does not justify unsafe memory access.

1. Do not repeatedly copy large files, complete items, image bytes, HWPX packages, or worker output
   between services. Materialize bytes only at an explicit input, workspace, validation, or commit
   boundary.
2. Cross-component references should use the smallest typed contract that can preserve identity and
   reproducibility. Prefer logical entity ID, immutable revision ID, artifact ID, artifact revision
   ID, SHA-256 content hash, schema ID and version, storage URI, and a typed manifest or DTO.
3. Model items, images, Content Packs, HWPX, and deliverables as:

   ```text
   logical entity -> immutable revision -> component pointers
                  -> artifact revisions -> content hashes
   ```

4. Never store large binary payloads in PostgreSQL. Store metadata, relationships, state, foreign
   keys, artifact pointers, and hashes.
5. A filesystem path is a storage location, not identity. Identity is a logical ID plus a specific
   revision ID.
6. Keep one canonical artifact. Other entities reference it; they do not maintain duplicate copies
   in other tables or folders.
7. Before dereferencing a pointer, validate target and revision existence, expected schema/version,
   media type, SHA-256, access permission, lifecycle state, and immutability.
8. Treat dangling pointers, stale revisions, deleted targets, and hash mismatches as explicit errors.
   Never silently substitute the latest revision or invent a recovery.
9. Distinguish a mutable "current revision" reference from an immutable pinned revision. Workflows,
   audit records, prompt provenance, and other reproducible history must pin a specific revision.
10. Do not pass large arbitrary dictionaries or JSON blobs when a typed pointer contract contains
    the data required by the use case.
11. A workspace copy is temporary materialization, not canonical source. Canonical source is the
    registered revision and its validated artifact.
12. Do not force pointer decomposition onto small immutable value objects with no independent
    lifecycle. Keep those values in a frozen typed model.

Implementation and review checks:

- Pointer DTOs include the identity, pinned revision, schema/version, and expected hash needed for
  safe resolution.
- Resolution code returns a typed result or a stable missing/stale/hash error.
- Tests cover missing targets, stale revisions, hash mismatch, immutable revisions, and duplicate
  references.
- Persistence tests assert that large binary content is absent from DB rows.

## Data-Structure-Driven Design and Optimization

1. Before implementing a substantial feature, state its dominant access patterns: key lookup,
   ordered iteration, membership, deduplication, FIFO/LIFO, priority scheduling, graph traversal,
   range query, append-only history, concurrent claim, or immutable snapshot.
2. Choose the structure that matches the operation:

   - key lookup: map/dict or indexed DB column;
   - uniqueness/membership: set, hash, or unique constraint;
   - FIFO: deque or an explicit indexed DB queue;
   - priority processing: priority queue or indexed ordering;
   - workflow dependency: DAG with adjacency representation;
   - event history: append-only monotonic sequence;
   - revision chain: immutable linked relation;
   - ordered immutable output: tuple or frozen typed model;
   - sparse relationship: adjacency list;
   - component lookup: keyed collection;
   - artifact assembly: typed manifest.

3. Replace repeated list scans with maps, indexes, or lookup tables when the operation is key lookup.
4. Do not implement repeated deduplication with list membership scans. Use a set, unique key, hash,
   or DB constraint.
5. Represent state transitions and workflow graphs with explicit transition tables, typed graphs, or
   state machines instead of nested `if`/`elif` blocks.
6. Prefer enums, typed identifiers, discriminated unions, schemas, and lookup tables over implicit
   naming conventions and repeated string comparison.
7. For a persistent or shared data structure, document expected scale, frequent operations, time and
   space complexity, ordering stability, concurrency needs, persistence needs, alternatives, and
   trade-offs. Keep this short when the choice is obvious.
8. Design DB queries from access patterns. Review foreign keys, unique constraints, B-tree indexes,
   partial indexes, and GIN indexes explicitly.
9. Avoid N+1 queries, full scans for indexed lookup, repeated JSON parsing, repeated hashing of the
   same immutable file, unnecessary deep copies, and O(n-squared) loops with a clear linear or
   indexed alternative.
10. Do not persist a derived value by default. If it is persisted, identify whether it is canonical
    or a cache and define invalidation or immutability rules.
11. Performance optimization requires evidence from a benchmark, query plan, profiler, throughput
    measurement, memory measurement, or an obvious complexity improvement. Do not leave an
    obviously wrong structure merely because current fixtures are small.
12. Prefer correct modeling, indexes, batching, and immutable pointers over micro-optimization. If an
    optimization adds complexity, document measured benefit and maintenance cost; keep the simpler
    design when benefit is unproven.

## Clear Hierarchy and Dependency Direction

Use this dependency direction:

```text
interfaces / CLI / future API / GUI
    -> application services / use cases
    -> domain models and state machines
    -> contracts / identifiers / value objects

infrastructure adapters
    -> implement interfaces defined by application or domain layers
```

Domain and contract packages must not import infrastructure packages.

1. Give each package and module one clear responsibility and one primary reason to change.
2. Higher layers depend on stable interfaces and contracts, not lower-layer implementation details.
3. Isolate PostgreSQL, NAS, Codex CLI, Slack, HWPX, HTTP, and filesystem behavior in infrastructure
   adapters.
4. Domain models must not operate on SQLAlchemy sessions, subprocesses, filesystem paths, or HTTP
   clients.
5. CLI code validates presentation-level input, constructs typed commands/queries, calls an
   application service, and renders the result. It must not implement business rules.
6. Workers implement neither orchestration nor persistence. They accept structured input and return
   structured results.
7. Application services own use-case orchestration, schema validation, transaction boundaries,
   idempotency, and calls to domain rules and adapters.
8. Do not introduce circular imports. Expose supported package behavior through `__init__.py` or an
   explicit public interface; external packages must not reach into private modules.
9. Do not create god classes, god services, mutable global registries, implicit singletons, or vague
   catch-all `manager`, `utils`, `helpers`, or `common` modules. Name modules by domain responsibility.
10. Split modules by responsibility and reason to change, not by an arbitrary line count.
11. Use dependency injection only where tests or adapter replacement need it. Do not introduce a DI
    framework for simple object construction. Prefer composition over inheritance.
12. Do not bypass a service boundary to mutate another component's tables or private modules.
    Cross-component communication uses existing protocols and application contracts.

## Simplicity and Maintainability

1. Choose the simplest implementation that satisfies current invariants and explicit extension
   boundaries.
2. Do not pre-build generic frameworks, plugin systems, metaprogramming, or abstraction layers for
   hypothetical future requirements.
3. Keep one authoritative domain rule and reinforce it with the necessary DB constraint. Do not copy
   the same business invariant into unrelated adapters.
4. Add an abstraction only for at least two real use cases or a clear adapter boundary. Prefer a
   function over a class hierarchy for single-purpose logic.
5. Replace growing boolean-flag APIs with typed commands, strategies, or separate use cases.
6. Make side effects explicit. A service or function should make clear what it reads, materializes,
   commits, and changes.
7. State-changing operations should return the result, generated IDs, prior/new state, event, and
   stable error code where those are relevant.
8. Name functions, classes, and modules after domain responsibility rather than implementation
   technique.
9. Comments explain the protected invariant, risk, design reason, or trade-off, not a restatement of
   the code.
10. A temporary workaround records its reason, impact, removal condition, related document or issue,
    and safe fallback.
11. Extend an existing implementation when it already owns the boundary. Do not build a parallel
    framework.
12. Optional adapters must remain removable without breaking production core. Extend public
    contracts and persistent schemas cautiously while keeping internal implementation simple.

## Required Design Procedure

Before a DB schema, workflow, artifact model, registry, queue, search, cache, or cross-service
protocol change, write a short design note covering:

1. responsibility and system boundary;
2. canonical source;
3. logical entity and revision model;
4. required pointers and resolution checks;
5. primary access patterns;
6. chosen data structures and indexes;
7. expected time/space complexity and scale;
8. transaction and concurrency boundary;
9. dependency direction and adapter ownership;
10. failure, retry, and idempotency behavior;
11. the simpler alternative and why it is insufficient.

Small local changes do not require a large design document.

## Required Review Checklist

Before completing a substantial implementation, verify:

- no file or payload is duplicated without a defined materialization boundary;
- logical ID, revision ID, artifact ID, artifact revision, and hash remain separate;
- reproducible history pins a revision instead of resolving an implicit latest value;
- pointer resolution validates existence, permission, schema, media type, lifecycle, and hash;
- dangling and stale pointers fail explicitly;
- data structures and DB indexes match the dominant access pattern;
- map/set/index should not replace a repeated list scan;
- there is no avoidable O(n-squared) behavior, N+1 query, or repeated parse/hash;
- unique constraints, foreign keys, partial indexes, and GIN/B-tree indexes are adequate;
- dependency direction is correct and domain packages do not import infrastructure;
- CLI and adapters contain no business rules;
- no parallel framework or unjustified abstraction was introduced;
- modules and classes have coherent responsibilities;
- constraints and tests protect idempotency and concurrency;
- optional adapters remain removable;
- optimization has evidence and complexity is justified;
- a simpler expression is not available;
- a maintainer can trace ownership and data flow quickly.

## Testing Requirements for Design Invariants

Add the applicable tests for pointer resolution, missing targets, stale revisions, hash mismatch,
immutable revisions, duplicate references, idempotent replay, concurrent creation, index-backed
queries, deterministic manifests, canonical serialization, lifecycle transitions, dependency
boundaries, forbidden cross-layer imports, absence of runtime Git/source dependency, and absence of
large binary DB values.

When a data structure or query optimization is material, include a synthetic benchmark or query-plan
test. Keep live, integration, and usage-consuming tests explicitly marked and opt-in as required by
the existing rules.

## Design Documentation

Record durable decisions in the appropriate ADR, architecture document, operations runbook, or
schema documentation. Keep `AGENTS.md` focused on enforceable rules and checklists rather than
duplicating feature implementation details.
