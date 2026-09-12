# Current System Status

Status date: 2026-09-12 (UTC)

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
| Fresh 25-Item production | Production plan/execution/review family 3.0 | Implemented, but pins Pack 1.15.1 |
| Two-source image handoff successor | Pack 1.15.9, standard control 13, knowledge control 10 | Repository candidate; activation required |

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

The HWPX image projection uses one authoritative typed validator in contracts, Manager, and
Builder:

- zero IMAGE slots require zero PNGs;
- one IMAGE slot requires one PNG and an empty panel label;
- two IMAGE slots require two distinct ordered PNGs and editable `(가)`/`(나)` HWPX text cells;
- mixed TABLE/IMAGE layouts preserve the actual zero-based visual-array ordinal and use no panel
  labels;
- member name, schema, media type, dimensions, ordinal, label, and staged filename must all match.

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

The 2026-09-12 candidate passed:

- 2,016 source unit tests across the explicit API/HWPX dependency environments;
- 26 Content-Team Item/exam renderer tests;
- 54 HWPX Manager/Application tests, with six isolated-PostgreSQL tests collected but skipped;
- explicit zero-, one-, and two-image HWPX render canaries;
- 39 deployment-boundary tests;
- Ruff format and lint for 1,286 files;
- mypy for 412 source files;
- canonical/package byte parity for the new control schemas;
- `deploy_release.sh` shell syntax and Git whitespace checks.

The skipped PostgreSQL tests were not redirected to the live database. They require an explicitly
created disposable test database according to the integration runbook.

## 7. Readiness and unresolved boundaries

1. Pack 1.15.9 and standard/knowledge control successors 13/10 still need the normal build,
   bootstrap, release, activation, and one-Item live canary sequence. Repository presence alone is
   not runtime activation.
2. The immutable 25-Item production V3 family pins Pack 1.15.1. A new production successor is
   required before a 25-Item run can honestly claim the Pack 1.15.9 two-source visual contract.
3. HWPX persistence tests that mutate a database must run against a disposable isolated PostgreSQL
   instance before production rollout.
4. After activation, live acceptance must cover zero, one, and two IMAGE slots and verify the
   resulting Artifact manifest plus HWPX package structure; local renderer tests do not replace
   that boundary.
5. Solution-report completion is mutable operational state and must be read from the batch-free
   corpus projection rather than frozen into repository documentation.

These are release gates, not reasons to weaken pointer, schema, approval, or idempotency checks.

## 8. Evidence used to form the next plan

The following repository documents are sufficient to reconstruct the major design boundaries:

- `README.md` for the product and current additive version map;
- `docs/adr/0076-content-team-prompt-to-hwpx-preflight.md` for this visual/HWPX change;
- `docs/architecture/KNOWLEDGE_BACKED_ITEM_EXECUTION_V3.md` for trusted evidence materialization;
- `docs/architecture/TRUSTED_EVIDENCE_REGISTRATION_GATE.md` for registration re-resolution;
- `docs/architecture/MOCK_EXAM_TRUSTED_RAG_PRODUCTION_V3.md` for the 25-Item pinned family;
- `docs/adr/0073-additive-past-exam-solution-reports.md` and ADR 0074 for solution-report lineage;
- `docs/architecture/LOCAL_GPU_IMAGE_ORCHESTRATION_V1.md` for local raster/compositor ownership;
- `docs/operations/API_INTEGRATION_TEST_DATABASE.md` for safe persistence testing.
