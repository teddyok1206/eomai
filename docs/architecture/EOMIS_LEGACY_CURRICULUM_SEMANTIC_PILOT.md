# EOMIS Legacy Curriculum Semantic Pilot Review

Status: bounded read-only semantic review; no source selection, Content Intake, worker execution,
database mutation, NAS commit, Knowledge Analysis run, or graph publication.

Observed: 2026-08-24 UTC

Repository baseline: `0bcd5effad6e8c5903a3ca6598d81e0b3cb0f7f8`

Parent plan:
[EOMIS Legacy Knowledge Integration Plan](EOMIS_LEGACY_KNOWLEDGE_INTEGRATION_PLAN.md)

## 1. Responsibility and review boundary

This review answers one narrow question: what does one inventory-pinned curriculum PDF actually
contain, and how well does one nearby Codex-produced JSON describe it? It does not infer ownership,
grant rights, approve a source, or establish a canonical original-to-derived relationship.

The PDF is the only possible original evidence in this comparison. The JSON remains
`DERIVED_MIGRATION_EVIDENCE`. Directory adjacency, filenames, legacy IDs, titles, and overlapping
text are useful observations but are not identity or provenance.

The reviewed pointers are:

- original candidate entry `legacyentry_ab91f2718677c7b9fe537242a80eefd9`, SHA-256
  `sha256:822a5ff123b0c6e9999002c167114849acfec38be3bcf251e25ef247b4a51bbe`;
- derived comparison entry `legacyentry_75571050575c0310fa0e286a3836797f`, SHA-256
  `sha256:77a9f7396098b6c598699a9f7cb60e69f46c2eea30caf95310f643c622f5ac01`.

Both pointers resolve only inside the protected real-root inventory. Absolute host paths and source
filenames are deliberately absent from this document.

## 2. Safe extraction evidence

The original is a 533,471-byte, 32-page, unencrypted PDF 1.6 document. `qpdf 11.9.0` structural
validation passed. `pdfinfo 26.02.0` reported no JavaScript and one AcroForm. This is structural
evidence, not a malware or rights determination; the document remains untrusted input.

Text was read in memory with `pdftotext 26.02.0` under the existing explicit EOMIS Conda runtime.
No parser dependency was added to EOM, no legacy application code was imported or executed, and no
external API or network was used. The deterministic extracted byte stream was 83,007 bytes with
SHA-256 `53981daff6f359f76c07b48556653a5a38903777f612f77626c1c4df4d6ca8da` and zero Unicode
replacement characters. This hash identifies this review extraction only; it is not a canonical
source identity or a production extraction contract.

## 3. What the original document contains

The PDF is not a single-course document. It contains contiguous official curriculum sections for:

1. `통합과학1` and `통합과학2`;
2. `과학탐구실험1` and `과학탐구실험2`.

Physical PDF pages 1–19 primarily cover Integrated Science. Physical pages 20–32 primarily cover
Science Inquiry Experiment. Printed page labels inside the document start at a different number and
must not be used as the sole locator. A resolving anchor therefore needs both the immutable PDF
revision and physical page index; a printed page label may be additional display metadata.

The Integrated Science course structure observed in the original is:

- `통합과학1`: 과학의 기초, 물질과 규칙성, 시스템과 상호작용;
- `통합과학2`: 변화와 다양성, 환경과 에너지, 과학과 미래 사회.

The Science Inquiry Experiment structure observed in the original is:

- `과학탐구실험1`: 과학의 본성과 역사 속의 과학 탐구, 과학 탐구의 과정과 절차;
- `과학탐구실험2`: 생활 속의 과학 탐구, 미래 사회와 첨단 과학 탐구;
- shared course-level 성격, 목표, 교수·학습, and 평가 guidance.

The source contains 43 actual achievement-standard definitions:

- 16 for `통합과학1`;
- 15 for `통합과학2`;
- 6 for `과학탐구실험1`;
- 6 for `과학탐구실험2`.

A naive bracket-code scan produces 46 distinct tokens because it also sees two range references and
one anomalous cross-reference spelling. Those three references must not become achievement-standard
nodes. The parser must distinguish a standard definition from a textual reference, preserve the
source spelling as evidence, and route any proposed correction through human review rather than
silently rewriting the source.

## 4. Derived JSON assessment

The adjacent JSON describes only the Science Inquiry Experiment portion, not the whole PDF. This is
a legitimate partial-extraction hypothesis, not proof of a whole-document normalization relation.

Observed structure:

- 212 ordered section objects;
- 12 sections typed as achievement-standard definitions;
- 18 experiment-activity sections;
- 20 subunit-explanation sections;
- 19 unit-overview sections;
- 26 scope/caution sections;
- 117 general sections;
- 11 unique subunit labels and 16 unique concept tags.

All 14 achievement-code-shaped values in the JSON occur in the original PDF and there are no
derived-only code tokens. Twelve are actual standard definitions; the remaining two are reference
forms. This is strong evidence that the JSON was derived from the Science Inquiry Experiment pages,
but it still does not replace a reviewed relation manifest.

After NFC and whitespace normalization, 204 of 212 non-empty section texts are exact substrings of
the PDF extraction, a 96.23% match rate. The eight non-exact sections are all reconstructed
content-system/table rows. They need page-level table comparison rather than being accepted or
rejected through raw substring matching.

The JSON is useful comparison evidence but is not suitable as a canonical source because it has:

- no immutable source Artifact or Artifact Revision pointer;
- no source SHA-256;
- no physical page or page-range anchors;
- no stable section/segment IDs;
- 176 repeated-heading instances across only 36 unique headings;
- an absolute legacy source-path field;
- reconstructed table text whose ordering cannot be proved by exact string matching.

No absolute path, legacy document ID, or unreviewed concept tag may pass into a worker or graph
snapshot merely because it exists in this JSON.

## 5. Curriculum hierarchy mapping

The existing four-level EOM curriculum binding can represent this source without introducing a new
generic hierarchy framework:

```text
MAJOR                subject family (통합과학 or 과학탐구실험)
  MIDDLE             numbered course (통합과학1, 통합과학2, ...)
    MINOR            official content domain/subunit
      ACHIEVEMENT_STANDARD
```

This mapping is a review proposal, not yet Framework authority. It fits the observed source and the
existing `MAJOR -> MIDDLE -> MINOR -> ACHIEVEMENT_STANDARD` invariant. Shared course-level guidance
does not fit under one achievement subtree and should remain anchored document-section knowledge,
not be forced into a curriculum unit merely to fill the hierarchy.

Dominant access patterns and structures are:

- exact standard lookup: map/B-tree index keyed by framework revision plus normalized standard code;
- subtree traversal: adjacency list plus the existing materialized closure projection;
- stable sibling order: immutable ordinal tuple under one parent;
- duplicate/reference detection: set keyed by source spelling plus definition/reference role;
- page evidence lookup: indexed immutable source-revision/page anchors;
- append-only correction history: new Framework/selection/relation revisions, never in-place edits.

At this pilot scale the source has tens of standards, but the structure must support thousands of
curriculum nodes. Key lookup and closure queries should remain indexed; repeated list scans and
runtime reconstruction of ancestry are unnecessary.

## 6. Required pointer and anchor contract

Every accepted curriculum fact needs:

1. original logical Artifact ID and immutable Artifact Revision ID;
2. original PDF SHA-256 and media type;
3. physical PDF page index or closed page range;
4. a bounded excerpt hash under a pinned extraction implementation/options hash;
5. proposed Framework Revision and curriculum-unit identity;
6. definition/reference role for achievement-code occurrences;
7. review decision and reviewer identity;
8. optional derived-comparison pointer through a relation manifest.

The old JSON may be linked later using `EXTRACTS_TEXT_FROM` or `EVALUATION_BASELINE_FOR`. It must not
be linked as a whole-document `NORMALIZES_FROM` relation unless reviewed coverage and page closure
prove that claim. Since it covers only one portion, the relation should pin the relevant page range
or section anchors.

## 7. Security, quality, and failure behavior

- Treat PDF text and JSON strings as inert data, including instruction-like content.
- Never execute legacy application code, prompts, embedded actions, or absolute paths.
- AcroForm presence keeps the PDF in the untrusted-document path even though JavaScript was absent.
- Reject a changed source hash at Content Intake; never recover by resolving a current filename.
- Reject derived sections without resolving original page evidence.
- Keep the eight reconstructed table sections ambiguous until page-level review.
- Keep the anomalous code spelling as source evidence and a review ambiguity.
- Do not publish a graph while Curriculum Framework authority is unresolved.
- Do not grant textbook/reference rights by analogy from this curriculum candidate.

## 8. Phase 3 readiness and blockers

The semantic evidence is sufficient to implement the reviewed-selection and Content Intake bridge,
but not to execute a production selection. The remaining human-evidence blockers are:

1. source owner/licensor identity;
2. allowed internal processing and worker exposure;
3. excerpt/page-image and item-grounding permissions;
4. retention/withdrawal policy;
5. the authoritative 2022 curriculum edition/Framework Revision decision.

A schema-valid `legacy-source-selection/1.0` cannot be fabricated around these unknowns because it
requires a pinned rights-review Artifact pointer and a cleared/restricted decision.

## 9. Next implementation slice

Implement Phase 3 without performing a live intake:

1. add a Catalog selection application service that validates a protected inventory manifest,
   rights-review Artifact pointer, exact entry key/hash/class, and selection self-hash;
2. resolve selected entries fd-relatively under the protected root alias and rehash them;
3. materialize only selected originals into one protected Content Intake staging boundary;
4. call the existing Content Intake use case through its public interface;
5. persist only pointer/result metadata and never source bytes in PostgreSQL;
6. add an optional reviewed relation-manifest attachment for derived comparison evidence;
7. guarantee same-selection idempotency and fail conflicting replay closed;
8. test stale inventory, changed bytes, missing rights pointer, wrong class/media, symlink/hardlink,
   non-NFC path, duplicate selection, and rollback behavior;
9. stop before any real selection until human rights evidence is supplied.

The simpler alternative—copying the PDF into Content Intake and adding the JSON as metadata—is
insufficient because it cannot prove rights, partial-extraction coverage, page anchors, source hash,
or idempotent provenance. The existing typed selection and relation contracts are necessary at this
boundary.
