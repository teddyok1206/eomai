# Textbook Knowledge Analysis V12 Checkpoint

Date: 2026-08-28 UTC

## Purpose and authority

This document is a small, content-free operational checkpoint for the running five-publisher
textbook analysis. It is not a generated worker result, a retry authorization, or a Graph
publication request. PostgreSQL remains authoritative for live state. The immutable Educational
Document Revisions and accepted-result Artifact Revisions remain authoritative for content.

No worker, service, batch, run, or Artifact was changed while producing this checkpoint. The audit
used a read-only database transaction and read-only validation of local worker results. It did not
print textbook text or worker prose.

## Frozen topology and execution identity

| Field | Value |
| --- | --- |
| Complete logical coverage | 495 ranges / 1,702 physical pages / 10 textbook volumes |
| Previously accepted prefix | 59 ranges |
| Current suffix | 436 ranges |
| Suffix batch | `analysisbatch_f74d4a2471a74016b77110a7b8bb82f3` |
| Preset Revision | `execpresetrev_d468d2b077bd45d787af5402421865f4` |
| Full topology SHA-256 | `sha256:d022af64c977bf51ae109d3da39a5d9de31a68bcbe00e447a79c97301682dfd3` |
| Suffix topology SHA-256 | `sha256:0046f6c5c8528117526f368e007b39f39bbde08bad9b72a7ab153df815349652` |
| Failure policy | `CONTINUE_AND_COLLECT` |
| Automatic retry | `NONE` |

The topology is ordered, gap-free, non-overlapping, and revision-pinned. The current suffix request
was submitted once with one authorization marker and one submission-attempt marker.

## Read-only progress observation

At the observation boundary, the suffix batch was `RUNNING` with the following exact database
accounting:

| Range state | Count |
| --- | ---: |
| `ACCEPTED` | 53 |
| `FAILED` | 2 |
| `SUBMITTED` | 1 |
| `PENDING` | 380 |
| Total | 436 |

The 53 accepted suffix ranges plus the preserved prefix represent 112 accepted logical ranges at
this checkpoint. All 53 accepted rows had distinct analysis run IDs and complete accepted-result
Artifact Revision and SHA-256 pointers. None of the current suffix runs was present in a published
Graph Snapshot.

## Accumulating-result quality sample

The most recent 30 completed, valid results were checked without rendering their content:

- 30/30 passed `knowledge-analysis-proposal-result@8.0` JSON Schema and typed validation;
- 30/30 were regular, non-symlink `0640` files;
- 30/30 matched the exact delivered PNG page numbers and image SHA-256 values;
- 105/105 sampled page observations were present and marked `OBSERVED`;
- all sampled proposals reported `general_knowledge_used=false`;
- the sample contained non-empty Markdown, anchors, nodes, edges, and claims across substantive and
  front-matter ranges; and
- sampled headings and graph structures coherently covered energy conversion, element formation,
  Earth systems, and textbook assessment/review pages.

Across all completed suffix workspaces present at the checkpoint, 53 results passed typed
validation and contained 183 exact page-image observations. This is strong structural and
source-attestation evidence. It is not a substitute for later human factual/editorial review, so
the batch remains unpublished.

## Deferred failures

The two failed ranges remain durable failures. They were not accepted, did not receive an accepted
Artifact Revision, and were not published.

| Ordinal | Pages | Range / run | Workflow / job | First typed failure |
| ---: | --- | --- | --- | --- |
| 9 | 85–88 | `analysisrange_4fc13939ff3547888c9299dbed579b57` / `analysisrun_3d307071541947b0885d8ae1e9e3a8ea` | `workflow_f4a3c7ba1f5d415b90ca8bb7b4bb14fa` / `job_5259ef3712ad4e91be26912c07509751` | anchor pointer does not resolve |
| 17 | 115–116 | `analysisrange_0cae8d2ead024747877a491ed3ccff9e` / `analysisrun_4bc1a8249bc240fe86aacbe93305c757` | `workflow_b886ffccaefc457eb3ab0955f6989554` / `job_c9482b6d77a64ccfbf6f86313bd67668` | edge endpoint type does not match its node |

Both worker processes returned JSON that passed the outer JSON Schema. The stronger typed model
correctly rejected the closed-reference or ontology mismatch. This is fail-closed behavior, not a
transport, authentication, timeout, or missing-page failure.

## Mandatory recovery boundary

Do not mutate or retry the running V12 batch. Let `CONTINUE_AND_COLLECT` drain every suffix range to
a terminal state. Afterward, recovery requires a separately reviewed and explicitly authorized
continuation:

1. read all 495 logical ranges and their terminal states from the authoritative database;
2. reconstruct the complete manifest and require the exact full topology hash above;
3. require all ten source revisions, analysis manifests, rights attestations, preset, and policy
   pointers to remain exact, current where required, approved, and SHA-matching;
4. use `REUSE_ACCEPTED` with the exact immutable accepted run ID for every successful range;
5. use `EXECUTE` only for each failed range and pin its failed analysis run as predecessor;
6. require unique range/run pointers, zero gaps, zero overlaps, and exactly 1,702 pages;
7. persist one new idempotency key, one authorization marker, and one submission-attempt marker;
8. forbid automatic retry and stop again if any replacement execution fails; and
9. publish no full textbook Graph until the successor proves 495/495 accepted coverage.

This procedure preserves completed work by pointer rather than copying artifacts. It also prevents
a failed range from being silently omitted, marked successful, or replaced by an implicit latest
revision.
