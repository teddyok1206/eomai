# Knowledge-backed item workflow V1

## Decision

The `generic-item-development@1.2.0` workflow creates one canonical assessment Item from a
bounded, structured brief without requiring subject-matter Source Intake. The worker may use its
built-in general scientific knowledge, but every cross-component message remains schema-valid and
the final Item Revision pins immutable artifacts and hashes.

Content Pack schema 1.1 records this as `built_in_general_knowledge` with empty Intake and mapping
pointer sets. It never borrows a placeholder source identity merely to satisfy provenance shape.

1. **Responsibility and boundary.** The Web GUI/API normalize natural language into a small
   `ItemBrief`. Catalog binds a released Content Pack and a reviewed stimulus-media pointer.
   Orchestrator remains the only worker coordinator. Catalog alone materializes the validated
   authoring result as canonical `ITEM_CONTENT`; HWPX remains a delivery adapter.
2. **Canonical source.** The approved Item Revision and its `ITEM_CONTENT` artifact are canonical.
   A worker result and a workspace copy are provenance/materialization, not canonical content.
3. **Entity and revision model.** `Item -> immutable Item Revision -> ITEM_CONTENT component` stays
   unchanged. Workflow, worker-result, media, and HWPX artifact revisions keep separate identities.
4. **Pointers and resolution.** The workflow snapshot pins Content Pack release, media artifact,
   media revision, artifact member, media type, dimensions, and SHA-256. Catalog verifies every
   pointer before registration; HWPX verifies it again when materializing input.
5. **Access patterns.** Workflow/step/result lookup is by indexed opaque ID. Upstream results are
   resolved once by immutable revision for prompt rendering and registration. Item and media
   components are keyed by `(component_type, ordinal)`.
6. **Structures and indexes.** Existing indexed DB records and unique component positions are
   retained. Prompt context uses a keyed map for O(1) step-result lookup; canonical body ordering
   remains an immutable tuple.
7. **Scale and complexity.** One item contains at most 100 bounded blocks and one result JSON is
   capped before parsing. Resolution and validation are O(blocks + choices). No binary enters a DB
   row.
8. **Transaction/concurrency.** Workflow start, human approval, registration, and artifact commits
   keep their existing idempotency and transaction boundaries. A registration key pins the
   workflow attempt and pack release.
9. **Dependency direction.** API/Web -> workflow application -> workflow/catalog contracts.
   Catalog implements artifact resolution/registration. Workers never access DB or NAS and never
   communicate directly. HWPX consumes only an approved Item Revision.
10. **Failure/retry/idempotency.** Missing/stale/hash-mismatched media or worker artifacts fail
    closed with no implicit latest-revision fallback. Step and registration idempotency keys retain
    replay semantics; human rework remains explicit.
11. **Simpler alternative.** Reusing the placeholder workflow would keep workers blind to real
    content and produce no `ITEM_CONTENT`; directly importing a hand-written fixture would bypass
    authoring/review/orchestration. Neither exercises the requested pipeline.

## Initial delivery-profile constraint

The first profile deliberately targets the existing `eom-question-template-v1` contract: Korean
single choice, five choices, one three-column data row, one bounded Hancom equation, an ordered
`ㄱ/ㄴ/ㄷ` statement set, and one pinned 800×500 PNG. This is a content-profile constraint, not the
canonical Item model. Textbooks and mock exams continue to consume the same approved
`ITEM_CONTENT` revision and may project it through other delivery profiles later.
