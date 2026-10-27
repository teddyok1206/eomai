# Creative archive extraction and verifiable solution proposal

## Exact input and task

Read the typed `work_input`, the staged source/page-set manifests and every image in the
workspace-root `codex-image-inputs.json`. Preserve the exact source ID, source revision, external
five-digit number and `source.input_sha256` in the output. An external number is metadata, not an
Item ID. A PDF page is a derivative of the pinned Office source, not an original past-exam
occurrence. Use only the delivered pages; do not look for a newer edition or a nearby source file.

Return `external-item-learning-result@1.0`. This first pass proposes one extracted Item and its
source-anchored solution steps. It does not replace the accepted past-exam V9 analysis or V10
additive-report contracts, create Graph IDs or approve the proposed Item.

## Separate the actual item from surrounding editorial material

Inspect the whole page before identifying the target. The archive can put a creative question
on the left, its editorial solution/metadata on the right, and an attached original past-exam
question at the bottom right. Do not combine these into one question.

Create a duplicate-free registry of visible regions with result-owned `extregion_` IDs. Give each
region exactly one role: `TARGET_ITEM`, `EDITORIAL_SOLUTION`, `REFERENCE_ORIGINAL`, or `OTHER`.
Use physical page numbers from the exact staged page set and normalized 0–10000 bounding boxes.
Record the observed text and confidence without inventing unreadable words. If the target cannot
be separated from a reference attachment, return an `AMBIGUOUS_REGION` blocking conflict.

`REFERENCE_ORIGINAL` may be described as a separate observed region but must never supply the
proposed Item content, answer, explanation or solution steps. An original attachment is not proof
of a past-exam identity, and the creative source must not be registered as that attachment.

## Preserve content representations and their anchors

Preserve the visible upper stem, text, formulas, native tables, diagrams, statement sets, choices,
answer and explanation independently. Do not generate a new question, improve the wording, add a
`<자료>` heading, convert a native table into prose, or replace an unresolved visual with invented
image bytes or a guessed path. If a required visual cannot be represented by the supplied Item
contract and validated inputs, report `UNRESOLVED_IMAGE` rather than a fake resolved image.

Choose each Item body's discriminated type first and emit only that branch's allowed fields.
Use `content_region_map` paths that resolve in the actual proposed `AssessmentItemContent`:
`title`, every `body[i]`, `interaction`, `solution.explanation`, `score.points`, and the applicable
`solution.correct_choice_ids` or `solution.accepted_answers`. Add finer mappings when evidence is
available; a plausible-looking but nonexistent path is invalid.

The stem, body and choices may cite only `TARGET_ITEM`. Solution fields and solution-step
summaries may cite `TARGET_ITEM` or `EDITORIAL_SOLUTION`. Scoring can also cite editorial metadata
in `OTHER`. No mapping may cite `REFERENCE_ORIGINAL`. Every reference must byte-for-byte match
this result's own region registry and have no duplicate IDs.

For a statement set, cover every declared statement exactly once in the structured explanation.
For single choice, the correct choice must be one of the actual declared choices; preserve its
source label. Do not infer an answer merely from a nearby number or from the attached original.

## Solve and cross-check, without manufacturing evidence

Produce an ordered, externally checkable solution, with contiguous `step_number` values starting
at 1. Each `reasoning_summary` states the relevant givens/operation, concise rationale and result
needed to verify that step, and cites exact target/editorial region IDs. When applicable, include:

- interpretation of each condition, table entry, graph axis, unit and visual label;
- the relation or formula applied and how the supplied values determine the conclusion;
- an individual check of each statement/choice and the reason an incorrect alternative fails;
- the final answer and a comparison with the visible editorial answer and explanation;
- inconsistencies, missing conditions, uncertain transcription or a unit/sign/label conflict.

These are public solution summaries, not private internal deliberation. Do not claim to have used
textbooks, GraphRAG or external sources that were not materialized for this job. General knowledge
is not a source anchor and cannot repair missing source evidence.

Set `MATCHES_EDITORIAL_SOLUTION` only with a visible `EDITORIAL_SOLUTION` region and an actual
answer comparison. A disagreement is `DISAGREES` plus a blocking `ANSWER_DISAGREEMENT`; an absent
editorial solution is `NO_EDITORIAL_SOLUTION`, not a guessed match. Record missing editorial
evidence with the appropriate conflict rather than implying the official solution was checked.

## Mechanical checks before returning

1. Validate the complete typed output and its single discriminated Item branches against the
   supplied JSON Schema. Return JSON only, without Markdown fences or out-of-contract commentary.
2. Check exact outer input/source/revision/external-number identity; never synthesize these IDs.
3. Require unique region IDs, at least one `TARGET_ITEM`, bounded page/region coordinates and
   physical pages that are actually present in `work_input.page_set.pages`.
4. Resolve every content path in the actual proposed Item and verify required-path coverage.
5. Compute emitted-region IDs minus declared-region IDs separately for every mapping, solution
   step and conflict; every difference must be empty. Enforce the role restrictions above.
6. Check contiguous solution-step numbers, exact choice/statement references and answer agreement.
7. `PROPOSED` requires a proposal, no blocking conflicts and no answer disagreement.
   `NEEDS_DECISION` requires at least one explicit blocking conflict; do not hide an incomplete
   reconstruction behind a superficially valid proposal.
8. Omit `result_sha256` from the model response as required by the supplied Codex result schema.
   The Orchestrator adds that hash over the exact submitted body at validation. Never guess a
   result SHA or change the pinned input SHA to make a result fit.
