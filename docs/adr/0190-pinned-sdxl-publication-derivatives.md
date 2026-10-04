# ADR 0190: Evaluate pinned publication derivatives without rewriting SDXL history

Date: 2026-10-04 UTC

Status: source implementation verified. Command/result schemas, metadata-only
admission, CPU worker and exclusive handoff are implemented. Installed lab execution and
canonical derivative publication remain PENDING; this is not quality acceptance.

## Why this boundary is next

Three strengths and one negative-clause control do not yield acceptable native
SDXL outputs. Stop that numerical/prompt sweep. The approved research plan already
includes V7 monochrome cleanup and deterministic scientific overlays after local
generation. Native-model quality and that complete publication output must be
measured separately. Neither deleting rejected history nor repainting it into an
apparent PASS is acceptable.

A read-only Orchestrator diagnostic used the initial three-case/two-arm canonical
result, source `c2e34752`, the existing installed pure `assessment_line_art_v2`
function and Pillow 11.3.0. All six computations satisfy its fixed bounds. No PNG
was written, model loaded, GPU lease acquired or historical byte changed.
Only tones 96/255 remain in each computed derivative; usable strokes and retained
scientific details are NOT_EVALUATED. This is viability, not quality acceptance.

## Design decision for the next implementation

1. Responsibility/boundary: extend the existing isolated image provider with one
   closed CPU publication-evaluation use case. Reuse its line-art function and
   filesystem handoff; do not introduce another inference/training framework.
   Orchestrator alone resolves, stages, validates and commits derived Artifacts.
2. Canonical source: exact successful target-comparison command and result
   Artifact revisions. Keep raw RGB, native grayscale, conditioning images,
   previous source admissions and rejected judgments unchanged. A copied view
   is never the source. The frozen V7 policy is a small immutable typed value.
3. Identity/revisions: new evaluation run identity and new Artifact revision;
   retained case/arm/seed identify ordered source outputs. Source logical case,
   source Artifact/revision, raw SHA, policy SHA, derivative SHA and result
   semantic SHA are distinct. Do not update an old generated member in place.
4. Pointers/resolution: pin command/result JSON members and derive each PNG
   pointer from the validated receipt, not operator-supplied arbitrary paths.
   Check existence, access, lifecycle, schema/media/raw SHA, matching command
   semantic hash, successful complete coverage and UTC chronology before pixels.
   Staged PNGs must equal those exact source members and be 800x500 grayscale.
5. Access patterns: one indexed metadata batch, keyed case/output lookup,
   immutable ordered BASE/LORA iteration, one bounded pixel batch and terminal
   replay. No repeated whole-corpus scans or per-image lineage traversal.
6. Structures/indexes: maps/sets for identity/coverage/duplicate validation;
   frozen tuples and a typed manifest for at most six outputs. Existing indexed
   Artifact store and file-set publisher; no table, queue, cache or new index.
7. Complexity/scale: O(n + total source bytes), bounded n<=6 and each input PNG
   by the existing image-read cap. Connected-component cleanup is O(W*H) at
   800x500. Stage six admitted inputs once; do not copy weights, datasets,
   source PDFs, original conditions or raw RGB into the derivative Artifact.
8. Transaction/concurrency: exclusive private workspace, root-owned read-only
   inputs, worker-owned candidates and one terminal receipt. CPU execution does
   not acquire GPU. Existing Orchestrator publication/idempotency owns the commit;
   only complete validated output can be registered as successful computation.
9. Dependency/ownership: schema and frozen models in image contracts; provider
   owns the pure cleanup/CPU adapter, Orchestrator its application use case and
   resolver/publisher. Domain models import no SQL/NAS/process/image provider.
   No new numerical dependency, external API or operating provider activation.
10. Failure/retry: preserve partial prefix and stable cleanup errors; never report
    a failed derivative as accepted. A receipt-less candidate or stale/hash/
    schema mismatch fails closed. Exact replay checks command, source and every
    derivative PNG without running transforms or writing files. Query/replay an
    uncertain execution rather than dispatching a new identity. Pin the policy
    and one six-output CPU quota before execution; no threshold/seed search.
11. Simpler alternative: editing the 72 rejected outputs, pretending their native
    receipts include cleanup, or applying unrecorded presentation whitening loses
    provenance and can conceal missing roots/leaves/light marks. Reusing the
    current pure function behind one explicit derived-output contract preserves
    history without creating a second model pipeline.

## Implementation and acceptance order

1. Define JSON Schema 2020-12 and frozen Pydantic command/result before worker
   behavior. Reuse the existing postprocess/2.0 policy/metrics/runtime values.
   Declare evaluation-only TRAIN scope, activation FORBIDDEN and unreviewed
   publication candidates. A technical result cannot assert semantic/visual PASS.
2. Add focused tests for missing/stale/hash/media/schema/permission pointers,
   wrong parent command/revision, incomplete/reordered source coverage, changed
   policy, duplicate members, secure staging, CPU-only operation, deterministic
   manifests, partial failure, exact transform-free replay and wheel resources.
   Keep the separate pre-existing dependency-boundary failure visible.
3. Build/install only the compatible isolated lab set if needed. Freeze source,
   policy, input hashes, no-model/no-training budget, Pillow and rollback before
   the one supported six-output CPU execution. No production service restart.
4. Register distinct derivative PNGs and verify committed bytes. Directly inspect
   source target, native output and derived output at original resolution. Check
   complete object count, flower/leaves/roots, wheels/light marks, cropping and
   missing/fused contours; white background alone is insufficient. Record gray
   versus black strokes and stroke readability rather than ignoring tone 96.
5. Compare raw-model and publication decisions separately. Do not relabel the
   72 native REJECTED images. Independent blind review and held-out admission
   remain separate required goal gates. Only a quality-passing candidate can
   enter the successor Item Preview/HWPX and activation/rollback gate.

If fixed cleanup cannot retain the required composition/details, stop tuning this
derivative. Then select one bounded structural-conditioning alternative from the
existing research plan, with its own reviewed model/license/hash/resource pins
before acquisition or implementation. No new weights are acquired by this ADR.

Evidence and exact diagnostic hashes are in the
[improvement plan](../operations/IMAGE_STYLE_IMPROVEMENT_PLAN_2026-10-03.md).

## Source implementation

The new `local-image-sdxl-publication-comparison-{command,result}/1.0` resources
were defined before the CPU worker. The full existing target metadata admission
is shared by both use cases; only the six native PNGs are staged for this one.
No training targets, conditioning images or adapter weights cross the derivative
workspace boundary. Existing released schemas/receipts are unchanged.

`postprocess/2.0` policy bounds have one contract-owned typed validation rule.
The provider maps its explicit violation code to the existing cleanup errors;
it does not parse human error text. Pixel transformation and frozen settings are
unchanged. Terminal replay validates receipt, complete source lineage, hashes,
RGB grayscale tones, pinned runtime and exact output membership without a
transform. Unsafe links, writable inputs, unreceipted outputs, partial failure
and ambiguous submission remain errors, never reasons to create another run.

The fixed CPU-only oneshot unit has no GPU/model argument or automatic restart.
It blocks NAS, repositories, credentials and model stores. It does not create a
new scheduler, queue, DB schema, dependency or production activation path.

Source gate: 242 focused/regression tests PASS, one explicitly excluded pre-existing
Catalog import-boundary violation; strict mypy on 13 core files, formatter/linter,
shell syntax and systemd template verification PASS. No live derivative was
executed by these synthetic tests.
