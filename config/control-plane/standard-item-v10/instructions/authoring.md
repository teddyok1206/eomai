# Authoring role contract

Read the complete content-team source prompt at
`references/guidance/content-team-integrated-science-authoring-v05.md`, followed by the exact editor
compatibility profile at
`references/guidance/content-team-hwp-question-editor-handoff-v1.md`. These byte-pinned files are
the content-and-presentation authority. Do not add a topic, wording, layout, visual-count,
table-count, equation-count, or subject-specific prohibition here.

Return authoring-result@9.0. If the reviewed request carries `mock_exam_slot`, treat its values as
one exact production contract, not preferences that may be substituted:

- Set `metadata.difficulty` from `preferred_difficulty`: `LOW`=`easy`, `MEDIUM`=`medium`,
  `HIGH`=`hard`.
- Make the canonical draft material profile equal both the request's `task_type` and
  `preferred_material_profiles[0]`. Classification is exact: non-null `inquiry` is `INQUIRY`;
  otherwise a DATA labeled block contributes `DATA`, a TABLE visual contributes `TABLE`, and an
  IMAGE visual contributes `IMAGE`; no distinct signal kind is `TEXT`, one distinct signal kind is
  that profile, and multiple distinct signal kinds are `MIXED`. Repeated signals of one kind remain
  that single profile. The later ordered profiles are planning alternatives and do not authorize a
  substitution for this occurrence.
- Set `inquiry` non-null exactly when `inquiry_required` is true and null otherwise.
- Set `draft.score_display` from `points_milli`: 1500=`1.5`, 2000=`2`, 2500=`2.5`, 3000=`3`.
- Preserve the reviewed request's `knowledge_source_mode` exactly in authoring metadata: an
  Evidence-Bundle-backed request is `graph_grounded`; an ungrounded request is
  `general_model_knowledge`.

The executable HWPX equation boundary is exact. Before returning, scan every equation source and
use no backslash command other than `\frac`, `\max`, `\prime`, or `\times`. Where the source guide
generally recommends a Greek-letter LaTeX command, write the required Greek glyph as ordinary
Unicode text outside `$...$` and `$$...$$` instead. If the required meaning cannot be preserved by
ordinary-text Greek plus the supported equation families, fail explicitly before returning; never
substitute an unverified command, plain-text approximation, or guessed HWPX representation.

Satisfy the required material profile using only structures supported by the content authority.
Preserve only the IMAGE slots that exact profile and authority require. Do not put an image prompt,
path, URL, or image bytes in the draft or Markdown. If any exact slot value cannot be satisfied,
fail explicitly instead of substituting another profile, difficulty, inquiry shape, score, or
provenance mode.
