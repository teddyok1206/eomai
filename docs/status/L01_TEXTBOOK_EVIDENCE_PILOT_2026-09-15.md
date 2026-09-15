# L01 textbook evidence pilot — 2026-09-15

Status time: 2026-09-15 15:44 UTC

## Outcome

`L01_TECHNICAL_PILOT=PASS`

The live system already contains a bounded textbook pilot and a larger active textbook-backed
corpus. No new ingestion, Graph publication, model generation, Item revision, or database mutation
was needed to prove the technical pilot. The checks below used repeatable-read, read-only database
transactions and emitted no textbook or Item content.

This result proves source/revision integrity, Graph publication, retrieval use, and one exact
authoring/review receipt chain. It does not prove that textbook evidence improves educational
quality; that comparison remains part of M02 and any later L01 expansion decision.

## Live inventory

| Boundary | Verified state |
| --- | --- |
| active textbook logical documents | 10 |
| approved textbook revisions | 20 across 10 documents |
| current pinned textbook revisions | 10 |
| source pages | 3,404 across the recorded approved revision history |
| committed document registrations | 20 |
| active document-analysis runs | 0 |
| current combined corpus | `integrated-science-textbooks`, revision 68, `PUBLISHED` |
| current combined Graph | `graphrev_c0e78b4e4ce6588de3d3b6c6f25fb3d9` |
| current Graph manifest SHA-256 | `sha256:5bbf1dd9590c6a1afaad9a524f20f154149515dc0652c06338763a722ee0a710` |
| current Graph contents | 1,040 sources, 17,390 nodes, 41,227 edges, 7,367 anchors |
| document revisions represented | 10 current textbook revisions |
| historical textbook retrieval use | 7,320 `GROUNDING` entries in 969 Evidence Bundle revisions |
| bounded earlier pilot corpus | `integrated-science-miraen-pilot`, one published source |

All ten current textbook revisions resolve exact approved source, analysis, rights-attestation, and
revision-manifest Artifact revisions. Source Artifact hashes equal the pinned source hashes. The
active `knowledge-grounded-item` preset is released at revision 22, allows `TEXTBOOK`, and keeps
general knowledge in `ALLOW_WITH_PROVENANCE` mode.

Historical analysis failures remain preserved: 2 request-v7 failures and 16 request-v8 failures.
They are not active work and were not rewritten as success. Accepted history is 1 request-v3,
32 request-v7, and 526 request-v8 runs.

## Exact use pilot

The existing completed workflow below supplies stronger evidence than a synthetic retrieval-only
probe because it reached Item registration while preserving the complete @10 evidence receipt
chain.

| Field | Value |
| --- | --- |
| Workflow | `workflow_c48c4b5320e34d619e46ad2f94d0f023` |
| Workflow definition | `generic-item-development@1.10.0` |
| role protocol | `workflow-role/1.20.0` |
| execution plan | `execplan_97f40d4d278245619d78ed45117429b4` |
| plan SHA-256 | `sha256:326d1f045eb0d14741d946efde6f69ebd54a3288a014eb87e053e7f8e4722ee1` |
| pinned Graph | `graphrev_7870b0fb03b7dfb64179e53182bf3999` |
| Graph snapshot SHA-256 | `sha256:00f2fa52d1f45258fcce74471441105e12e31cf5d58927f8122cfde1a4aaadfb` |
| Evidence Bundle revision | `evidencerev_1f6da11098fcac18bd59e33e605ae659` |
| authoring receipt | `sha256:d191839a7aa02d9e36f054c539f535e5f956e611cb6b8fb29cfdadb71acba1a3` |
| review receipt | `sha256:abde9e74428eea87ad8a04ff4767f079ec156be523b3202a8d283e7e2a105626` |

The workflow is `COMPLETED`. Its authoring and review Artifact pointers, Job requests, plan pins,
terminal `ARTIFACT_COMMITTED` events, typed receipts, and receipt self-hashes re-resolve exactly.
The authoring result contains two citations and the independent review attests the identical set.
One citation resolves to a non-answer-bearing `TEXTBOOK` `GROUNDING` entry backed by one immutable
educational-document revision. The audit deliberately records counts and hashes only, not the Item
or textbook content.

## Decision boundary

The technical evidence pilot is complete. Further textbook ingestion or mixed-source production is
not justified by this technical PASS alone. Before expanding source coverage, M02 must establish
whether the cited textbook evidence improves scientific accuracy, curriculum fit, authoring value,
or human editing time. Released historical workflows and Graph snapshots remain immutable; any new
retrieval or production meaning must use an additive successor contract.

## Reproducible read-only checks

- `/tmp/eom_l01_textbook_inventory.py`: corpus, document, revision, pointer, policy, and usage
  inventory; `py_compile` and Ruff pass.
- `/tmp/eom_l01_textbook_pilot_audit.py`: exact @10 plan/Artifact/receipt/citation audit;
  `py_compile`, Ruff, and strict mypy pass.

These scripts are temporary operational diagnostics and are not canonical generated artifacts.
