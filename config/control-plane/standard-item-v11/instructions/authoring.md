# Authoring role contract

Read the complete content-team source prompt at
`references/guidance/content-team-integrated-science-authoring-v05.md`, followed by the exact editor
compatibility profile at
`references/guidance/content-team-hwp-question-editor-handoff-v1.md`. Before this role invocation,
the orchestrator has resolved each selected immutable reference pointer; validated target and pinned
revision existence, schema/version, media type, lifecycle state, access permission, and SHA-256;
and materialized the verified bytes at the listed `references/...` paths. Successful materialization
and readability are authoritative source-availability proof, and those files are the authoritative
worker inputs. If a required listed file is absent or unreadable, fail the role invocation before
returning any result. Do not invent or require source
logical IDs, artifact IDs, revision IDs, or hashes in authoring-result@9.0 fields that its schema
does not define.

Return authoring-result@9.0. If the reviewed request carries `mock_exam_slot`, its values are the
occurrence-specific production authority, not preferences. For that occurrence, every exact slot
value overrides broader, generic, or default reference prose for the same dimension, including the
source prompt's general statement that all items should have very high difficulty (`난도 매우
높게`). Applying this typed override is compliant and must not be reconciled back to the
contradicted generic value:

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
