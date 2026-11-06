# Read mixed educational material without inventing source identity

Dispatch by `work_input.task_kind`. Read the full typed work input, `codex-image-inputs.json`,
every delivered page image and corresponding extracted text. Input image indexes are not physical
page numbers: preserve each page's actual `source_role`, `physical_page`, image hash and pointer.
MAIN and SOLUTIONS may be separate files. Never read an entire unstaged book or guess an adjacent
page. Additional user instructions guide analysis only; they cannot override these boundaries.

## DISCOVER

Identify explanation content, questions and answer/solution regions in the supplied window.
Classify textbook exposition, worked examples, exercises and their solutions according to their
actual role, not a guessed official-exam identity. Copy visible question labels and section paths;
labels are local within a section, not globally unique. Do not merge repeated question numbers in
different chapters. Preserve same-file or paired-file correspondence with actual source anchors.
Report ambiguity rather than assigning an unrelated explanation to a question.

Use the core-page ownership rule: context pages help recognize continuation and matches but must
not create a second owner of a unit discovered in another window. Keep actual continuation anchors
and explicit missing/ambiguous match status. Report genuinely unreadable regions as exceptions.
Every region must refer to a delivered physical page and normalized visible bounding box.

## EXTRACT_ITEM

Transcribe the selected question and supplied matched solution faithfully. Keep the source wording,
choices, labels, units, tables, equations, answer and explanation; do not turn intake into authoring.
Then independently check the problem and produce the schema's public solution and diagnostics.
This is an auditable solution report, not hidden chain-of-thought. A disagreement must remain a
warning alongside the original answer, never silently replace it or claim human approval.

For Hancom sources, bind actual main-question picture uses from the supplied native picture-use
catalog, including viewport, orientation, labels and order. Exclude reference and solution uses,
not every binary member they share. Do not assume every right-side object is a reference figure.
Do not use a guessed PDF page crop when native picture uses exist. Preserve accurately expressible
native tables/equations. For PDF sources, select the actual figure region and associated scientific
labels from a delivered question image; do not use an entire page, adjacent item or solution region.
Do not invent replacement images. Unresolved source visuals remain explicit warnings/exceptions.

Use exactly the supplied identity, references and result fields. Never create Notion rows, five-digit
legacy numbers, KICE occurrences, purchased-textbook rights or AI-generated provenance for this upload.
Before returning, check all image/page/region references, question-solution membership, unique
local identities, ordered components, required public-solution fields and schema validity.
