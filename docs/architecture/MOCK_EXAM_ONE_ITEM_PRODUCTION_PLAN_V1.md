# Mock-exam one-Item production plan V1

Status: implemented as a pure contract and deterministic builder; execution integration is a
separate application-layer change.

## 1. Responsibility and boundary

`mock-exam-production-plan/1.0` turns one released mock-exam assembly policy, its released layout,
and the pinned Integrated Science editorial outline into exactly 25 independent invocations of the
existing `generic-item-development@1.8.0` one-Item block. It plans creation work only. It does not
select existing Items, invoke workers, approve Items, publish Graph nodes, assemble a form, or write
NAS/DB state.

## 2. Canonical sources

The released assembly policy owns coverage and score constraints. The released layout owns
position, inquiry, difficulty, and preferred material profiles. The raw-hash-pinned editorial
outline owns subject/unit labels and parentage. The generation block pins Content Pack `1.13.0`,
its source-tree hash, workflow `1.8.0`, and the already reviewed content-team guidance text/hash.
No plan field introduces a new content or output-shape rule.

## 3. Entity and revision model

The production plan is an immutable, content-addressed value with `production_plan_id` and
`plan_sha256`. Policy revision, layout revision, outline revision, generation-block revision, and
the later workflow/Item revisions remain separate identities. A planned workflow call is not an
Item and contains no `item_id` or `item_revision_id`.

## 4. Pointers and resolution checks

The builder verifies released state, subject agreement, layout-to-policy revision/hash, guidance
revision/hash, and policy-to-outline raw hash. Each call pins the generation-block key, revision,
and hash. Its frozen `mock_exam_slot` travels inside the V3 brief through the API request, resolved
workflow-domain request, author/review prompt context, and Item-content component provenance.
Before content materialization and registration, the Catalog gate requires exact inquiry presence
and validates authored difficulty plus the canonical material classification against that slot.
`points_milli` remains assembly provenance and is deliberately not equated with the single-Item
`score_display`. An executor must resolve every pinned runtime reference before starting a
workflow; mismatch or absence is an explicit error, never a fallback to a different release.

## 5. Access patterns

Primary operations are keyed policy-requirement lookup, requirement-local membership when the
released requirement sets `distinct_units=true`, ordered slot traversal, ordered outline-child
traversal, and immutable serialization. The builder uses maps and requirement-local sets for those
lookups, and tuples for stable output order. It intentionally imposes no whole-exam unit-uniqueness
rule; repeated middle units remain legal unless their own released coverage requirement forbids it.

## 6. Data structures and indexes

In memory, requirement IDs and requirement-local selected units are hash-indexed; outline units and
children use the existing immutable resolver indexes. There is no persistence or DB query in this
layer, so no new DB index is required. A future execution table should use a unique key on
`(production_plan_id, workflow_call_id)` and index execution state for concurrent claiming.

## 7. Scale and complexity

Current scale is fixed at 25 slots, 21 coverage slots, and 41 outline units. Building indexes and
walking slots is `O(U + S * A)`, where `U` is outline size, `S` is slots, and `A` is the small
allowed-unit set per requirement; memory is `O(U + S)`. Canonical hashing is linear in the small
plan payload. Output ordering is deterministic.

## 8. Transaction and concurrency boundary

The pure builder has no transaction or concurrency boundary. The future application executor owns
one transaction for recording the immutable plan, and a separate idempotent start boundary per
workflow call. Workers remain isolated and communicate only through the orchestrator; workers do
not write NAS.

## 9. Dependency direction and adapter ownership

The JSON Schema and Pydantic values live in Catalog contracts. The builder depends only on stable
contracts and identifiers. API/CLI presentation code may request a plan; an application service may
map each call into the existing Workflow start command. PostgreSQL, control-plane resolution,
Codex CLI, filesystem, and NAS behavior stay in infrastructure adapters.

## 10. Failure, retry, and idempotency

Stale pointers, unsupported 25/50 shape, missing curriculum units, incorrect coverage counts,
requirement-local distinctness failure, and slot/output mismatch have stable errors. Exact inquiry
presence prevents a non-inquiry slot from increasing the released four-inquiry total. Plan replay
over identical inputs produces the same plan ID, hash, call IDs, unit choices, and request hashes.
Retrying a failed workflow uses its same call identity only through the orchestrator's explicit
retry semantics; it must not silently select an already approved Item or create a second successful
result for the same call.

## 11. Simpler alternative and why it is insufficient

Feeding the existing assembly planner a bank of approved Items is simpler, but it means “select 25
existing Items,” not “run the one-Item generation block 25 times.” A free-form loop of 25 API calls
also loses deterministic coverage, score, inquiry, prompt provenance, and replay identity. This
small immutable plan is the minimum boundary that preserves the requested production semantics.

## Execution mapping (application layer)

For every `workflow_calls[]` row, the application layer maps the pinned block plus `item_brief` to
one `WorkflowStartRequest`:

```json
{
  "definition_key": "generic-item-development",
  "definition_version": "1.8.0",
  "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
  "image_mode": "required",
  "pack_key": "generated-knowledge-item",
  "environment": "development",
  "registry_mode": "CREATE_ITEM",
  "execution_preset_key": "knowledge-grounded-item",
  "item_brief": "<workflow_calls[N].item_brief>",
  "educational_retrieval": {
    "schema_version": "educational-retrieval-requirement/1.0",
    "corpus_key": "integrated-science-textbooks",
    "query_kind": "ITEM_PREPARATION",
    "curriculum_root_key": null,
    "topic_keys": [],
    "required_item_elements": ["choice", "paragraph"],
    "source_classes": ["APPROVED_ITEM", "PAST_EXAM", "TEXTBOOK"]
  }
}
```

The API's existing V3 conversion resolves `item_brief.curriculum_selected_unit_key` to the exact
Graph root. `required_item_elements` above scopes evidence retrieval; it does not require a fixed
count of tables, images, or equations. The content-team prompt and image-decision branch continue
to decide the actual item shape.
