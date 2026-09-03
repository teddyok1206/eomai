# Content-team HwpQuestionEditor handoff profile V1

This reference is a reviewed, typed adaptation of the content-team handoff archive with SHA-256
`dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91`. It must be read together
with the complete, byte-preserved authoring prompt. The prompt remains the editorial source; this
reference specifies the actual program grammar and layout behavior that its Markdown must satisfy.

Produce exactly one UTF-8 Markdown item. Do not emit headings, Markdown emphasis, horizontal rules,
block quotes, code fences, HTML, Markdown links/images, URLs, image paths, image prompts, or
validation commentary.
Preserve ①–⑤ choices and one exact answer line. A ㄱ/ㄴ/ㄷ combination item preserves the ordered
statements and an answer such as `정답 : ③ (ㄱ, ㄷ)`; another choice form omits the statement block
and records the selected choice's core answer content in the parentheses, as required by the source
prompt. Use exactly `[출제의도]`, `[개념출처]`, `[풀이 및 정답 해설]`, and `[오답 해설]` in
that order. For a combination item, explain each correct statement only in the correct-answer
section and each incorrect statement only in the wrong-answer section; each appears once, with
`[풀이] 참조` when the shared explanation already establishes it.

For a general item, use no visual marker when none is needed, or use one of these ordered visual
structures:

1. `그림`
2. one Markdown table, with no standalone `표`
3. `그림` followed by one Markdown table
4. one Markdown table followed by `그림`
5. `그림 (가)` followed by `그림 (나)`
6. `표 (가)` + table followed by `표 (나)` + table

Do not create more than two independent visual items. A standalone image marker is an empty layout
slot, not a path or embedded image. EOM resolves actual image bytes through a separate immutable
Artifact Revision. Tables must be rectangular, use 2–5 columns, and retain the Markdown row order.

When a boxed source or condition is needed, use one explicit `<자료>` or `[자료]` block and/or one
explicit `<조건>` or `[조건]` block. If both exist, 자료 precedes 조건. Their content is
subject-neutral input, not a sample-derived default, and is rendered from the pinned labeled-block
prototype rather than hand-built XML.

Inquiry/experiment items use matching 탐구 or 실험 labels. Goal is optional; procedure and result
are required. Procedure contains at least `(가)`, `(나)`, `(다)` in chronological order and does not
mix results into the steps. A result table is placed directly inside the result section without a
standalone `표`. Do not mix the inquiry box with the general visual-slot cases.

Keep `$...$` and `$$...$$` equation sources intact. Use only the supported program families:
number, variable, fraction, subscript, superscript, chemistry/ion notation, prime, ratio,
comparison, implicit coefficient-variable, signed scalar, and simple addition/subtraction. An
unsupported expression must fail preflight; never approximate it with plain text or guessed HWPX
XML. Do not introduce sample-derived spelling, subject matter, or review criteria as runtime
defaults. The byte-preserved source prompt remains evidence, while typed platform contracts remain
the executable authority.

The canonical EOM item is `AssessmentItemContentV2`, which retains the complete editorial structure
and decimal score exactly. The Markdown is a deterministic second member of the same Catalog
artifact, not a competing source of truth. Historical V1 items remain readable but are never used to
coerce or truncate a V2 item. Never invent a newer template, prototype, artifact, or revision when a
pinned one is unavailable.
