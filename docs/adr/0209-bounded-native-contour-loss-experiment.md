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

Next: freeze a release commit, build/verify the
compatible isolated lab wheels, and perform canonical full-cohort metadata
preflight before any training dispatch. Preserve old installed artifacts and
production binding. There has been no weighted-loss training or new generated
sample for this ADR; full goal/quality gates remain ACTIVE/NOT_ACCEPTED.
