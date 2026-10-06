# ADR0209: One bounded native contour-loss learning hypothesis

Status: IMPLEMENTED IN SOURCE; NOT INSTALLED OR TRAINED. 2026-10-06 UTC.

## Evidence and decision

[ADR0208](0208-installed-native-lora-loading-parity.md) establishes actual LoRA
loading/scaling and paired TRAIN noise-prediction response, not a runtime defect.
The adapter improves all measured regions, but dark-source cells improve less
than nearwhite cells, most weakly on the toned car. Whitespace does not dominate
the measured loss. More steps, harder binarization, caption rewrites or another
control-strength sweep are not justified by that result.

Test exactly one learning hypothesis: gently emphasize cells containing existing
dark source pixels while preserving all tone, fine hatching, labels and native
geometry. This is an experimental objective change, not a bug fix or a guarantee
that dark pixels are semantic outlines. It can overweight original text or
hatching too; evaluation must detect that risk.

## Short design and implementation order

1. Responsibility/boundary: existing native LoRA experiment contracts,
   Orchestrator admission/staging and isolated trainer. No new service, queue,
   registry, worker-to-worker traffic or NAS-writing worker.
2. Canonical source: the unchanged100-target training1.2 command pinned in
   ADR0208 and the actual registered source PNG revisions. Use the same exact
   TRAIN memberships, captions, dimensions, exposure schedule4:2:4, seed and
   existing800-step recipe. Do not overwrite old command/adapter identities.
3. Identity/revision: add an explicit successor native training command only
   because the objective meaning changes. JSON Schema2020-12 before its frozen
   Pydantic value/model and numerical behavior. Existing1.0–1.2 schemas/bytes/
   dispatch meaning remain unchanged; no broad `isinstance` fallback.
4. Pointers/resolution: new command pins old canonical source metadata and
   operation evidence, base stack and target revisions/hash/media/permissions/
   lifecycle. Existing source closure validation and bounded staging remain
   mandatory before tensors/GPU. New adapter records the exact successor command.
   Extend output schemas only if their frozen predecessor cannot represent it.
5. Access/structures: keyed sample/target lookup, immutable ordered sample tuple,
   existing deterministic exposure schedule, single linear source-cell pass.
   Each8x8 source cell is dark-containing when any luminance<96. Keep other
   cells, including gray and white. No segmentation/model/semantic relabeling.
6. Complexity/scale: O(total native input pixels) preprocessing, O(latent cells)
   cached scalar weights,100 images. No repeated image parsing per training step
   or binary DB/cache aggregate; no new dependency or index needed.
7. Numerical rule: scalar cell weights2 for dark-containing,1 otherwise,
   broadcast across latent channels. Loss equals
   `sum(weight * squared_error) / sum(broadcast_weight)` in float32. Weights remain
   positive; loss is nonnegative, keeps every cell, and equals ordinary MSE when
   weights are uniform. Fixed bounded2:1 is the one change, not a sweep or an
   inverse-frequency rule. Do not turn source pixels into latent ground truth.
8. Transaction/concurrency: reuse current command idempotency, exact owner ledger
   before one dispatch, exclusive GPU lease, immutable result commit. No DB schema,
   direct row update or exposure schedule mutation. A timeout is observed under
   the same identity; unknown processing does not authorize a new training key.
9. Dependency/adapter: domain defines the frozen objective; numerical trainer
   owns RGB/luminance decoding and tensor reductions. CLI only constructs/validates
   commands. No domain filesystem/torch imports or inference-policy duplication.
10. Failure/retry: reject bad dimensions/weights, mismatched source hashes,
    nonfinite loss, invalid band geometry or runtime/version drift explicitly. Preserve
    failure artifacts; no automatic offload, auto-retry or extra steps. Objective
    cannot be enabled by ambient environment or silently affect earlier commands.
11. Simpler alternative: keep old uniform MSE and run longer. It is simpler but
    does not isolate the observed unequal regional response. Existing MSE is
    correct and retained; the experiment tests value, not required correctness.

## Verification and bounded acceptance

- Source tests first: schema/Pydantic agreement and frozen predecessors; uniform
  weight equivalence, known weighted arithmetic, normalization, empty-dark source,
  channel broadcast, determinism, finite gradients, dtype handling and rejection;
  command/hash/result lineage, duplicate dispatch and resource budgets.
- Build/verify/install only the required compatible isolated lab wheels. Preserve
  production provider/binding and existing installed rollback artifacts. Verify
  installed source/RECORD before one admitted training run. No production update.
- One new adapter, maximum800 steps, same frozen cohort/seed/optimizer/budget as
  the baseline; no checkpoint continuation, weight search or data edits. Freeze
  exact invocation/runtime/time-memory budget before dispatch. Record actual
  optimizer/model calls separately from later PNG generation.
- Reuse the source-band diagnostic on the new adapter as a new immutable
  diagnostic identity, against exactly the same original source/caption/noise/
  latent recipe. Do not present lower TRAIN loss as the final success gate.
- Before generation, pin one evaluation manifest for the existing four
  source-free geometry cases and one object-supported photo case. Budget five
  new LoRA outputs, zero new source acquisition; reuse compatible pinned BASE
  outputs rather than regenerate them. No choosing seeds/prompts after seeing
  results. Validate current adapters support exact successor lineage first.
- Own visual review compares structural contour decisiveness, halo/ghost strokes,
  legitimate controlled tone, scene/geometry fidelity and prompt intent. If darker
  text/hatching or halos increase without structural improvement, reject this
  hypothesis rather than pile on postprocessing. Prior failed images stay intact.
- Independent blind review and untouched document-level HOLDOUT remain required
  before any broader quality claim. Any later production use still requires
  successor Item Preview/HWPX canary plus activation/rollback gates.

## Source implementation and actual CPU verification

Native command1.3 adds a closed `loss_policy` value and an immutable
`objective_evidence` pointer to the completed operation review. JSON Schema was
defined first; its canonical and wheel-package copies are byte-equal, raw SHA
`4084b214375339f228053508cdac29f9cb25d073882b7a7c1906a3707a646c8d`.
Earlier command1.0–1.2 schema bytes/hashes/meanings are unchanged. No new result
schema is necessary: result/adapter1.0 already pin the exact command content hash
and profile, rather than implicitly naming an objective. Existing inference
protocols are not loosened to accept1.3 adapters; their successor evaluation
admission remains future work, before generating the candidate samples.

The existing metadata admission now requires and verifies the operation evidence
as well as its original canonical source closure. The owner resolver/stager and
isolated native CLI reuse their exact closed version dispatcher. No alternate
publication or worker protocol was added. Only parsed1.3 commands route the
explicit frozen loss value into the numerical recipe;1.2 retains uniform MSE.

`eom_image_trainer/native_contour_loss.py` owns decoded-luminance pooling and
float32 tensor accounting. The shared VAE input preparation decodes each PNG
once, uses unchanged RGB for the VAE, and derives Pillow-luminance weights from
that same decoded input only when1.3 asks for them. It returns a frozen encoded
input value; weights are cached once, never reparsed per micro-step. The old
`_latents` instrumentation interface still returns its original latent tuple.
Sample/latent/weight counts fail explicitly before optimizer construction if
inconsistent. Existing loss/gradient nonfinite and budget guards remain in force.

Tests cover schema/model/canonical/wheel agreement, strict closed policy values,
required/role/hash/duplicate evidence, exact result binding, immutable predecessor
samples and exposure schedule, explicit native routing and cached sample-weight
index use in the same800-update loop. That loop uses CPU fakes and is **not**
training evidence. Regression fixtures retain ordinary MSE and fail if the1.3
branch silently falls back to it.

`tests/integration/test_native_contour_loss_cpu.py` separately runs actual torch
arithmetic with CUDA initialization forbidden. Default source invocation skips
all10 tests before importing torch. Explicit developer CPU invocation with the
lab torch and source package paths executed **10 PASS** in1.069s: known weighted
loss/gradients, uniform-MSE equivalence, fp16 overflow avoidance/gradient agreement,
dark-threshold/cell order, retained gray/white and empty-dark inputs, invalid
shape/weights/dtype/gradient rejection. Models0, GPU0, institution image reads0,
optimizer0 and training0. This source CPU result is not an installed-wheel or
CUDA training acceptance. No new numerical dependency is required.

Broad native/micro/source/runner/checkpoint/geometry/photo-object-support regression
gate: **527 PASS,10 explicit CPU opt-in SKIP** in126.71s. Ruff lint/format,
strict mypy across six source/integration modules, shell syntax and diff checks
PASS. The type checker uses the explicit source-test interpreter for Pillow
resolution; using the API interpreter alone initially reported its absent Pillow
dependency, not a source defect. No suppression or dependency installation was
added to disguise that environment difference.

## Frozen build and real canonical metadata preflight

Source/release candidate `92fed3a86a6a2423b604170eb36993004b32f57f` is committed.
The immutable archive build/required-wheel-member inspection PASS; three outputs
in `/tmp/eom-image-trainer-build/92fed3a86a6a2423b604170eb36993004b32f57f.aToYaT/dist`:

| Component | Wheel SHA-256 |
|---|---|
| Contracts | `701ba948604ec687c4374a7a22440ea33573f600c33b4bbd0672a8591b18c637` |
| Provider | `10be9e8f4cbc8fa145ce357236bc9af7449dd73d5fe6f8ac4555497083de924f` |
| Trainer | `b59416ef059e7ad88e2c6d79be1a72b346d0fb4c287596c7ba222792654107cc` |

This is BUILD_ONLY: no claim of newly installed wheel RECORD/runtime acceptance.
The final-source actual CPU test run also passed10/10 in1.047s, separately from
the first1.069s development run. Neither CPU invocation loads models or trains.

At2026-10-06T10:28:44.952417UTC the real owner admitted native TRAIN100 across
66 PDF documents/55 exam groups/eight prepared target batches. It re-resolved the
old full source closure and the new objective receipt,42 metadata members/579,444
bytes. All original target pointers/pixels/conditioning/seed/exposure/optimizer/
dependency/budget/base-stack/screening fields remained equal to the1.2 command.
PNG reads0, models0, training dispatch0, HOLDOUT0. The exact prepared identity is
`imgsdxlnativetrainrun_c9bad421f3c0e65a81f01e7df4f2bf76`, semantic command SHA
`5d51baeb901a90ccf5bf35dc9d33ca44f49b9d4d066486b8f3279fd7b7626a35`.

Initial archive listing was unsorted and the authoritative file-set validator
rejected it in pure `_request` **before** publication lock/job/staging. This was
an operator manifest-order error, not a source/trainer defect; the correct guard
was not changed. The exact prepared command/run/hash/timestamp was retained.
A separate finish operator revalidated that same source closure and published
the sorted file-set, including the original failed operator/log. No new command
identity, training retry, direct DB row change or failed-history success rewrite.

Canonical eight members/147,003bytes committed and re-resolved equal:
`artifact_8c7a653efe0e446e8d5e904aa6941162` /
`rev_2398f9eb27d6436eb534e1cf08181164`,
`manifests/sdxl-native-lora-command.json`,
schema `eom://schemas/image-provider/local-image-sdxl-native-lora-command/1.3`,
raw SHA `fdf230a6f836c16094f3c0cfb602b3e68b5c2743e3df3bb80fccdc21c00f47d0`.
Publication receipt:
`/tmp/eom-native-contour-preflight-20261006/publication.json`.
No PNG/weights/source PDFs copied to this evidence artifact.

Next: verify required compatible wheels and rollback, install only the isolated
lab environment, validate installed1.3 capability and actual numerical inputs,
then stage/dispatch the **same pinned** prepared training command once. Existing
production binding is unchanged, five services ACTIVE, GPU idle2MiB/0%. Laboratory
installation/capability is still PENDING, not READY; there is no live training unit
to wait on. No weighted training or new generated sample yet. Goal remains
ACTIVE/NOT_ACCEPTED, including independent blind/HOLDOUT/Item-HWPX gates.
