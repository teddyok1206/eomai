# ADR 0082: Material requirement authority precedence

## Status

Accepted.

## Responsibility and system boundary

The reviewed Item Brief chooses one exact student-visible material form. The mock-exam layout slot
provides an ordered set of forms that the planner may choose from; it does not choose the form for a
V4-or-later Brief. Authoring and review consume the selected form, while Catalog and HWPX retain the
existing deterministic structural validation. Workers remain isolated and communicate only through
the orchestrator.

The production incident that motivated this successor selected `DATA` for a slot whose allowed set
was `(TEXT, DATA)`. The V4 wire contract and deterministic validators accepted that selection, but
the previous standard role instruction still required `preferred_material_profiles[0]`. The review
worker therefore emitted a false blocking `MATERIAL_PROFILE_MISMATCH` finding.

## Canonical source and revision model

For Brief schema `4.0`, `item_brief.material_requirement` is the canonical selected form and
`item_brief.task_type` is its exact redundant projection. `mock_exam_slot.preferred_material_profiles`
is the immutable ordered allowed set. The selected form must be a member of that set, but need not be
its first member. Brief schema `3.0` retains its historical first-preference meaning.

The correction is additive:

- Content Pack `generated-knowledge-item/1.16.1`;
- standard control bootstrap `14.0` and knowledge-grounded bootstrap `11.0`;
- mock-exam production plan/execution `5.0`, pinning the successor Pack while retaining Workflow
  `1.10.0`, role protocol `1.20.0`, Brief `4.0`, and material requirement `1.0`.

All earlier Pack, control, plan, execution, and checkpoint bytes remain unchanged and readable.

## Required pointers and resolution checks

The production plan pins the logical generation block, block revision and self-hash, Pack key and
version, Pack source-tree hash, Workflow definition/version, role protocol and schema bundle, Brief
schema, and material-requirement schema. Runtime resolution pins the exact released Pack revision
and hash and exact execution preset revision and hash. Every Workflow pins the selected requirement,
the allowed slot tuple, Graph/Evidence provenance, and its resolved execution plan.

Resolution fails closed if the selected form is outside the allowed set, differs from `task_type`,
has an incoherent panel count, or if any Pack/preset/plan pointer or hash differs. Review instructions
must explicitly prohibit treating `preferred_material_profiles[0]` as the selected form for Brief
`4.0`.

## Access patterns, structures, and complexity

The fixed production plan performs ordered iteration over 25 positions. Membership of one selected
form in a slot's bounded allowed tuple is constant bounded work; global identity and duplicate checks
use sets and position-keyed maps. Plan construction and validation remain `O(Items)` time and space,
with `Items = 25`. No new database query, index, large payload, or persisted derived cache is needed.

## Transaction, concurrency, retry, and idempotency

Existing Workflow, checkpoint compare-and-swap, Artifact commit, and command-lease transactions are
unchanged. A production `5.0` occurrence cannot resume from a `4.0` checkpoint because schema family,
plan ID, plan hash, generation block, Pack release, and preset revision are pinned. Replays use the
same operation keys and may adopt only exact existing results. A blocked `4.0` occurrence is retired
through the existing production retirement boundary; its immutable review evidence is not rewritten.

## Dependency direction and adapter ownership

JSON Schema and frozen contract models own the wire invariant. Control-plane and Pack assets express
the worker instruction. The application coordinator resolves and pins them; infrastructure adapters
only transport or materialize validated pointers. Catalog and HWPX consume contracts through their
public interfaces and do not infer a replacement material form.

## Failure and acceptance gates

Tests cover every fixed production position, especially all selections that are not the first allowed
profile; Brief `3.0` legacy behavior; Pack/control predecessor byte preservation; exact successor
hashes; schema/Pydantic parity; resolver/checkpoint family separation; and a review prompt regression
that says the selected form may be a later allowed member. A live canary must complete all 25
authoring/review/registration paths, including one-table, two-table, one-image, two-image, and mixed
forms, before assembly and HWPX acceptance.

## Simpler alternative considered

Reordering every layout slot so the selected form is first would rewrite the released layout policy
and erase the distinction between an allowed set and an occurrence selection. Ignoring one review
finding would trust an unvalidated exception and leave future workers exposed to contradictory
instructions. Mutating Pack `1.16.0` or the production `4.0` plan would break reproducibility. An
additive successor is the smallest change that preserves history and makes the authority order
unambiguous end to end.
