# Current System Status

Latest recorded update: 2026-10-09 (UTC). Older sections retain their observation dates.

## Bounded review-result correction — source candidate, 2026-10-09 (UTC)

The latest failed single-item request had committed authoring and review Artifacts; post-result
classification rejected reviewer-authored complexity 2 when the typed draft scores 1. The source
candidate now routes only declared complexity/reason/decision mismatches to a second or third proof,
with exact prior review and expected/observed feedback. Authoring/image/Graph/Pack pins remain fixed.
Infrastructure retries cannot reset this budget; content rework and stronger review retain their
existing policies. Integrity failures remain terminal, not corrections.

Unit/domain/Catalog/dependency and actual wheel-resource gates: 175 PASS. Disposable PostgreSQL
correction gates: 22 PASS, including separate concurrent commands, crash recovery, third-proof
exhaustion and unchanged image/tier pins. The combined existing Workflow/submission/correction
PostgreSQL gate is 66 PASS (including those 22); operational installation is separately pending
at this source checkpoint. No model/Item/GPU/HWPX execution or historical
failed-workflow restart is claimed. See [ADR 0160](../adr/0160-natural-stimulus-presentation.md).

## Natural prose and native table presentation activation — 2026-10-09 14:35 UTC

The shared API/Catalog/Orchestrator release is installed from
`578ddd9a8f23a1a3aa9be3ee6e256344230d98aa`. New single-item requests resolve released
`generated-knowledge-item@1.20.15` in the existing development activation environment.
Authoring and review both receive the same pinned Handoff V2 excerpt: ordinary explanation does
not automatically become a labeled DATA box, while small numerical or qualitative comparisons
can remain native tables. Explicit material requirements, original team-lead files, predecessor
executions and the 25-item production contract are preserved.

Authenticated API smoke, installed release/RECORD verification, isolation and readiness PASS.
A read-only check against the registered Pack Artifact verified the exact bundle hash,
Brief V5 compatibility and both rendered profile `12.2.1` prompts. All relevant services remain
active; Web and the separate chat activation were not redeployed. No new migration, model/GPU
invocation, Item generation or HWPX rebuild was performed. Actual generated editorial quality is
not newly evaluated. Exact pins, evidence and rollback are in
[ADR 0160](../adr/0160-natural-stimulus-presentation.md) and the
[version matrix](../architecture/ACTIVE_RUNTIME_VERSION_MATRIX.md).

## Conversational internal search CHAT-READTOOLS-1 — 2026-10-08 19:02 UTC

`일반 → ChatGPT` can now search and read internal Items conversationally without
manual attachment. The dedicated Codex worker requests two bounded native read
tools; the Orchestrator executes them through the actor-authorized Catalog
application boundary and commits validated tool receipts before returning results.
No worker DB/NAS/Catalog access or chat mutations were introduced.

Installed API/Catalog/chat source: `7fb311fbfab683f9b3cf4cea123812e1f4e62591`;
compatible Web remains `6c765820d21f91dd1ef277219a894f25ddabac57`; DB remains
`20261008_0049`. Source gate: 623 PASS; disposable PostgreSQL gates: 49 + 23 + 12
PASS. Actual HTTPS canary: three completed turns, verified native SEARCH/READ,
accepted solution-report citations, exact-pin follow-up, source Preview navigation,
one idempotent HTTP replay and history reload PASS. Original 21 terminal receipts
remain unchanged. Both chat units and the API/Web/Catalog/workflow services are
active. Two task-owned disposable databases were removed through guarded cleanup.

The first C06 candidate completed without tools and is retained as non-acceptance.
The installed model's direct-tool exposure was corrected with a supported strict
CLI setting, without enabling shell/code execution or changing auth/model metadata.
See [read-tool acceptance](GENERAL_CHAT_AGENT_SEARCH_ACCEPTANCE_2026-10-08.md) and
[design](../architecture/GENERAL_CHAT_AGENT_SEARCH_DESIGN.md).
Implementation tag C06 does not close the original plan's C06 image/multimodal work.
The following C04/C05 section is its dated predecessor, not the current release pin.

## General chat representative operational connection — 2026-10-08 UTC

`일반 → ChatGPT` now uses the dedicated Codex slot as a read-only EOM assistant.
Explicitly attached immutable Items and accepted additive solution reports are
actually passed to the model, with verified citations, follow-up context and
timestamped authorized system observations. API/Catalog/chat release `276f31ea`
and Web `6c765820` are compatible installed pins; migration remains `0049`.
Authenticated grounding/replay/history/source navigation passed. PC/mobile final
read-only presentation passed; no production content approval is implied.
See [acceptance record](GENERAL_CHAT_REPRESENTATIVE_ACCEPTANCE_2026-10-08.md).
Other sections retain their stated historical scope and observation dates.

## SDXL image-quality goal checkpoint — 2026-10-03 (UTC)

User approval separately extends the immutable SSD-1B data authorization to internal SDXL
comparison/training only. The optional offline SDXL model stack/reference probe was installed;
the production V6 binding remains unchanged. Six TRAIN depictions at two seeds and four same-input
conditioning-strength controls produced 16 actual model outputs. The Orchestrator validated and
committed terminal results and 42 PNG members (including conditioning/raw variants). The PNG count
is not the planned 42-output/four-arm pilot, which remains pending. Our own inspection rejects all
16 for style/composition artifacts; independent blind-review acceptance has not occurred.

The numerical UNet-LoRA loop is now shared behind real SSD and SDXL architecture wrappers, with
distinct bundled/fixed VAE locations and unchanged SSD checkpoint identity. Nonfinite tensors,
gradients/adapter values and new SDXL resource bounds are checked. Focused source regressions:
87 PASS at the numerical checkpoint. The subsequent micro application/CLI/Orchestrator handoff
now passes 137 focused tests and 9 dependency/publication tests; full non-live image-runtime
suite: 244 PASS; Ruff, targeted mypy and release-shell syntax PASS. These tests use CPU fakes
for loop accounting, not real GPU training. No installed trainer or operating model was replaced
at that source checkpoint. The 12 sanitized diagnostic operator logs are archived as
`artifact_bb025e48f4d44032bcef8e13a2cbb503` /
`rev_238a506019a24c678d335bce6c776bbc`, separate from canonical GPU result revisions.

Subsequent live micro acceptance: tested source `da1fde0e` was installed only in the existing
trainer environment plus one optional offline unit, with exact predecessor rollback wheels,
wheel/installed RECORD checks, actual worker imports/CUDA and `pip check` PASS. One approved
16-TRAIN/200-step SDXL run completed in 474,435 ms at 5,704,160,768 bytes peak Torch GPU allocation.
The Orchestrator validated and committed 20 result/derived-PNG/PEFT members as
`artifact_e4cca31093f1467f8742384ba404dcd4` /
`rev_02b106d8920f479e8dc7aa453d304ef2`; the adapter remains EVALUATION_ONLY with automatic activation
FORBIDDEN. Final loss 0.013273741118609905 is not a quality score. No post-LoRA generation or blind
acceptance has occurred. Original source pixels/captions and reserved images remain unchanged.
Own derived-data inspection still sees gray surfaces, existing redaction holes, one frame fragment
and small objects on white canvases. Nine sanitized micro operator logs are archived as
`artifact_1c2e2ecfc4de48f3be863ab5c71955ec` / `rev_240783417edd4306a923fe3a8b9b3519`.
Production V6/inference environment are unchanged; operating services stayed active and GPU is
idle after the run. Next is pinned adapter evaluation, not automatic operating activation.

The [current image improvement plan](../operations/IMAGE_STYLE_IMPROVEMENT_PLAN_2026-10-03.md)
pins source/model/result hashes, distinguishes correct conditioning polarity from actual contour
extraction, records inspected dataset limitations and lists the remaining quality/activation gates.

## Document-review activation incident — 2026-10-03 (UTC)

An owner-scoped paired-document upload failed with `CONTROL_PRESET_NOT_PUBLISHED`: the installed
API requires `workflow-role/1.27.0`, while the published document-review preset was still the V4
policy supporting only 1.25/1.26. Workflow 1.2 was already active. No account permission change is
required. The unpublished V5 bootstrap also incorrectly pinned V3 as its predecessor although
instruction revision 5 must follow released revision 4. Its candidate predecessor pins now match
the exact released V4 preset, instruction revision, and hashes. V1–V4 and source PDF artifacts are
unchanged. The protocol tests assert all five predecessor pins to prevent this copied-config
regression. Operational recovery uses the existing evaluated bootstrap, followed by the existing
owner-authenticated upload replay; it does not rewrite failed history or create duplicate reviews.
Activation and completed review are separate evidence; a passing source test alone is not live
activation evidence.

Live recovery: V5 was published through `bootstrap_pdf_document_review_control_plane` with source
`8fb76dba8251ee3d2820fcdf3107bb7bd95cb4a7`. Current released preset
`execpresetrev_b478cf2d7ae647e0917de9a3cbadede0` pins instruction revision 5
`instrrev_c6a97fc4831a807893742c1e40db7539`. The installed resolver accepted protocol 1.27 and its V2
Graph retrieval policy (`LIVE_POLICY_PREFLIGHT=PASS`). Focused protocol tests: 28 PASS; Ruff lint and
format checks: PASS. The failed original owner-scoped review set remains `FAILED_RETRYABLE` until
its authenticated upload replay. Activation did not regenerate the documents, create a duplicate
review, or claim that review execution has completed. No service restart or new wheel is needed
for this configuration-only publication; the installed API already owns the V3 request path.
Additional execution/projection/evidence tests: 8 PASS (36 focused tests in total). The production
bootstrap module passes mypy. An optional direct mypy invocation on the existing protocol test
module reports 108 pre-existing broad-output-union/fixture typing errors outside the changed
assertions; this is not a production-module type-check PASS and remains test-typing maintenance
debt. Ruff checks passed on the changed test module. Slack recovery milestone was delivered.

The subsequent real submission exposed a separate first-start bug: the API hashed a
`CREATE_DOCUMENT_REVIEW_EVIDENCE` command without its default `schema_version`; the canonical
contract includes that field and rejected the hash. Read-only reproduction using the pinned
14-page question and 7-page solution succeeded for the base request, failed for the unversioned
command and passed for the explicitly versioned command. The first-start adapter now hashes the
complete versioned command. A regression test exercises the real adapter up to the private Catalog
boundary, while the existing replay test still asserts that replay does not consult mutable policy.
Focused source tests: 21 PASS, one disposable-PostgreSQL-only test skipped. Ruff and mypy pass on
the changed adapter and regression test. The second failed review set is terminal `FAILED_FINAL`;
it is not manually changed to success or made retryable. After deployment its owner must refresh
the browser and submit again, creating an explicit successor request while retaining failure
history. The original PDF Artifacts remain intact.

Runtime follow-up: API release `af88f0f9d994a48c00126c14a3b878bb2f04af12` was installed through the
normal release script. Wheel RECORD, installed import, runtime isolation and readiness checks
passed; the first-start and replay tests also pass against the installed package (2 PASS).
Migration remains `20261003_0046`; V5 is still the current released document-review policy. This
confirms the repaired request-building boundary, not an owner-authenticated completed review;
the release's authenticated smoke was deferred because its credentials were not configured.
Owner resubmission after browser refresh remains the next live execution check. The privileged
deployment's Git status check temporarily rewrote `.git/index` as root mode 0600; only that exact
index file's owner/mode was restored to the repository operator. Read-only privileged Git checks
should use `GIT_OPTIONAL_LOCKS=0` in a subsequent maintenance patch.

On 2026-09-27 the repository and isolated local-image runtime completed a corpus-grounded visual
subject benchmark over the occurrence-backed 520-item science baseline. The immutable inventory
closes 537 observations as 514 covered plus 23 explicit omissions and identifies 87 subjects. The
benchmark exercised 69 deterministic routes, 18 BASE/ADAPTER pairs, and two forbidden human-raster
requests; both negative controls were rejected. An independent, pointer-bound review classified
the results as 69 diagnostic-only, five base-preferred, seven adapter-preferred, and six where
neither variant is acceptable. The LoRA adapter remains `EVALUATION_ONLY`, activation stays
`FORBIDDEN`, and the existing base-only provider binding is unchanged. Route diagnostics are not
production-quality evidence because the real path uses worker-authored safe SVG through the
Catalog compositor. See
[Science visual subject benchmark](SCIENCE_VISUAL_SUBJECT_BENCHMARK_2026-09-27.md) and
[ADR 0132](../adr/0132-science-subject-quality-gate.md).

The repository now contains the protocol-first successor that closes the four limitations observed
in the live V2 audit. Workflow `pdf-document-review@1.2.0`, role protocol `workflow-role/1.27.0`,
result `pdf-document-review-result@3.0`, resolved plan V15, and the V5 control bootstrap require
exactly ten independent axes including `EDITORIAL_CLARITY` and `TYPOGRAPHY`. Every detected Item has
an ordered independent-solve, answer, condition, unit, choice, explanation-step, cross-document,
and Graph-evidence record. Any unverified target—including insufficient originality—or any
incomplete item decision forces `NEEDS_HUMAN_DECISION`.

Catalog derives a bounded Graph scope from the exact PDF revisions with indexed node-term lookup
and publishes an Evidence Bundle V5 requiring accepted solution evidence. The Orchestrator stages
the exact manifest/context, validates evidence and anchors plus scalar result paths before NAS
commit, and stores a self-hashed result-bound receipt in the same `ARTIFACT_COMMITTED` event. API,
Scientific Studio, and the native-panel annotation request have additive V3 projections while V2
history remains readable. This paragraph describes the repository candidate and is not an implicit
claim that the successor is active in a particular runtime. See
[ADR 0111](../adr/0111-graph-grounded-exhaustive-document-review.md).

On 2026-09-24 the paired document-review path and its native PDF comment-panel derivative were
verified against one completed live review without changing the review, source documents, or
annotation artifacts. The pinned result covers a 14-page question document and a 7-page solution
document. Its combined verification, cross-document, and finding anchors touch all 21 source pages;
it contains 25 question-to-solution checks, and every check has both role-correct question and
solution anchors. The result records eight verification axes, one confirmed low-severity structure
finding, and one derived V2 annotation whose standard PDF comment panel is user-confirmed as
downloadable and usable.

That audit also fixes the boundary of the historical V2 claim. The released result `@2.0` requires at
least one verification target and one cross-document check, but it does not mechanically require
one target for every preset criterion, page, or detected Item. The live result omitted dedicated
`EDITORIAL_CLARITY` and `TYPOGRAPHY` targets, and its `ORIGINALITY` target was `INSUFFICIENT` while
the aggregate status remained `COMPLETE`; aggregate status currently follows uncertain candidates
and insufficient cross-document checks, not every insufficient verification target. Existing
bytes and historical results remain immutable. Those limits are not reinterpreted in place; the
additive V3 successor described above owns exhaustive coverage and fail-closed insufficient-target
semantics. See
[Document Review Detail Audit](DOCUMENT_REVIEW_DETAIL_AUDIT_2026-09-24.md) and
[ADR 0110](../adr/0110-native-pdf-review-comment-panel.md).

On 2026-09-21 the repository added a protocol-first, additive Graph-verification review candidate.
It is repository-verified only and is not an implicit live activation claim. The candidate pins
Workflow 1.13, role protocol 1.24, result family 12, Content Pack 1.19, standard control 17,
knowledge control 14, and evidence-usage validation receipt 3.0 as one compatible release set.
Review now plans its verification targets before reaching a verdict, checks visual material first
when present, classifies suspected issues as `CONFIRMED`, `DEMOTED`, or `UNCERTAIN`, and permits only
confirmed issues to become blocking findings. For structurally complex or uncertain reviews the
orchestrator may issue one exact, self-hashed escalation directive for one stronger independent
review attempt. The source review Artifact remains immutable and the final receipt chain binds the
source and selected review attempts. Workers still neither communicate directly nor write NAS.

The same candidate validates requested source classes against the actual pinned Evidence manifest,
resolves cited evidence and anchors through the pinned Graph revision, and resolves every review
target and candidate application path to a non-null scalar draft leaf. Catalog registration
re-resolves the V3 receipt and exact review lineage. This gives a future PDF textbook review feature
reusable verification concepts, but not a license to reuse Item result schemas: document review
requires a separate additive protocol for document revisions, page/region anchors, claims, and
review reports.

The read-only [2026-09-15 runtime baseline](RUNTIME_BASELINE_2026-09-15.md) records the roadmap
starting point. The 2026-09-16 M01 completion evidence below supersedes its mutable solution-report
and queue/lease counts. The architecture and historical acceptance remain applicable.

The coordinated [2026-09-15 release alignment](RELEASE_ALIGNMENT_2026-09-15.md) subsequently moved
the installed Application API and Scientific Studio Web to one verified `d4748d1` source identity.
Authenticated Preview, media, and download behavior were subsequently verified by S03/S04.

The follow-up [Preview and HWPX acceptance](PREVIEW_HWPX_ACCEPTANCE_2026-09-15.md) passed the public
HTTPS session, V1/V2/V3 Preview compatibility, media hash, material-contract, and existing single
and 25-Item HWPX download checks. The user subsequently confirmed the real-browser Preview V3 and
authenticated HWPX download. Gate A is therefore `PARTIAL_MANUAL_PASS`; only the previously defined
Hancom layout and editability observation remains unrecorded. The accepted 25-Item delivery is one
Assembly-level whole-exam HWPX build, not 25 separate per-Item build rows.

The roadmap follow-up has also prepared the frozen M02 human-quality worksheet, completed the M03
automated UX foundation and M04 operational projection, verified an existing textbook-grounded
author/review receipt chain for the limited L01 technical pilot, and re-ran 185 focused V5
production/readiness tests for L02. These technical results do not substitute for educational
review.

M01 reached terminal completion on 2026-09-16. The exact occurrence-backed denominator is 520;
the separate trusted-RAG canary remains intentionally outside it. A repeatable-read final audit at
04:44:41 UTC found 520 accepted V10 successors, active/pending/current-failed all zero, and no
duplicate accepted predecessor. The canonical target-to-successor mapping hash is
`sha256:d3ec932f2b85cf44b8289b5bf77459f5e40c86071139ffb982473472ab522520`.
Seventeen terminal attempts remain immutable historical evidence. Finalization disabled the
automatic refill mode and removed the bounded accelerator through its official manager, leaving
the healthy canonical Workflow runner only. See
[M01 solution-report backfill](M01_SOLUTION_REPORT_BACKFILL_2026-09-15.md).

L03 measured 17 accepted reports across slots 05 and 06 during the 33.5-minute available scale-out
window. It also added a source candidate for typed PostgreSQL backup manifests and verified the
newest existing 754 MB dump against its historical manifest. The newest dump has not been restored
in this session, Artifact-store snapshot/replication is not verified, and RTO/RPO remain undefined.
See [L03 capacity and recovery](L03_SOLUTION_REPORT_CAPACITY_BASELINE_2026-09-15.md).

This document describes the repository state, not an implicit claim that every additive successor
is active in a particular runtime. Mutable service, activation, queue, lease, and corpus-progress
state remains authoritative only in Scientific Studio and the corresponding typed API views.

On 2026-09-17 the repository added and then activated protocol-first in-product customer support.
It reuses one owner-scoped
Workflow as the canonical case, pins `customer-support@1.0.0`, `workflow-role/1.22.0`,
`resolved-execution-plan/10.0`, and a V4 capacity successor that reserves slot 06 for a one-shot
read-only `gpt-5.6-terra/medium` diagnosis. The worker cannot mutate application state, contact
another worker, use network access, or write DB/NAS; only the Orchestrator validates and commits
its immutable result Artifact. The API and Studio expose authenticated create/list/read use cases,
owner-only history, exact idempotent replay, cursor pagination, stale-response protection, and no
operator-only summary. Migration `20260917_0036` adds the explicit `CUSTOMER_SUPPORT` Workflow
stage and the partial owner/history lookup index; additive migration `20260917_0037` seeds the two
customer-support permissions for every built-in authenticated role. The compatible API/Web/worker
set was installed and one bounded live canary reached `ANSWERED`; exact replay returned the same
Workflow without another worker execution, and post-canary active commands, Jobs, API idempotency
records, and held leases were all zero. See [ADR 0096](../adr/0096-orchestrated-customer-support.md),
the [rollout runbook](../operations/CUSTOMER_SUPPORT_ROLLOUT.md), and the
[live acceptance receipt](CUSTOMER_SUPPORT_ACCEPTANCE_2026-09-17.md). Manual Studio layout and
usability review remains consolidated for the end-of-work user checklist.

## 1. Product boundary

EOM currently has one primary product path: request one Integrated Science Item, resolve an exact
Workflow/Content Pack/control-policy/Graph context, run isolated authoring, conditional image,
review, and registration roles through the orchestrator, require human approval, register one
immutable Item Revision, and optionally project it into HWPX.

Workers read staged local inputs and return typed local results. They neither communicate with one
another nor write PostgreSQL or NAS. The orchestrator validates JSON Schema 2020-12, Pydantic,
pointers, hashes, evidence usage, and state transitions before it alone commits canonical Artifact
Revisions. The Catalog owns Item registration and Graph/evidence application boundaries. The HWPX
Manager owns delivery projection and commits validated builder output.

## 2. Canonical identities and current additive families

| Capability | Repository family | Runtime note |
| --- | --- | --- |
| Single Item production | Workflow 1.10, role protocol 1.20, result family 10 | Implemented |
| RAG evidence use | Evidence manifest 2.0 and evidence-usage validation receipt 1.0 | Implemented and fail-closed |
| Registered content | Assessment Item Content 3.0 on Catalog protocol 1.13 | Implemented |
| Local image | Image result 10, local provider 1.0, prompt policy 1.4 | Implemented; external APIs forbidden |
| HWPX Item/exam | HWPX content-team protocol 3.0 | Implemented |
| Past-exam solution report | Knowledge Analysis Workflow/result 10 | Implemented as additive Artifact |
| Material-first request | Material requirement 1.0, Item Brief 4.0 | Active in the verified V5 run |
| Fresh 25-Item production | Production plan/execution family 5.0 | Active; pins Pack 1.16.1 |
| Material-first Content Pack | Pack 1.16.1, standard control 13, knowledge control 10 | Released and exercised live |
| In-product customer support | Workflow 1.0, role 1.22, result 1.0, plan 10.0 | Active; bounded live canary and exact replay PASS |
| Graph-verification review candidate | Workflow 1.13, role 1.24, result 12, receipt 3.0, Pack 1.19, standard 17, knowledge 14 | Repository-verified; not activated live |

Logical IDs, revision IDs, Artifact IDs, Artifact Revision IDs, schema identities, storage paths,
and SHA-256 hashes remain separate. New versions are additive; released predecessors are not
edited or reinterpreted.

## 3. RAG and knowledge state

The current batch-free past-exam corpus consists of 50 source PDFs, 25 occurrence revisions, and
520 approved Item analyses in one published Graph lineage. Its typed denominator is the set of
distinct Item Revisions placed in those past-exam occurrences and joined one-to-one to an accepted
V9 analysis. A separately approved trusted-RAG canary Item has no past-exam occurrence placement or
V9 base in that projection and is intentionally outside the 520 solution-report target. The earlier
521 statement mixed that separate product lineage into the past-exam denominator and is superseded
by the 2026-09-15 read-only target-set audit. “Learning” here means RAG ingestion and indexed
evidence, not model-weight training. Evidence resolution is bounded, permission checked,
schema/media checked, revision pinned, and hash verified.

The current trusted-RAG path requires authoring and review to cite the same exact Evidence Bundle
entry and Graph anchors and to identify non-null scalar application locations in the draft. The
orchestrator recomputes a validation receipt against canonical manifest/context bytes before an
Artifact success transition. Registration re-resolves the receipts; a boolean grounding flag is
not sufficient.

Detailed solution reports are additive to the existing 520 analyses. They record externally
reviewable solution steps, concept-to-assessment links, choice diagnostics, and unresolved issues;
they do not request or store hidden chain-of-thought. The user-facing corpus view reports only the
whole-corpus totals and completion state. Batch/run/work-unit details remain internal orchestration
and recovery data. Existing ID-oriented endpoints remain available for a future administrator
view without being the default presentation.

## 4. Image and HWPX state

The authoritative visual flow is:

```text
two unchanged content-team lead sources + KICE guide
  -> image worker reads all sources
  -> typed drawing intent per actual IMAGE array slot
  -> optional local GPU semantic raster
  + deterministic sanitized SVG scientific overlay
  -> immutable PNG Artifact Revision
  -> HWPX slot projection from the registered Item Revision
```

The local GPU has two short CLIP text encoders. It therefore receives the worker-authored bounded
semantic subject plus a fixed monochrome/white-background/no-decoration policy, rather than a
truncated copy of the full team-lead documents. Full source hashes, scene constraints, scientific
labels, exact geometry, and worker drawing intent remain available to validation and provenance.
Scientific labels are rendered deterministically; HWPX panel labels are never rasterized.

The Item request first distinguishes the student-visible material form from image execution:

- `TEXT`, `DATA`, and `INQUIRY` have no IMAGE slot;
- `TABLE` with `panel_count=1` is one editable native table, zero PNGs, no panel label, and no image
  placeholder;
- `TABLE` with `panel_count=2` is two native tables with editable `(가)`/`(나)` labels;
- `IMAGE` has one or two ordered IMAGE slots;
- `MIXED` has exactly one IMAGE and one TABLE in the authored order.

The image step is therefore skipped for a table-only Item. Its RAG request still asks for table
structure evidence. Catalog review publication and approved-Item Graph publication recompute the
same canonical retrieval-element set instead of assuming every Item is image-backed.

The HWPX projection uses one authoritative typed validator in contracts, Manager, and Builder:

- zero IMAGE slots require zero PNGs;
- one IMAGE slot requires one PNG and an empty panel label;
- two IMAGE slots require two distinct ordered PNGs and editable `(가)`/`(나)` HWPX text cells;
- mixed TABLE/IMAGE layouts preserve the actual zero-based visual-array ordinal and use no panel
  labels;
- member name, schema, media type, dimensions, ordinal, label, and staged filename must all match.

Whole-exam rendering accepts heterogeneous reviewed layout branches only when their HWPX headers
form one ordered append-only resource-table chain. It selects an existing maximal header, keeps
all shared IDs byte-semantically stable, and rejects incomparable or changed definitions instead
of synthesizing a union or renumbering references.

HWPX input staging now opens untrusted sources without following the final symlink, copies into a
fresh target, computes the pinned SHA-256 while streaming, checks source/file-descriptor identity
before and after, rejects truncation/growth, and removes a partial target on failure. Builder JSON
is bounded and read through the same stable-file boundary. Output HWPX is bounded, hash checked,
and compared again with the staged Artifact primary before NAS commit.

## 5. Presentation state

Scientific Studio presents product concepts first: corpus totals, Item/Workflow/build states, and
active Codex slots. Routine descriptions and low-value helper copy have been reduced. Runtime
settings live in the administrator area. Technical IDs and keys are retained for support and audit
but disclosed only from an explicit detail view. Corpus learning is batch independent in the user
interface.

The repository now includes additive Item Preview 3.0 for canonical Item Content V1, content-team
V2, and content-team V3. It preserves native tables and their ordered relationship with images;
`TABLE_ONLY` renders one table with no image request or empty placeholder. Content-team PNGs are
read through a new permission-checked Application API and private Catalog operation keyed only by
the approved Item Revision and visual ordinal. Artifact IDs, NAS paths, and member names are not
accepted from the browser.

Frontend/backend alignment is release-blocking rather than a manual convention. Tests close the
browser-to-BFF route inventory, BFF-to-OpenAPI operation inventory, Preview schema-to-renderer block
set, DOM selector and ES-module graph, backend-state-to-Korean-vocabulary map, and the exact
source/wheel/RECORD/installed file inventory. Preview requests clear stale edit/HWPX pointers on
start or failure and ignore responses from superseded selections.

## 6. Validation and operational evidence

The 2026-09-13 candidate passed 2,916 non-live tests in the explicit dependency environment for
each runtime. Another 158 live, database, or privileged tests were skipped because their opt-in
conditions were not enabled:

- API, domain, Catalog, Orchestrator, and Scientific Studio: 2,755 passed / 35 skipped;
- full HWPX plus the local-image adapter: 160 passed / one privileged test skipped;
- PostgreSQL integration collection: one pure test passed / 122 opt-in tests skipped;
- focused material-first mock-exam/Catalog/Graph and deployment/schema suites are contained in the
  passing totals above;
- strict mypy passed for 414 source files, and Ruff format/lint passed for 1,301 files;
- regenerated V4 schemas passed canonical/package byte parity and Draft 2020-12 validation;
- `deploy_release.sh`, the non-live runner, and Git whitespace checks passed;
- real platform, API-contract, and HWPX-builder wheels were constructed, then the packaged V4
  schemas and changed HWPX module were compared byte-for-byte with repository sources.

`tests.unit` and `tests.integration` now have collision-free package module identities. The single
non-live entrypoint keeps API and HWPX dependency environments separate and refuses every live,
database, or privileged opt-in variable. Skipped PostgreSQL tests were not redirected to the live
database; they require an explicitly created disposable database under the integration runbook.

The 2026-09-14 release and operational acceptance added the following evidence:

- the Application API suite passed 511 tests, with 14 explicit opt-in tests skipped;
- the full HWPX and related HWPX Application boundary passed 225 tests, with one privileged test
  skipped;
- all six HWPX persistence tests ran against an explicitly created disposable PostgreSQL database;
  migration, runtime-role reconciliation, release-wheel inspection, and cleanup passed without
  redirecting the tests to production data;
- Pack 1.16.1 and production plan/execution 5.0 completed one fresh 25-Item generation, review,
  human-approval, registration, analysis, rating, and assessment-assembly chain;
- the resulting immutable Item set rendered twice identically before release, and the official HWPX
  API then published the same 258,452-byte output with 25 sections, 81 native equations, seven
  native tables, 13 visual slots, six PNGs, and 40 ZIP entries;
- the published HWPX output SHA-256 is
  `sha256:8eed5f6961a17df3f65ba62d42690659d9ad85bb9cc267ba6f58f5ecaf7983f8`; an authenticated
  [Studio download](https://eomai.duckdns.org/studio/api/v1/mock-exam-hwpx/builds/hwpxbuild_f3686d5ca87042e390537464a49f1878/download)
  resolves that exact Artifact Revision.

The 2026-09-14 Preview V3 compatibility audit used one read-only production snapshot and projected
all 558 current approved Item Revisions: four canonical V1, three content-team V2, 31 content-team
V3, and 520 legacy V1 URI-alias Items. No content or database state was changed. The independent
material matrix includes a table-only case with zero image components, so aggregate exam success
cannot mask that branch.

The final Preview V3 repository candidate passed the standard non-live gate: 2,924 API/domain/
Catalog/Orchestrator/Studio tests, 197 HWPX/local-image tests, and one integration-collection pure
test. The gate skipped 35 live or database API tests, one privileged HWPX test, and 126 explicit
PostgreSQL/system tests instead of redirecting them to production. Full Ruff format/lint passed for
1,331 files and strict mypy passed for 417 source files. The new component-media operation also
passed its focused Catalog, API/OpenAPI, browser, pointer-negative, and release-integrity suites.

The 2026-09-17 customer-support source candidate passes the current standard non-live entrypoints:
2,991 API/domain/Catalog/Orchestrator/Studio tests passed with 36 explicit live or database skips;
197 HWPX/local-image tests passed with one privileged skip; and the integration collection retained
one pure PASS while 127 PostgreSQL/system cases stayed opt-in. Focused support tests additionally
cover schema/Pydantic parity, owner authorization, exact idempotent replay, cursor pagination,
stale-browser responses, partial-answer withholding, and missing/stale/hash/lifecycle Artifact
resolution. Ruff, strict mypy on changed source, shell/JavaScript syntax, schema mirror parity, and
OpenAPI checksum checks pass. Wheel inspection, compatible deployment, the dedicated root-owned
900-second support worker template, and one bounded live canary were subsequently verified. The
canary completed one immutable `workflow_support` Artifact, the owner projection returned
`ANSWERED`, exact replay created no second execution, and post-canary work/lease counts were zero.
See the linked live acceptance receipt for exact content-free identities and preserved failures.

The customer-support PostgreSQL gate then passed in a newly created guarded disposable database.
It migrated from an empty database through `20260917_0037`, downgraded one revision, upgraded back
to the exact head, reconciled the isolated runtime role, and removed the database after the test.
The focused persistence case proved first publication plus exact replay of the normal immutable
`DRAFT` → `RELEASED` preset history, preservation of capacity V3 while V4 stays current, stable
plan binding, and use of `ix_workflow_customer_support_owner` for the owner-history query. This is
database integration evidence only. The same gate verifies the exact two customer-support
permissions and their ten built-in role bindings. Live activation and the successful Codex call
are separate evidence recorded in the live acceptance receipt.

The historical failed build/checkpoint remains preserved as audit evidence. The successful official
build is a new immutable build resource; no failed record was rewritten.

The 2026-09-21 Graph-verification candidate passed 335 focused tests with 33 explicitly guarded
integration skips, 2,231 remaining full-unit tests, and 739 API/Studio tests with 14 guarded skips. Full Ruff
format/lint passed for 1,418 files, strict mypy passed for 422 source files, Python compilation,
shell syntax, Git whitespace, schema mirror parity, and generator idempotence passed. The new
workflow-engine integration case was collected but not redirected to a live database because no
explicit disposable PostgreSQL database was provided. Two unchanged image-provider component
tests also remain environment-specific because the API environment has no Pillow and the image
environment has no pytest. These are recorded environment boundaries, not fabricated PASS results.

## 7. Readiness and remaining boundaries

1. The material-first V5 family and Pack 1.16.1 have passed a live heterogeneous 25-Item run and an
   official whole-exam HWPX build. Released V1–V4 executions remain pinned to their original Pack
   and must never be silently upgraded.
2. The live exam covered native tables, PNG-backed visuals, equations, and mixed reviewed layouts.
   A compact per-material regression matrix must continue to exercise TEXT, DATA, one/two TABLE,
   one/two IMAGE, MIXED, and INQUIRY independently so a later Pack cannot hide one branch behind a
   successful heterogeneous aggregate.
3. HWPX persistence mutations remain disposable-database-only. The six-test gate has run once for
   this release line and stays required for future storage or state-machine changes.
4. The current official HWPX resource is valid even though an earlier checkpoint contains an
   immutable failed build. Recovery tooling must create or resolve an idempotent successor; it must
   not mutate history or reinterpret a failed build as successful.
5. Solution-report enrichment completed the exact 520 occurrence-backed past-exam bases. The final
   typed projection has 520 completed, no active/pending/current-failed target, and no duplicate
   accepted successor. Its canonical completion-set SHA-256 is recorded above. A separate canary is
   not added merely to make the denominator 521.
6. The next product-quality gate is no longer basic transport feasibility. It is measured reviewer
   acceptance: scientific correctness, evidence relevance, novelty, visual accuracy, explanation
   quality, and HWPX edit time must be recorded without weakening schema, pointer, approval, or
   idempotency checks.

These are release gates, not reasons to weaken pointer, schema, approval, or idempotency checks.

## 8. Evidence used to form the next plan

The following repository documents are sufficient to reconstruct the major design boundaries:

- `README.md` for the product and current additive version map;
- `docs/adr/0076-content-team-prompt-to-hwpx-preflight.md` for this visual/HWPX change;
- `docs/adr/0077-material-first-item-and-independent-hwpx-acceptance.md` for the material contract;
- `docs/adr/0078-hwpx-exam-header-superset-merge.md` for heterogeneous whole-exam HWPX headers;
- `docs/adr/0090-content-team-explicit-equation-and-output-acceptance.md` for exact equation and
  output acceptance;
- `docs/architecture/KNOWLEDGE_BACKED_ITEM_EXECUTION_V3.md` for trusted evidence materialization;
- `docs/architecture/TRUSTED_EVIDENCE_REGISTRATION_GATE.md` for registration re-resolution;
- `docs/architecture/MOCK_EXAM_TRUSTED_RAG_PRODUCTION_V3.md` for the 25-Item pinned family;
- `docs/adr/0073-additive-past-exam-solution-reports.md` and ADR 0074 for solution-report lineage;
- `docs/architecture/LOCAL_GPU_IMAGE_ORCHESTRATION_V1.md` for local raster/compositor ownership;
- `docs/architecture/ITEM_PREVIEW_V3.md` for the native preview and frontend/backend alignment gates;
- `docs/operations/API_INTEGRATION_TEST_DATABASE.md` for safe persistence testing.

## 9. Recommended next plan

The current documents and verified runtime evidence support this order:

1. Deploy the additive M02 quality-workbench migration/API/Studio release after its disposable
   PostgreSQL gate, then evaluate the existing 25-Item accepted set without rerunning production.
   A scorecard is `READY` only after the full primary review, independent ten-Item sample, and all
   differing-observation resolutions are complete.
2. Keep a small release-blocking material matrix with one independently checked example for TEXT,
   DATA, one/two TABLE, one/two IMAGE, MIXED, and INQUIRY. Validate the registered Item manifest and
   rendered HWPX for each branch before relying on a whole-exam aggregate.
3. Measure product quality with the reviewer scorecard: scientific correctness, evidence relevance,
   novelty, answer uniqueness, visual accuracy, explanation quality, and minutes of HWPX editing.
   Use the measurements to revise the next additive Content Pack rather than changing a released
   prompt or interpreting transport success as Item quality.
4. Complete administrator observability for immutable IDs, revisions, hashes, retry history, and
   failure receipts while keeping batch, lease, and internal keys out of the default user view.
5. Introduce a successor production contract only when a changed Pack or acceptance rule requires
   it. Preserve V5 reproducibility and reuse the existing pointer, idempotency, approval, and
   disposable-database gates.

Database backup validation alone is not complete disaster-recovery evidence. The repository now
contains a protocol-first paired DB/Artifact verifier and runbook. Every run compares the complete
ordered Artifact revision inventory; sampled and full member-byte modes remain distinct. An actual
DR PASS still requires an operator-owned immutable Artifact snapshot and a disposable restored
database.
