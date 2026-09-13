# Current System Status

Status date: 2026-09-13 (UTC)

This document describes the repository state, not an implicit claim that every additive successor
is active in a particular runtime. Mutable service, activation, queue, lease, and corpus-progress
state remains authoritative only in Scientific Studio and the corresponding typed API views.

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
| Material-first request | Material requirement 1.0, Item Brief 4.0 | Implemented; activation required |
| Fresh 25-Item production | Production plan/execution family 4.0 | Implemented; pins Pack 1.16.0 |
| Material-first Content Pack | Pack 1.16.0, standard control 13, knowledge control 10 | Repository candidate; activation required |

Logical IDs, revision IDs, Artifact IDs, Artifact Revision IDs, schema identities, storage paths,
and SHA-256 hashes remain separate. New versions are additive; released predecessors are not
edited or reinterpreted.

## 3. RAG and knowledge state

The validated past-exam baseline consists of 50 source PDFs and 520 approved Item analyses in one
published Graph lineage. “Learning” here means RAG ingestion and indexed evidence, not model-weight
training. Evidence resolution is bounded, permission checked, schema/media checked, revision
pinned, and hash verified.

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

## 6. Validation evidence for this repository candidate

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

## 7. Readiness and unresolved boundaries

1. Pack 1.16.0 and the material-first V4 family still need the normal build, bootstrap where
   required, release, activation, and one-Item live canary sequence. Repository presence alone is
   not runtime activation.
2. The new production V4 runtime must complete a fresh checkpoint canary that proves each Item's
   material requirement derives the exact image mode and retrieval elements. Existing V3 executions
   remain pinned to Pack 1.15.1 and must never be silently upgraded.
3. HWPX persistence tests that mutate a database must run against a disposable isolated PostgreSQL
   instance before production rollout.
4. After activation, live acceptance must cover TEXT, DATA, one TABLE, two TABLEs, one IMAGE, two
   IMAGEs, mixed IMAGE/TABLE, and INQUIRY. It must verify the Item manifest and HWPX package, then
   build one heterogeneous 25-Item exam; local renderer tests do not replace that boundary.
5. Solution-report completion is mutable operational state and must be read from the batch-free
   corpus projection rather than frozen into repository documentation.

These are release gates, not reasons to weaken pointer, schema, approval, or idempotency checks.

## 8. Evidence used to form the next plan

The following repository documents are sufficient to reconstruct the major design boundaries:

- `README.md` for the product and current additive version map;
- `docs/adr/0076-content-team-prompt-to-hwpx-preflight.md` for this visual/HWPX change;
- `docs/adr/0077-material-first-item-and-independent-hwpx-acceptance.md` for the material contract;
- `docs/adr/0078-hwpx-exam-header-superset-merge.md` for heterogeneous whole-exam HWPX headers;
- `docs/architecture/KNOWLEDGE_BACKED_ITEM_EXECUTION_V3.md` for trusted evidence materialization;
- `docs/architecture/TRUSTED_EVIDENCE_REGISTRATION_GATE.md` for registration re-resolution;
- `docs/architecture/MOCK_EXAM_TRUSTED_RAG_PRODUCTION_V3.md` for the 25-Item pinned family;
- `docs/adr/0073-additive-past-exam-solution-reports.md` and ADR 0074 for solution-report lineage;
- `docs/architecture/LOCAL_GPU_IMAGE_ORCHESTRATION_V1.md` for local raster/compositor ownership;
- `docs/operations/API_INTEGRATION_TEST_DATABASE.md` for safe persistence testing.
