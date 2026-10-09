# Item Preview math presentation

The browser owns this presentation-only boundary. Canonical Item JSON, revisions,
hashes, API/Preview schemas, approval and HWPX rendering are not rewritten.

`renderPreviewText` handles paired `$…$`, `$$…$$`, `\(…\)` and `\[…\]` in authored
paragraphs, materials, inquiry, table cells, choices, claims and solution text.
Existing Hancom-script equation blocks retain their separate formatter; explicitly
math-delimited equation text uses the same renderer. Bare Hancom notation is not
reinterpreted as LaTeX. Unmatched/escaped delimiters, currency text,
unsupported syntax and oversized formulas preserve their original text.

KaTeX **0.19.0**, MIT, is a new pinned browser-only dependency. A correct parser
is needed for nested fractions, roots, exponents, indices and science notation;
expanding the existing Unicode replacement regex would silently misrepresent
mathematics. The unmodified ESM build and license are vendored in the Web wheel,
with exact hashes enforced by tests and installed RECORD inventory. The maintainer
import script validates the pinned npm tarball SHA-512 and streams only two exact
members through `apply_patch`; it never extracts arbitrary paths.

Runtime has no CDN, npm, remote font, external API or dynamic dependency lookup.
MathML-only output uses the browser's native math layout and system math fonts.
Untrusted formulas use `trust=false`, 100 macro expansions, maximum size 10em,
4000 characters per formula and a fresh macro scope per expression. Each text
field allows at most 128 rendered formulas and 48000 characters; larger fields
remain readable plain text. Parse errors are never HTML-injected or shown as
tracebacks. Rendering failures affect only the offending expression.

Access is ordered forward scanning, O(text length) plus bounded parser work,
with no persistent/cache state or transaction. DOM output is temporary materialization.
Source text remains untrusted, inserted via text nodes; KaTeX produces MathML via
its DOM API. It receives no navigation, filesystem, model, or service authority.
No DB schema, migration, worker protocol, registry or queue is involved.

Verification covers the actual Chromium controller and styles, all authored text
surfaces, normal/escaped/unmatched dollars, inline/display math, nested notation,
unsafe URL/HTML commands, macro isolation/recursion, budgets, and unchanged input.
The release inventory must include renderer, library and license, and an actual
authenticated installed Preview check is separate from source fixture success.

Reference: [KaTeX options](https://katex.org/docs/options) and
[security](https://katex.org/docs/security).
