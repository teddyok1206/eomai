# EOM question template V1 content shape

## Why table, image, and equation are always present

The repeated `table -> image -> equation` section is intentional in
`eom-question-template-v1`; it is not an accidental renderer default.

The first production-shaped HWPX profile was deliberately bounded to one structure that could be
validated end to end against a fixed Hancom-authored template. The profile requires exactly six
ordered semantic blocks:

1. stem paragraph;
2. one three-column, one-row data table;
3. one pinned 800×500 PNG stimulus;
4. one bounded Hancom equation stimulus;
5. prompt paragraph;
6. one ordered `ㄱ/ㄴ/ㄷ` statement set.

It also requires five single-choice options and a two- or three-point score. The same invariant is
enforced at three distinct boundaries for different reasons:

- `validate_eom_question_template_content()` rejects content that cannot fit the delivery profile;
- `project_question_template()` maps the six typed blocks to fixed HWPX template bindings;
- `QuestionTemplateBuildService` verifies the native equation and table counts in the generated
  package before Artifact registration.

Catalog currently constructs generated `ITEM_CONTENT` from the authoring result in exactly this
order. Consequently, workers are also prompted and schema-constrained to produce all three stimulus
forms even when a particular science question would naturally need only one of them.

## Architectural interpretation

The canonical `AssessmentItemContent` model is broader than this delivery profile. The restriction
belongs to `eom-question-template-v1`, not to Item identity, Artifact storage, workflow orchestration,
or HWPX in general. Other textbook, mock-exam, and question styles can reference the same approved
Item Revision through a different delivery profile.

Do not loosen V1 in place. Existing Items, builds, validation receipts, and fixed-template counts
depend on its immutable meaning. A flexible successor should be additive, for example:

- `eom-question-template-v2` with a typed discriminated layout variant;
- a new authoring-result/schema family whose block requirements match that profile;
- a new Content Pack release and HWPX projection/binding manifest;
- explicit native-object expectations per variant, with no implicit filler table/image/equation;
- compatibility tests proving V1 history remains readable and V2 rejects unsupported combinations
  before build submission.

Until that successor is reviewed, the fixed trio remains a deliberate acceptance and template
compatibility constraint.
