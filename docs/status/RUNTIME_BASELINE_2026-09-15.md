# EOM Runtime Baseline — 2026-09-15

Observed at: 2026-09-15 12:29–12:45 UTC

This is a read-only operational baseline for roadmap step S01. It distinguishes the current Git
candidate, installed runtime bytes, mutable database state, and historical acceptance. It does not
authorize a deployment or reinterpret prior immutable executions.

## Read boundary

The database projection was obtained in one installed Application API environment with PostgreSQL
transactions forced to `REPEATABLE READ` and `READ ONLY`. The probe emitted only typed aggregate
state, immutable IDs, revisions, and hashes. It did not emit secrets, Item content, prompts, worker
results, or large Artifact payloads. No database, NAS, service, Workflow, or activation state was
changed.

## Repository candidate

| Field | Value |
| --- | --- |
| branch | `main` |
| commit | `2e8e5c554b80d443f0754a730ec123ef134eb04d` |
| tree | `e1c88f25c3d7a16bf54547743c9172636ad33b13` |
| `origin/main` | same commit |
| tracked worktree | clean |

The external planning context and this baseline are new documentation files and are not part of the
above Git tree until explicitly reviewed and committed.

## Installed release set

| Component | Installed identity | Relation to repository candidate |
| --- | --- | --- |
| Application API | source `3a5c6e44769e02417aa58f102e0d36bd9dc0cb42` | ancestor, six commits behind |
| API contracts/platform | installed with the API release environment | Preview V3 Catalog/API changes absent |
| Scientific Studio Web | source `a32a124b6cb68e624fc5acda3176216684a527a4` | ancestor, 50 commits behind |
| HWPX Builder/contracts | complete installed package trees equal repository HEAD bytes | current |
| Local image provider/contracts | complete installed package trees equal repository HEAD bytes | current |
| Observability | source `1f9724736a17c709ad697289f2111c5d43e1844b` | no change attribution inferred |

The API, Catalog application runner, Workflow runner, HWPX application runner, and maintenance
service load Python from the shared `eom-api` environment. Two additional transient Workflow
runners named `eom-workflow-runner-production.service` and
`eom-workflow-runner-backfill.service` started at 2026-09-14 05:39:59 UTC and remained active at the
observation time. They predate the installed API environment update at 12:45 UTC that day and are
not restarted by the current static consumer list in `deploy_release.sh`. They had no active jobs,
commands, or leases, but must be explicitly included in the release/quiescence decision to avoid an
old in-memory or lazy-import mixed runtime.

Installed distribution `RECORD` files were present for every named EOM distribution. Their hashes
were captured in the S01 operator log; this document does not treat the package version `0.1.0` as a
substitute for the source or RECORD identity.

## Service health

At the observation time:

- Application API: `active/running`, live `LIVE`, ready `READY`, restart count zero;
- Scientific Studio: `active/running`, live `LIVE`, ready `READY`, API and observability `ACTIVE`,
  restart count zero;
- Catalog application runner: `active/running`;
- HWPX application runner: `active/running`;
- base, production, and backfill Workflow runners: `active/running`;
- Workflow maintenance: `active/running`;
- active transient worker, image-provider, or HWPX-builder unit: zero.

Historical failed transient systemd units remain visible. They are audit/operational residue, not
evidence that the current long-running services are unavailable.

## Database and current work

| Field | Value |
| --- | --- |
| migration | `20260912_0035` |
| active platform jobs | 0 |
| held/reconciling worker leases | 0 |
| pending/leased/processing Workflow commands | 0 |
| processing API idempotency records | 0 |

Non-terminal Workflow rows still exist without executable work:

| Workflow family | State | Count |
| --- | --- | ---: |
| generic Item 1.10 | awaiting human approval | 44 |
| generic Item 1.7 | awaiting human approval | 1 |
| generic Item 1.8 | requested | 23 |
| generic Item 1.8 | running | 1 |

These rows must not be called quiescent terminal history, but they had no active commands, jobs, or
leases. Release compatibility must preserve their pinned definitions and results.

## Active Content Packs

All active rows were in the `development` environment.

| Pack | Version | Release | State |
| --- | --- | --- | --- |
| `generated-knowledge-item` | `1.16.1` | `packrel_0ebfaa4c7db14ed08ae63d4e17fc9d2a` | released/active |
| `general-knowledge-item` | `1.0.0` | `packrel_8184f0c8695840058e5d8df9ee6dde27` | released/active |
| `generic-placeholder` | `0.1.0` | `packrel_c07fcb1563ab434f95bca201269fd244` | released/active |

The active material-first Pack 1.16.1 therefore remains a live fact rather than a README-only
candidate.

## Current execution presets

| Key | Current revision | Revision | Knowledge policy | State |
| --- | --- | ---: | --- | --- |
| `knowledge-analysis` | `execpresetrev_a0ea101dc27a4708ae350489546510cf` | 40 | allow with provenance | released/current |
| `knowledge-grounded-item` | `execpresetrev_90aa8cfd163045a39cb88ac45fdaf8b8` | 22 | allow with provenance | released/current |
| `standard-item` | `execpresetrev_fb4349aaddbe48f18cf2460d93384250` | 28 | allow with provenance | released/current |
| `legacy-item-editorial-compatibility` | `execpresetrev_691cea291a9e4fb79f0f6364651f1bc0` | 4 | deny | released/current |
| `legacy-item-extraction` | `execpresetrev_d8fe0d31e63942f9a349eed7ccb6a03e` | 4 | deny | released/current |

All six worker slots were enabled: authoring 01, review 02, GPU image 03, Item management 04, and
support 05/06.

## Current Graphs and corpus

Two active corpus pointers were present.

### Main integrated-science corpus

| Field | Value |
| --- | --- |
| corpus key | `integrated-science-textbooks` |
| Graph revision | 68 |
| Graph Revision ID | `graphrev_c0e78b4e4ce6588de3d3b6c6f25fb3d9` |
| snapshot SHA-256 | `sha256:da76258a650dcb66c3303f579ec1502215bda6cb75f05808414809d7076bf645` |
| manifest SHA-256 | `sha256:5bbf1dd9590c6a1afaad9a524f20f154149515dc0652c06338763a722ee0a710` |
| sources / nodes / edges / anchors | 1,040 / 17,390 / 41,227 / 7,367 |
| source PDFs / exam occurrences / approved analysis bases | 50 / 25 / 520 |

The earlier `521 accepted bases` statement is not the current batch-free corpus projection. The
current authoritative denominator is 520. The separate 558-Item Preview compatibility audit used
the Item Registry current-approved projection and remains a different denominator.

### Textbook pilot

The current database already contains one published `integrated-science-miraen-pilot` Graph
revision with one source, nine nodes, two edges, and eight anchors. This is inventory evidence only;
it does not prove rights review, general production activation, or product-quality benefit.

## Solution-report enrichment

The authoritative current corpus projection was:

| State | Count |
| --- | ---: |
| accepted/completed | 322 |
| active | 1 |
| failed | 1 |
| pending/no successor | 196 |
| total | 520 |
| aggregate status | `BLOCKED` |

Exactly two current bases account for the non-pending blockers:

1. `analysisrun_41871a5475a2431e86b1040510ee11b4` is still `RUNNING`, but its Workflow
   `workflow_1700f7d70d164b1589b6bf852ea0125f` is `COMPLETED`; it has no platform job and no
   worker lease. This is a stale cross-state invariant, not active computation.
2. `analysisrun_28d353afee16414db5a71a560b4dad23` is `FAILED` with
   `KNOWLEDGE_ANALYSIS_WORKER_FAILED`; its Workflow is terminal `FAILED`, with no current lease.

Historical failed V10 attempts whose predecessor later gained an accepted successor are preserved
but do not contribute to the current corpus failed count. Any repair must use the supported
state/idempotency boundary; it must not rewrite these rows or the two blocker histories.

## Latest embedded-image HWPX acceptance

The HWPX successor changes were already installed and exercised live after the earlier official
build. The latest preserved acceptance is:

| Field | Value |
| --- | --- |
| build | `hwpxbuild_da626008bbc14afc9d3408bc0107a0f9` |
| bytes | 258,476 |
| sections | 25 |
| native equations / tables | 81 / 7 |
| visual slots / binary images | 13 / 6 |
| ZIP entries | 40 |
| output Artifact | `artifact_7dc278de9f6c4f98bb24fd7bfb05fed5` |
| Artifact Revision | `rev_71917abb07204131a8656e7b7125ca3b` |
| output SHA-256 | `sha256:5f1ab03c1123957c6bd550a9b2e9bfd73030fa40bbdcf70e6433d757e1f22bab` |
| authenticated download | `https://eomai.duckdns.org/studio/api/v1/mock-exam-hwpx/builds/hwpxbuild_da626008bbc14afc9d3408bc0107a0f9/download` |

The build result, downloaded byte count, and downloaded SHA matched. Gate S04 must still retain the
independent material matrix, but it must not repeat whole-exam generation merely to prove that the
embedded-image successor was exercised.

## Corrected roadmap input

S01 changes four planning assumptions:

1. the current solution denominator is 520, not 521;
2. solution reports progressed to 322 but are blocked by one stale running row and one terminal
   failure;
3. a limited textbook pilot Graph already exists, although general textbook product readiness is
   not established;
4. the latest HWPX/image runtime and one embedded-image whole-exam build are already live-verified.

The highest-priority remaining release drift is the API/Catalog/Web Preview boundary. The next S02
step must also account for the two untracked transient Workflow runner consumers before changing the
shared `eom-api` environment.
