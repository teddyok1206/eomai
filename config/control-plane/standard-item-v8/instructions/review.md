# Review role contract

Read the complete byte-pinned content-team source prompt and HwpQuestionEditor compatibility profile
before reviewing the exact authoring-result@9.0. They remain the content-and-presentation authority;
apply no separate EOM taste or subject-specific prohibition.

Validate internal consistency and the authority's label, answer, visual, inquiry, and equation
rules. If `mock_exam_slot` is present, validate the exact source/final score mapping
1500=`1.5`, 2000=`2`, 2500=`2.5`, 3000=`3`. Validate that authoring metadata preserves the request's
authoritative `knowledge_source_mode`, including `graph_grounded` for an Evidence-Bundle-backed
request. Return a blocking `SCORE_MISMATCH` or `KNOWLEDGE_SOURCE_MODE_MISMATCH` finding for those
respective mismatches. Otherwise return review-result@9.0 without inventing a finding.
