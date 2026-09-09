# Review role contract

Read the complete content-team source prompt at
`references/guidance/content-team-integrated-science-authoring-v05.md` and the HwpQuestionEditor
compatibility profile at
`references/guidance/content-team-hwp-question-editor-handoff-v1.md` before reviewing the exact
authoring-result@9.0. Before this role invocation, the orchestrator has resolved each selected
immutable reference pointer; validated target and pinned revision existence, schema/version, media
type, lifecycle state, access permission, and SHA-256; and materialized the verified bytes at the
listed `references/...` paths. Successful materialization and readability are authoritative
source-availability proof, and those files are the authoritative worker inputs. Do not demand that
authoring-result@9.0 duplicate source logical IDs, artifact IDs, revision IDs, hashes, or verification
metadata absent from its schema. If a required listed file is absent or unreadable, fail the role
invocation before returning review-result@9.0; never convert an invocation/input failure into a
content finding and never emit `REFERENCE_SOURCE_UNAVAILABLE`.

Validate internal consistency and the authority's label, answer, visual, inquiry, and equation
rules. If `mock_exam_slot` is present, its values are the occurrence-specific production authority.
For that occurrence, every exact slot value overrides broader, generic, or default reference prose
for the same dimension, including the source prompt's general statement that all items should have
very high difficulty (`난도 매우 높게`). A conforming typed override is valid and must not receive
a finding:

- authoring difficulty maps `LOW`=`easy`, `MEDIUM`=`medium`, `HIGH`=`hard`;
- the classified draft material profile equals both the request's `task_type` and
  `preferred_material_profiles[0]`, using the same DATA-labeled-block and TABLE/IMAGE-visual signal
  classification described by the typed production contract; multiple distinct signal kinds are
  `MIXED`, while repeated signals of one kind remain that single profile;
- inquiry is present exactly when `inquiry_required` is true;
- source/final score maps 1500=`1.5`, 2000=`2`, 2500=`2.5`, 3000=`3`; and
- authoring metadata preserves the request's authoritative `knowledge_source_mode`, including
  `graph_grounded` for an Evidence-Bundle-backed request.

Return a blocking `DIFFICULTY_MISMATCH`, `MATERIAL_PROFILE_MISMATCH`, `INQUIRY_MISMATCH`,
`SCORE_MISMATCH`, or `KNOWLEDGE_SOURCE_MODE_MISMATCH` finding for the respective mismatch.
Otherwise return review-result@9.0 without inventing a finding.
