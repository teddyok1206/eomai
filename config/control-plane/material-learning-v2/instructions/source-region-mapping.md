# EXTRACT_ITEM source-map clarification (append to the released V1 role instructions)

This clarifies the existing result contract; it does not change the source or its answer.
`proposal.content_region_map` must have exactly one mapping for every required content path:

- `title`, `interaction`, `score`;
- each `body[i]`, using its zero-based position (not its `block_id`);
- `solution.explanation`;
- `solution.correct_choice_ids` for `single_choice`, or `solution.accepted_answers` otherwise.

A mapping for the parent object `solution` does NOT replace the two required solution leaf
mappings. Additional resolvable paths may be mapped, but no `content_path` may be repeated.
Every `region_ids` entry must identify an actual region in this result. Use the existing
field-specific source-role rules; do not invent a source region or claim an independent
answer was printed in the source. Keep independently solved conclusions in `solution_report`.
When editorial evidence exists, include its actual `EDITORIAL_SOLUTION` region and map source
answers and explanations to that region. Do not omit the supplied matched solution pages.
If no matched editorial answer is supplied, keep `solution_origin=INDEPENDENT_PROPOSAL_UNVERIFIED`
and the independent report's honest no-editorial cross-check. A target-question anchor may support
an explicitly independent proposal; it must not be described as a printed editorial answer.

Before submitting, enumerate these required paths from the actual proposed content and compare
them with the unique `content_path` values in the map. Check both solution leaves explicitly.
The Orchestrator will reject an incomplete map. Do not return an almost-complete proposal or
change the schema to hide a missing reference.
