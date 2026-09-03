# Integrated Science item authoring v2

Reviewed derivative of `staging/문항_생성_가이드_v05.md`, SHA-256
`sha256:62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435`. Reference only;
runtime authority remains the pinned instruction bundle.

The authoring result must project to one UTF-8 HwpQuestionEditor Markdown file containing one
item. The file contains no headings, bold, horizontal rules, block quotes, fenced code, HTML,
image syntax, image paths, URLs, or prompt text. Item number and score are plain text. The answer
is one line exactly like `정답 : ③ (ㄱ, ㄷ)` and includes answer content, not only a number.

Use exactly `[출제의도]`, `[개념출처]`, `[풀이 및 정답 해설]`, and `[오답 해설]`. Correct
statements belong only in the answer explanation and incorrect statements only in the wrong-answer
explanation; explain each ㄱ/ㄴ/ㄷ once, using `[풀이] 참조` for shared reasoning.

Use only standalone `그림`, `그림 (가)`, `그림 (나)` markers. Tables are Markdown tables directly;
use `표 (가)`/`표 (나)` only for two tables, never a standalone `표` for one. Inquiry/experiment
items use the exact 탐구/실험 목표·과정·결과 labels, at least three ordered procedures, and keep
results out of procedure steps. These review notes and image prompts stay outside item Markdown.

This profile emits exactly five choices and preserves ordered ㄱ/ㄴ/ㄷ statements. The source
prompt's `[2.5점]` display must not be silently coerced into the canonical integer score; reject it
at the typed boundary until an approved decimal-score schema exists. Visual/equation blocks resolve
through immutable artifact pointers.
