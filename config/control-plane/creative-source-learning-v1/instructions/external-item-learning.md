# Source-faithful archive extraction with independent public solution

Return the supplied `external-item-learning-result@2.0` role-result schema. Read the exact
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

For each diagram use a `source_image` block: block_id, purpose, source_region_id,
target_region_id and alt_text. source_region_id identifies the tight diagram region and
target_region_id its containing TARGET_ITEM region on the same delivered page. Both regions must
be declared TARGET_ITEM, the crop must be contained in the parent, and neither may borrow pixels
from the attached original or editorial solution. The owner renders and commits the crop later.
Never emit or guess an image Artifact ID, path, hash, PNG bytes or a direct full-page image pointer.

Where a source table contains drawings, keep readable tabular data native when separable and
declare tight source-image regions for its drawings. If the visual/table is inseparable, the
combined target-only visual can be one source_image with all visible information faithfully
described. A lack of pre-existing cropped PNG pointers is NOT UNRESOLVED_IMAGE: this contract
deliberately asks for source regions. Use UNRESOLVED_IMAGE only if the actual visual is unreadable
or cannot be safely separated from unrelated content.

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
