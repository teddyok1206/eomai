# ADR 0201: Explicit native1.1 adapter source-initialized comparison

## Status

Implemented and source-verified, 2026-10-05 UTC. No live experiment, installation,
production activation or image-quality approval follows from source tests.

## Decision and required design procedure

1. Responsibility: extend the existing source-initialized Canny comparison contract,
   metadata admission and paired executor, not a second worker or inference framework.
2. Canonical source: frozen reviewed TRAIN spatial command/result and reference PNGs,
   exact native training command/result/adapter manifest and original authorization.
3. Identity: add explicit reference command/result1.2; predecessor1.0/1.1 bytes and
   logical/revision/hash identities remain immutable. New input/version yields a new run.
4. Pointers: new reference1.2 pins evaluation-command1.4, whose version map is native
   training-command1.1/result1.0/manifest1.0. Resolve existence/lifecycle/permission/
   schema/media/canonical bytes/hash and complete training closure before binary reads.
5. Access: closed wire/model lookup, indexed metadata resolution, ordered bounded
   paired cases, map/set identity and membership checks. No implicit latest or fallback.
6. Structures: immutable protocol lookup and existing frozen source DTOs/manifests;
   O(metadata bytes + case count), at most3 reference cases/6 generated outputs.
   Existing caps, DB/index/cache/queue/storage layout and dependencies are unchanged.
7. Transaction/concurrency: existing Orchestrator staged command owner, physical GPU
   lease, artifact commit/idempotency and no-write terminal receipt replay. Workers
   read only staged local inputs and never communicate directly or publish NAS.
8. Dependency direction: contracts own the wire/provenance rule; application and
   provider adapters consume it. No domain-to-infrastructure import or new privilege.
9. Failure: crossed command/result/evaluation families, missing/stale/hash/permission,
   corrupt source/adapter and invalid geometry provenance fail before weights/models.
   Preserve failed/partial receipts; unknown execution is not a reason to resubmit.
10. Retry: exact same command replays terminal receipt without transforms, generation,
    GPU acquisition or writes. New training revision requires a new immutable identity.
11. Simpler alternative: run old reference1.1 or alias training1.1 into training1.0.
    Insufficient: the former cannot consume reviewed exterior targets, the latter
    changes released semantics. One explicit successor through existing ownership is
    smaller than a parallel evaluator or a new generic registry/framework.

## Numerical and quality boundaries

Evaluation-command1.4 supplies pinned native adapter lineage only; its diagnostic
generations are not executed by the reference consumer. Its declared case/caption/
canvas/negative provenance must nevertheless validate. Reference pair retains the
spatial predecessor's exact prompts, seed, Canny controller and control parameters,
832x512 initializer, strength0.35, scheduler/effective steps and resource bounds.
Adapter substitution is the intended independent variable; old weights must never
be silently loaded. Result1.2 binds the exact evaluation and adapter manifest hashes.

This is still REVIEWED_TRAIN_REFERENCE_NOT_HOLDOUT with quality NOT_REVIEWED and
activation FORBIDDEN. It does not implement native reserved validation or independent
blind review, enlarge the dataset, permit another exhausted12-target40/200 experiment,
or establish production quality. Those full-goal gates remain open.

## Source acceptance

JSON Schema2020-12 first, matching frozen models and one authoritative closed codec;
preserve predecessor hashes. Tests must cover schema/model agreement, exact1.4 pin,
native1.1 metadata admission before binaries, inherited cases/numerics, immutable
hash/revision binding, crossed result family rejection, failed/partial replay with
zero side effects, supported CLI/staging/publication, packaged schema equality and
release-wheel closure. Ruff/type/focused tests precede core commit. Installed actual
role and any GPU execution remain separate evidence, not claims inferred from tests.

## Source implementation checkpoint

The schema-first successor now uses the existing metadata admission, command publisher,
workspace/CLI and paired executor. A closed immutable three-family codec owns evaluation
pins, command/result parsing and exact result-family selection. Native1.1 weights alone
are staged; geometry case/caption/canvas/negative provenance validates before binaries.
No backend, numerical policy, dependency, DB, service, privilege or activation change.

Combined focused regression **366 PASS**, including31 new successor tests (earlier29
and predecessor79 runs overlap, not additional unique tests). Full dependency audit
**5 PASS/1 pre-existing failure**: Catalog expansion/pilot imports from
`source_page_crop_expansion_inputs.py`. Preserve this failure; not whole-repository PASS.
Strict mypy4 modules passed with both Python3.12 and Python3.11 targets, using the image
test interpreter for Pillow typing. Initial API-only type invocation lacked Pillow;
correct interpreter selection fixed the invocation without ignoring missing imports.
Ruff/format5 files, release-script shell syntax and diff checks PASS. Image test inventory
includes the new suite. Released four reference schema hashes remain unchanged.

Source-only tests use synthetic inputs/backends and do not establish model quality.
Release wheel closure/source-free checks are next; lab installation, actual worker-role
execution and a bounded native1.1 trained adapter comparison are not yet recorded.
The60 distinct prepared target IDs do not become accepted by this consumer change.
