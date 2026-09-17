# Current System Status

Status date: 2026-09-17 (UTC)

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

On 2026-09-17 the repository added a protocol-first in-product customer-support candidate. It is
not described as live merely because the source exists. The candidate reuses one owner-scoped
Workflow as the canonical case, pins `customer-support@1.0.0`, `workflow-role/1.22.0`,
`resolved-execution-plan/10.0`, and a V4 capacity successor that reserves slot 06 for a one-shot
read-only `gpt-5.6-terra/medium` diagnosis. The worker cannot mutate application state, contact
another worker, use network access, or write DB/NAS; only the Orchestrator validates and commits
its immutable result Artifact. The API and Studio expose authenticated create/list/read use cases,
owner-only history, exact idempotent replay, cursor pagination, stale-response protection, and no
operator-only summary. Migration `20260917_0036` adds the explicit `CUSTOMER_SUPPORT` Workflow
stage and the partial owner/history lookup index; additive migration `20260917_0037` seeds the two
customer-support permissions for every built-in authenticated role.
See [ADR 0096](../adr/0096-orchestrated-customer-support.md) and the
[rollout runbook](../operations/CUSTOMER_SUPPORT_ROLLOUT.md). The guarded disposable-PostgreSQL
gate has passed; wheel inspection, compatible deployment, and live-canary status must still be
recorded separately before this candidate is called active.

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
| In-product customer support | Workflow 1.0, role 1.22, result 1.0, plan 10.0 | Repository candidate; live activation pending |

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
OpenAPI checksum checks pass. This remains source evidence until wheel inspection, compatible
deployment, and one bounded live canary are separately recorded.

The customer-support PostgreSQL gate then passed in a newly created guarded disposable database.
It migrated from an empty database through `20260917_0037`, downgraded one revision, upgraded back
to the exact head, reconciled the isolated runtime role, and removed the database after the test.
The focused persistence case proved first publication plus exact replay of the normal immutable
`DRAFT` → `RELEASED` preset history, preservation of capacity V3 while V4 stays current, stable
plan binding, and use of `ix_workflow_customer_support_owner` for the owner-history query. This is
database integration evidence only. The same gate verifies the exact two customer-support
permissions and their ten built-in role bindings; it does not imply live activation or a successful
Codex call.

The historical failed build/checkpoint remains preserved as audit evidence. The successful official
build is a new immutable build resource; no failed record was rewritten.

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

1. Perform the prepared M02 human quality review of the existing 25-Item accepted set; do not rerun
   production merely to collect the scorecard.
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
