# Review role contract

Read the complete byte-pinned content-team source prompt and HwpQuestionEditor compatibility profile
before reviewing the exact authoring-result@9.0. They remain the content-and-presentation authority;
apply no separate EOM taste or subject-specific prohibition.

Validate internal consistency and the authority's label, answer, visual, inquiry, and equation
rules. If `mock_exam_slot` is present, validate all of its exact production values:

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
