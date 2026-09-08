# Authoring role contract

Read the complete content-team source prompt at
`references/guidance/content-team-integrated-science-authoring-v05.md`, followed by the exact editor
compatibility profile at
`references/guidance/content-team-hwp-question-editor-handoff-v1.md`. These byte-pinned files are
the content-and-presentation authority. Do not add a topic, wording, layout, visual-count,
table-count, equation-count, or subject-specific prohibition here.

Return authoring-result@9.0. If the reviewed request carries `mock_exam_slot`, set
`draft.score_display` from its exact `points_milli` mapping: 1500=`1.5`, 2000=`2`, 2500=`2.5`,
3000=`3`. Preserve the request's `knowledge_source_mode` exactly in authoring metadata: an
Evidence-Bundle-backed request is `graph_grounded`; an ungrounded request is
`general_model_knowledge`. Preserve only the IMAGE slots the authority requires. Do not put an
image prompt, path, URL, or image bytes in the draft or Markdown.
