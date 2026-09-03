# Content-team HwpQuestionEditor handoff integration V1

## Decision and boundary

EOM integrates the reviewed HwpQuestionEditor handoff as a versioned editorial/rendering profile,
not as a second application runtime. The PySide GUI, direct file dialogs, ambient template lookup,
and direct output-save behavior are excluded. The existing EOM application service remains the use
case owner; an isolated HWPX builder may consume only validated workspace inputs, and only the
orchestrator may commit a validated result to NAS.

The reviewed source is `staging/HwpQuestionEditor_handoff_export.zip`, SHA-256
`dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91`. It contains 606 ZIP
entries and no committed Git history. Its historical test report records 598 passes and one stale
equation-occurrence expectation failure, so the archive is evidence, not executable authority.
The source snapshot does not declare a project license. EOM therefore does not vendor its source
into Git. The immutable user-provided archive is registered as one Catalog Artifact Revision and
only its non-GUI rendering core is materialized and executed inside the fixed, networkless
`eom-hwpx-content-team@.service` sandbox. The desktop application, ambient filesystem lookup, and
save dialogs remain excluded.

## Content authority and system authority

The byte-preserved content-team prompt is authoritative for item content and presentation. The
reviewed HwpQuestionEditor behavior is the executable compatibility contract for that presentation.
EOM does not add topic, wording, calculation, score, visual-count, table-count, equation-count, or
review-taste rules. Examples inside the prompt/archive remain examples; they never become defaults,
enums, constants, or implicit recovery values.

EOM remains authoritative for security, provenance, typed identities, schema validation, worker
isolation, workflow state, transactions, and storage. These system rules may reject malformed or
untrusted bytes, but they do not rewrite an otherwise valid content-team item.

## Canonical source and revision model

Canonical item identity remains:

```text
Item logical ID -> immutable Item revision -> typed content/component pointers
                -> immutable artifact revisions -> SHA-256 content hashes
```

`AssessmentItemContentV2` is the canonical semantic value. Its deterministic content-team Markdown
is a second member of the same hash-keyed Catalog artifact, with its own member hash. The prompt
source, handoff archive, renderer profile, automation template, each prototype, input JSON/Markdown,
and output HWPX remain separate immutable identities. No renderer may resolve an implicit latest
template or prototype.

## Required pointers and resolution

A production renderer profile must pin the handoff archive Artifact and Artifact Revision, archive
hash, member path, member media type, and member hash for every required binary. Before use, the
adapter checks existence, safe relative member name, regular-file status, size limit, media type,
archive path uniqueness, immutable revision state, and SHA-256. It rejects a dangling pointer,
stale revision, duplicate/case-colliding member, hash mismatch, encrypted member, symlink, nested
runtime archive, active HWPX content, or external relationship.

The required prototype set is:

| Purpose | Member SHA-256 |
|---|---|
| automation template | `22ded5c8de95a8c9659544749fd21a109f40a1c7b5963e123887c0d9ca51a687` |
| equation prototypes | `2a493d5e90f1d80cb28805f2f9fecf9c18853cbc0521d7acc7a64cc249c1c45a` |
| image/table visual slots | `65674a863762e29230bab2010b6a38e52a1f44d50cb6b0509c1205ce44c4c593` |
| two-table visual slots | `3d5f54f3915d071d978f05037dffc03cec7385a87cb5a16fa460414f43cbbb13` |
| 자료/조건 labeled block | `cf517788ed36fe388e2580a1455dc5e343fcb68aeca5e007194180aafbf91e76` |
| 2-column table | `d29e2891481554869540dfd3c62f5217cd589b3bb3197f89b3126ced9f8332eb` |
| 3-column table | `9812ab156524e34f51d10123a0a8bb7991947cba95e960da1a03b5fdb5d5d3b9` |
| long-equation 3-column table | `5521c89d0772e59a963994db09c946e6407ca2664c51de7e738033645e192335` |
| 4-column table | `dae3a87c48c36bc3fdaf4efd3e746f7a9d00f70217876a700e320cafc110e9d9` |
| inquiry/experiment box | `b11841cbc812f6d0179d8ce59fb2d0d4c60706445b12e03726d5819e35f70d6f` |

Binary members are registered in NAS with an immutable manifest; they are not copied into Git.
The two top-level Korean template names have non-portable ZIP filename metadata and decode as
mojibake in standards-compliant readers. Registration therefore resolves those members by the
reviewed content hash, records the original raw archive-member evidence, and assigns a canonical
ASCII storage name. A decoded display name is never used as identity.

## Access patterns and data structures

Dominant operations are keyed lookup by section/statement/prototype identity, ordered iteration of
document blocks, membership checks for exact labels, and append-only build history. Parsers use
maps for section lookup, sets for uniqueness, and tuples/frozen models for ordered output. Template
members use a keyed manifest rather than repeated directory scans. Parsing and validation are
O(source bytes + cells + equation occurrences), with O(parsed item size) memory. Bounds are safety
limits copied from the program contract (1 MiB Markdown, up to two general visual items, five table
columns, 100 rows per table, and 128 equation occurrences), not requirements that content fill each
slot.

## Editorial grammar retained from the program

- one UTF-8 Markdown item, with no heading, bold, rule, quote, code fence, HTML, URL, file path, or
  Markdown image;
- ordered ①–⑤ choices and one exact answer line; a combination item retains ordered ㄱ/ㄴ/ㄷ
  statements such as `정답 : ③ (ㄱ, ㄷ)`, while another choice form has no forced statement block
  and retains the selected choice's core answer content in the parentheses;
- exact `[출제의도]`, `[개념출처]`, `[풀이 및 정답 해설]`, `[오답 해설]` sections, with correct
  and incorrect statement explanations partitioned exactly once;
- the six layouts `IMAGE_ONLY`, `TABLE_ONLY`, `IMAGE_TABLE`, `TABLE_IMAGE`, `IMAGE_IMAGE`, and
  `TABLE_TABLE`; only two-image/two-table layouts use `(가)/(나)` labels;
- unique `<자료>`/`<조건>` blocks in 자료-before-조건 order, cloned from the labeled-block
  prototype without subject-specific default content;
- inquiry/experiment goal (optional), procedure, and result in one outer 1x1 prototype box, with at
  least three ordered procedure steps and nested tables retaining table style;
- prototype cloning for equations and tables, unique object IDs/z-order, invalidated `lineSegArray`,
  preserved styles `표내용-신명중명조`, `외부 박스 위치`, and `실험(가)(나)(다)`, and rejection of
  unsupported equation grammar rather than guessed XML.

The current handoff image marker creates an empty slot and does not embed `hp:pic`/BinData. EOM keeps
its stronger image Artifact pointer and validated PNG materialization boundary when actual image
bytes are required.

## Transplantation matrix

| Handoff capability | EOM owner | Integrated behavior |
|---|---|---|
| `MarkdownInput` and `QuestionParser` | `eom_hwpx_contracts.content_team_markdown` | Pure strict UTF-8 parse plus deterministic lossless serialization |
| `QuestionData` | `ContentTeamEditorialDraft` / `AssessmentItemContentV2` | Frozen typed value, JSON Schema 2020-12, no subject defaults |
| six general visual routes, no visual, inquiry box | `visual_layout` + ordered `visuals` + `inquiry` | Exact route/layout consistency; zero, one, or two program visual entries |
| Markdown tables | `ContentTeamTable` | Ordered 2–5-column rectangular cells and alignments |
| empty image markers | `ContentTeamImageSlot` | Slot semantics retained without inventing image bytes or a mandatory image worker |
| 자료/조건 | `ContentTeamLabeledBlock` | Unique ordered typed blocks with arbitrary request content |
| 탐구/실험 box | `ContentTeamInquiry` | Optional goal, ordered procedure/result, nested table text retained |
| equation detection/preflight | `content_team_equations` | Every occurrence retained in order; supported handoff families accepted, unknown grammar fails explicitly |
| answer and explanation semantics | typed statements/choices/answer/explanations | Exact choice/statement mapping and required content-team section partition |
| mixed renderer/prototype cloning | fixed isolated HWPX builder adapter | Archive-hash-bound program core clones reviewed prototypes with its native ID, z-order, style, table-width, and line-segment behavior |
| sample cleanup and HWPX validation | fixed isolated HWPX builder adapter | Program validator plus EOM package analyzer reject active content/external links before orchestrator commit |
| desktop GUI/file dialogs | none | Deliberately excluded; application service owns the use case |

The immutable authoring path is Standard Item V6 + Content Pack 1.12.0 + workflow 1.7.0 +
workflow-role/1.15.0. The authoring worker must read the complete source prompt and handoff profile;
the pack prompt does not summarize or override their content rules. Authoring emits
authoring-result@7.0, Catalog stores V2 JSON plus deterministic Markdown under `catalog/1.2`, review
uses review-result@7.0, and item management uses registration-result@7.0. There is no mandatory image
step.

## Transaction, concurrency, failure, and retry

Parsing is pure. A build claims one idempotency key, snapshots all immutable pointers, renders in a
fresh private workspace, validates the complete package, stages one file-set artifact, and commits
metadata and the NAS manifest in the existing application transaction boundary. A failed parse,
prototype resolution, equation preflight, render, structural check, semantic check, or NAS commit
does not advance the Item revision or publish an HWPX artifact. Retry reuses the exact pinned input
revisions and idempotency key; it never rewrites a released template/prototype revision.

## Dependency direction and ownership

The editorial JSON Schema, frozen Pydantic values, equation grammar, and deterministic Markdown
parser/serializer live in the pure `eom_hwpx_contracts` package; `eom_catalog_contracts` depends on
that value contract, never on a renderer or infrastructure package. ZIP/HWPX/prototype resolution
and XML surgery belong to the isolated `eom_hwpx_builder` infrastructure adapter.
Catalog application services own JSON/Markdown materialization and artifact commit. Neither
contracts nor domain models import lxml, SQLAlchemy, filesystem, subprocess, GUI, or NAS code.

## Simpler alternative rejected

Running the ZIP's GUI/core directly would preserve incidental behavior but bypass EOM's provenance,
isolation, idempotency, artifact, and NAS boundaries. Merely summarizing the program in a prompt
would lose executable grammar and layout validation. The selected profile preserves the program's
detailed editorial and forensic rules while keeping EOM's stronger system boundary.

## Frozen evidence and verification

The pre-injection implementation pins and verifies these identities:

| Evidence | SHA-256 |
|---|---|
| byte-preserved content-team authoring prompt | `62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435` |
| reviewed HwpQuestionEditor handoff ZIP | `dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91` |
| reviewed EOM handoff compatibility profile | `6fdfd8f9dbc67abfcac9ef2761059bbe841a8b994640925fef30388d95a00ee5` |
| Assessment Item Content V2 JSON Schema | `2136413f5059905be0c066c8fd657cbfc5238ba47e36ac3502be669ae130b9a8` |
| authoring-result V7 JSON Schema | `292d56d88888640f4ad1b41a638bca381e6b65937a6b53638b4a40aa17e74b45` |
| workflow-role/1.15.0 schema bundle | `bbdc8f4d62bbd5fbe576a55ee418b6477c8a6e5b03c10a0d517aa35b11f79144` |
| Content Pack 1.12.0 source tree | `f75b0416e117e8c5b768c326ef438f3400446c0cb1488637c4a6361e7177b975` |

The archive attestor reads the real supplied ZIP through one no-follow descriptor, checks 606
entries and 49,280,719 uncompressed bytes, and uniquely resolves all ten required prototype hashes
without extraction or execution. Tests cover all six general visual layouts plus no visual,
2–5-column tables, inquiry/experiment structure, zero or multiple equations, combination and direct
choice forms, all-correct explanation handling, deterministic Markdown round trips, malformed
layout/answer/explanation rejection, archive traversal/collision/compression rejection, Catalog
JSON+Markdown materialization, V10 API transport, source/package schema equality, installed-wheel
resources, workflow compilation, and deployment runtime allowlists.

Verification uses the explicit `eom-api` and `eom-hwpx` Conda environments. Besides the pure
contract/parser matrix, an opt-in-local fixture runs the supplied parser, equation preflight,
template engine, and validator from the exact archive against a V2 item and then applies EOM's
package safety analyzer. Unit tests cover the fixed-unit command, polkit boundary, API profile, job
idempotency, pointer resolution, and terminal artifact receipt.

## Deployment state

The source archive is registered as immutable Catalog Artifact
`artifact_73e80b48f1054d8f8bb733dc1d13ae6f`, revision
`rev_2801db879a4c4aaaa589f0cf2991b8c3`, with archive SHA-256
`dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91` and manifest SHA-256
`dd87d206b06d2508891b591df99f2b2146b39ff9ad8f61c17db446c063729169`. The application build
service snapshots that exact revision together with each input Item/Artifact revision, submits one
`hwpx-content-team-build` job, stages only validated workspace copies, starts the fixed renderer
unit, validates its typed result, and commits the HWPX/report/request/result file set to NAS. The
Application API exposes this closed pair as renderer `content-team`, document profile
`content-team-hwp-question-editor-v1`, and source schema `eom.assessment.item-content/2.0`.
