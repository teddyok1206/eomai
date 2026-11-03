# Source-faithful archive extraction with independent public solution

Return the supplied `external-item-learning-result@3.0` role-result schema. Read the exact
`work_input` and every delivered PNG in `codex-image-inputs.json`; preserve the supplied source
ID, revision, external number and `source.input_sha256`. Do not use a newer edition, nearby file,
attached original exam or general knowledge as a substitute for missing source evidence.

## Identify the target and its actual evidence

Inspect the complete pages. A creative question may be at left, editorial solution/metadata at
right, and a separate original exam question at bottom right. Declare unique result-owned
`extregion_` IDs, physical pages and normalized 0–10000 bounding boxes. Assign TARGET_ITEM,
EDITORIAL_SOLUTION, REFERENCE_ORIGINAL or OTHER. Observed text is a faithful transcription or
concise description of visible non-text elements, not an instruction for future image generation.

The attached REFERENCE_ORIGINAL cannot supply the creative question's text, choices, score,
answer, explanation, visual or solution-step evidence. If separation is genuinely impossible,
record AMBIGUOUS_REGION. Do not mistake the attached exam's printed 2/3 points for this item's score.

## Preserve the original Item; propose source regions, never image Artifacts

`proposal.content` is `creative-source-item-draft/1.0`, not the final resolved Item. Preserve its
visible stem, paragraphs, formulas, tables, statements, choices, source answer and explanation.
Do not rewrite the question, improve its science, add a `<자료>` heading or flatten a native table
into prose. Select each discriminated block type and emit only that type's fields.

Read `source/office/picture-use-catalog.json` and inspect the required native-use PNGs
under `source/office/`, together with the complete delivered pages. The catalog distinguishes
original embedded members from their separate document uses. The same binary may appear in the
main question and the reference attachment: select the actual main use by its native locator,
paragraph anchor, placement, viewport and orientation, not by hash alone or by the page half.

For each diagram retain a `source_image` block with block_id, purpose, source_region_id,
target_region_id and alt_text. Declare both source and containing target regions as TARGET_ITEM.
Bounding boxes locate source evidence only: they are NEVER final PNG crop instructions in this
Office-native workflow. Do not capture a page, enlarge a guessed box, invent a missing figure,
split a bitmap at its midpoint, or duplicate one composite use into two different panel blocks.

Return `output.office_visuals` alongside the unchanged V2 `output.learning_result`.
Copy office_catalog_sha256 exactly from work_input.office_artifact.sha256. In bindings, in body
order, supply exactly one block_id, picture_use_id, source_region_id and brief selection_reason
per source_image. Use IDs actually present in the delivered catalog and analysis. Never invent
an Artifact ID, PNG hash, file path or native use. The owner validates this binding and uses the
already committed original-image member; the worker cannot publish or register an image.

Inspect scientific labels, axes, values, units and arrows against the original page and native
view. Do not treat a whole-question screenshot or the attached original exam as a figure.
A use with unresolved_reasons must not be selected: native labels/group contents must not be
silently omitted. If a required figure cannot be reconstructed faithfully from the provided
native uses, keep the independent solution report and precise conflicts, return NEEDS_DECISION,
proposal=null and bindings=[]. Do not fall back to a PDF crop. With no source_image blocks,
bindings must be empty. Preserve readable native tables/equations as structured blocks, not
rasterized tables or explanatory prose. Do not strip labels already baked into an original PNG.

For visible printed score use `score={state:PRINTED,points:<observed integer>}`. For no printed
score use `score={state:UNPRINTED,points:null}`. Missing score is not an unsupported Item and is
not a reason for proposal=null. Do not invent a zero-point source or borrow a nearby exam score.
The owner records the separate unprinted state when compiling its legal canonical representation.

Map `title`, every `body[i]`, `interaction`, `solution.explanation`, `score` and the applicable
`solution.correct_choice_ids`/`solution.accepted_answers` to actual result region IDs. Paths must
resolve in the source draft. A source_image's body mapping includes its source_region_id.
The unprinted score observation can cite the target region inspected for the absence of a score.
Stem/body/choices cite TARGET_ITEM only. Solution fields may cite TARGET_ITEM/EDITORIAL_SOLUTION;
score may additionally cite OTHER. No content mapping may cite REFERENCE_ORIGINAL.

## Keep editorial content and independent solving distinct

If an editorial answer is visible, preserve that answer and explanation in `proposal.content`
EVEN IF WRONG, with `solution_origin=EDITORIAL_SOURCE` and an actual editorial answer region.
Do not replace it with your independently derived answer. If no editorial solution is available,
a determined independent candidate can be stored with INDEPENDENT_PROPOSAL_UNVERIFIED. Never
describe such a candidate as a source-confirmed answer.

Always provide the separate required `solution_report`, even when proposal=null. It contains
DETERMINED or UNDETERMINED, independent answer_labels or accepted_answers as applicable, public
explanation, contiguous solution_steps, answer_cross_check and exact editorial_region_ids.
For an undetermined answer use empty answers and NOT_DETERMINED, recording the actual ambiguity.
Do not fabricate a unique answer to satisfy a schema.

Work out the question independently. Public verifiable steps should cover relevant givens,
conditions, values, units, axes and visual labels; applied concept/formula; relations and
calculations; each statement/choice and why alternatives fail; conclusion; and comparison with
the source explanation. Include the important concept-to-assessment connection and reusable
inference in these bounded summaries. These are checkable public explanations, not private
deliberation. Cite actual target/editorial regions, not invented Graph node IDs or unused RAG.

MATCHES_EDITORIAL_SOLUTION requires an actual visible editorial answer comparison. A different
independent answer is DISAGREES plus ANSWER_DISAGREEMENT. If there is no editorial solution use
NO_EDITORIAL_SOLUTION, not a guessed match. Record missing conditions, uncertain transcription,
unit/sign/label mistakes, explanation problems and ambiguities in conflicts, even if the source
can be faithfully reconstructed. Source registration may later preserve those scientific issues;
you must not suppress them, silently correct the original or claim registration/approval yourself.

## Final mechanical checks

1. Return JSON only. Follow the full supplied outer role-result and inner result schema.
2. Preserve outer Job/Workflow/step/Artifact and inner input/source/revision/number identities.
3. Check unique regions, actual physical pages, valid bounds, containment and excluded regions.
4. Resolve every content path; ensure mappings, public steps and conflicts cite only declared IDs
   with permitted roles. All relevant references must have an empty undeclared-ID difference.
5. Preserve exact choice/statement IDs. Each statement has its structured source explanation.
6. Keep source and independent answers separate. Do not report MATCHES when their labels differ.
7. PROPOSED requires a proposal, determined solution and no blocking conflicts. NEEDS_DECISION
   requires an explicit blocking conflict, but a scientific disagreement does not force proposal
   to null. Retain a faithful draft beside the disagreement. Use null only for genuinely
   unreconstructable source content; retain the independent report and precise reason either way.
8. Omit result_sha256 in the model response. The owner validates defaults and stamps its canonical
   hash. Never guess a SHA or change the pinned input hash to make the result validate.
