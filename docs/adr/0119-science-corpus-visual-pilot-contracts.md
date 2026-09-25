# ADR 0119: Science-corpus visual pilot contracts

- Status: Accepted for bounded implementation
- Date: 2026-09-25 UTC
- Scope: fewer-than-100-source visual-pattern and SSD-1B feasibility pilot

## Responsibility and boundary

Catalog resolves the published science corpus and exact Content Intake PDF members. The
Orchestrator validates those pointers, materializes a bounded workspace, invokes an isolated
PDF/image worker, and alone commits the validated output file set to NAS. The worker cannot query
PostgreSQL or NAS and cannot publish an Artifact. The production image provider remains
inference-only; GPU training remains isolated and mutually exclusive with inference.

The contracts added by this decision cover only authorization, deterministic source selection,
page/crop discovery, and reviewed pattern classification. They do not activate an adapter or a new
renderer rule.

## Canonical source and revision model

The canonical input is the immutable `science-assessment-web-corpus-manifest/2.0` Artifact member.
It pins each PDF through a Content Intake logical Artifact, immutable Artifact Revision, member
path, media type, schema, and file SHA-256. Its semantic manifest, acquisition, metadata resolution,
and resolution-policy hashes remain separate values.

```text
science corpus Artifact Revision
  -> internal visual-training authorization revision
  -> visual pilot plan revision (12..96 selected PDFs)
  -> page/crop result Artifact Revision
  -> human-reviewed visual-pattern inventory revision
     ├─ bounded LoRA micro-probe successor
     └─ typed Python/SVG renderer-rule successor
```

Generated page images and crops are workspace materializations until the Orchestrator commits the
validated result. A storage path is not identity. PDF bytes, PNG bytes, and adapter bytes never enter
PostgreSQL.

## Pointers and resolution checks

Every Artifact member pointer is checked for logical and revision existence, approved lifecycle,
exact member existence, schema, media type, declared SHA-256, manifest membership, regular-file
identity, size bound, and stable bytes. The plan rejects implicit latest revisions, duplicate
documents, duplicate PDF hashes, source members that do not end in the document hash, and corpus or
authorization drift.

The authorization records the user's explicit approval of the validated internal exam-material
corpus for deterministic pattern analysis and internal SSD-1B LoRA training. Public availability is
not represented as public-domain status. Raw-source export is forbidden and the only model
derivative is an internal LoRA adapter.

## Access patterns and data structures

Dominant operations are exact pointer lookup, deterministic stratified selection, ordered page
iteration, candidate membership/deduplication, partition grouping, and pattern aggregation.

- one map keyed by document ID and one set of PDF hashes provide `O(1)` expected lookup and
  uniqueness;
- strata are keyed by `(subject_family, issuer_type)` and hold stable SHA-256-ranked tuples;
- train, validation, and holdout membership is grouped by an exam identity hash before selection;
- page/candidate output is a tuple sorted by document, physical page, and box/identity;
- primitive support counts are computed in `O(v)` time and `O(k)` space for `v <= 512` candidates
  and a bounded pattern-key set;
- no new DB table or index is required because canonical state is an immutable Artifact file set and
  existing primary-key/revision indexes resolve its pointers.

The pilot selects at most 96 PDFs, renders at most 384 pages, emits at most 512 candidate crops, and
permits at most 96 reviewed LoRA crops. The first execution intentionally uses a smaller target.

## Guidance and rendering authority

The plan pins, rather than rewrites, all three existing authorities:

1. the integrated-science authoring team-lead guidance;
2. the HWP question-editor handoff guidance; and
3. the KICE illustration guide.

The reviewed inventory may recommend a Python/SVG primitive only when at least two observations
support it. Labels, values, axes, arrows, plots, tables, apparatus state, and other answer-bearing
geometry remain authoritative deterministic content. LoRA candidates are limited to reviewed
non-authoritative raster style such as organisms, fossils, natural/geologic/astronomical scenes, and
textures. A candidate marked unknown cannot enter training.

## Transaction, concurrency, retry, and idempotency

The plan identity is the canonical hash of the corpus and authorization pointers, exact selected
sources and partitions, limits, tool hashes, guidance hashes, and creation metadata. Same key with a
different plan is a conflict. Each worker attempt writes only into a fresh local workspace. Failed
results remain failed; a new attempt reuses the immutable plan but receives a separate attempt
identity. The Orchestrator validates all result members and commits metadata and the terminal event
in the existing transaction boundary.

Source selection and page rendering may use bounded parallelism, but output ordering is canonical.
Selection is deterministic and never samples an implicit current corpus. A publication retry must
resolve the same pinned revisions and hashes.

## Failure and rollback

Missing/stale pointers, schema/media/hash mismatch, page-render failure, unsafe member paths,
candidate overrun, result-hash mismatch, partition leakage, or unauthorized candidate use fails
closed with a stable code. Partial worker files remain noncanonical and are removed with the
workspace. Existing corpus, production provider binding, adapters, Content Packs, prompts, and
renderer rules are unchanged, so rollback is omission of the new pilot Artifact or selection of the
previous binding/rule.

## Simpler alternative rejected

Reusing the item-revision crop contract would require invented `itemrev_` and assessment-anchor
identities for raw PDFs and would make a page document appear to be an approved item. Training from
whole pages would include item text, answers, publisher marks, and answer-bearing geometry. A single
untyped script would also lose revision, authorization, and partition provenance. The additive
contracts are the smallest honest boundary that can feed both the existing LoRA evaluation loop and
the deterministic renderer improvement loop.
