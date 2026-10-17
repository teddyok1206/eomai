# Private Chat QUERY workflow completion

2026-10-17 UTC. Design before protocol/behavior. This is the missing C4 execution
boundary in the original incremental-RAG goal, not another queue or an activation.

1. Responsibility: admit a distinct fixed private-question application step into
   the existing Runner only after source/claim/control and native admission are
   connected. Define its fixed graph, canonical completion receipt and small step
   output first. The existing Chat owner and Orchestrator retain their authority.
2. Canonical source: the owned immutable user message; existing private execution
   record/result/shard/vector Artifact; original Workflow/step/command allocation.
   Never copy the native input/question into another canonical file or DB field.
3. Identity: preserve Workflow/step, launch Job, Artifact producer Job, receipt
   producer Job and Artifact revision/hash as distinct concepts. Pin the original
   live Chat origin hash separately from the private basis and public query scope.
4. Resolution: supplied closure validation binds actual request/policy/bundle,
   launch, original Chat origin, text-free intent, result and numeric members.
   It checks exact member names/schema/media/raw hashes, shared file-set revision,
   basis and current expectations. It does not prove current authority by itself.
5. Access patterns: fixed two-step DAG and bounded key/hash comparisons. Existing
   unique Workflow/step/attempt and original native Job key remain authoritative.
6. Structures: frozen values and a closed JSON Schema2020-12 resource, registered
   in the existing native resource owner. No table, queue, cache, mutable dispatch
   registry, dependency or generic execution framework is added by this contract.
7. Complexity: O(bounded intent/result metadata), constant graph and member count;
   vectors remain behind their Artifact pointer, not duplicated in the receipt.
8. Transaction: the future submission and RUNNING/allocation commit must preserve
   the existing Workflow→command root fence. Pin the original live origin at that
   boundary; never replace it after expiry, crash or another claim. No SQL root
   spans native work. Completion and replays reauthorize the appropriate live or
   historical owned-source read boundary without reviving expired execution.
9. Dependencies: pure workflow/contracts validate values; existing Orchestrator
   publishes; Runner owns leases/state transitions; infrastructure implements
   current source/Identity/runtime reads. Workers gain no DB/NAS access.
10. Failure/replay: reject cross-family or cross-origin outputs, altered immutable
    pins and malformed nested copies. One native attempt only. An uncertain launch
    retains its original key/history, not another inference or a fabricated success.
11. Simpler alternative: relabeling a private result as the released reference
    application result bypasses its source contract and SQL CHECK. A distinct
    fixed definition/receipt is necessary; copying the entire Runner is not.

The first contract slice deliberately does not enable the compiler's private
dispatch, submit a Workflow, widen the step-result CHECK or create a migration.
Those changes must land with actual source admission/checkpoint execution and
guarded persistence tests. Existing compiler/Runner parsers must still refuse the
private definition until that composition exists. Historical INDEX/reference
schemas, keys, outputs and canonical bytes remain unchanged.

The pure receipt validator takes expected original IDs and origin from its owner,
not from model output. Hash equality or a supplied origin is never a permission
grant. Native result validation reuses the existing private encoder contract; no
tokenizer, scoring, pooling, normalization or binary implementation is introduced.

Required source tests: resource/mirror/hash, strict fixed graph and one attempt,
bool/coercion/extra-field rejection, canonical roundtrip, unvalidated nested model
copies, exact original origin/actor/basis/launch and file-set closure, raw versus
semantic hashes, wrong producer IDs, timestamps, and old parser/compiler rejection.
No model execution or mutating DB test is implied by these pure-value tests.

## Contract checkpoint

The distinct packaged schema and frozen definition/receipt/step-output are now
implemented. Schema raw SHA-256:
`694c6043fc7f78f662b01bf05d7d812453efdbdfa400b3b4fcfc85c31f21195a`.
They bind the owner-supplied original origin, actor, basis, request/control/native
launch, text-free execution record and result/shard/binary raw hashes. The three
actual Jobs and the separate receipt versus four-member numeric file sets cannot
be merged. Existing private numeric validation is reused, not reimplemented.

Final related source regression: **402 PASS/74.06s across16 suites**, including
55 new private workflow cases. Earlier50/397 subsets overlap and are not added.
Strict mypy2 production files and Ruff/format3 files PASS. The initial new fixture
failed because it hashed a noncanonical `+00:00` timestamp before the typed UTC
`Z` conversion; the fixture was corrected, not the canonical/hash invariant.

This is **SOURCE_PASS / NOT_INSTALLED / NOT_ACTIVE / C4_NOT_ACCEPTED**. Compiler
and current Runner admission intentionally remain closed; their explicit rejection
is tested. No DB/state/queue or persistence behavior changed, so no mutating DB
test or migration is claimed. No runtime, service, authentication, model or source
policy was changed for this pure contract checkpoint. Actual owner admission,
atomic origin/allocation, completion publication/checkpoint execution and Chat
tool delivery remain necessary, alongside the unchanged full-goal gates.
