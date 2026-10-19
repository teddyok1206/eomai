# Mixed native Workflow carriers

2026-10-19 UTC. Contract-only successor of the registered-review integration
design; no runtime/coordinator/claim/definition activation is implemented here.

1. Responsibility: carry mixed source-plan2 through an explicit service request2,
   original launch-ownership2 and completion2, without worker source authority.
2. Canonical inputs: real owner-captured plan2, new immutable native policy1.1
   instance pinned to definition2.0.0, original encoding Job request1 and numeric
   input/result/shard1. Old policy bytes are not relabelled as new definition.
3. Identity: Workflow/step/launch/reservation Job, source-plan raw/semantic SHA,
   association, original allocations and actual registration remain distinct.
4. Pointers: request2 requires namespace2/source-plan2 and native policy1.1;
   intent2 requires source-plan2; completion2 requires registry2/index2 and exact
   receipt member2. No legacy schema accepts these by widening its literals.
5. Access: bounded original-owned-set membership, encoding lookup, exact row,
   source/profile/evidence and whole-index completion closure.
6. Structures: frozen typed frames, tuples and maps/sets, existing schema registry
   with separate pinned successor resources. No new queue/cache/database model.
7. Scale: at most1,024 owned Jobs/entries and64MiB ownership metadata; request/
   receipt64KiB and step output8KiB. Batch validation is O(n+bytes), not repeated
   full numeric input/result validation for every completion event.
8. Concurrency: no stored token, lease secret or transferable grant. Existing
   command generation/late source/IAM/commit/CAS and physical owner fences remain.
9. Dependency: Workflow contracts depend on pure Catalog/operator contracts.
   Reuse existing actual numerical types; extract only genuinely shared pure
   checks, never duplicate the runtime state machine or introduce infrastructure.
10. Failure: unknown/cross-version fields, wrong definition/source-plan/policy/
    original intent/allocation/hash/row/result/registration fail closed. Old
    parsers continue rejecting successor frames. No retries, replay key change,
    current-head lookup or authority inference.
11. Alternative: widening ownership1 would mutate pinned historical meaning;
    new numeric Job/input/shard versions would fragment identical encoding work.
    Only the three metadata carrier boundaries need additive successors.

Native execution policy1.1 has no namespace field, so its schema is reusable;
the new policy instance must pin the new definition SHA and actual same service.
Data-access policy1.2 is separately owned by Catalog, not this numerical policy.
Coordinator checkpoint2 must later carry registration2/output2; actual coordinator
behavior and runtime closed dispatch remain the orchestrating owner's next step.

The frozen contract slice passed 320 focused source tests in 52.19 seconds
(`mixed-native-carriers-freeze.xml`), including the unchanged released-family,
coordinator and dependency suites; the new carrier leaf passed 40 tests. Strict
type checking, Ruff and formatting passed for the eight owned Python files.
Successor frames are independent frozen models, not subtypes of released1
frames. Supported original-read dispatch preserves the original intent/completion
family when mixed work borrows a completed encoding Job1; it never retags that
history. These are source-only contract proofs, not runtime admission, native
execution, registration or production activation evidence.
