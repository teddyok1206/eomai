# Mixed INDEX Workflow definition successor

2026-10-19 UTC. Source-only contract slice of
`REGISTERED_REVIEW_INCREMENTAL_INTEGRATION_DESIGN.md`; not an installed runtime,
service admission, source grant or proof of execution.

1. Responsibility: declare the fixed INDEX Workflow2 for mixed source-plan2 and
   request2. Compiler and static definition admission only; no runner behavior.
2. Canonical source: a separate JSON Schema 2020-12 definition1.4 and immutable
   `local-embedding-index/2.0.0` YAML. Definition1.1/1.0.0 bytes stay unchanged.
3. Identity: definition key/version, canonical definition SHA, Workflow ID and
   native execution identity remain separate. No implicit latest or upgrade.
4. Resolution: a hash-pinned packaged schema validates the exact schema1.4,
   fixed limits and ordered application/terminal steps before typed parsing.
5. Access patterns: exact definition/protocol lookup and ordered two-step
   iteration. There is no worker dispatch, Codex role or arbitrary operation.
6. Structures: an independent frozen `LocalEmbeddingWorkflowDefinitionV2`, the
   existing fixed `LocalEmbeddingStep` and terminal, and one exact admission tuple.
7. Complexity: bounded 64KiB parse/hash, two ordered steps and O(1) admission.
   There are no new dependencies, persistent indexes, caches or queues.
8. Concurrency: canonical bytes and SHA are immutable values; this pure slice
   owns no DB/session/claim/lease. The original owner must later reauthorize work.
9. Dependency: pure Workflow contracts/compiler depend on existing value types
   and pinned schema registry. No Catalog infrastructure or runner imports.
10. Failure/replay: wrong version/purpose, extra fields, copied forged values,
    reordered steps or non-fixed limits fail closed. Recompilation of the same
    definition yields the same bytes/hash. Old parsers still reject definition2.
11. Simpler alternative: widening definition1.1 would redefine pinned history;
    changing the numeric protocol would duplicate unchanged computation. Only
    metadata definition2 advances; `local-embedding/1.0` and incremental result1
    remain the existing fixed numerical boundary. Runtime support is separate.
