# Science examination illustration improvement plan

This plan implements the user's approved local illustration-quality goal. Reference images supply
object shape and composition; LoRA supplies examination-style strokes and restrained tones.
Scientific labels, axes, units and exact geometry remain Python/SVG/native HWPX responsibilities.
Success requires semantic accuracy as well as style, not merely passing edge-density measurements.

## Verified baseline and limits

TRAIN-only follow-up freeze, **2026-10-04 22:20 UTC**: test the existing reviewed
target cohort's **10 CLEAN_CONTOUR targets** separately from its23 restrained-tone
and5 fine-hatching targets. This is a small diagnostic hypothesis, not a proven
cause of earlier weak style transfer or an independent quality acceptance. The
existing closed command/result1.1, exact target captions/PNG revisions, trainer,
GPU lock and Orchestrator handoff already support a selected subset; no successor
schema, backend modification, model download, service change or DB migration is
needed. Keep all38 earlier inputs and their adapter immutable.

Freeze at most **one fresh 200-step run**, rank/alpha8, learning rate1e-4, batch1,
accumulation4, seed20261004, 768×512 exact prepared RGB, maximum3,600,000ms and
16GiB allocated GPU memory. It starts from the same pinned BASE, not from the
38-target adapter. Exactly800 micro-samples means80 exposures per selected image,
versus approximately21 in the38-target pilot; dataset size/exposure and expression
mix therefore change together. This is **not a controlled claim that expression
mix alone explains quality**. Six of the ten targets depict people; this is a
limited contour-style track, not comprehensive object/family coverage.

Before dispatch, re-admit canonical source/target/authorization lineage, freeze the
exact10-target command, stage only those TRAIN PNGs, and visually inspect their
hashed contact sheet. Any new target defect is excluded before GPU execution and
reported without changing historical review bytes. Selected immutable targets and
the two used preparation batches are pinned in the command; no duplicate dataset
Artifact/PNG copies are published. Source-contact views are diagnostic materialization,
not newly generated images. Existing VALIDATION28 outputs and source QA correction,
spent TRAIN fallback budgets, and unopened HOLDOUT pixels remain unchanged.

New model inference allowance in this training checkpoint is **0**. A comparison
must be frozen separately against the actual resulting adapter, with explicit
matched inputs, usage budget and limitations; a training loss is not a style gate.
Terminal publication/replay must verify exact staged target bytes and the adapter,
with no new training on replay. Production V6 and Item/HWPX activation stay forbidden.

Latest checkpoint, **2026-10-04 21:59 UTC**: the frozen reserved comparison is now
executed, validated, published and own-screened. Command bytes/source/cases/seed
were unchanged. Numerical worker source `41b5fed146c192778ffc20d2c68978917064ea25`
produced **28 BASE/LORA outputs /14 VALIDATION cases /7 groups**, in **56,790ms**
with measured peak GPU memory **10,763,590,656 bytes** (~10.02GiB), RTX5080.
Raw RGB and800×500 grayscale publication outputs are separately hashed. There
were no TRAIN-reference/HOLDOUT binary reads, new training, sweeps, GPU retries,
new model downloads, migrations, production activation or service restarts.

Lab-only verifier source `8ad0f72b6bb1e30fc1246d99321c2b887d3d2c52` keeps the
trainer DB-free and uses the fixed CPU-only installed `eom-image` adapter. Exact
source-fit RGB/Canny/publication transforms passed under pinned numerical versions;
Orchestrator readmitted canonical command/source/adapter lineage before publication.
All **85 result members** resolved byte-for-byte. Result:

- `artifact_ea415733085d4f01a1d8afa2e6d9edcd` /
  `rev_e0f257881d83416584965fba59c12b20`.
- Primary `manifests/sdxl-validation-comparison-result.json`, raw SHA
  `3397f78030c107ccc9599f2fa182e78fed7db1a3fec4245f82a7d65dea198c31`;
  semantic SHA `91099c68ae1ffbe11572a635fe792cca77fe04b1b728ac011104234b0a61e6a8`.
- Actual installed-role terminal replay:128 files verified; model/GPU/transform/
  write counts all0. No regeneration followed the publication-environment failure.

Own inspection viewed all28 final outputs and14 source fits in three contact
sheets, four full-resolution triplets and one native RGB output; all28 native
rasters were measured. Broad pose/object arrangement and white canvas are preserved,
but this is **not independent or scientific-detail certification**. Median native
BASE/LORA mean absolute channel difference is1.0865 on the0–255 scale. Metallic
and plastic gradients and raster-soft source contours remain. This demonstrates
reference preservation, **not LoRA superiority, novel-photo conversion or institutional
indistinguishability**. Do not promote this candidate to production or Item/HWPX.

**Own source QA correction:** `WHEAT_SEEDLING_UPRIGHT` retains an isolated black
triangular/arrow-like remnant left of the stem, copied by both arms. Earlier clean
source QA missed it. Exclude this source from subsequent clean benchmarking until
an explicitly reviewed successor frame exists; do not erase pixels, alter old
review/Artifact bytes or rerun this batch to conceal the failure. The current batch
still honestly contains14 cases/28 outputs; subsequent provisional clean eligibility
is at most13 cases, and the source-family count is still3, not4.

Source regression359 PASS; unchanged-provider regression25 PASS; dependency5 PASS
with the same known predecessor test explicitly deselected. Strict mypy, Ruff,
shell/diff and full wheel RECORD/non-editable imports passed. Both lab installations
retained numerical dependencies and the trainer; rollback wheels and hashes are
recorded. Production V6 binding remains
`f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`; all five primary
services remain active. Git pushes0; production deployments0 in this checkpoint.

Twenty-four text evidence records and three diagnostic contact sheets were committed
and all27 resolved byte-for-byte as `artifact_b3f7c596cac0467196fa412946bfa6f2` /
`rev_a1366262e5774effaaeb14a48b8ac2d2`. Primary `reports/own-reserved-review.json`,
raw SHA `d06645ddcc305ab51e164e2c8c7d3f78d8a3fa43f2854d4e6f75263e4cf50dd9`.
The binary contact-sheet value schema is
`eom://schemas/operations/image-comparison-contact-sheet/1.0`: bounded single-frame
RGB PNG, width1200, at most4million pixels, diagnostic labels only. These composed
views are not Item visuals or another copy of canonical source/model binaries.
Temporary user views are in `/tmp/eom-image-validation-execution-samples-20261004/`;
their canonical counterparts are the evidence revision's `views/contact-01..03.png`.

Next: use this evidence to freeze **TRAIN-only** target/style/resolution improvement
and missing-fourth-family source work separately. No more generation on the frozen
VALIDATION batch, no automatic parameter sweep, no validation-to-training leakage.
Full training/four-arm study, independent blind review and accepted Item Preview/HWPX
canary remain unfinished; **goal stays ACTIVE**. Human visual-review links are saved
for the user's consolidated later review, not treated as already approved.

Previous checkpoint, **2026-10-04 21:48 UTC**: installed numerical source
`41b5fed146c192778ffc20d2c68978917064ea25` completed the frozen14-case reserved batch:
**28 outputs**, result semantic SHA
`91099c68ae1ffbe11572a635fe792cca77fe04b1b728ac011104234b0a61e6a8`.
An actual installed-role replay verified128 files with zero model calls, GPU leases,
transforms or writes. The command Artifact is `artifact_abb45f7583c74f53ac35b0f8ff7f050f` /
`rev_62f51c1614774d00a76eaba61f1f820c`; its previously frozen bytes/hash/identity are
unchanged. No new TRAIN/HOLDOUT binary reads, training, sweep or production activation.

Two operator/environment failures are preserved: a protected-reader rejection of a
group-writable repository unit before command/workspace/dispatch mutation (caller now
compares the installed unit to immutable Git bytes), and SQLAlchemy missing in the
deliberately DB-free trainer interpreter before result publication. No dependency was
installed to bypass isolation. Publication now uses a fixed CPU-only installed worker
subprocess for exact transform verification and the Orchestrator environment for
canonical admission/commit. Revised source regression359 PASS, dependency5 PASS /
1 known explicit deselection, strict mypy and Ruff/diff checks PASS. CPU-verifier
installation, canonical result publication and own quality inspection are pending.

Previous source checkpoint, **2026-10-04 21:35 UTC**: the reserved numerical worker,
existing fixed service handoff and Orchestrator-owned publication adapter are now
implemented. Historical768×512 source admission remains strict; native reserved
cropping uses the separately declared fit policy, shared Canny/white initializer
geometry and one paired GPU lifecycle. Terminal replay verifies exact result,
initializer, conditioning and raw/final member closure without another transform,
model load or GPU call. Publication readmits the registered canonical command and
all original inputs before verifying the exact transforms and calling the existing
idempotent Artifact publisher. No new queue, service, dependency or migration.

Source tests: **353 PASS**, dependency tests5 PASS /1 known explicit deselection,
strict mypy8 source files, Ruff format/check, shell syntax and diff PASS. The first
simulated19-test suite had14 failures caused by future fixture timestamps; the test
clock was corrected and production future-input rejection strengthened. This is
not a live GPU failure or an altered source contract. Full terminal logs were not
captured; these are terminal outcome summaries. Actual numerical installation,
28 generated outputs, canonical result and own review are still pending at this
source checkpoint. One frozen14-case batch only; no TRAIN fallback or sweep.

Previous checkpoint, **2026-10-04 21:12 UTC**: the explicit reserved VALIDATION
command/result `1.0`, Pydantic identities/result-prefix checks and metadata-first
Orchestrator admission are implemented at source `0d634a987bcf4488d08a598e1e8b2adf80ceeb6b`.
[ADR 0193](../adr/0193-reserved-validation-spatial-comparison.md) distinguishes the
historical TRAIN command as numerical configuration only, not case authority. It
permits 12–16 uniquely pinned reserved cases, one previously frozen seed and at most
32 BASE/LORA outputs; source and experiment membership are not retroactively changed.
It does not relax the independent blind review's minimum-four-family requirement.

Actual canonical read-only admission passed for **14 VALIDATION cases /7 PDFs /7
exam groups**, with27 bounded metadata members,42 distinct canonical pointers and
212 guarded read/read-only SQL statements (140 canonical member read calls). The
frozen local candidate is `imgsdxlvalcmprun_b6ed90bf72715028a0c3071a8b9d7238`, semantic
command SHA `0045b3e388ca1342b7986b1c5e8dc0640faeef79b36507d2ed05ed36e4967c4f`;
its local canonical JSON raw SHA is
`f2635417653066571bba390404f1c4468a9b1c294e469c749363e47df366d7c9`.
Expected pair coverage is28 outputs, not32 fabricated results. PNG/PDF/adapter bytes,
HOLDOUT pixels, training and GPU executions were all0 in this admission. No actual
worker workspace or canonical execution command was submitted.

New and predecessor source regression **334 PASS** (including36 new tests), dependency
regression **5 PASS /1 known explicitly deselected test**, strict mypy four changed
files, Ruff format/check, shell syntax and diff checks passed. The existing Catalog
infrastructure-import violation was not fixed or silently classified as PASS.
All three candidate wheels were built; their complete RECORDs passed (216/43/29
members). A non-editable ZIP import validated173 schema resources and the actual
14-case command without Torch. Candidate wheel directory:
`/tmp/eom-image-trainer-build/0d634a987bcf4488d08a598e1e8b2adf80ceeb6b.ww7EwN/dist`.
These packages are **not installed** in production or the numerical worker.

Ten text-only evidence records were committed and resolved byte-for-byte:
`artifact_ee358570a7594ea3a8e6f6c77ea30707` /
`rev_faba831e64c14f33aa596542736b22cb`, primary
`reports/actual-reserved-preflight.json`, raw SHA
`6566c63de0fd61d3ec2d35e4703d311c118490a2ebdd4943b9f64bc13307f65e`.
The archive includes development fixture failures, private publisher-invocation
errors and a safe-reader permission refusal; all occurred before publication and
the caller was corrected without weakening the supported publisher. Original
source/model PNGs and bytes were not duplicated. Full pytest logs were not captured;
the terminal outcome is recorded explicitly as a summary, not mislabeled a full log.

**Numerical worker / fixed handoff / result publisher / actual reserved GPU comparison
remain NOT_IMPLEMENTED or NOT_EXECUTED.** Next is to implement those boundaries using
the admitted original sources, native-dimension fit and existing offline numerical/
GPU-lease/pair/replay machinery, then one bounded matched batch. No TRAIN fallback,
parameter sweep, implicit schema relabeling or automatic activation. Production V6
binding SHA remains `f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`;
all five primary services were active. Full training, four-arm comparison, independent
blind review and Item Preview/HWPX canary remain unfinished. Goal stays ACTIVE.

Previous checkpoint, **2026-10-04 20:27 UTC**: the four historical VALIDATION crops
were audited against their four original pages from three PDFs. Exact canonical
bytes were admitted and staged read-only (2,070,513 bytes;30 guarded read/read-only
statements). All four are **not selected for the new clean-reference benchmark**:
the plant has a stray remnant, the pulling person's head/upper torso was partly
erased, and both apparatus crops retain label/leader residue. This finding is
limited to those four crops, not a retrospective rejection of all TRAIN targets.
Their historical approval, identities, partitions and artifact bytes are unchanged.

Two explicitly frozen discovery windows added **five previously unseen eligible
exam groups/pages** and **twenty previously unseen pages**; the latter are not
twenty new independent groups. Additional original bytes were2,999,812 +10,743,675.
Across the first discovery, historical-page audit and these two windows there are
**49 unique original pages /34 PDFs /27 exam groups**. All are VALIDATION; no
HOLDOUT pixels or new PDF downloads were read. Contact sheets are diagnostic
views, not canonical source images or proof of full-resolution inspection of
every page. Native pages needed for the selected frames were inspected directly.
The first second-window metadata preflight incorrectly required twelve newly
unseen groups and failed before creating a workspace or reading PNG bytes; the
discovery-only minimum was corrected without lowering any quality acceptance.

Thirteen literal V3 frames were processed by the existing fixed CPU adapter and
viewed individually. **Ten clean source derivatives** from six PDFs/groups passed
own source QA: a partial leafy stem, an intact rope-pulling person, two student
portraits, a wheat seedling, mineral-filled cart, drill-bit/rod group, metal-ingot
stack, boy holding a light cord and a hockey player. The first hockey frame retained
`B`; a separately pinned frame removed that label without erasing pixels. Both
goat frames were rejected: one retained a label/arrow and the tighter one clipped
the head. The three rejected frames and failure history are preserved, not
registered as eligible source targets. Some accepted native drawings are small;
registration does not prove suitability for every high-resolution style metric.

Supported Orchestrator publication committed the accepted10 once and verified
all12 canonical members, including exact equality to inspected PNG bytes:

- review `artifact_3be6832c1d0f4bb88d8e558dc75b7fb9` /
  `rev_9608f737b5384d6583eef5d0bc8ef621`, raw SHA
  `f3bc1e840213b0be6c4828cfd03c3b49cd7700c5d6452dd6f7219c946459acc3`;
- crop set `artifact_e1ad9a7c3fa04685b6e8d7cd00294b94` /
  `rev_a8c90dab545c4bba88fab0de3f5cd0c0`, raw SHA
  `122aecdd716c3409420d08a89bf3065596f863b3594476bfa8c9259449e9431e`.

Together with the previous four V3 source crops this gives **14 depictions /7
PDFs /7 exam groups /8 original pages**, not eighteen clean crops including the
four historical masked ones. Classification is honestly limited to
`LAB_APPARATUS`, `LIVING_ORGANISM` and `PHYSICAL_OBJECT`. No rock-filled cart is
relabelled a standalone natural specimen, and no isolated boy is relabelled a
complete real-world scene to pad the family count. An average-hash screen found
no pairs at distance<=6; that is not full visual duplicate clearance against
TRAIN/HOLDOUT. The existing minimum-four-family blind gate remains **NOT_MET**;
14 source crops alone do not constitute12 generated/grounded evaluation cases
or32 independent blind cases.

Thirty-three text-only QA/provenance/operator/failure records were committed and
all hashes resolved: `artifact_b48a6d1ea75e477d926ad0715d69f4b2` /
`rev_bfb719c20d5a4b9994dfd6482244894f`, primary `reports/own-source-review.json`,
raw SHA `fb8733d6f24a9162c95b467ae49b77b369a6930ac16e5097a5adb122d634f0a0`.
This references previous evidence and canonical PNGs rather than copying them.
The evidence safe-reader rejected two group-writable local stdout logs before
publication; their exact permissions were strengthened to600, and the failure
was retained. No protocol/worker/runtime code changed in this checkpoint; the
190-test source regression and candidate-wheel evidence below are historical
references, not falsely reported as rerun. Private operators passed formatter/
lint and real typed-admission/CPU/publication/hash checks.

New GPU outputs/training/HOLDOUT reads0; native total84 and exhausted TRAIN
fallback remain unchanged. Production V6 hash and all five active services were
checked unchanged. Full goal remains ACTIVE. Next: obtain the missing genuinely
appropriate source family and perform visual duplicate/cohort checks, then
implement the explicit reserved-source generation/evaluation successor. Never
relabel probe PNGs as Item semantic rasters, feed these VALIDATION crops into
TRAIN-only commands, or spend further TRAIN fallback. Novel-reference conversion,
LoRA advantage, full training/four-arm/32-case review and Item/Preview/HWPX
activation remain unproved/unperformed.

Previous checkpoint, **2026-10-04 19:46 UTC**: authoritative metadata inventory and
VALIDATION-only source curation are complete for this bounded window; full quality
goal remains ACTIVE. Original plus supplemental frozen lineage contains **270
distinct PDFs**: TRAIN180 / VALIDATION45 / HOLDOUT45, with 797/207/216 original
page pointers and 1508/356/440 raw candidate rows respectively. These rows are
not approved object crops. Original approved crop metadata remains16/4/4; latest
TRAIN micro-LoRA used38 reviewed targets from26 PDFs/25 exam groups. Metadata
inventory resolved36 unique pointers with94 guarded read/read-only-begin SQL
statements and no PNG/PDF reads. This is the admitted visual subset, not the entire
downloaded corpus or the 520-item GraphRAG denominator. Earlier108-source reports
below remain historical, not overwritten by the combined270-source scope.

Frozen discovery inspected **20 VALIDATION original pages**, 20 PDFs/exam groups,
10,841,059 bytes; HOLDOUT binary reads0. Twenty diagnostic contact-page views and
six native-resolution page views led to eight literal region proposals. Visible
people/cars/scenes can be absent from detector candidates, so the first legacy
parent-intersection preflight refused them before workspace creation/CPU cropping.
[ADR 0192](../adr/0192-reviewed-page-regions-without-detector-parent.md) adds review/
set `1.2` (V3) with an explicit `REVIEWED_ORIGINAL_PAGE` anchor, without fake parent
IDs or weakening V1/V2. Exact PDF/page/frame/hash/partition admission, shared CPU
crop adapter and Orchestrator publisher are reused. Source `fe6aa118`; regression
**190 PASS / one explicitly deselected unchanged infrastructure-import test**,
strict mypy5 source files PASS, Ruff/shell syntax/diff PASS. Three candidate wheels
have exact RECORD verification, zip-import/schema/Pydantic/canonical roundtrip PASS;
they were **not installed** into production or existing numerical worker runtimes.

Actual fixed CPU processing produced eight proposed crops from four VALIDATION
documents/groups. Own pixel inspection accepted four literal source derivatives
(bottle-blowing portrait, collapsed bag, distillation apparatus, separating funnel),
from **two documents/groups**, and rejected four contaminated/small frames. Exact
functional apparatus geometry remains code-owned; these are style references,
not generative scientific-topology approval. Accepted derivatives were published
once through the existing owner: crop set `artifact_e2265d33d84c45c59cc9f7857e6137b2`
/ `rev_d6049cf325e544f4be49725d2dbd8658`, primary raw SHA
`c9c88aadb62410701c3b5bfed7c7ada7049398a2a7b98c41d749c92a11746a0a`;
review `artifact_c2990ce6c7514da49afe2a7b75374f2c` /
`rev_c29fa4ea4c0249a59d1a2b8fa18765cd`. All six canonical members verified and
PNG bytes equal the inspected preflight. Rejected selections retain their evidence.

Thirty-two nonbinary evidence members, including actual failure/guard-correction
history, are in `artifact_5ba5b9d7c23f45b7aedb87ba44ed3ea4` /
`rev_ce73fffcef5441e5b158c59c1164f29b`, primary `reports/own-source-review.json`,
raw SHA `9a4378d2e0a82ccd994f467a4f0d0faf415a237200ea9f4996a08d25734638b2`.
Four clean source derivatives do **not** constitute a12-case validation cohort or
a32-case independent blind cohort. Blind V1's semantic-raster output schema remains
different from actual probe-output PNGs; an explicit generation/evaluation successor
is still needed. No output pointers were relabelled. New GPU/training/downloads0;
HOLDOUT0; native generated total84 and TRAIN fallback remainder0 unchanged. V6 and
all five services unchanged/active; no Preview/HWPX canary or activation opened.
Next: audit existing VALIDATION crop eligibility and curate more independently
sourced VALIDATION regions, then freeze the actual bounded evaluation successor.
Novel photo/sketch conversion, LoRA learned-style benefit and independent acceptance
remain unproved. Full-training/four-arm/32-case gates below are not removed.

Previous checkpoint, **2026-10-04 18:12 UTC**: the deliberate final source-
initialization diagnostic is installed lab-only and executed once. Same three
TRAIN references, existing Canny maps/models/prompts/seed/controller and LoRA1;
only original grayscale white-paper RGB initialization with fixed strength0.35
changes. Scheduler grid30, actual effective timesteps10. Six BASE/LORA outputs in
**21.220s**, peak **10,763,590,656 bytes (~10.02GiB)**. Source `26a1d667`,
regression450 PASS plus one additional timestep test PASS, strict mypy12 files
PASS; one unchanged infrastructure-import test remains explicitly excluded.
Initializer pixels and fixed publication crops independently reconstructed;
all13 canonical members verified. Actual installed worker terminal replay checks
43 files unchanged, with model/lease/canvas/write counts0, no Torch/Git/source.
Direct own inspection: **reference preservation, white-paper and composition
6/6 PASS**, not final independent institutional-style acceptance. Gray periodic
backgrounds disappear in both arms; BASE improves too, so learned LoRA benefit
and novel-reference conversion/generalization remain unproved. Fixed grayscale
publication crops are distinct from native RGB, which can retain color traces.
Result `artifact_9b7b92dec76e43e2bce0d22828228010` /
`rev_7822975a2ed04cf498d2905f2f9510c1`, raw receipt SHA
`74d8eb27261f857c3af1d69d2fa4c7b052605b0ffa854025724e04ecac156f45`.
Own review and20 other text-only records archived in
`artifact_6a8617bc39874778a7758c7fa2a48d54` /
`rev_589cdcb7af904853b0fb8f1d178c194f`, primary `reports/own-reference-review.json`,
raw SHA `620dce8f8f7db704d419921c715d981ea863e96e967ddf6623da011eb712ecb8`.
Native outputs84; previous78 and cleanup derivatives6 remain own-REJECTED.
Fallback12/12 consumed, remainder0; no further TRAIN sweep/retry/retraining.
New training/reserved reads/downloads0; operating V6 and five services unchanged.
Independent/heldout/Preview/HWPX/activation remain unopened; GOAL ACTIVE.
Next is read-only reserved-population and blind-contract compatibility inventory.
Existing blind V1 requires12–32 distinct depictions, four subject families and
semantic-raster output pointers; three TRAIN references and probe-output PNGs
must not be padded or relabeled to satisfy it. Reuse packet/answer-key ownership
with an explicit additive evaluation contract only after that inventory.

Previous checkpoint, **2026-10-04 17:15 UTC**: ADR 0191's fixed Canny ControlNet
controller was acquired/installed lab-only with exact hashes/license evidence,
wheel RECORD and actual worker safe-header verification (844 fp16 tensors, no
model inference). One frozen comparison used the same three TRAIN references,
captions/negative prompts, seed104729, Euler ancestral/30 steps/CFG7 and LoRA1.0.
Six outputs in **45.948s**, peak **10,763,098,624 bytes (~10.02GiB)**. Source
`6e7f1620`, regression403 PASS/one known exclusion, strict mypy10 PASS. Thirteen
result members/crop reconstructions/canonical bytes verified; installed replay
verified38 files with model/GPU lease/Canny/write counts0. Own inspection of all
six native/final images and original sources: LORA composition3/3 improved, but
final quality **REJECTED6/6** (gray/periodic backgrounds and rough contours; BASE
fan also adds two objects). This is not independent or heldout acceptance.
Result `artifact_43c6a3311c9b43dd800c056ea81def35` /
`rev_f95ec4eaf45f434aa2c241b64a952328`; 34 text-only evidence members archived
in `artifact_d9bf33372c714fff82a052bcefc596c9` /
`rev_a8b25cf7c1ba4f68901461d3a2d8b520`. Native78 remain own-REJECTED; old cleanup6
and conditioning3 are separate. Training/reserved reads0; operating V6/services
unchanged; GOAL ACTIVE. No automatic use of the remaining fallback quota. Next:
read-only target/normalization/conditioning audit before any new frozen successor.
Installer/source-prefix diagnostic and wrong-environment publication import
failures are retained; recovery verified installed state without reinstall or
another GPU submission. Earlier checkpoints below are historical.

Previous checkpoint, **2026-10-04 16:02 UTC**: ADR 0191's closed CPU Canny
input preparation is implemented, installed lab-only and executed once over the
same three reviewed TRAIN targets. Three binary 832×512 maps in **120ms**;
canonical four-member byte equality, installed CPU reconstruction and transform-
free replay PASS. Source regression278 PASS, strict mypy9 PASS; one explicitly
excluded existing infrastructure import violation remains open. Direct source/map
inspection: own input-detail **3/3 PASS**, not finished illustration quality.
Optional OpenCV4.11.0.86 installed; other numerical versions/trainer unchanged.
Twenty-six non-binary evidence members archived. Controller weights and numerical
comparison pending; no new model/GPU output, training or reserved-source reads.
Native72 and CPU publication derivatives6 remain own-REJECTED, counted separately
from the three control inputs. Operating V6 unchanged; independent/heldout review
NOT_PERFORMED and GOAL ACTIVE. Next: pinned license/model/comparison admission
before one six-output spatial diagnostic, no threshold/prompt/seed sweep. Earlier
checkpoints below are historical.

On 2026-10-03 the readable operating binding is SSD-1B V6, hash
`sha256:c77908be126161e5a08082958ebc06af63b6f64fda11ce8154f198a90058843c`.
The checked-in V7 institutional-style configuration is a candidate, not the active baseline.
The host exposes an RTX 5080 with 16,303 MiB. GPU/NAS were unavailable in the earlier restricted
execution context and became accessible after the interruption; that earlier observation does not
establish a service outage. Model directory listing requires the existing privileged adapter.
The 06:05 UTC read-only audit resolved the approved object and raster crop sets through the existing
Orchestrator control-Artifact resolver. Schema/Pydantic, approved revision, member hashes, PNG
decode/dimensions and linked authorization/review hashes passed. Each contains 24 members
(16 train / 4 validation / 4 holdout): object line art spans 20 PDFs / 19 exam groups, raster scenes
19 PDFs / 19 exam groups. These are not hundreds of new training examples. Existing partitions stay
unchanged. The 768-candidate review has 24 object-line-art eligible entries; its diagram/raster
categories cannot simply be relabeled as object line art to reach the full-training target.
The protected model-root inventory found the SSD-1B logical model directory, not an SDXL candidate
stack. A full installed-weight audit and runtime throughput measurement remain pending.
No quality gain or blind-review PASS has yet been measured.

## Implementation order

1. Record the current binding, model revisions and reviewed crop provenance. Reuse existing
   Artifact pointers instead of copying images to Git. Keep V6 available for rollback.
2. Implement the document/duplicate-group split contract in ADR 0175. Freeze source metadata,
   internal authorization and independent holdout groups before training. Default full-experiment
   targets are 100–200 train, 24–40 validation and 32 blind-test depictions; report shortages.
3. Add additive SDXL model-stack and evaluation-command schemas before provider behavior.
   Pin base, VAE, T2I-Adapter, line detector and LoRA revisions/hashes separately. Verify lineart
   polarity from the pinned upstream implementation. Do not claim SDXL adapters work on SSD-1B.
4. Extend the existing isolated candidate provider/trainer. Use fixed local weights, offline
   inference, the current GPU lock and bounded staged inputs. No new queue or external LLM API.
5. Begin with an evaluation-only micro LoRA: rank 8, alpha 8, 200 steps, batch 1, accumulation 4,
   frozen text encoders/VAE and fp16 where supported. Validate numerics and GPU compatibility.
   Only then compare up to three full-training candidates: rank 8 with low/current LR and rank 16
   with low LR. Exact learning rates and memory bounds must be pinned before execution.
6. Run six subjects through V7 at two seeds, Informative Drawings once, SDXL+T2I base at two seeds,
   and SDXL+T2I+LoRA at two seeds: 42 proposed outputs, not outputs already produced. If structural
   fidelity fails, add a bounded ControlNet/IP-Adapter comparison of at most 12 outputs.
7. Expand to 12 diagnostic and 32 independent same-depiction blind comparisons. Use the existing
   separate presentation-packet/answer-key contracts. Record prompt/reference/model/seed hashes,
   morphology/semantic judgments, pseudotext, latency, peak VRAM and output hash.
8. Only a passing candidate proceeds to a successor single Item Preview and HWPX canary. Verify
   package-internal PNG relationships, download SHA, labels and rollback. Do not activate a model
   merely because training or rendering succeeded.

## Proposed decision criteria

Require zero unresolved critical scientific contradictions and pseudotext in accepted images.
Pilot adoption targets are at least 90% usable, mean semantic/composition score at least 4/5 and
generated-origin identification no more than 65% across 32 depictions with three independent
reviewers. These are proposed operational gates, not a statistical proof of indistinguishability.
Each rejected image remains rejected regardless of the aggregate average. Independent reviewer
availability is a human gate; automated metrics and our own inspection cannot substitute for it.

Measure resource limits against fixed-input V6/V7 runs before choosing an operational ceiling.
Training data, validation selection and blind comparison populations must not overlap by source
PDF or reviewed duplicate group. Reference-conditioned composition preservation is evaluated
separately from free generation. Follow the existing internal-use authorization scope.

## Progress and evidence

### 2026-10-04 original-page recovery implementation

All sixteen original TRAIN inputs were compared with fifteen canonical unredacted page PNGs.
No VALIDATION/HOLDOUT pixels, model calls or registry writes were used in that read-only audit.
The full pages reveal incorrect morphology captions as well as OCR-redaction damage: the alleged
microscope is a telescope/solar projection apparatus; the alleged glove includes a cold pack;
the alleged flask/delivery tube is an electrolysis crucible/power supply; the alleged balance is
a heat-conduction experiment. These observations qualify the old small-data experiment; they do
not change its immutable command, adapter or rejected outputs.

ADR 0184 adds reviewed original-page literal crops with corrected captions and frozen source
partitions. It reuses complete historical lineage admission, bounded unique-page resolution,
the existing CPU trainer processing and Orchestrator file-set publication. The processor runs
as the existing `eom-image` identity with a fixed script and no model/GPU/credential inputs.
Literal pixels are not resized, masked, thresholded or reconstructed. New PNG pointers use the
existing institutional crop media contract, allowing the original document-group split to be
reused without a new queue, database or dependency.

Final focused regression: **175 PASS**, including 34 new source-page cases. Ruff formatting/lint,
strict mypy on five changed core modules, release-shell syntax and diff checks PASS. The earlier
169-PASS run preceded six additional negative/duplicate/read-group tests; counts overlap.
Actual source recovery publication/visual inspection is pending at this implementation checkpoint.
Full-data training, independent blind review and production activation remain pending.

The actual CPU preflight produced twelve candidates in 4,577 ms from eight TRAIN pages, eight
PDFs and seven exam groups. Visual inspection corrected two selections, then deferred the
telescope's remaining annotation leader and a student's speech-bubble tail rather than masking
object pixels. Eleven literal candidates are selected for first publication; extra depictions in
the same source panel are not additional independent PDFs/groups.
The first publication request was rejected by the existing receiver before DB/NAS mutation:
the new producer used an Artifact type without the required `control_` namespace. Read-only
audit confirms **job rows=0**, CPU crop dispatches=0 for that rejected request; the private intent
and log remain evidence. The producer now follows the existing namespace (receiver unchanged),
and its test double delegates to the real receiver's pure file-set preflight. Final source gates
are **176 PASS**, including 35 new source-page cases. The prior 175/169 runs overlap.

For future split assembly, preserve **all** original source partitions. The existing split
snapshot can represent fixed members; its seed-assignment helper must not reshuffle previously
used TRAIN groups into VALIDATION/HOLDOUT merely to satisfy minimum counts. Exact/near-duplicate
review and full-count readiness remain separate, explicit gates.

### 2026-10-04 actual original-page recovery and expansion inventory

Source `335830d6cd29cd7eb37d2c3b892e5e54244277cf` successfully published eleven literal,
individually inspected crops from six TRAIN PDFs / six exam groups in **3,003 ms**. They include
people, a heated beaker, prehistoric animals, furniture, domestic equipment and animal pairs.
Source captions now describe the actual depictions. No OCR masks, guessed contour repair,
resize, thresholding or model inference was applied. Every committed PNG equals its separately
inspected CPU preflight by byte hash. Multiple depictions in one original panel are still one
source PDF/group; they are not independent evidence or unseen-data tests.

Reviewed intent: Artifact `artifact_c3de6b03293a405796d1c18188debc98`, revision
`rev_3ce604536808451ba52bc7785fe7174a`, member `manifests/science-source-page-crop-review.json`,
raw SHA `sha256:6dece566b3d88f0a65f5129eaf42a3deaa2cdb7d401332fad7126b9879d909f3`.
Canonical crop set: Artifact `artifact_f1b0ad42df2f4d7ebbf6e9401d28894a`, revision
`rev_54583c92322b4d8084c295744b97096e`, member `manifests/science-source-page-crop-set.json`,
raw SHA `sha256:6a57fb579c34eb0345e3ae11ae4e470230aaac90a30f5116841e7661104a9661`,
semantic SHA `sha256:54d2d8c0ef7f2a93711ee1f5e8c6ee8b18c6982e7995a2a8bd5821c12512c0f2`.
It has eleven PNG members plus one manifest, state `REVIEWED_SOURCE_DERIVATIVES` and activation
`FORBIDDEN`. This is source-data recovery, **not eleven newly authored AI images**, independent
blind review or full-data training approval. The source telescope's annotation leader and a
pointing student's speech-bubble tail remain deferred, with failed/preflight evidence preserved.

The metadata-only expansion inventory has **503 total TRAIN candidate rows / 49 PDFs / 40 exam
groups / 174 original TRAIN pages**. These totals include already inspected parents; they are
not 503 remaining, eligible or approved examples. Candidate authority/representation remain
`UNKNOWN_REVIEW_REQUIRED`. Existing selected-source partitions are TRAIN 72 / VALIDATION 18 /
HOLDOUT 18 and are unchanged. No reserved pixels were read for this inventory. Its raw SHA is
`sha256:2dc72d79f69edbdc818aa088bfe0751cef0ffebf8093bcf7cdc08111da86faaa`.
The archived operational snapshot's `remaining_train_metadata_*` fields refer to this same
**total pool**, not a post-review remainder; this clarification does not rewrite that snapshot.

Own review, exact source pointers, expansion metadata, operational snapshot, operator sources and
bounded success/failure logs are archived as 22 members at Artifact
`artifact_7c6a9469f80148c39da78d2fbc71dcbe`, revision
`rev_4d327e6c720f4b2082873939cb42dbf0`, primary `reports/own-source-review.md`, raw SHA
`sha256:984d018b7edf49f3113f1af330f5ec1d7fc75d0632e7029d5ca87198fa2eaf50`.
PNG/PDF bytes are referenced rather than duplicated into this evidence archive.
The initial archive preflight correctly rejected group-writable local logs before publication;
only those two generated evidence files were made private before the successful replay.

Final source gates: **176 PASS**, Ruff format/lint and strict focused mypy PASS; immutable
trainer/contract/provider wheel build and RECORD/resource inspection PASS. New wheels were built
but **not installed** by this source recovery. The fixed CPU processor used the existing isolated
trainer identity and pinned Pillow. Five production services stayed active and the operating V6
binding raw SHA stayed unchanged (`sha256:f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`).
This phase used 14 CPU preflight crops and eleven published reproductions, **zero GPU calls,
training updates, reserved-data reads or activations**; repeated crops are not independent data.

Next: inspect bounded batches of the original TRAIN pages, record literal boxes and accurate
caption/expression decisions, deduplicate across source groups, and pin a sufficient new dataset
and execution budget before further training. Full-data readiness remains `INSUFFICIENT`.
Actual SDXL authored outputs stay 36, all own-REJECTED; independent blind review and a quality-
passing Item Preview/HWPX canary remain open. Whole goal stays ACTIVE.

### 2026-10-04 expanded source inspection and full-corpus inventory

The complete existing TRAIN discovery pool was inspected in 21 contact sheets, then 31 shortlisted
regions at original pixel resolution. Contact sheets are diagnostic views, not training examples.
Three bounded read batches materialized 159 new original TRAIN pages (83,900,063 bytes); fifteen
already verified local views were reused. No VALIDATION/HOLDOUT pixels or PDF bytes were read.
The pool is dominated by graphs, tables and annotations; its 503 entries are not 503 eligible crops.

Twenty-two literal CPU preflight crops from seventeen pages were individually inspected; two
framing corrections excluded a speech-bubble tip and a power-plant table border/title. Twelve
candidates were reproduced and committed in **5,493 ms**, with every canonical PNG equal to its
inspected preflight. They span ten additional-set PDFs / nine exam groups. Across both sets the
actual total is **23 candidates / 15 source PDFs / 14 exam groups**, not 23 independent documents.
Subjects include a volumetric flask, comb/hair, bell-jar plant and mouse composites, mouse/syringe,
trilobite, swimmer/pool wall, desk/book, portraits/gestures and a power plant. Captions describe
literal source compositions. Small targets, restrained gray tones and fine hatching are explicit
target-preparation concerns; these candidates are not yet a uniformly prepared training dataset.
Ten annotated, clipped or repeated preflights are deferred rather than silently erased or relabeled.

Additional reviewed intent: Artifact `artifact_ffff0226bc3b4936975399960957a277`, revision
`rev_b581b40af0e7419fa453ba5308967dbf`, member `manifests/science-source-page-crop-review.json`,
raw SHA `sha256:e039ce397b74bade0217cf5436008d890d16ba4538faf9a6d8448242e4f7ab0d`.
Additional canonical set: Artifact `artifact_99ef287ab02b48a5822f7d980252bf90`, revision
`rev_3e418a2af6a5494d9b18be10670ddab2`, member `manifests/science-source-page-crop-set.json`,
raw SHA `sha256:5913745e41c31b9ef91ffa0083a44c764d41ffc70486320f28796da512adc413`,
semantic SHA `sha256:3611d5e43c2485645b1645a5a55fcfbb5c11b60d1cf5c9ae7f31c654862c567a`.
State remains `REVIEWED_SOURCE_DERIVATIVES`; activation is `FORBIDDEN`.

Read-only resolution of the originally authorized full corpus established **1,251 PDFs / 5,218
pages**, versus the 108 previously selected PDFs (TRAIN 72 / VALIDATION 18 / HOLDOUT 18). There are
**1,143 unselected PDFs**; 769 have issuer/year/grade/session identity metadata not represented in
that selection. These are metadata inventory counts, **not new TRAIN assignments, eligible images
or visual-independent-source assertions**. Corpus pointer: Artifact
`artifact_1b0d9eb8926c42dc865a5822c2e83c59`, revision
`rev_bc9b3cd11b384b4f9f9ac6bbfc789495`, member `corpus-manifest.json`, schema
`eom://schemas/legacy-assessment/science-assessment-web-corpus-manifest/2.0`, raw SHA
`sha256:244393c86005b5ced0ce64970da3af3f8e07b0b2cfe8fee2c0d9e92f48bba02b`, semantic SHA
`sha256:b2503fefb04aa9c0a0eb318e352bb797500a6c1e5dc8c2ed617bf6275b485c99`.

Own source review, exact publication, discovery/detail indexes, provisional/final selections,
whole-corpus metadata and bounded operator/log evidence are archived as twenty members at Artifact
`artifact_cad0ee66d01646e99aa72890095c42e6`, revision
`rev_2a11107a1a3e4301858306e64153ce90`, primary `reports/own-expansion-review.md`, raw SHA
`sha256:8a968011c5a88d0b676845b0c7c03beb139db81e5293bc3144b61a1ed3bee3fc`.
The evidence archive references PNG/PDF pointers instead of duplicating those bytes. Existing
**176 PASS** core gates are reused because this phase changes no core source or runtime. It makes
zero GPU calls, training updates, reserved-data reads or activations. Five services are active;
the operating V6 binding remains unchanged. Full-data readiness is still `INSUFFICIENT`.

Next: reuse the existing isolated PDF pilot for a bounded selection of previously unselected
documents from the same approved corpus. Preserve every historical source/group partition and
the common selection seed; quarantine duplicates before admitting new TRAIN pixels. New pilot
lineage must be admitted through the supported contracts, not attached to an old inventory by
inventing candidate IDs. Reuse existing schema/application paths where sufficient; add only the
smallest tested successor boundary if the existing lineage cannot express a supplemental pilot.
No new queue, database, external model API or production activation is needed for this expansion.

### 2026-10-04 supplemental source protocol checkpoint

ADR 0185 records why increasing old campaign limits or prefiltering the corpus is insufficient:
the former repeats up to all 108 old PDFs; the latter can change the original group partition map.
The additive pilot plan/command **V1.3** freezes complete predecessor plan Artifact pointers,
validates every previous document/PDF/group/hash/partition against the full approved corpus, and
excludes old document identities only after whole-corpus group assignment and shard ranking.
The existing isolated CPU renderer, original page/candidate/result media contracts and Orchestrator
commit owner are reused. There is no new queue, DB migration, model API or production binding.

Staging, isolated worker and result admission now share a closed version codec instead of separate
version-switch implementations. Exact V1.0–V1.2 command bytes are preserved in regression tests.
The V1.3 publisher uses an optional type-only import so unrelated historical CLI imports remain
compatible with their older installed contract set; this is not an import fallback or schema coercion.
The new staged-pilot entry point has a metadata-only preflight before PDF reads/publication/dispatch.

Final source gates: **140 PASS** in the explicit image-test environment (eight suites, including
29 supplemental-source/codec cases) and **59 PASS** corpus-contract tests in the explicit API
environment. These tests overlap earlier checkpoints; do not sum historical counts. Ruff format/
lint, strict mypy on six core modules plus three operator modules, release-shell syntax and diff
checks PASS. An initial source run exposed a tuple-versus-JSON-array validation bug in the new
factory; it was fixed before release. Earlier isolated-import failures were a mixed source/installed
test-environment invocation; the historical importer now remains independent of optional V1.3
runtime imports, and its correct explicit-environment rerun passed. No operating dependency was
installed to make a source test pass.

Actual supplemental selection preflight, compatible lab-wheel installation and PDF extraction
remain pending at this source checkpoint. Proposed bounded cohort: three disjoint workers, at
most 54 previously unselected PDFs / 384 pages / 512 candidates each, run sequentially. Confirm
actual selected source/page/partition counts and exact release identities before dispatch. New
discovery regions are not approved training data; literal crop admission, target preparation and
source/duplicate grouping remain separate. The old inventory is not rewritten to contain new IDs.
Recovered source candidates remain 23; actual SDXL authored outputs remain 36 own-REJECTED.
Full-data readiness is `INSUFFICIENT`, independent blind review is unperformed and V6 is unchanged.
Whole goal remains ACTIVE.

### 2026-10-04 actual supplemental extraction and crop-provenance checkpoint

The metadata-only preflight for source `d3a001ac109ed9fb3cff77a05ffe0805ef4dfba3` passed
all three supplemental shards without PDF reads or registry writes. Exact new inputs are
**162 previously unselected PDFs / 737 pages**, partitioned **108 TRAIN / 27 VALIDATION /
27 HOLDOUT PDFs**. The original 108 PDFs are excluded, all new document/PDF identities are
distinct, and the original whole-corpus seed/group partitions are retained. The three actual
worker scopes are 54 PDFs each and 246 / 252 / 239 pages respectively, each capped at 512
automatic regions. These are bounded discovery inputs, not 162 approved illustration examples.

Immutable Git wheels were built/inspected. Only contracts and trainer wheels were installed
in the protected **experimental trainer** environment, with installed RECORD, `pip check`,
actual worker-identity CPU import/no-Torch and existing isolated unit verification PASS.
Old `ad1716d6…` rollback wheels/hashes are retained. Provider distribution, inference environment,
V6 binding, GPU lock ownership/mode and production units stayed unchanged; no service restart.
Contracts wheel SHA `eb83886cffd5b1383cc106abe3d962975ec493c54b109f2356b5c3cc67ad7b0f`;
trainer wheel SHA `5a148963889137c65c06a7a729b473a294c04f4a3e2b5fc27dc75f1f0bd90f03`.

All three plans and exclusive workspaces are staged. Actual extraction is sequential through
the existing private-network/private-device CPU unit; no new queue, worker protocol, GPU job or
training update. At this checkpoint shards 0 and 1 completed and were committed by Orchestrator,
while shard 2 is running. The first two results total **498 pages / 1,024 automatic regions**;
regions include tables/graphs/annotations and are not quality-approved line drawings.

| Shard | Exact result Artifact / Revision | Result member raw SHA |
| --- | --- | --- |
| 0 | `artifact_7eb1b7d4d7c54ea0bfb2989358d30ca2` / `rev_df6e5e1d7bba432f9cb57a2b2807bd85` | `ff999085a12206108a3d3407d393be9ab56667b900548dfe9dd0ed4471c192b9` |
| 1 | `artifact_1ab90ca13b61457b90b058172963394b` / `rev_20f253dd666d4ad79b786d93febba4fa` | `d9d62f1a0955cfac72e7500220c9675c44fb40a760aee521d9f37b90a861e66f` |

The result member is `manifests/visual-pilot-result.json`; each exact result binds its plan's
semantic hash and complete original-page/candidate member closure. A first collection-only
operator invocation rejected cleared `ExecMain` timestamps after systemd garbage-collected a
completed oneshot. It submitted/published nothing and did not change source. After inspecting
that empty checkpoint, the collector used exact pinned terminal result/runtime and full PNG
closure instead of treating service health/timestamps as execution proof. It preserved the failed
log/operator, the same three command identities and all outputs; no extraction was resubmitted.

[ADR 0186](../adr/0186-supplemental-original-page-crop-provenance.md) adds **crop review/set
V1.1**, rather than attaching supplemental candidate IDs to the old inventory. Complete new
plan/result pairs and the same original authorization/predecessors are admitted before PNG
reads. Catalog replays its existing authoritative full-corpus selection; Orchestrator batches
immutable metadata and unique page pointers, then reuses literal CPU crop processing/publication.
V1.0 schemas/meaning and PNG/dataset split contracts remain unchanged. No new dependency, DB
migration, queue, framework, production deployment or automatic training admission.

Current source gates: **170 PASS** across nine focused suites (including 30 supplemental crop
admission/version/closure cases), plus **59 PASS** corpus-contract regression tests in the
explicit API environment. These overlap earlier counts and must not be summed with them.
Ruff format/lint, strict mypy on five changed core modules, release-shell syntax and diff checks
PASS. Initial new-test runs caught an error-class expectation mismatch; the Orchestrator now
reports its own stable admission error while preserving the Catalog cause. A final negative test
also enforces exact review/output version pairing even for a rehashed legacy-shaped output.
These were source
test failures, not production incidents or model retries. New crop V1.1 live publication and
corrected-data training have not yet run at this source checkpoint.

Next: close shard 2 and archive exact release/staging/publication evidence; inspect TRAIN original
pages, select complete literal objects with correct captions/expression and document/duplicate
grouping, then prepare/freeze corrected-data training and separate validation/holdout budgets.
Do not visually inspect reserved pixels for TRAIN tuning, automatically train discovery regions,
relabel source crops as AI outputs, or generate again in the exhausted diagnostic cohort.
Reviewed source candidates remain **23**, actual SDXL outputs **36 own-REJECTED**, independent
blind review `NOT_PERFORMED`, full-data readiness `INSUFFICIENT`, V6 unchanged, GOAL=ACTIVE.

At **2026-10-04T07:37:07Z**, all three supplemental CPU cohorts finished and were committed:
**162 new PDFs / 737 pages / 1,536 automatic regions**, with zero GPU/training/activation calls.
Shard 2 result is `artifact_6c791faf82de4b7cbccc2b7ef1522282` /
`rev_52f85af6e224451b844a9e362464bcaa`, member `manifests/visual-pilot-result.json`, raw SHA
`sha256:37a30655a5a484743b99b0f409f4f63f9fa55a3467a3fd98b22657adbdf79f92`, semantic SHA
`sha256:ba463769968ba104dc6dba0bcdc79409ce18467a4d9914c19a7047ec66f51ea7`.
Discovery and crop review now share the same read-only complete-lineage admission, so inspecting
TRAIN pages does not require inventing a review/caption. Final discovery-extension regression is
**174 PASS**, including four new shared-admission/input-negative cases; this replaces, not adds
to, the overlapping 170-test checkpoint. The actual extraction success does not increase approved
source-crop or authored-image quality counts. Literal review and data admission remain next.

### 2026-10-04 supplemental TRAIN inspection and actual literal publication

Source `400f1c0941e9d4af9d62d536a49ef5825466c201` reused shared metadata admission for all
three plan/result pairs before reading TRAIN pixels. The read-only observer materialized
**1,005 TRAIN candidate views / 101 PDFs / 360 unique original pages** through six bounded batches.
Own inspection covered all 42 discovery sheets and 95 selected original-context views. It did
not view VALIDATION/HOLDOUT pixels, approve all automatic regions or run a GPU.

The provisional 72 literal crops were individually represented in hash-checked viewing sheets,
then all 72 corrected crops were viewed again. **49 frames and seven captions** were corrected;
caption correction is not another independent drawing. Native original pixels were cropped, not
masked, resized, reconstructed or thresholded. Viewing thumbnails are a separate local boundary.
The source pool spans cars/truck, apparatus, animals/plants, landscapes and person illustrations.
Clean contour, restrained gray and fine-hatching expression remain distinct metadata.

At **2026-10-04T08:33:56Z**, the supported Orchestrator publisher committed:

| Document | Artifact / Artifact Revision | Raw primary member SHA |
| --- | --- | --- |
| Review V1.1 | `artifact_87740cab1a024143a78eab86f5537b5b` / `rev_d1d74dc15c894636b43d58652f4f1055` | `b814f0b8a70597a384df79e9ed11c26b94752175e5752ceb3a1a4807d57df63f` |
| Source set V1.1 | `artifact_1629e2ef829f46b3b258ee97e429843e` / `rev_bcab8901313a4d998fee64601eb06cfb` | `3d282df8b06758d503fc6ea680176460f3aa33b18b7580302404907ad187252b` |

Primary paths are `manifests/science-source-page-crop-review.json` and
`manifests/science-source-page-crop-set.json`. The set contains 72 canonical PNGs plus its manifest,
logical ID `imgsourcecropset_96ad4438ccaa6a25d92d7e6e4a4cbc4f`, revision
`imgsourcecropsetrev_a1615350ee98eeabc98bdce5a1ae1532`, semantic SHA
`sha256:cc6a8c1921c7316301cf9acd87f1c1c7655e56a8604ae39819a4bd1907f38ca2`.
Publication took 28,633 ms. Every committed PNG and manifest was resolved and hash-/byte-compared
with the exact preflight file. Prior 23 sources remain unchanged; aggregate **95 candidates /
58 source PDFs / 48 exam groups**, not 95 independent documents or approved training targets.
Cross-set exact pixel hashes, identities, TRAIN inheritance and max-3/PDF, max-4/group checks PASS.
Near-duplicate review and final target admission are separate next gates.

Own screening of the NEW 72 is **42 READY_FOR_TARGET_PREPARATION_WITH_NOTES**, including nine
isolated outside-object marks needing explicit safe preparation, and **30 DEFER_TARGET_REPAIR_OR_REFERENCE_ONLY**.
Do not train raw crops with labels/leaders, erase object contours, discard useful references or
count exact geometry/native-drawing material as approved GPU style samples. The corrected frame
and actual surrounding text, not a plausible miniature caption, determine the object's identity.

The 39-member evidence set is `artifact_5eb67225f2874fc890281b9fa650ddbb` /
`rev_6fc6f9f415734f2389cd5475c75f8227`, primary `reports/own-supplemental-source-review.md`, raw SHA
`sha256:d074da1d1ae4d7e65e9ed22416bfbd3467b5286b2000fa446794ad7b36646a53`.
It contains bounded metadata/logs/operators, **zero duplicate PNG/PDFs**; primary committed bytes
were resolved and verified. The first framing invocation failed JSON Schema before reads because
a temporary wire field used tuples instead of JSON lists. Local screening initially omitted source
PYTHONPATH; archive preflight rejected group-writable task files. These were corrected in their
caller/environment/0600-file boundary without loosening contracts, production state changes,
rerunning extraction, direct DB repair or model retries. Failed applicable logs remain evidence.

Source gates remain **174 PASS** plus separate **59 PASS** corpus-contract regression; do not
sum overlapping historical counts. CPU extraction lab is installed from `d3a001ac…`; `9f2d2502…`
was built but not installed. Production V6 is unchanged, five production services active.
New GPU calls=0, training updates=0, target-training admissions=0. Old 36 SDXL outputs stay
own-REJECTED, old diagnostic allowance 12/12 consumed, independent blind review NOT_PERFORMED,
full-data readiness INSUFFICIENT, activation FORBIDDEN. GOAL=ACTIVE.

### 2026-10-04 actual literal-source CPU target preparation

ADR 0187 / source `965022f307c95d9ad85a31a09e37d93b4614e5f3` adds target command/result **1.1**
for one pinned literal crop-set revision. It preserves the old 16-input target **1.0** bytes/meaning
and reuses its fit/mask/caption operations, Orchestrator staging and isolated CPU systemd unit.
No new database, queue, service framework or dependency. Full original/supplemental corpus metadata
is admitted before selected-only TRAIN PNG reads; worker receives no NAS/DB/model access.

Focused source/legacy/admission/workspace/micro-run/control-publication gates **207 PASS**, formatter,
linter and five core strict type checks PASS. These overlap earlier source counts; do not sum them.
Two immutable contracts/trainer wheels were installed only into the lab trainer; installed RECORD,
actual worker import/Pillow 11.3.0 and pip check PASS. Production provider/binding/units unchanged.
Rollback is the preserved `d3a001ac…` contracts/trainer pair; no production service was restarted.

The monkey's proposed mask interrupted its contour in own preview and was deferred, so the first
actual command covered the exact 72-source population as **41 PREPARE / 31 DEFER**. It ran in
**2,252ms**, staged 45 files and committed 41 PNGs + result manifest. Own viewing covered every
target on seven hash-checked sheets. Six targets were flagged: small profile/footer residue (77),
left outside-truck fragment (533), robot label/leader (646), speech-tip fragments (661, 859), and
source-frame-clipped beaker (940). No target/source bytes were overwritten or discarded.

A separate **3 PREPARE / 69 DEFER** command corrected only 533/661/859, ran in **234ms**, staged
7 files, and committed 3 revised PNGs + manifest. Its 69 deferred selections are not 69 new failures;
already usable targets remain referenced. All three actual revised PNGs were own-viewed; the truck
remains a tone/scene-track candidate with a scene-edge note. 77/646/940 need original-context/native
or frame recovery before selection, not an invented reconstruction.

Both actual results passed installed worker/Pillow byte reconstruction, zero-transform receipt
replay, output closure, bounded secure reads and committed/workspace PNG equality. Torch was not
loaded. Initial result: `artifact_d50bd600731e4072aeb2237e6fa6730d` /
`rev_222b8ae8c8fb48b197774439183ca585`, raw primary SHA
`sha256:bd4c56b27735ce3f6238559c627a5f25b085670bba0036859bb7c16b95751ed3`.
Refinement: `artifact_8f75cf7851b6470eaef0831b46e307ca` /
`rev_b84fd533d5b84f7aa911b452ec1a1798`, raw primary SHA
`sha256:b29a826455bfd370eac605282039f9fcd7ef26c9c48a3c724766c8b2b40a88e5`.
Both primary members are `manifests/sdxl-training-target-result.json` with schema `/1.1`.

Chosen **38 source candidates = 35 first targets + 3 revised targets**, **26 PDFs / 25 exam groups**.
Do not count 44 realized PNGs as 44 independent drawings. Exact-hash duplicates=0, existing bounded
average-hash/Hamming≤2 flags=0, maximum per PDF/group=3/3. This is not exhaustive semantic deduplication.
Expressions: CLEAN_CONTOUR=10 / RESTRAINED_TONE=23 / FINE_HATCHING=5; do not train these as one
undifferentiated style or let GPU pixels own scientific labels/geometry. Source pool remains 95;
previous 23 source candidates are not automatically admitted by this target review.

At **2026-10-04T09:37:52Z**, 26 metadata/log/operator evidence members were archived:
`artifact_3bce4fee87f141febad135f790eaa3a2` / `rev_b4846e18f23f49c0952b4ea5e9e328ac`,
primary `reports/own-target-review.md`, raw SHA
`sha256:8f87b5bca79b77052eccd8c07f519fa6b2eb121aaf3ec6552f6436b795ddcc93`.
Zero duplicate PNG/PDF members; primary committed bytes verified. The temporary refinement publisher
initially asserted the first cohort's 41/31 counts and failed before publication; corrected caller
expectations validated/published the same successful run/result. No worker rerun, DB repair or
failure-as-success reinterpretation. The failed log/operator is preserved.

Operating V6 unchanged, five production services ACTIVE. New GPU calls=0, training updates=0,
training admissions=0, reserved-pixel views=0. Own review is not independent review. These target
lists are operational evidence, not an implicit dataset protocol. Full-data readiness INSUFFICIENT,
independent review NOT_PERFORMED, old 36 outputs own-REJECTED, old diagnostic 12/12 consumed,
activation FORBIDDEN, GOAL=ACTIVE.

Local own review: `/tmp/eom-sdxl-literal-source-target-own-review-20261004.md`; first target sheets
`/tmp/eom-sdxl-literal-source-target-own-view-20261004/sheet-00.png` through `sheet-06.png`, actual
revised PNGs `/tmp/eom-sdxl-literal-source-target-refinements-20261004/`. These are institutional
source-derived input candidates, not newly generated AI samples.

### Historical next pilot boundary at the CPU-target checkpoint

1. Target-preparation successor and actual 38-source own review are complete at this boundary.
   Preserve the old 1.0 family and both committed 1.1 result revisions; use typed output pointers
   rather than preparing/copying the same usable targets again.
2. Recover remaining source-frame/annotation candidates only when needed without discarding
   references. Include the prior 23 only after their own target review, not automatically because
   they are registered sources. Keep source/target own review separate from training approval.
3. Assemble a small corrected-data pilot using existing split/grouping invariants. Keep logical
   source identity, target revision, dataset revision and raw hash separate; review near duplicates
   and material-family/source concentration. Report the actual denominator; do not manufacture
   100 samples by duplicate resizing or reshuffle previous TRAIN into reserved partitions.
4. Introduce only the training/evaluation successor that actually needs the new target/dataset
   references. Pin a NEW bounded training/comparison cohort and its usage authorization before
   model execution. The old exhausted 12-output diagnostic allowance is not reset by a rename.
   Source-candidate publication grants no inference/training budget and no production activation.
5. Compare fixed base versus corrected-data LoRA using truthful source/prompt/seed pins and
   separate TRAIN diagnostic versus reserved/independent assessment. Only a passing candidate
   reaches the planned Item Preview/HWPX canary and separate activation/rollback gate.

Local own-inspection files (not new AI outputs):
`/tmp/eom-supplemental-source-crops-framed-20261004/*.png`; decisions in
`own-source-screening.json`. Canonical PNGs reside only in the committed Artifact, and evidence
archives reference them rather than introducing a second canonical payload.

### 2026-10-04 actual 38-source SDXL pilot and matched diagnostic

[ADR 0188](../adr/0188-reviewed-literal-target-sdxl-micro-training.md) adds closed
training/evaluation command/result **1.1** successors while preserving released 1.0 bytes,
the original sixteen-input meaning and adapter-manifest 1.0. No DB schema, dependency,
queue, service or production binding was added. Source commits `17e0bc75` / `1ff36399`:
training regression **189 PASS**, broader evaluation regression **290 PASS**, strict types,
formatter/linter and immutable wheel/resource/RECORD checks PASS. Do not sum overlapping suites.

The new command freezes **38 distinct source drawings, 26 PDFs / 25 exam groups**, selected as
35 first targets plus 3 repaired revisions. TRAIN only; no artificial enlargement of the
denominator, reserved-pixel reads=0, no second resize/mask/PNG rewrite. Training input hashes
equal realized hashes. One authorized run, **200 steps**, seed 20261004, rank/alpha 8,
maximum 3,600,000ms and 16GiB allocated GPU memory; production activation FORBIDDEN.

Actual training run `imgsdxlmicrotrainrun_faebf4cffe0d29cb799f88ec3d95e785` completed successfully:
**474,973ms**, loss **0.024936307221651077**, peak allocated GPU **5,704,160,768 bytes**.
RTX 5080; Python 3.11.15 / Torch 2.7.1+cu128 / Diffusers 0.35.2 / Transformers 4.56.2.
The low training loss is not an image-quality acceptance result.

- Command: `artifact_0170495f310941039f264597bf6728b9` /
  `rev_b93a8cb2ac5d4c10b9e7df2a2274d37f`, member
  `manifests/sdxl-lora-micro-command.json`, schema `/1.1`, raw SHA
  `sha256:5a1a9ad6c62f31cacc911bd18be7898b86638ac0d3266499abce974916cd7971`.
- Result/adapter: `artifact_ca69f2ad44f84e35be396e9df246a1f7` /
  `rev_3221c81d6d1b4c5c8229e4144398d92f`, primary
  `manifests/sdxl-lora-micro-result.json`, schema `/1.1`, raw SHA
  `sha256:ea43ce7370867867f839bcce56e4bb4ea11c1c152ed144e9048acc29f48557a3`;
  semantic result SHA
  `sha256:fc5c21c79a90eb7cc34a5b10755fa72323699b8877c2f5064e29f667c479fd6b`.
  Four members only: result, adapter manifest, config and safetensors; zero duplicate target PNGs.
- Adapter: `imgadapter_268d02fd5e1666b693d3e630e3880c95` /
  `imgadapterrev_906b2b4d9c3b6d9f5d9c5220657e2200`; manifest raw SHA
  `sha256:dfb6cdc8135c071b34a02bc705a71ba6fa7ac6cbde9ecbab24986bad11b4494f`,
  semantic SHA `sha256:2ba6227e858b2d5c614530f22df532b4c4129a48dcdd0825a1e2cc8435cf2a8e`.

The fresh comparison was frozen before inference: plan SHA
`sha256:22120c35552aba5a87f9f257ed8687d79905281283e1efb46715cd4edfcbd388`,
**6 BASE + 6 new LoRA outputs**, no training updates, no retries. Old 12/12 diagnostic allowance
remains exhausted; this distinct new cohort is also 12/12 consumed. Both arms use the same
six original TRAIN reference PNGs, style prefix on both prompts, seed 104729, 30 steps,
guidance 7.0 and T2I strength 0.8; only style LoRA differs (absent versus strength 1.0).
This is `LEGACY_TRAIN_REFERENCE_DIAGNOSTIC_NOT_HOLDOUT`, not clean-source or generalization proof.

BASE runs in the existing `eom-image` environment, LoRA in `eom-image-trainer`. These wheels
are not falsely reported as identical: generation/conditioning/encoding ASTs and active BASE
loader branch were compared, along with identical numerical SDK versions. The old unused
loader keyword and new unselected style branch were explicitly accounted for. Local checks
in both text encoders found maximum **67 tokens**, no truncation. No operating package/unit
was changed to make the comparison.

| Result | Duration | Peak allocated GPU | Committed Artifact / Revision |
| --- | ---: | ---: | --- |
| BASE, six images | 28,418ms | 8,280,481,280 bytes | `artifact_6e4be4fa9cd24267861337125598f928` / `rev_2ad1244c864b460ead6d4d5b36be2694` |
| LoRA, six images | 32,830ms | 8,328,740,352 bytes | `artifact_82fab6e945654f9998ca68d881bf8f54` / `rev_c7ba6d1f7ba24b57b9d01e9fa5268015` |

Result raw SHAs respectively:
`sha256:04d7eb9890ea941c5f7b7d29d7e66e8ffe845b8a2e9f96c2ebc0b423d8205f6f` /
`sha256:cf0bb1e80617e57bbfad4e116919681649ad8bf39277149e8d21c40a501aed50`.
Each result has 19 declared members; every committed member matched workspace bytes via
the bounded batch resolver. Raw RGB and native 800×500 grayscale publication outputs remain
separate derivations. No display whitening, thresholding or cropping conceals failed native output.

All twelve images were inspected directly by the implementing agent:

| Depiction | Observed LoRA change | Remaining blockers / own decision |
| --- | --- | --- |
| Radio | reduced grid contrast/reflections, aerial preserved | gray field, shadow, fine texture; REJECTED |
| Trilobite | white halo reduced, segmented contours persist | gray grid, grain/dense fills; REJECTED |
| Deciduous tree | some background lines reduced | left stray line, bottom frame, gray/hatching; REJECTED |
| Heated vessel | grid largely disappears, contours simplify | gray field, heavy fills/halos, geometry unverified; REJECTED |
| Protective glove | harsh reflections/grid soften | patch/mark, imperfect cuff, gray field; REJECTED |
| Microscope | excessive shading/edge halos diminish | right vertical line, grid/gray, dense fill; REJECTED |

All six LoRA mid-tone fractions increase; foreground occupies **976–1000 per mille** of
the canvas. Background gray makes fine-detail/edge metrics misleading. A lower detail score
is not a quality PASS. Total actual SDXL outputs are now **48**, all own-REJECTED; independent
blind review remains NOT_PERFORMED. No Item/HWPX canary or production activation is justified.

Actual installed training replay exposed an ownership defect missed by same-owner development
fixtures: staged targets are root-owned 0440 inputs; old regenerated crops are worker-owned
outputs. `cf6746ae` corrects only successor replay's input ownership assumption. Pinned SHA,
bounded regular-file/no-link/non-group-world-writable checks and output ownership guards remain.
The regression failed first; changed hash/writable/symlink negatives pass. Focused **102 PASS**,
broader **298 PASS**, strict types and formatter/linter PASS. Actual worker replay then passed
for training and both comparison arms: zero model calls/steps, no Torch import, no new copies.
No input chown, target rewrite, retraining or terminal-receipt repair was used.

Lab contracts/provider are source `1ff36399`; the replay-only trainer wheel is `cf6746ae`, SHA
`48c846d3f61d8b4f09230e6403507f69a7eadc9f986fb348bd1a1ba9114930d8`. Its verified rollback
trainer wheel is `1ff36399`, SHA `805ddb31bffc91195b8a84c1ad4ef6fd659ddc0c8069a442cfec3c0ef300fe9e`.
Existing units/GPU lock unchanged; five production services ACTIVE; GPU idle; operating V6
binding SHA `f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845` unchanged.

Evidence: **44** operator/report/log members, no duplicate PNGs/weights, all registered bytes
verified; `artifact_b3709263327546909055c89d3ab5f471` /
`rev_f9eba51e9cf44497a076b914285b0dae`, primary `reports/own-comparison-review.json`, raw SHA
`sha256:e7166dfc034374b4b698ebc02583eddab309239d7d2636127381529f6db9529d`.
Caller schema mismatch, replay failures and a private-evidence permission preflight failure are
preserved. Corrections did not re-run training/inference or reinterpret failed history as success.

Local actual AI samples: `/tmp/eom-sdxl-reviewed-comparison-samples-20261004/`
`{radio,trilobite,deciduous_tree,heated_vessel,protective_glove,microscope}-{base,lora}-104729.png`.
These are new generated outputs, unlike earlier source-derived candidate targets. Own review:
`/tmp/eom-sdxl-reviewed-comparison-own-review-20261004.json`.

### Historical follow-up scope after the measured 38-source pilot

1. Preserve this adapter/result/cohort and REJECTED outputs. Do not spend the exhausted
   diagnostic quotas again, change native bytes into apparent PASS results, or increase steps
   merely because training loss is low.
2. Admit a small clean literal-source reference/conditioning cohort through the existing
   Orchestrator owner. New training 1.1 is supported; legacy reference diagnostic support does
   not silently grant clean target/reference or held-out evaluation support. Determine the
   minimal typed reference successor needed before worker behavior; no parallel trainer.
3. Keep input geometry, artifact lineage, expressions/captions and model settings explicit.
   CLEAN_CONTOUR, RESTRAINED_TONE and FINE_HATCHING remain distinct rather than one vague style.
   Investigate white-canvas/background behavior before purchasing more samples or training steps.
4. [The official model card](https://huggingface.co/TencentARC/t2i-adapter-lineart-sdxl-1.0)
   describes bright outlines on a dark conditioning background and uses a learned detector.
   This supports checking the detector/input distribution, not guessing an inversion bug from
   gray output alone. Verify the exact pinned implementation before changing polarity/policy.
5. Freeze a distinct bounded matched cohort before further inference; keep reserved partitions
   closed until their declared independent evaluation boundary. Full data readiness remains
   INSUFFICIENT, independent quality NOT_PERFORMED, activation FORBIDDEN, GOAL ACTIVE.

### Actual reviewed-target matched comparison, 2026-10-04

`7cda7e33` adds `local-image-sdxl-target-comparison-{command,result}/1.0`, pinning the
actual reviewed evaluation command 1.1, its successful 38-target training result,
adapter revision and selected prepared PNG revisions. These PNGs are reviewed
institutional-source derivatives, not raw originals or new generated drawings.
Source/target revision, recipe expression, schema/media/hash and full original PDF
lineage are validated before pixels. Only the three selected PNGs and two adapter
members are staged; the 38-image training set is not copied into this evaluation.
Legacy learned-conditioning and new target-reference execution retain different
source/result contracts and share one numerical pair loop, one GPU lease and
fresh BASE/LORA pipelines. Existing isolated systemd template, NAS commit owner,
queue/DB/schema, scientific overlays, team prompt files and production stay unchanged.

Frozen input cohort: PEDESTAL_FAN, FLOWERING_PLANT_WITH_ROOTS and
KICK_SCOOTER_WHEEL_LIGHTS from three different source documents/exam groups. All
three exact target PNGs were viewed before selection. Both arms use each exact
reviewed training caption, the same existing negative prompt, seed 104729 and the
pinned 30-step/guidance-7/T2I-0.8 numerical settings. Both tokenizers: maximum
67/77 tokens. This is `REVIEWED_TRAIN_TARGET_NOT_HOLDOUT`; zero reserved pixels.

New quota: one pair, six outputs, no training. Run
`imgsdxltargetcmprun_cc970021ebb2599641b46a761e3ea703` completed in **30,383ms**,
peak allocated GPU **8,328,740,352 bytes**. The new cohort is exhausted **6/6**;
the earlier two 12/12 cohorts remain exhausted, not reset or relabeled.
Command: `artifact_8cb2359e63424f37bb1ed910510d83c3` /
`rev_88a2a82d3a5f4ae9a9fe7ee5e15baf63`, raw SHA
`sha256:4a3ce96bf9aa4af0f7ce6442aeb9ada1526174c294f58d86a558987c6c3eeb75`.
Result: `artifact_566856b16d3f454a825b20aa37a40a8c` /
`rev_f9f58bc9073d4d66b04fd71cb5b4640d`, primary
`manifests/sdxl-target-comparison-result.json`, raw SHA
`sha256:7e7a4868a5b5e3cf4a1a6d76c424216e62620505349a0d02b07510df9afd43d8`,
semantic SHA `sha256:89594030277462276148c4972cc6447c84decd3ac2b80e6e291636c9f908e0e9`.
All **16** declared members (receipt, three derived conditioning PNGs and twelve
raw/final PNGs) matched canonical registered bytes. No training PNG/weight copy
was committed. Raw RGB 832×512 and native grayscale 800×500 are separate outputs.

Direct native inspection, without whitening/thresholding/cosmetic repair:

| Case | LoRA observation | Remaining blocker / own decision |
| --- | --- | --- |
| Fan | background grid disappears; broad outline mostly retained | gray canvas, dark blades/base, edge noise, unverified mechanics; REJECTED |
| Plant | bars disappear; four leaves and overall layout persist | gray/halo, dark leaves, altered root branching; REJECTED |
| Scooter | background bars removed; side arrangement mostly retained | gray/rough doubled contours, altered handlebar/wheel/light marks; REJECTED |

Both arms are rejected for all three cases. LoRA edge fractions decrease
171→42, 149→46, 141→33 per mille, but mid-tone fractions increase
832→922, 869→964, 950→977. Nonwhite backgrounds make canvas foreground
990–1000 per mille for LoRA. These metrics do **not** prove useful object
simplification or science accuracy. Cleaner TRAIN inputs alone did not remove
the failure in this small cohort; this is an observation, not a causal proof.

CPU regression: **386 PASS / one explicitly deselected pre-existing failure**.
The unfiltered run's unchanged Orchestrator→Catalog import violation in
`source_page_crop_expansion_inputs.py` is retained as separate maintenance work,
not reported PASS. Nine changed source modules pass strict mypy; lint/format,
shell syntax, diff, wheel resource/RECORD and actual worker CPU imports pass.
Actual installed replay passes for new six outputs/three conditionings, old
38-target training, old six BASE/six LoRA and four learned-comparison outputs:
zero model calls, no Torch import, no files changed. Failed prefixes, changed
hashes, duplicate targets, unreceipted outputs and time/memory ceilings are tested.

Lab contracts/provider only: source `7cda7e33`, wheel SHAs
`b002c75e04900f01436631f6acc449b647aeec7dc6dd4caa08d955c1d5bcec55` /
`881afc0cca2893455d6af2b7afa2fb8d40a36613f256e7fc170f8e1a775df368`.
The `cf6746ae` trainer and rollback wheels remain; operating V6 hash
`f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`
and five services are unchanged. No restart, extra training or production activation.
Own review and sample materializations:
`/tmp/eom-sdxl-target-comparison-own-review-20261004.json`,
`/tmp/eom-sdxl-target-comparison-samples-20261004/`
`{pedestal_fan,flowering_plant_with_roots,kick_scooter_wheel_lights}-{base,lora}-104729.png`.
Independent review NOT_PERFORMED; no Item/Preview/HWPX canary or quality activation.

Durable metadata/operator/log archive: **19** members, zero PNG/weight duplicates,
all registered bytes checked; `artifact_c9a944fd889f496fb93161e4d66dcbbe` /
`rev_c4236d934fdb4cd688b54b3d7a16a9bb`, primary
`reports/own-comparison-review.json`, raw SHA
`sha256:e21ea4b8440b60df16c3dc00a330f5f2a2b99ab91b5034ef4b7d4a3ee3ba7e7b`.
Archive owner source `6dbf6085` and generation source `7cda7e33` are recorded
separately. Initial archive preflight refused the archive guard script's own
literal secret-marker strings before any publication; that failure is preserved.
The guard script was excluded, not the guard weakened. No GPU/training replay or
historical-result modification occurred. Slack checkpoint `devreport_365de099f0d841f7b46569406df9d93d`
was SENT (HTTP 200), explicitly reporting quality REJECTED and full goal ACTIVE.

**Next:** first compare the pinned implementation/preprocessing/decoder assumptions
with primary sources, preserving current native bytes and policy meaning. The
[model card](https://huggingface.co/TencentARC/t2i-adapter-lineart-sdxl-1.0)
describes bright outlines on dark conditioning; its example uses
[controlnet_aux 0.0.7's actual detector](https://raw.githubusercontent.com/huggingface/controlnet_aux/v0.0.7/src/controlnet_aux/lineart/__init__.py),
which inverts the network output after resizing. That is not evidence by itself
that EOM's final polarity is wrong. No new dependency/download or polarity change
was made. If source parity admits it, freeze a **distinct T2I-zero matched control**
using the existing numerical baseline/evaluation/target contracts, same selected
targets/captions/seed, new pinned numerical-command identity and a separate quota.
Do not fabricate historical use of the new setting or rerun an exhausted cohort.
This control tests whether adapter conditioning contributes to the gray surface;
it does not imply shape preservation/quality PASS and does not justify more training.

### Actual same-input T2I-zero control, 2026-10-04

Test-only source `fabe6288` verifies that both conditioning scales 0.0 and 0.8 reach
the existing numerical pipeline, including prompt/shape/numerical/error/cleanup
cases. Focused tests **75 PASS**, Ruff format/lint PASS and strict mypy on three
unchanged numerical/contract source modules PASS. The first test invocation used
a nonexistent filename and ran zero tests; its error is retained, not a source
failure or a live attempt. The earlier unrelated dependency-boundary violation
is unchanged and is not reclassified as PASS.

No schema, dependency, worker behavior, package installation, queue, migration or
production activation was added. The lab still uses contracts/provider source
`7cda7e33` and the `cf6746ae` trainer; exact installed wheel/RECORD verification
passed without mutation. A frozen intent precedes new command publication, and
the final frozen plan precedes staging/dispatch. Original case/reference PNG
revisions, captions, negative prompts, seed 104729, 30 steps, guidance 7.0,
LoRA strength 1.0 and conditioning policy are identical to the preceding pair.
Only numerical T2I conditioning scale changes 0.8→0.0; command identities and UTC
timestamps change accordingly. Both tokenizers remain at maximum **67/77**.

New baseline command 1.0 `artifact_f42ef1ec2beb41f4a1c31c6eb2db1cdd` /
`rev_631253c04d714a7fbbfab314c8e314c2` and evaluation command 1.1
`artifact_5a22ecff7769480da52bce1722cd114d` /
`rev_54b66045670e4c17b342ba65c227ba6a` are numerical provenance pins only.
Neither original six-case baseline nor six-case LoRA evaluation was dispatched;
no historical result is claimed to use the new setting. The target-comparison
command pins that new evaluation and uses the same three actual prepared targets.

Run `imgsdxltargetcmprun_58762fd0eecb14b520ceba5ef77b6ccc` completed **6/6** in
**28,964ms**, peak allocated GPU **8,328,740,352 bytes**. Its independent six-output
quota is exhausted; all old quotas stay exhausted. Command
`artifact_954b75a5ebf648289f510416b5f13130` /
`rev_2f41969e3f9d448fb032de37b7d8bc7d`, raw SHA
`sha256:8be43c8615f7861318fbaf3066f4436336202c0b70279254d7f86be20c3bc23f`.
Result `artifact_afd93f6fc56b44fba1ba8d468ad865d2` /
`rev_8c0380d5c4cb48a79f5fe63625e5f638`, primary
`manifests/sdxl-target-comparison-result.json`, raw SHA
`sha256:7094159a2b47d7076323fff7fe06fb4cdca53fb0e44d610e7476967f8c62d7da`,
semantic SHA `sha256:cad3270062fd7191977807a1607f548edffec63a5429c67aaf3a8d52a90f3d65`.
All 16 receipt/conditioning/raw/final members match canonical registered bytes.

Native inspection of all six outputs, actual targets and preceding LoRA images:

| Case | Zero-control observation | Own decision |
| --- | --- | --- |
| Fan | BASE makes three views; LoRA makes two fans with split gray/white canvas | REJECTED: one source object and arrangement lost |
| Rooted plant | both arms make two enlarged flowers without the four leaves/root system | REJECTED: required scientific parts lost |
| Scooter | BASE is malformed; LoRA recognizes a scooter but changes handlebar/light marks and adds ground/gray gradient | REJECTED: source semantics/layout and white canvas fail |

LoRA mid-tone fractions change 922→523, 964→454 and 977→796 per mille.
These are descriptive metrics, not quality acceptance. T2I conditioning contributes
to the observed surface/layout behavior in this three-case/single-seed control,
but is not demonstrated to be the sole cause. Removing it is not a usable repair:
gray areas remain and composition is no longer conditioned. White decoded regions
also do not, by themselves, establish or exclude a generic decoder defect.
No whitening, thresholding or cosmetic edits were applied.

The [pinned model card](https://huggingface.co/TencentARC/t2i-adapter-lineart-sdxl-1.0/raw/5f1f33b049b96fa599f0aa3d77b31dbef5095e97/README.md)
and [actual upstream conditioning image](https://huggingface.co/Adapter/t2iadapter/resolve/3c291e0547a1b17bed93428858cdc9b0265c26c7/figs_SDXLV1.0/cond_lin.png)
both support bright contours on a dark background. The example's downloaded and
revision-pinned bytes match SHA
`sha256:d6fa8c2936da8e279e567375736a8f62c53ed48ae046f7d33e86a1b57f9e9b5f`.
It was viewed solely as a source audit: not a training/reference/model input.
The [pinned detector implementation](https://raw.githubusercontent.com/huggingface/controlnet_aux/v0.0.7/src/controlnet_aux/lineart/__init__.py)
inverts after resizing. This audit does not justify silently flipping current
polarity or changing an old policy. Detector quantization/resolution and actual
conditioning distributions remain separate possible factors, not proven defects.

Actual installed replay validates new and parent six-output results without
models, GPU acquisition, Torch import or file changes. Five production services
stay active; operating V6 binding SHA remains `f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`.
GPU idle after completion. Independent review NOT_PERFORMED; Item/Preview/HWPX
canary and activation NOT_PERFORMED. Total 60 own-REJECTED outputs is not a blind
test denominator or a generalization score.

Own review/sample copies: `/tmp/eom-sdxl-target-zero-own-review-20261004.json` and
`/tmp/eom-sdxl-target-zero-samples-20261004/` with the same three depiction names
and BASE/LORA arms. Durable metadata/log/operator archive: **16** verified members,
no duplicate PNG/weights; `artifact_fc1dfc5ee75045a2a1bee32e480452ef` /
`rev_a1cbc922468d4fdeb01a9908b657263b`, primary `reports/own-comparison-review.json`,
SHA `sha256:1c5abcb670bbd676f8ebfcda0b6fcab0fd972f8e2d16d926fd7aae2df909b9de`.
Archive/operator source `fabe6288` is separate from numerical source `7cda7e33`.
Slack `devreport_f7ff7e6c418441a08568a34aa11b2fb7` SENT, HTTP 200; checkpoint
completion explicitly leaves full GOAL ACTIVE and quality REJECTED.

**Historical next proposal, executed below:** freeze one distinct midpoint T2I-strength
control **0.4**, at most six
outputs with these same inputs/seed and no additional training. Judge one-object
counts, the exact required leaves/roots/light marks, layout and native white
canvas together against 0.8 and 0.0. This control is proposed, not submitted.
If it fails, stop an open-ended strength sweep and audit the background prompt/
conditioning distribution before selecting one further factor. Do not obtain a
quality PASS by discarding required parts, repainting backgrounds or redefining
historical contracts/results.

### Actual midpoint, negative-clause control and CPU publication viability, 2026-10-04

Source `c2e347520580348f60a2d4ec19f0125196ddf0e7` adds only backend passthrough
coverage for 0.4 alongside 0.0/0.8. Focused **82 PASS**, strict mypy on three
unchanged source modules PASS, operator formatter/linter PASS. No schema, worker
behavior, new dependency, installation, queue, migration or operating activation.
Lab contracts/provider remain `7cda7e33`, trainer `cf6746ae`; actual RECORD/pinned
wheel verification is reused without invoking installation. The unrelated existing
Catalog infrastructure import-boundary failure remains separate and unresolved.

#### Frozen midpoint control

One new pair uses the same three prepared TRAIN targets, captions, negative
prompts, seed 104729, 30 steps, guidance 7.0, LoRA strength 1.0 and conditioning
policy. Only T2I scale 0.8→0.4 and new identities/timestamps change. New numerical
baseline/evaluation pins are metadata, not dispatches of their legacy six cases.
Frozen plan SHA
`sha256:dfb5f1b28fd9a15dc29cc4efab706d3c9e957f728b488dc778ef9b84b98654cf`.

Run `imgsdxltargetcmprun_296c46c29abc9d11d763d3f0b4d61814`: **6/6 outputs**,
**29,526ms**, peak allocated GPU **8,328,740,352 bytes**, all 16 published members
equal workspace bytes. Command `artifact_a5cfac85f7a847ea97685dd50ea9d49f` /
`rev_ad32a9939bf9426ca3493ea98301df6c`, raw SHA
`sha256:41911f02bf746db80571302dcbfad76ba8abc0969c2bc63d997924c912bb9851`.
Result `artifact_998e7104532244eb817d4aa2341207d6` /
`rev_6185828e898649aba0c6e20c10e98b25`, member
`manifests/sdxl-target-comparison-result.json`, schema `/1.0`, raw SHA
`sha256:9c640d80ddbe58a84027dfb8bae3e5bba3eec6616b6c329b6d155957d6c97ee5`,
semantic SHA
`sha256:446e0b50792e91f7b870b23c962280e74bf3b0d78b268622b0bbab57f07c3440`.

All six native images were directly inspected. Both fan arms multiply source
objects; both plant arms invent extra flowers/plants and change roots/petals.
The scooter gains background objects or retains gray canvas with incorrect
handlebar/wheel-light contours. BASE plant has a lighter background but wrong
source composition. All six REJECTED. None of the tested 0.8/0.4/0.0 settings
satisfies style and source meaning together. This bounded three-TRAIN-case,
one-seed observation closes this strength sweep; it is not a holdout score or
proof of a universal decoder/adapter defect.

#### Single-clause negative control

One distinct pair removes only the exact comma-delimited `nonwhite background`
clause from each negative prompt. All source/reference/positive-caption/model/
LoRA/seed/numerical values equal the original T2I-0.8 pair. New case IDs, prompt
hashes and staged member names truthfully reflect the prompt change; **all case
values are not claimed unchanged**. Both tokenizers max **63/77**, down from 67.
Team prompt original files and operating prompts are unchanged. Frozen plan SHA
`sha256:a247c52ec8dcd225ba8e2ee89df08cca11ce305091e80117415a1fa800e9ea3a`.

Run `imgsdxltargetcmprun_11f4da73e87b992dff1592dd3c521cb7`: **6/6 outputs**,
**29,705ms**, same 8,328,740,352-byte peak, all 16 canonical members verified.
Command `artifact_553279db48fa461f92936d49216229d0` /
`rev_791998adf3904d1a960dc7b3c2d81c42`, raw SHA
`sha256:9faec6fc71d9231cb6775466bdf29f04921c88dd8d307be5a17860507f1e5d04`.
Result `artifact_cf4250d995314afea0e4d3f175991e99` /
`rev_c9f96b1139a1453ea6a5cd8a8ba3ca82`, same result member/schema as midpoint,
raw SHA `sha256:1c11a4d642bbbb3b7e746ae68e9fa5eaffc97cafb976fd1c3a4448952486637c`,
semantic SHA
`sha256:6e6e8bbec38e4629d3ab3ce0a9e74d2bc4a7571f3097137ace443ebbb7a36f6c`.

Direct native inspection again rejects all six. LoRA gray canvas is nearly
unchanged; BASE still has grid/extra objects/halos, while required plant roots,
fan details and scooter light marks remain inaccurate. Do not claim this clause
as a demonstrated cause or promote its removal into production. New outputs
12, new training/reserved reads/retries 0, total actual SDXL 72 all own-REJECTED.
Both new quotas and all historical quotas are exhausted.

Actual installed replay checks negative/midpoint/zero/original target cohorts,
each six outputs/three conditionings, with model/backend/GPU entry points denied.
No Torch import or workspace/hash/mtime change. Five production services ACTIVE,
GPU idle 2MiB/0%; operating V6 raw binding SHA unchanged:
`f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`.

#### Frozen V7 CPU viability, not derived-output acceptance

The original approved research plan includes publication cleanup. A read-only
Orchestrator diagnostic resolves the initial T2I-0.8 command/result and six
native PNGs by exact Artifact/revision/schema/media/raw SHA, verifies workspace
bytes against canonical members and calls the existing public pure cleanup.
No old receipt/output is modified, derivative PNG written or new model acquired.
The lab's actual installed Pillow **11.3.0** is used, not image-test's 12.3.0.
Implementation raw SHA is
`sha256:31f097ed863c0859d4d675fc480da39d7912a57aa1e4cebf9ffe2e08c86b2ecb`.

Config source is an immutable `c2e34752` Git blob, raw SHA
`sha256:45c02d40fead0986a1adbbc470e50ef953b4eda6eea7c89024c07b9d1ece9243`;
its postprocess value is validated with the existing JSON Schema 2020-12 fragment
and frozen Pydantic model. Policy semantic SHA
`sha256:2e76d2456fa719ed0791d256008e02a68ad0bf6642a1359811cd1705250abc33`.
Policy settings are unchanged; no threshold search, learned transform, GPU or
training. Existing pure postprocessor tests **4 PASS**, reported separately from
the 82-test source suite, not added as a new unique aggregate.

All six CPU computations pass fixed foreground/border/edge/detail bounds.
Computed LoRA foreground fractions are 0.0521125 / 0.0715175 / 0.049005, versus
native 0.9999725 / 0.9944825 / 0.98984. Border foreground becomes zero. Every
computed derivative contains only gray 96 and white 255, not dark 32. Thus this
is **technical viability**, not proof of readable black strokes, restored parts,
source composition, visual or independent quality. Quality NOT_EVALUATED; saved
PNG count 0. Wrong/missing roots, leaves, light marks and duplicate objects cannot
be repaired or excused by a white-background metric.

#### Evidence and next boundary

Own judgments, plans, pointers, operators, focused/type/replay logs and CPU
diagnostic are archived as **30** verified metadata/log members, zero duplicate
PNGs/weights: `artifact_560d8f90194b4ae29a9d50c595818c33` /
`rev_15580007808b46be916bdcd4cd1809f4`, primary
`reports/own-comparison-review.json`, raw SHA
`sha256:bf68e81d5fb92df43346600725857f68577bcf80febdaa98ed03b556d3008dc9`.
Operator/archive source `c2e34752` remains distinct from generation source
`7cda7e33`. Development prep corrections did not rerun a dispatched cohort or
alter failed/historical records. Slack `devreport_7362ee3676fb4b889bfeffbaf8536325`
SENT, HTTP 200; full GOAL remains ACTIVE, independent review NOT_PERFORMED and
Item/Preview/HWPX canary/activation NOT_PERFORMED.

Local own reviews: `/tmp/eom-sdxl-target-midpoint-own-review-20261004.json`,
`/tmp/eom-sdxl-target-negative-ablation-own-review-20261004.json` and
`/tmp/eom-sdxl-v7-postprocess-viability-20261004.json`. Native AI viewing copies
use `/tmp/eom-sdxl-target-{midpoint,negative-ablation}-samples-20261004/` with the
same three depiction keys and BASE/LORA arms; these are not publication-cleaned
samples or newly eligible training targets.

Next: [ADR 0190](../adr/0190-pinned-sdxl-publication-derivatives.md) proposes a closed
CPU derivative command/result and isolated execution over these pinned native
outputs with the unchanged V7 policy. Define the wire contract before worker
behavior; reuse existing cleanup/handoff/commit owner, not a second framework.
Then register distinct candidate PNGs and inspect source/native/derived details.
This boundary is **NOT_IMPLEMENTED** here. No new GPU strengths/seeds, negative
guessing, training, model acquisition or operating activation is granted by the
successful CPU viability test. Keep native 72/72 rejected history unchanged.

### CPU publication derivative source implementation, 2026-10-04

[ADR 0190](../adr/0190-pinned-sdxl-publication-derivatives.md) now has a source
implementation; the NOT_IMPLEMENTED statement above is its preceding checkpoint.
Closed JSON Schema 2020-12/Pydantic command and result precede the CPU worker.
Both metadata resolvers reuse full source, split, review and adapter provenance;
native pixels are resolved only after that admission. The new workspace stages
metadata and at most six native PNGs, not source PDFs, targets or model weights.

The existing pure postprocess/2.0 pixel algorithm and all frozen settings remain
unchanged. Its six style invariants have one typed contract rule shared by the
old V7 receipt, provider and new derivative result. Existing error messages and
stable provider codes remain supported without matching human text. Native
outputs/receipts and all released schema bytes are preserved.

The CPU worker rejects runtime mismatch before creating outputs. It records a
bounded successful set or failed prefix; technical success remains UNREVIEWED
and activation FORBIDDEN. Exact replay checks parent history, all input/output
hashes, grayscale tone/dimension/mode and output membership, with zero transforms
or writes. Extra files, unsafe links, group-writable inputs, stale source,
unreceipted candidates and wrong policies cannot trigger silent regeneration.
The existing exclusive handoff and publisher are reused, with a fixed private
CPU-only systemd template. No new DB/migration/queue/dependency/model/GPU call.

Source gate: **242 PASS**, one explicitly deselected pre-existing Catalog import
boundary violation. Strict mypy on **13** core modules, formatter/linter, shell
syntax and systemd template verification PASS. Early fixture-construction and
static typing corrections happened before any install or live dispatch; their
failure logs remain separate, not relabeled successful runtime attempts.
Lab installation, six-output CPU execution,
canonical derivative publication and direct source/native/derivative visual
review are PENDING. Operating V6 and all previous model outputs are unchanged.
The separate pre-existing Catalog infrastructure import violation remains open;
no filtered source suite is represented as repository-wide PASS.

### Actual CPU derivative publication and rejection, 2026-10-04

Core source `30ae15d5`, immutable packaging source
`f14d2824dfe54791760cb3618632d9c9e6314ab9`. Only contracts/provider in the
numerical lab and the fixed CPU template were installed. Installed wheel RECORD,
actual worker import without Torch, `pip check`, private unit verification and
five production services pass. Trainer remains `cf6746ae`; operating inference
environment/configuration remains unchanged. Rollback contract/provider wheels
from `7cda7e33` are retained with exact installed bytes/raw hashes in install
evidence. No enabled daemon, restart, privilege/group change, DB migration or
weight acquisition. The first build preflight rejected an unstaged packaging
file before building; its reviewed packaging additions were committed separately
and the clean immutable build passed. No live operation was repeated for that.

Frozen plan SHA
`sha256:dcd42e86b72f09d39f03fd1b3806a9c1d47e9bc58eb4ba3caaf4257753f8bdf5`.
Command `artifact_18d7930291b04e07ae6372310e3495f6` /
`rev_3df7f9498a444918a57fa92fe2344851`, member
`manifests/sdxl-publication-comparison-command.json`, schema `/1.0`, raw SHA
`sha256:433ba152b1f4013820ab81f1014445e369b15ae2e5293d0bd90fd917664be158`.
It pins initial target-comparison command/result and unchanged postprocess/2.0
semantic SHA `sha256:2e76d2456fa719ed0791d256008e02a68ad0bf6642a1359811cd1705250abc33`,
Pillow 11.3.0, one CPU run/six derivatives and zero model/training/reserved reads.
Publication validation has a separate six-reconstruction CPU quota; replay has
zero transforms. Installation's existing GPU-inode mutex protects package
quiescence; the CPU worker does not acquire or use a GPU.

Run `imgsdxlpublicationrun_21d8ea22501a745ce42527805b44f7e6`:
**6/6 derivatives**, **3,276ms**, private oneshot terminal success/exit 0.
New result `artifact_d455a78e4e014eeeb561c987237a8094` /
`rev_23c2cb2c755f42cabde1785c8b1a68d0`, primary
`manifests/sdxl-publication-comparison-result.json`, schema `/1.0`, raw SHA
`sha256:0e853f970f35075a40d6bc951875d8342e2d02d93fee5c80fb0de2169aa2ff06`,
semantic SHA
`sha256:5cb09e27311fa59da98120257f44e16c1b998a644b56da50318d9f7dc9da6178`.
All seven committed members equal staged bytes. Installed-role reconstruction
reproduces six PNG hashes/metrics and the preceding diagnostic exactly. The
new pure implementation file SHA is
`sha256:2d59c08241d49772a9a24abd510d3cc2bcc4f245de27f2cde293bc41bfee9038`;
it differs from the prior file because policy validation is shared, not because
the frozen pixel algorithm/settings changed.

Actual worker replay verifies exact source and output closure without transforms,
Torch, model/GPU entry or file/hash/mtime change. All four historical target
cohorts likewise replay after installation with model/GPU entries denied.
Five production services ACTIVE, GPU idle 2MiB/0%; operating V6 raw binding SHA
`f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845` unchanged.

#### Own native-resolution source/native/derivative decision

All three exact source targets and all six native/derived images were inspected.
Source viewing hashes match pinned prepared targets. Every derivative has only
tones 96/255 and zero border foreground; these technical checks do not make the
images usable. **Own quality 0/6 accepted, 6/6 REJECTED**:

| Depiction | BASE derivative | LoRA derivative |
| --- | --- | --- |
| Pedestal fan | Background grid/lines remain; fused blades/grille | Cleaner canvas, but hub/grille separation lost and jagged filled contours |
| Plant with roots | Background bands and invented root shape | Four rough leaf positions remain; petals, veins and root topology fuse/erase |
| Scooter wheel lights | Background bands, malformed details and no light marks | Rough single-scooter pose remains; spokes/light marks/handlebar details disappear |

Do not repair these judgments with threshold/tone/seed tuning or claim missing
parts were restored by whitening. Original 72 native judgments stay REJECTED;
the six derivatives have distinct Artifact identity and are not six new model
calls. Independent/heldout judgments remain NOT_PERFORMED; Item/HWPX canary and
activation remain gated on genuine scientific/visual quality.

Viewing copies (unadopted diagnostic samples):
[fan](/tmp/eom-sdxl-publication-samples-20261004/pedestal_fan-lora-104729.png),
[plant](/tmp/eom-sdxl-publication-samples-20261004/flowering_plant_with_roots-lora-104729.png),
[scooter](/tmp/eom-sdxl-publication-samples-20261004/kick_scooter_wheel_lights-lora-104729.png).
All six variants and source/native links are in
`/tmp/eom-sdxl-publication-own-review-20261004.json`. These are workspace views;
the registered revisions above remain canonical. Human checks are deferred to
the final combined reviewer packet, not counted as PASS now.

Own review, frozen plan, source/preflight failures, successful build/install,
operators, reconstruction/publication/replay logs and Slack checkpoint are
archived as **24** verified non-binary members, no duplicate PNG/weight files:
`artifact_73e58cbe825040ecbf252f067989548e` /
`rev_97b0f22ea07c47b6a2f5b907f575a7f2`, primary
`reports/own-comparison-review.json`, raw SHA
`sha256:2bdfaf6d6d4c1bb6cee296cbdf638f84a378fe9857f7a0d932fd50f90ed8c9a1`.
Slack `devreport_f964351c1efa4f20b64ac88e94675d6f` SENT, HTTP 200; checkpoint
completed, full GOAL ACTIVE. Next: choose one bounded spatial-conditioning
alternative with explicit license/model/file/source/resource pins before
acquisition, using step 6's existing fallback scope. No new model was downloaded
or dispatched by this checkpoint.

The initial **14:54 UTC read-only proposal**, retained as history, is
[ADR 0191](../adr/0191-bounded-sdxl-spatial-conditioning-alternative.md):
one SDXL Canny ControlNet factor, not ControlNet plus IP-Adapter plus retraining.
Read-only preflight at 14:54 UTC records exact model revision/configuration/expected
safetensors SHA and an optional headless OpenCV wheel in ADR 0191. It detects
inconsistent upstream model-card base metadata and does not substitute the
existing base license as proof for the controller. Controller license-text proof,
new contracts, actual optional-library compatibility and conditioning execution
remain pending; no weight or library was downloaded/installed. Three
source-conditioned edge maps must retain required details before
any weight acquisition/GPU request. First pair is proposed at six new outputs
within the existing fallback ceiling, not submitted. Current library metadata
was checked without Torch import, weight reads or model calls; research/proposal
does not grant a numerical PASS or a fresh retry quota.

At the later **16:02 UTC checkpoint**, CPU preparation and optional-library
compatibility are no longer pending: source `b1e4a36e`, three committed maps,
own input-detail3/3 PASS and installed reconstruction/replay PASS. Evidence
`artifact_605737dbd28c4c92a8ac1729b67fca52` /
`rev_ed711467c73f4334bea6ab14532c8c10`, 26 members, primary
`reports/own-input-review.json`, SHA
`d6f6877ad2fa0542356455476da8a83d82552408dfe5764e9637652a93c8b478`.
No duplicate binary members. Exact recipe, installation/version pins, source-
detail findings and old preflight failures are in ADR 0191. The controller license,
model/comparison contract and first six-output numerical run remain pending;
this checkpoint is not a substitute for the full quality goal.

Completed source checkpoint: JSON Schema 2020-12 and frozen Pydantic split contract, bounded
union-find grouping by PDF logical identity, PDF byte hash, exam group and reviewed duplicate
cluster, deterministic assignment and propagated pinned holdout groups. Input is limited to 10,000
samples; shortages remain `INSUFFICIENT`. Canonical/packaged resources and release inclusion maps
are aligned. Focused regression suites: 83 PASS, including 30 split tests and a 10,000-member
synthetic grouping case. Ruff format/lint, targeted mypy and release-shell syntax checks PASS.
An initial broader test collection used the API environment, which has no Pillow; it was rerun in
the explicit image-test Conda environment without changing the production API dependencies.

The additive SDXL stack contract in ADR 0176 now pins base/lineart adapter/fp16-fixed VAE roles,
upstream revisions/licenses, required sorted local members and component/stack hashes. It rejects
SSD-1B substitution, pickle/executable files and incomplete component sets, and permits evaluation
only (`activation_policy=FORBIDDEN`). Thirty additional protocol tests PASS; the five related suites
now total 113 PASS. Runtime implementation and architecture/tensor verification are still pending.
The first split checkpoint `80c65cdc` also passed the normal provider/contract wheel build; no
operating environment was installed by that build.

Public upstream metadata was read on 2026-10-03, without downloading weights:

- SDXL base: `462165984030d82259a11f4367a4eed129e94a7b`;
- TencentARC lineart adapter: `5f1f33b049b96fa599f0aa3d77b31dbef5095e97`;
- fp16-fixed VAE: `207b116dae70ace3637169f1ddd2434b91b3a8cd`.

These are acquisition candidates, not installed component/weight hashes. The first bounded
diagnostic can use already-approved lineart PNGs and explicit polarity conversion. Photo-detector
weights remain subject to provenance/license verification: the hub's aggregate `other` license
does not establish the individual weight permission merely because the implementation is MIT or
Apache-2.0. This narrow prerequisite does not stop the preprocessed-lineart comparison.

Direct inspection of the approved vehicle, plant and animal members shows different rendering
grammars (gray gradients, thin botanical contours, dense hatching). The animal crop still has an
original choice marker. Approval/identity validity is not a promise of text-free, homogeneous
training pixels. Keep these originals and historical partitions immutable; record text masking or
derived crop decisions and separate expression types before training. Do not count a recrop as a
new independent source document or move an old holdout into train.

Next is the bounded experiment command/result contract and safe isolated weight staging, then
six-subject comparison. GPU training, the 42-output pilot, blind-review decisions and live
activation are pending. No dataset split Artifact has been published by this source checkpoint;
the pure split function does not resolve permissions or publish bytes itself. Important
completion/blocker milestones go to Slack; routine progress is kept here.

The technical candidates and upstream sources are recorded in
[the research document](../references/SCIENCE_ASSESSMENT_IMAGE_MODEL_RESEARCH_2026-10-03.md).
Existing institutional comparison evidence remains in
[the candidate status](../status/INSTITUTIONAL_IMAGE_STYLE_CANDIDATE_2026-10-02.md).

### 2026-10-03 isolated diagnostic checkpoint

The bounded base-only command/result and compiled-prompt provenance schemas now have an offline
provider implementation. Staged reference/command/policy hashes, dimensions, exact model membership,
architecture, prompt capacity, finite numeric outputs, measured duration/VRAM, terminal partial
failure and zero-inference replay are checked. The shared prompt-capacity rule is reused by the old
SSD-1B backend, not reimplemented as a version-specific repair. Scientific labels and geometry
remain outside the model. The optional systemd oneshot keeps the existing private identity,
GPU lock, offline network and NAS/secret/repository restrictions. No new queue or daemon exists.

The evaluation-only stack was installed into the existing protected model store with 24 pinned
members (7,266,590,927 bytes). Identity is `imgmodel_88a4de9207f4da7ab4e77de2478cd64e`,
revision `imgmodelrev_f0cf22164fb6a9171ddbcd13c88270da`, manifest
`sha256:abde5fe212767a675bf91b9d3a2e5c85a96950e186bd2b950607c8387d148280`.
These are installed hashes, not merely upstream candidates. Production binding remains V6.
This checkpoint does not mean the candidate runtime was installed or GPU inference/training ran.

Six proposed TRAIN-only diagnostic subjects are a microscope, burner/vessel, protective glove,
radio, deciduous tree and trilobite. Existing Catalog prompt policies 1.7 and 1.8.1 both fit the
two real 77-token encoders (positive 36–54, negative 63–67 tokens for these subjects). No prompt
truncation was needed, and no production prompt was changed. References still require visual
inspection before final selection, and HOLDOUT/VALIDATION stay unused for tuning.

Focused source checks at this checkpoint: 125 tests PASS (including split regression), Ruff and
targeted strict mypy PASS; shell syntax and systemd template verification PASS.
The first broader image suite overlapped a schema/fixture edit and recorded 4 failures / 179 PASS;
the final-source rerun passed all 191 tests after aligning the command's 1,800-second cap with the
1,830-second isolated timeout. This is not a GPU or operating incident.
The original corpus permission explicitly allows internal SSD-1B LoRA only. The user has been
asked to extend it to internal SDXL comparison/training. Until that reply is recorded, no approved
exam crop is submitted to SDXL and the prior permission is not reinterpreted. Sudo authentication
permits protected installation, not an implicit expansion of the corpus-use scope.

### 2026-10-03 Orchestrator admission checkpoint

The new read-only input preparation use case resolves the exact approved crop/prompt-policy
revisions through the existing Orchestrator resolver. It verifies original authorization,
inventory/review, campaign plans/results and TRAIN-only membership before materializing any PNG.
Wrong source revisions, hashes, dimensions, duplicate references/depictions and reserved partitions
fail explicitly. It returns at most eight ordered staging members; it does not dispatch a worker,
write DB rows or publish image bytes. Compiled policy/command metadata publication reuses the
existing idempotent Orchestrator publisher, not a second NAS writer or queue.

Admission and the existing resolver/publisher/corpus/split/stack/dependency/environment regressions
passed 152 tests, including the final timestamp-edge test; Ruff and targeted strict mypy passed.
This is synthetic source evidence, not a live corpus submission. The earlier diagnostic wheel also
passed 74 tests using only extracted
wheel packages, without source-path imports. The provider wheel and optional SDXL unit are not yet
installed. GPU inference, micro LoRA, expanded data, blind review and production canary remain pending.
The explicit SDXL corpus-use extension is still awaiting the user's reply; no historical approval
or existing production binding has been changed.

### 2026-10-03 SDXL scope extension

The user replied `승인할게` to the explicit internal SDXL comparison/LoRA question, recorded at
2026-10-03 18:35:22 UTC. This approves `INTERNAL_SDXL_COMPARISON` and
`INTERNAL_SDXL_LORA_TRAINING` for the same internally approved exam material. It does not authorize
raw-source export, external processing or automatic operating-model activation. The original
SSD-1B authorization stays immutable; the new scope/time/user-message hash is pinned separately in
each SDXL provenance/command. The preceding pending statements describe earlier checkpoints, not
the present approval status.

### 2026-10-03 SDXL micro protocol checkpoint

The additive micro command, adapter manifest and result families pin the SDXL stack, new corpus-use
approval, original crop revision/captions, exact 16 TRAIN members and reserved 4/4 partitions.
They record derived-pixel hashes separately and forbid operating activation. Existing object-line-art
partition validation is reused without changing released schema bytes. The three JSON Schema
2020-12 resources are mirrored in contract wheels and release verification maps.
The selected protocol/admission/split/dependency regressions passed 132 tests; Ruff format/lint,
targeted strict mypy, release-shell syntax and diff checks passed. These are synthetic source
checks only: the SDXL-specific training backend, GPU micro-training and measured quality remain
pending. No adapter or operating binding has been replaced by this checkpoint.

The private Orchestrator staging/dispatch adapter now creates only exclusive pinned-run workspaces,
checks every input against the command, preserves partial handoffs and addresses a fixed offline
systemd unit. The presentation script delegates admission, staging and dispatch rather than
reimplementing crop rules. Focused handoff/admission/micro/dependency checks passed 71 tests,
including 14 new filesystem/dispatch tests; Ruff and targeted strict mypy passed. Initial test
invocation/fixture-order issues were corrected before this final run. No GPU execution is implied.

### 2026-10-03 isolated runtime and live input preflight

Candidate provider/contract wheels from `6c90270a` were installed into the existing explicit image
environment with the optional offline SDXL unit only. Wheel/installed RECORD byte verification,
actual image-identity imports, CUDA availability and `pip check` passed. The protected V6 binding
hash remained `f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`.
No group/polkit/operating-unit/control-policy change or restart was performed. The previous exact
`fc0b78c5` provider/contract wheels remain hash-verified rollback inputs.

All six proposed references were inspected: several retain gradients, photograph-like texture,
clipped contours or original redaction marks. Approved provenance is not homogeneous line-art
quality; these distinctions must be preserved in training selection and comparison records.
Live admission found three historical pilot receipts with one canonical terminal newline. The
new resolver now accepts that existing representation without rewriting bytes or hashes; compiled
SDXL provenance remains strict canonical JSON. Extra whitespace/double-newline still fails.
The 84-test final handoff/admission/resolver/publication/micro/dependency regression passed,
with Ruff and targeted strict mypy. This preflight discovery caused zero model calls; the already
committed compiled prompt policy is retained and replayed through its same publication identity.

The first fixed-systemd dispatch failed at command-file admission, before output-directory/model
creation (19:12:51 UTC; zero generated outputs and no worker result). The new descriptor walker
incorrectly required read/list permission on traversal-only `/srv/eom` (0711). It now uses Linux
`O_PATH` for no-link ancestor traversal and opens only the actual target for bounded I/O. Ancestor
permissions, worker privilege and production binding are not expanded. The failed unit/workspace
is retained; the corrected runtime is tested before a deliberately pinned successor experiment.
The 51 probe/model/acquisition/backend tests passed, including an execute-only ancestor regression.
Ruff format/lint passed; targeted strict mypy uses the image-test interpreter with silent checking
of unchanged imports. Broader imported legacy Pillow annotations exposed existing errors and are
not represented as a whole-package mypy PASS.

### 2026-10-03 first measured SDXL diagnostic

The corrected, deliberately new run `imgsdxlproberun_8b2b08110e6462366b1346dca1284a0a`
completed all six TRAIN subjects at seeds 104729/130363: 12 model outputs, 49,799 ms overall,
8,280,481,280 bytes peak GPU allocation. Actual worker runtime was Python 3.11.15,
Torch 2.7.1+cu128, Diffusers 0.35.2, Transformers 4.56.2 and RTX 5080/CUDA 12.8.
The fixed inputs used 30 steps, guidance 7.0 and adapter scale 0.8. Production binding and
service availability were unchanged; no LoRA was loaded or trained.

Canonical command: `artifact_fd83bbb76bca49fea6401bf06094560f` /
`rev_b00fe42acc524532908bbfd6fd7f33ad`,
`manifests/sdxl-lineart-probe-command.json`, raw member SHA
`sha256:1fe831027f688dbc607535bf29e35e2c3f156024978c8955645d41936442a695`.
Command semantic SHA is
`sha256:22ad53f2868eacdbaf11c5ae844d2e99dae2ee1256202f65d5e29d03d3923f1a`.

The Orchestrator validated the terminal result against that separately pinned canonical command,
then committed the result and 30 PNG members (6 conditioning, 12 raw, 12 final) to
`artifact_0b6df6892e134d0e8839395c691dfb4d` /
`rev_c7a262df52c04925b9af8dbde00b7f5b`. Result member is
`manifests/sdxl-lineart-probe-result.json`, raw SHA
`sha256:cf1a9cd6dd45cb41a0f9ef215e41a5eedde2efeb27c8bc01d0928f5521114cd5`;
its separate semantic result SHA is
`sha256:98d4890292a7aa2d8445a7a6b7f49262bf671b000f996b494d40c06ff9e14fcc`.
An inspection invocation initially used the semantic hash as the member hash and correctly failed
closed; the corrected read-only invocation did not rewrite evidence or rerun inference.

Technical receipt/PNG integrity passed. **Our own inspection rejects all 12 for exam style**:
gray backgrounds, grid/banding, shadows, dark filled surfaces/white contours and inherited
redaction marks are visible. This is not an independent blind review or a scientific-accuracy
approval. Existing raw-canvas raster metrics measured foreground below 245 at 922–1000 milli,
border foreground at 945–1000 milli and midtone at 742–876 milli. These are descriptive measurements,
not newly invented acceptance thresholds; reference foreground was 199–333 milli and source
resolution/whitespace differ. Temporary inspection copies are not canonical training data.

The pinned [TencentARC model card](https://huggingface.co/TencentARC/t2i-adapter-lineart-sdxl-1.0/blob/5f1f33b049b96fa599f0aa3d77b31dbef5095e97/README.md)
and the [official conditioning example](https://huggingface.co/Adapter/t2iadapter/resolve/main/figs_SDXLV1.0/cond_lin.png)
confirm white contours on black. The downloaded example's actual SHA is
`d6fa8c2936da8e279e567375736a8f62c53ed48ae046f7d33e86a1b57f9e9b5f`;
the example URL is mutable, not an immutable model revision. The
[detector implementation](https://github.com/huggingface/controlnet_aux/blob/v0.0.7/src/controlnet_aux/lineart/__init__.py)
extracts a learned contour map before inversion. Our declared
`FIT_GRAYSCALE_INVERT_832X512/1.0` instead inverts the original gray surfaces. Correct polarity
does not make those two preprocessing algorithms equivalent. No polarity bug is established;
the source of the artifacts is still being isolated. Detector-weight authorization remains
separate, and no detector weights were acquired by this inspection.

Before spending training time, run only four strength controls: microscope/radio at seed 104729,
the same stack/reference/prompt/steps/guidance, adapter scale 0.0 versus 0.35. Each has an exact
new command and two outputs, using the existing schema, Orchestrator admission, exclusive
workspace, fixed unit and GPU lock. These are intentional diagnostic experiments, not failure
retries or a new acceptance cycle. The previous 0.8 evidence stays immutable and rejected.
Do not silently change the released conditioning policy to an edge detector; changed preprocessing
requires a successor contract if the evidence warrants it. The installed Diffusers adapter
constructor has no `add_watermarker` argument; the ignored keyword was removed with a regression
assertion (31 probe/backend tests, Ruff and targeted mypy passed), not a new configuration flag.

SDXL training/backend implementation, clean training selection/expanded document split,
the complete four-arm 42-output comparison, independent blind review and Item/HWPX activation
remain pending. No technical success is relabeled as quality acceptance.

### 2026-10-03 conditioning controls and numerical backend

The two controlled runs completed, without a new operating release or input-policy substitution:

| Adapter scale | Run | Result Artifact / Revision | Model outputs | Duration |
|---|---|---|---:|---:|
| 0.0 | `imgsdxlproberun_4a85f7f25f66fb0285cda3d4ab529004` | `artifact_638757f0fb5f468a883c092080594a50` / `rev_5503cac0209245399f355dce8c09d1cc` | 2 | 14,332 ms |
| 0.35 | `imgsdxlproberun_d700a9df194bba18398d04759e4fa5d0` | `artifact_65bc46ef0cef4dbfb6e053618b5cd1df` / `rev_2764f9bb4dc2433191c37ec24c1bacb8` | 2 | 13,812 ms |

Both used the same microscope/radio source, prompt, seed 104729, stack and generation settings.
Each result was independently compared to its committed command and all six PNG members before
Orchestrator publication. Own inspection rejects all four: the 0.0 images still have gray/dark
surfaces, a wrong microscope structure and radio pseudotext; 0.35 still has grid/scene additions,
heavy strokes and multiple unintended objects. Inference: the adapter's current gray-surface
conditioning is not the only source of style defects, and strength tuning alone is insufficient.
This does not prove the relative causal contribution or that LoRA will succeed. The 0.8 run's
evidence and failed first handoff remain immutable. Follow-up comparison budget used is 4/12.
Total SDXL model calls are 16; 42 stored PNG members include conditioning/raw/final variants and
must not be confused with the planned four-arm **42 generated-output** comparison, still pending.

All 16 original TRAIN source PNGs were inspected without modifying them or using reserved pixels.
They include white/gray/hatch exam imagery but also original letters/numbers, cut-off objects,
table-frame lines and existing redaction marks. The micro trial remains a bounded technical/style
direction test, not evidence of a homogeneous or expanded independent training population.

The existing numerical training backend was factored into one shared frozen-input UNet-LoRA
implementation. The released SSD wrapper keeps its actual command, bundled VAE and pinned
checkpoint load/save; the SDXL wrapper uses its actual stack, separately pinned fixed VAE,
200-step recipe and no checkpoint/implicit resume. No SSD pointer cast, copied training loop,
new framework, dependency, DB table or queue was added. Loss, gradient norm, latent and final
adapter nonfiniteness plus resource bounds fail before accepted adapter publication.
This is source implementation: the SDXL micro workspace application/CLI/handoff and actual GPU
training are still pending, and the installed trainer has not been replaced.

The final focused source run passed 87 tests, including CPU-fake accumulation/optimizer accounting,
frozen parameters, resume and failure-before-save cases, plus old trainer/micro/checkpoint/contract
and dependency regressions. The fakes are not CUDA numerical evidence. Two earlier invocations
failed the explicit image-test inventory gate while the new files/ordering were being added;
the final sorted manifest is complete. Ruff, targeted strict mypy and release-script syntax passed.
The complete non-live image-runtime suite also passed all 213 tests. The 12 bounded, sanitized
operator logs are durably archived through the Orchestrator as
`artifact_bb025e48f4d44032bcef8e13a2cbb503` /
`rev_238a506019a24c678d335bce6c776bbc`; raw log bytes are audit attachments, not new worker messages.
An initial archive invocation correctly refused group-writable temporary logs before any DB write;
only these completed task logs were made private (0600) before the successful archive. No record
or Artifact was deleted. Slack milestone `devreport_136a750f49c846c5bff6e667b7b08ae8` was delivered.

The clean source checkpoint `e0f1eea9dbc42fb3135563f3f4eb56da6f9a7b2c` built and inspected all
three release wheels from its immutable archive. This is build evidence only; none were installed:

- contract wheel SHA-256: `c0ac893af9f5e37a9c975407b91b31cd4f9dc03c94b990d583899f02fa2a57d3`;
- provider wheel SHA-256: `f40ea0d08d48d319ce31956a55b421ee3d4ab7c84ff8632192ca54cfd61e9d00`;
- trainer wheel SHA-256: `6c390e2d75c5d3bb6ea4c39a3c616527752e40786f445ff20d7970e02d0b1c2e`.

Archive location: `/tmp/eom-image-trainer-build/e0f1eea9dbc42fb3135563f3f4eb56da6f9a7b2c.TZQrmc`.
At 20:18 UTC the API, Web, Catalog/HWPX application runners and Workflow runner remained active;
GPU was idle (2 MiB allocated). No service restart, policy activation or operating trainer update
is implied by the successful build. Next implementation is the SDXL micro application and fixed
handoff/CLI, using the admitted original 16 TRAIN sources with explicit derived redactions; actual
micro training, held-out evaluation and candidate canary remain subsequent gates.

### 2026-10-03 SDXL micro application and handoff checkpoint

The SDXL micro command now has an application-owned workspace runner, a fixed
`sdxl-micro-probe` trainer entrypoint and offline `eom-image-sdxl-lora-micro-probe@.service`.
The Orchestrator reuses one complete historical source-lineage validator for diagnostic and
micro inputs, then checks all 16 original TRAIN declarations before PNG materialization. Only
command, crop-set, authorization and 16 TRAIN PNGs are staged (19 members); the four validation
and four holdout IDs remain metadata only. The same exclusive private handoff, readonly inputs,
shared GPU lock, approved-artifact publisher and fixed systemd dispatch are reused. No new queue,
DB schema, model dependency, worker privilege or activation path was introduced.

The runner checks exact source hashes/dimensions/captions, realizes declared white redactions
without modifying the originals, records separate derived pixel hashes, rejects duplicate/blank
realizations and accepts only an exact validated two-file PEFT adapter. Success requires all
200 optimizer updates, actual pinned dependencies and frozen duration/VRAM budgets. SIGTERM
produces cancellation evidence; the previous handler and GPU lock are released. Terminal replay
revalidates stored bytes and does not retrain; unreceipted intermediate outputs are not overwritten.
The unit allows the 3,600-second maximum application budget plus 60 seconds for terminalization.

Focused source/contract/old-checkpoint regressions: **137 PASS**; dependency and existing
publication regressions: **9 PASS**; full non-live image-runtime suite: **244 PASS**. Ruff,
targeted strict mypy (five changed production modules), diff whitespace and release-shell syntax
passed. The first application tests exposed a JSON-array/tuple mismatch in adapter manifest
construction; it was fixed at that boundary. Invalid synthetic identities, the test publisher
stub shape and one incorrect test-file invocation were corrected before the final run. These
failures are not GPU executions or historical result replacements. CPU stubs do not establish
actual SDXL training or quality acceptance.

Read-only installed trainer preflight reports Python 3.11.15, Torch 2.7.1+cu128, Diffusers 0.35.2,
Transformers 4.56.2, Accelerate 1.10.1, PEFT 0.17.1 and bitsandbytes 0.47.0. New wheels/unit have
not yet been installed at this source checkpoint. Next is a bounded trainer-only update with
exact rollback artifacts, followed by one independently pinned 16-TRAIN/200-step GPU micro run.
The inference environment and production V6 binding are not part of that update. Full grouped
dataset expansion, four-arm comparison, independent blind review and Item/HWPX canary remain open.

### 2026-10-03 actual SDXL micro training acceptance

The tested source `da1fde0ef5ccced19beb600396e9620258e8f1fc` was built from a clean immutable
archive at `/tmp/eom-image-trainer-build/da1fde0ef5ccced19beb600396e9620258e8f1fc.PIFUQb/dist`.
Wheel SHA-256 values are:

- image contracts: `dc01129fdfe72de8681d2115bea90a6055a4e313b4ac856f05dda51a8c0e2330`;
- provider: `7a92342344e6cb8ca562dabc260afc14fed6b991929fc4562a5247ab8a6aaa18`;
- trainer: `67508e5c7a3fd5b5056e74bf0a0186be94009a8dc1bcd7528ca871f1d996a6e8`.

Only the existing **trainer environment** and new optional offline micro unit were updated.
All wheel RECORD entries, installed member bytes, actual `eom-image` imports/CUDA and `pip check`
passed. No inference-environment install, production binding change, group/polkit change, service
restart, DB migration or model activation occurred. Exact installed-predecessor wheels from
`efa5e9bdfb253d98fb3966734a92645ed7d7f31e.oqaW1I/dist` were checked against both their archive hashes
and installed bytes before replacement. Rollback inputs remain:

- contracts: `ee4c22f1fb7015ed7a0028a6adfd6a008ca329fb31befad667ba86248f442977`;
- provider: `cfeef996af9c34adb581aec0b46295028782dd599e1e510721414f801f73219f`;
- trainer: `3d04c96b834e50b41a6cdd8f7dafcd64be284d7cff392306cc0995f4aae48294`.

The Orchestrator admitted/published/staged one new command and dispatched only
`eom-image-sdxl-lora-micro-probe@imgsdxlmicrotrainrun_2dd52d6f74119674e2fbccdd7fdef3ca.service`.
Command Artifact / Revision: `artifact_16942489d5694ebe9fb571953444cb6b` /
`rev_0f5da5f12a72485ea14e4d8b58067186`, member `manifests/sdxl-lora-micro-command.json`.
Raw command SHA: `sha256:e68a6b46243357aac0782f42ffe84b61a1e1196b73560d333c3e2d61b8869e45`;
semantic command SHA: `sha256:9f1558c83511460dabdaf3f46bd4b8a0612f675f8162dbc58de73c7db9e2c0d5`.
Its explicit masks affect five TRAIN samples (13 normalized boxes): original letters/numbers,
adjacent inset and layout-frame regions, not source PNG/caption identities. Only 16 TRAIN PNGs
were staged; the four validation/four holdout IDs did not materialize as trainer input.

The real GPU run completed **SUCCEEDED**, with all **200 optimizer updates**, **474,435 ms**
application duration, **5,704,160,768 bytes** peak Torch GPU allocation (5.312 GiB) and final
loss **0.013273741118609905**. The actual dependency/GPU fingerprint matches the command:
Python 3.11.15, Torch 2.7.1+cu128, Diffusers 0.35.2, Transformers 4.56.2, Accelerate 1.10.1,
PEFT 0.17.1, bitsandbytes 0.47.0, CUDA 12.8, RTX 5080, compute capability 12.0.
Systemd separately records successful terminalization at **2026-10-03 21:02:37 UTC**.
The pinned library's `torch_dtype` deprecation warning is not a training failure; no retry,
unreceipted-output overwrite or fabricated runtime fingerprint was required.

Before canonical publication the result was checked against its committed command, all 16
derived RGB 768x512 PNG hashes/dimensions and the exact validated PEFT file set/manifest.
Orchestrator result Artifact / Revision: `artifact_e4cca31093f1467f8742384ba404dcd4` /
`rev_02b106d8920f479e8dc7aa453d304ef2` (20 members: result, 16 derived PNGs, adapter manifest,
config and safetensors). Primary member: `manifests/sdxl-lora-micro-result.json`.
Raw result SHA: `sha256:6220ae31e36a3c263c2785ea218a5c6c7d73ae0fb6bcaf72ed1531358fea7a15`;
semantic result SHA: `sha256:86fb9d6d4824b839be897afeade1a1139fde33a1c2b5d0b4b05a204e1a8e643c`.
Adapter identity: `imgadapter_b133f7fe8b93686687afbbc46937c116` /
`imgadapterrev_87887be637f79587d932166c302e44f4`;
manifest semantic SHA: `sha256:971cb7a7b14d1259f3239a762bdb7ce81803ebcb9f996bfd3695c1fbaefb156f`.
The adapter remains **EVALUATION_ONLY / automatic activation FORBIDDEN**.

Own inspection of all five mask-affected derived samples confirms removal of the selected
letters/numbers and most frame lines, but still shows gray surfaces, existing redaction holes,
a furniture-frame fragment and small objects on large white canvases. The watch's redaction also
removes face detail. These are explicit dataset limitations, not a clean-full-dataset claim.
Low training loss is **not** evidence of morphology, composition, generation quality or educational
correctness. No post-LoRA image was generated in this training phase; the 16 earlier comparison
outputs remain rejected by own inspection. Independent blind review remains NOT_PERFORMED.

Nine sanitized build/preflight/install/handoff/journal/publication/Slack evidence attachments are
durably archived as `artifact_1c2e2ecfc4de48f3be863ab5c71955ec` /
`rev_240783417edd4306a923fe3a8b9b3519`. Slack start/completion receipts
`devreport_1e99d22e85544edabba6640e03b576a8` and `devreport_311814b3eaf1433eaa0cf6b6b2128084`
were SENT (HTTP 200); the completion report explicitly refers only to the micro training phase.
API, Web GUI, Catalog/HWPX application runners and Workflow runner remained active. GPU returned
to idle (2 MiB). The overall image-quality goal remains active.

**Next authorized work:** add the smallest additive evaluation contract that pins this accepted
SDXL adapter, its training result and exact base stack before provider loading. Keep released
inference probe 1.0 and its original prompt/reference/result semantics intact. Compare the same
compiled content-team prompts, source references, seeds and generation settings, with explicit
LoRA strength and output budget. Do not call an unpinned local adapter path a reproducible model,
silently cast it to an SSD adapter, retrain this successful micro run, or activate it from loss alone.
Expanded document/duplicate-group training data, remaining four-arm outputs, independent blind
review and passing Item Preview/HWPX canary are still required before full-goal completion.

### 2026-10-03 matched-input SDXL LoRA evaluation source gate

The additive `local-image-sdxl-lora-evaluation-command/1.0` and result family now pin the
baseline command, accepted micro command/result/adapter-manifest Artifacts, separate logical
adapter/revision/semantic hash and explicit strength. Baseline prompts, source PNGs, seeds,
conditioning, sampler and dimensions are reused unchanged. Shared pure evidence/coverage
validation and the shared generation loop preserve the released base-only 1.0 schema bytes;
no old receipt is relabelled as a LoRA run. Metadata admission now precedes materialization so
training/source provenance can be checked without re-reading the corpus or staged PNGs.

The fixed optional offline evaluation unit uses only `eom-image-trainer`, the existing GPU
lease and root-owned read-only inputs. No new dependency, DB/index/migration, queue, inference
environment update, production binding, permission/group change or automatic activation is
included. Bounded safetensors loading verifies exact finite rank-8 UNet targets and alpha 8
through the installed public Diffusers/PEFT API. Evaluation does not add the training caption
trigger to only one arm: doing so would confound the matched prompt comparison.

Source gates: **127 focused contract/admission/handoff/replay/dependency tests PASS**,
**273 full non-live image tests PASS**, strict mypy of nine changed production modules PASS,
Ruff formatting/lint PASS, release-shell syntax and diff whitespace PASS. The twelve pure
evaluation contract tests also pass in the explicit API environment without Pillow/provider
imports. Initial fixture time/publisher shape/expected resolver exception and test inventory
invocation issues were corrected before these final gates; these are not model executions.
A read-only operator lookup used the wrong column name; its failed log was preserved and the
follow-up uses the existing typed resolver, not direct SQL. No DB row was changed.

The accepted adapter manifest member's raw SHA is
`sha256:42cb8c200f83e87a1e21155aee8742cf12f538e641e983a6f6f28572081144bb` (1,232 bytes),
distinct from its semantic SHA. Config SHA is
`sha256:bca3e61a9357e06a5ee21c3c0855375786b9a54a8124eee20953f704738b921e` (202 bytes).
Safetensors SHA is `sha256:0b4f6f511157af989fe6391c7b9ee5665d74314e5bb0138a23ff308f781300e6`
(46,607,400 bytes, 1,120 F32 tensors). The successful read-only preflight is
`/tmp/eom-sdxl-lora-eval-preflight-20261003.r2.log`; the first failed lookup log is retained.

Next: build/install the exact tested trainer-only compatible wheel set with predecessor
rollback inputs, run one bounded six-case/two-seed LoRA evaluation against the original
baseline, publish validated PNGs/receipt, then measure and inspect all twelve outputs.
This source gate is not CUDA evaluation or illustration-quality PASS. The full goal remains
active; full grouped-data expansion, four-arm acceptance, blind review and Item/HWPX canary
are not closed by this implementation.

### 2026-10-03 actual matched-input LoRA evaluation — technical PASS, own quality REJECTED

Tested source `cc2f32e76ad872147f954580a1bdca00855bc65b` built from a clean archive at
`/tmp/eom-image-trainer-build/cc2f32e76ad872147f954580a1bdca00855bc65b.q1pQyU/dist`:

- contracts wheel SHA `dea935ffe52521ab990e5fda1df9fe07b83a2db3f7be8629f73b1512b23da085`;
- provider wheel SHA `e705316d2c27c10bc95e061c3e5766523cb57274d6cfea8e08dd04e9167b40fb`;
- trainer wheel SHA `ab54190eef0585460db4cb964bd5c05fdb2781f8e5e1a342640ac280381975b2`.

Only the trainer environment and optional `eom-image-sdxl-lora-evaluation@.service` were
installed. All wheel RECORD/installed bytes, worker identity imports/CUDA, `pip check` and
unit validation passed. The predecessor three wheels at `da1fde0e...PIFUQb/dist` were checked
against their exact hashes and installed bytes and remain rollback inputs. No inference
environment, production V6 binding, groups/polkit, migration or operating service was changed.

The Orchestrator submitted **one** command for six original TRAIN depictions and seeds
104729/130363, 30 steps, guidance 7.0, T2I conditioning 0.8 and LoRA strength 1.0. Run:
`imgsdxlloraevalrun_754ffbe1373f65ec96875ad71cf6b36d`.
Command Artifact / Revision: `artifact_bfd265c836974054b8d06ab67ab9fc5c` /
`rev_716fc2b516b744c2b8915c574e72395e`, member `manifests/sdxl-lora-evaluation-command.json`.
Raw command SHA: `sha256:1f0a699dae6c38ef5a7131192ec0b30704d5f212aab0a89e564cd935f7b2ac1d`;
semantic SHA: `sha256:9a907e5beae0b1b9e7a0db89b0568d90cf2ebcfacb9e7eeabec5713e9bc03b6f`.
All 14 staged members passed admission. Neither held-out pixels nor new prompts were used.

The actual isolated GPU run returned **SUCCEEDED**, **12 outputs**, **58,428 ms**, peak Torch
allocation **8,328,740,352 bytes**, RTX 5080 / CUDA 12.8 / compute 12.0 / Python 3.11.15 /
Torch 2.7.1+cu128 / Diffusers 0.35.2 / Transformers 4.56.2. Systemd also terminalized successfully.
This is actual numerical evidence, not a CPU fake or an assertion that illustrations are good.
All six conditioning records (including byte SHA) are exactly equal to the original baseline.
The baseline result remains `artifact_0b6df6892e134d0e8839395c691dfb4d` /
`rev_c7a262df52c04925b9af8dbde00b7f5b`; no historical output was replaced.

After command/result/adapter/baseline and PNG dimension/hash checks, the Orchestrator committed
the new result plus 30 PNG members to `artifact_b8fd18412d9d44638d0ce2828ef77c2e` /
`rev_b940a28d33f04cbaa9ba6a0202034445`. Primary member:
`manifests/sdxl-lora-evaluation-result.json`.
Raw SHA: `sha256:809b5b56f50263a828329b24d5f69f8c92ac16c0f064171c6203bcc686f20cfd`;
semantic SHA: `sha256:1f6b201f0fef87cab5374f46f4dd1146f839cd0b2ed029f5bdb79abde546a0de`.
The two early publication invocations failed before writes: incomplete operator import paths,
then a transcribed wrong baseline logical ID. The typed resolver refused it. The original
publication record supplied the exact logical ID for the same pinned revision/hash; there was
no fallback to latest, data repair or extra GPU execution. Failed logs remain preserved.

Own inspection viewed **all twelve PNGs**, not a selected best seed:

| Subject (two seeds each) | Concrete own observations | Own adoption decision |
|---|---|---|
| Microscope | gray background, dark fill, extraneous vertical borders/frame-like lines | REJECTED |
| Heated vessel | gray background and shaded liquid; second seed breaks the upper vessel outline | REJECTED |
| Protective glove | grid, shading, redaction-like panels and pseudo-symbols | REJECTED |
| Radio | shadow, dense speaker textures and fabricated brand/text-like marks | REJECTED |
| Deciduous tree | gray trunk/background, bottom panel and stray vertical marks | REJECTED |
| Trilobite | gray grid and highly textured solid rendering rather than restrained exam strokes | REJECTED |

Descriptive native-canvas foreground range is 946–1000 per mille (baseline 922–1000);
mid-tone range is 836–988 (baseline 742–876); border foreground is 854–1000. These
same-resolution measurements corroborate the gray-background/tonal problem, not science
accuracy or a statistical quality score. Presentation-normalized borders are white by
construction and must not be cited as successful original-background generation.
No accepted illustration, independent blind review, educational correctness or generalization
PASS is claimed. This is TRAIN-only diagnosis with a 16-sample micro adapter, not held-out testing.

Inspection copies (explicit temporary materialization, not canonical sources) are in
`/tmp/eom-sdxl-lora-evaluation-samples-20261003`, both seeds for all six subjects. No PNG was
retouched to make the sample look successful. Ten sanitized build/read/install/handoff/journal/
publication/Slack logs are canonically archived as `artifact_646ffd5a0a8243d58dcf55ab5a91a154` /
`rev_45754e9a259e43419964823b7530c306`. Slack milestone
`devreport_f0711e634c0b4ffc88003ab674530e66` was SENT (HTTP 200), reporting technical PASS,
own quality REJECTED, no activation and whole-goal still active. Operating services remained
active and GPU returned to idle (2 MiB). Neither rejected predecessor nor new result is deleted.

**Next:** before any larger training run, separate the learned style effect from T2I gray-surface
conditioning using the existing bounded-control budget and already-pinned microscope/radio
control inputs. The baseline-strength-only controls used 4/12 follow-up outputs; the new twelve
LoRA images are the planned LoRA arm, not twelve additional controls. Reuse their original
compiled prompts, source/seed/base settings and the accepted adapter; do not silently redefine
the released conditioning policy or acquire unverified detector weights. A changed contour
preprocessing policy needs its own successor/evidence. Full grouped-data expansion, unfinished
V7/Informative Drawings arms, blind review and passing Item Preview/HWPX canary remain open.

### 2026-10-03 LoRA/no-T2I control and licensed extractor prerequisite

The existing additive evaluation path dispatched one two-output control, without changing installed
packages, the original compiled prompts, the adapter or operating V6. It pins the previously
accepted microscope/radio strength-0 baseline at seed 104729 and uses the same LoRA strength 1.0.
New run: `imgsdxlloraevalrun_2fad38bef1859690207ced1f7aee0210`.
Command Artifact / Revision: `artifact_9fc72f19b4e14061b808bfd36c9ef637` /
`rev_ebca0e0eedd246808cbaae8e8a678477`, member
`manifests/sdxl-lora-evaluation-command.json`, raw SHA
`sha256:fefc1b97791c013a5456a3995aafcc5353fd192ce18cfba46dd71d4831b5262c`, semantic command SHA
`sha256:b4fd4e810bb35d5e56dfa6d65c15b756bb3281d1731c466487d51b034e48ed14`.

The isolated unit's journal records SUCCEEDED at `2026-10-03T22:14:32.888597Z`, two outputs,
15,658 ms and peak 8,328,740,352 bytes; semantic result SHA
`sha256:1f55170e1e6dd08023b2dcfe86b2e42cc5c3fa5a762567edec326fdc5c6e9144`.
This is terminal runtime evidence, not yet canonical result publication or visual acceptance.
At the 22:37 UTC checkpoint, the direct non-interactive sudo route required authentication;
protected result-byte validation, canonical commit, sample materialization and own inspection were
pending. This did not establish that the tmux authentication route was unavailable. The publication
operator is `/tmp/eom-sdxl-lora-control0-publish-20261003.py`; it pins the existing baseline revision
and validates the full result and all seven members before Orchestrator publication. It submits
no model work. Do not regenerate these two outputs simply because observation/publication waits.

There have now been 30 actual SDXL model outputs: base 12, original strength controls 4, matched
LoRA 12 and this control 2. The last two lack own visual verdict; previous rejected images remain
rejected. Follow-up controls consume 6/12 outputs. The complete four-arm comparison, independent
blind review and activation criteria have not passed.

Primary-source research located the original author's MIT-labelled weight distribution and verified
that fine/coarse model hashes equal the two weights used by the upstream lineart detector. See
[the research addendum](../references/SCIENCE_ASSESSMENT_IMAGE_MODEL_RESEARCH_2026-10-03.md#2026-10-03-추가-확인-선화-추출-가중치의-원-배포처)
and [ADR 0180](../adr/0180-pinned-informative-lineart-extractor.md). This resolves the narrow source
provenance prerequisite through an actual author distribution; it does not imply installation,
numerical correctness or improved images.

An additive evaluation-only manifest contract now separates extractor logical/revision/manifest
identity, pins fine/style-1 upstream/license/code/weight hashes, permits only four sorted runtime
members, bounds weight/metadata sizes and forbids activation or runtime pickle/code files. JSON
Schema 2020-12 and frozen Pydantic mirrors are aligned; 36 new pure contract tests pass inside the
API environment without Torch/Pillow. The four focused contract suites total 110 PASS; the existing
image suite remains 273 PASS; new contract plus dependency-boundary checks total 42 PASS. Ruff,
targeted strict mypy, release-shell syntax and diff checks pass. These counts are separate suites,
not additive independent coverage. No weights, migration, new dependency, worker protocol or
service installation were introduced by this source gate.

Next: finish the pending control's protected publication/inspection after authentication; then
implement restricted weight conversion/tensor checks and a separately pinned learned-extraction
command/result before dispatch. Preserve original TRAIN crop/provenance admission and original
SDXL receipt semantics; do not use derived PNGs as though they were original approved crop members.

### 2026-10-03 control publication/own review and extractor source build closed

The approved `EOM:3.0` operator route completed protected publication without any inference rerun.
Control result: `artifact_6501e0cf9d6340d1a60a2170b59413a2` /
`rev_b466e4fee4994c478cb9359d06de5ef7`, member
`manifests/sdxl-lora-evaluation-result.json`, raw SHA
`sha256:61e36ec90d3fc81337a055705776fb0b927d0cdb27e085da86143817607c44f3`, semantic SHA
`sha256:1f55170e1e6dd08023b2dcfe86b2e42cc5c3fa5a762567edec326fdc5c6e9144`.
All seven result/conditioning/raw/final members, original baseline conditioning hashes and original
runtime fields passed validation. Baseline pinned raw result SHA was resolved/verified as
`sha256:84d31ae4ad6c3e54e21c07665e085bf1c81dea9811b38dc9d38c4c9bdcb9fead`; its known semantic
identity and exact Artifact/Revision were preserved.

Both actual final images and both matching original baseline images were opened at original
resolution. Own visual outcome is **REJECTED for both**, not independent blind-review acceptance:

| TRAIN subject | Main observed defects | Native foreground / midtone, milli |
|---|---|---|
| MICROSCOPE | Gray background, glossy beam/shading, implausible cropped microscope structure | LoRA 785/687; base 800/596 |
| RADIO | Extra microphone, gray panels, dense speaker texture, pseudo text/numbers, shading | LoRA 742/583; base 597/246 |

Removing T2I does not remove all style defects; this LoRA alone does not satisfy the fixed-prompt
exam-style requirement. This two-TRAIN-case control does not establish each causal contribution,
generalization, a future model's failure, or independent reviewer judgment. The training style
prefix remains absent from both matched arms; its effect was not tested here. Gray inversion,
training style distribution and prompt/trigger selection remain distinct hypotheses.

Inspectable temporary copies: `/tmp/eom-sdxl-lora-control0-samples-20261003/microscope.png` and
`/tmp/eom-sdxl-lora-control0-samples-20261003/radio.png`. They are local viewing materialization,
not canonical replacements or accepted product illustrations. All 30 actual SDXL outputs now have
own REJECTED verdicts; follow-up control use remains 6/12. No extra generation occurred during
publication, review, documentation or evidence repair.

Extractor source checkpoint `39e15a3c2412cffefc651bdf6213d977e64c5c8f` passed both provider and
trainer release builds. Common contract wheel SHA:
`1d80a26a19d5a3da1161220f9802fdfb97bcc3769218d436ca7dcd4ff770a9ef`; provider wheel SHA:
`9da47fa82c1ff4dfe36ecf4cc3e2de662aba36d285b6e8ec74fbe87ec0f87b13`; trainer wheel SHA:
`501cb4a2db8ac1f38cead020ddab3e0e28154aa5fa38b823339ba9604570979b`.
Build archives are `/tmp/eom-image-trainer-build/39e15a3c2412cffefc651bdf6213d977e64c5c8f.q7hjGu`
and `/tmp/eom-image-provider-build/39e15a3c2412cffefc651bdf6213d977e64c5c8f.H8RBJT`.
A wheel-only import/resource check used the API interpreter with the contract wheel ZIP as its
import source, verified the 2020-12 schema and confirmed Torch/Pillow and runtime source imports
were absent. None of these candidate wheels or extractor weights was installed. Existing trainer
runtime remains `cc2f32e7`, inference runtime/binding remains the previous V6.

Slack milestone deliveries were SENT/HTTP 200:
`devreport_4a62121077a54468a86c27283c770419` (source prerequisite) and
`devreport_6db4137330c74b43a65edc1de2286010` (control publication/own review).
Nine explicit sanitized evidence logs are canonically archived at
`artifact_fc82a812903349ac938449b9392cfc4b` /
`rev_db1745a05a044e5da5ea0c678dcb790f`, primary `logs/lora-no-t2i-own-review.log`.
The first evidence publication correctly rejected group-writable generated log inputs before
DB/NAS publication. Only these validated local evidence files were restricted to mode 0600; the
original failure log was preserved and included in the successful archive. No validator/source
policy was weakened, and no worker/model operation was retried to repair this operator error.

Next remains restricted extractor conversion/tensor validation and additive learned-conditioning
command/result implementation. Full-data expansion, remaining comparison arms, independent blind
review and a passing Item Preview/HWPX canary remain open. The whole image-quality goal is ACTIVE,
not complete; rejected model outputs never authorize activation.

### 2026-10-03 learned extractor acquisition and actual CPU acceptance

The source implementation now has separate restricted acquisition, public pinned HTTP and
offline exact-revision resolution responsibilities. The CLI delegates these rules; there is no
new queue, database schema, daemon or dependency. The existing manifest schema bytes and old
gray-inversion policy are unchanged. See ADR 0180 for the boundary and packaged MIT notice.

An actual acquisition in the explicit `eom-image-trainer` environment fetched and verified the
author's pinned README, architecture source and 17,173,511-byte weight. Restricted CPU loading
converted 24 F32 tensors / 4,290,945 parameters to 17,165,948-byte safetensors. Every tensor and
the synthetic before/after CPU forward were bit-identical. Seven real numerical acceptance tests
passed; a separate one-test CPU-construction gate also passed under a non-CPU default-device
context. Wrong shape/key/dtype/device/layout/non-finite tensors and corrupt inputs were rejected.
CUDA initialization was guarded against; no actual exam-image extraction, GPU generation,
training, HWPX render or production configuration change occurred in this phase.

Source gates: final focused contract/runtime/dependency/old-SDXL regression **166 PASS**, complete
isolated image unit gate **318 PASS**, strict type checker six production/CLI files PASS,
formatter/linter/shell syntax/diff checks PASS. These suites overlap and must not be added as one
unique-test total. Normal API-side collection skips the eight real numerical tests without the
explicit opt-in; it does not import Torch/Pillow or fetch public model files.

Acquisition materialization: `/tmp/eom-informative-lineart-acquisition.an987FIa/model`.
Extractor logical ID `imgextractor_1de9b4ea4cbdd167a6ba88f0b45f91d3`; immutable revision
`imgextractorrev_93c4e6202a52e2d5a76f33f517b05e62`; semantic manifest SHA
`sha256:aa2ad3750048e0ab118fad3353b98d6811dc2b26db01379bd5b85cf63fa6b62d`; derived weight SHA
`sha256:597e257afa95df3e989460590d62a7c6ba487c2b7afd63cf10145712a043963c`.
This is staging, not a protected installed model or an inference receipt. The original `.pth` was
not written into the model directory; remote executable source was not executed or retained there.

The focused source gate initially exposed a new factory's UTC string/hash normalization error;
it was fixed at canonical construction, not by weakening the manifest validator. Later, a broader
regression invocation omitted the identifiers package source path and failed collection. Its log
is retained separately; the corrected full-source invocation passed. Developer test failures do
not reinterpret historical runtime failures, and neither issue required service changes.

Next: build and verify this immutable candidate, archive exact model/evidence through the existing
Orchestrator publisher, then add the extraction command/result and original TRAIN admission before
dispatching six learned-contour inputs. Do not make derived PNGs impersonate original approved
crops. The previous 30 rejected SDXL images remain rejected; independent blind review, full-data
expansion, remaining comparisons and quality-passing Item Preview/HWPX remain open. Goal ACTIVE.

### 2026-10-03 acquisition candidate build and canonical evidence closed

Implementation source `9045b7e3ab290e09f689fe89ace7f474709b37ba` passed both immutable release
builds. Common contract wheel SHA
`2d8b050d84a0716da23b9994e5e1f48373192872be9b43d310cd97d63247b6cd`; provider wheel SHA
`f0ec003b8f9f803f2dd56049a2a0287e39a68613cbf6d98440fa68f02b10989f`; trainer wheel SHA
`60c9feed87dcb4106da5b2531ece579882a11ffd482a69f4a213c6de08aa287f`.
Build roots: `/tmp/eom-image-provider-build/9045b7e3ab290e09f689fe89ace7f474709b37ba.ubb2DY`
and `/tmp/eom-image-trainer-build/9045b7e3ab290e09f689fe89ace7f474709b37ba.JDXsCQ`.

A wheel-only check outside the repository verified all three wheel hashes and every RECORD
entry, imported the new model/contract code from the wheel ZIPs, resolved the packaged MIT
notice and loaded actual converted weights for a finite bounded synthetic CPU forward. It did
not install wheels, access corpus images, acquire CUDA, call network inference or change an
operating binding. This additional synthetic check is not a generated exam-image sample.

The existing Orchestrator `ControlFileSetPublisher` committed the primary typed extractor
manifest, its four exact model members and ten sanitized logs (including the source-path
collection failure) as **15 members** to:

- Artifact `artifact_a588ec0385d148eea65bd37163fc6113`;
- Revision `rev_f0946b1223654ac9bb321232462a67c6`;
- Primary `manifests/informative-lineart-manifest.json`;
- Primary raw SHA `sha256:0106db12c5ad95a520213c10eadbfcf92b6ae1c11f1da932850a48f5ad2953e9`;
- Extractor semantic manifest SHA remains
  `sha256:aa2ad3750048e0ab118fad3353b98d6811dc2b26db01379bd5b85cf63fa6b62d`.

Opaque model-member format tags are governed by that primary manifest's exact `ModelFile`
records and numerical acceptance, not presented as JSON worker-message schema validation.
Canonical publication used the existing resumable application boundary; no worker wrote NAS,
no binary entered PostgreSQL or Git, no direct row update, protocol rewrite or migration occurred.
The approved `EOM:3.0` route was verified and succeeded without another password request.

Slack checkpoint `devreport_70dc8d3659794d3b8268ed39fb89959e` was SENT / HTTP 200 at
2026-10-03T23:44:43.867538Z. Read-only checks found the five real API/Web/Catalog/HWPX/Workflow
services active. V6 production configuration raw SHA is still
`f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`.
Installed trainer remains `cc2f32e7`, inference provider remains `67fd3190`; this new candidate
and extractor are **NOT INSTALLED**. Acquisition/CPU source gates are closed, but corpus
extraction/admission, matched image quality, full-data/independent review and product canary
remain open. The whole goal remains ACTIVE. Next: additive six-case extraction command/result.

### 2026-10-04 original-provenance learned extraction: actual six-case checkpoint

Implementation `2e5ebffe2279f6ff126626d666f796c16c38e655` adds the pure 2020-12/Pydantic
extraction command/result, original TRAIN source admission, a bounded indexed Artifact-member
batch read, the existing exclusive workspace handoff and an offline fine-generator adapter.
ADR 0181 defines the responsibilities, immutable pointers, concurrency and failure boundaries.
No new DB schema, queue, daemon, dependency, worker privilege or implicit-latest resolution exists.
The old original-crop/gray-inversion and SDXL/LoRA contracts keep their previous meaning.

Final focused source/old-contract/dependency regression: **239 PASS**; complete isolated image
unit gate: **346 PASS**; strict types for nine production/CLI files PASS; formatter/linter,
shell syntax, systemd syntax and diff checks PASS. These overlapping suites are separate gates,
not a summed unique-test count. Initial source fixtures were rejected for group-writable file
permissions; fixtures now obey the same safe-I/O rules as the actual root-owned handoff. A wrong
backend call signature was caught by strict types before installation/GPU use and fixed at the
call site. A later regression invocation named a nonexistent test file; its failure log remains
in the evidence archive and the corrected regression passed. Validators were not weakened.

Immutable release build:
`/tmp/eom-image-trainer-build/2e5ebffe2279f6ff126626d666f796c16c38e655.Fbyllb`.
Contract wheel SHA `cae74d9807e29d59a55809b7c3e13cdc03c1d8d97b98f616d77774fc7f8b44d5`;
provider SHA `0e6cda5e17f66c6c9a93940d7d0db6a6c9793d3344ca53e0bcd2d14698c8eaf7`;
built trainer SHA `d52dd4147c8d98fc5bf6ca873787bacd1080e9df5f9056cc6ab199a43e8e958e`.
Only the contract/provider wheels were installed into the numerical trainer environment. All
wheel RECORD entries and worker-identity import/model-read/CUDA capability were checked. The
trainer distribution itself remains the earlier `cc2f32e7` wheel; the operating inference
environment remains `67fd3190`. The new trainer wheel was built, **not installed**.

The converted exact extractor revision is now installed as EVALUATION_ONLY under the existing
protected model store, with root ownership and image-group read permission. Its previously
published manifest/weight hashes are unchanged. One optional, fixed oneshot template uses the
existing image identity, offline/protected filesystem sandbox and physical GPU lease. The
operator update held that same GPU inode while checking quiescence/installing; old contract and
provider wheels from `cc2f32e7` were verified as rollback inputs. No operating services were
restarted; no Polkit/group/secret/production binding was changed.

Actual extraction command:

- Run `imglineartextractrun_abb6468621e4f0b6c0b2276da6350633`;
- Artifact `artifact_db82d6f97daa410f8f007c5952928072` /
  `rev_c7514bf952eb444fbae02ee7a628e532`;
- Primary `manifests/informative-lineart-extraction-command.json`;
- Raw SHA `sha256:4e9594c6541e17b7faeec50c9c416cb9455032456d593ad7c0d3971c68552fca`;
- Semantic command SHA
  `sha256:9c0df3e32a76671c896dd279b5a22c1f390ef87eb5e2a9dad4cabe9fa9a190ae`.

It pins the existing six-case baseline command, canonical converted extractor manifest and
original case IDs. Nine bounded inputs were staged; there was one dispatch, no reconstructed
crop registration or new SDXL/training request. At 2026-10-04T00:31:57.673420Z the installed
provider completed all six cases: **2,553 ms**, **376,991,232 peak allocated GPU bytes**.
The Orchestrator independently validated original hashes, coverage, canonical receipt,
12 PNG sizes/media/modes and exact raw/inverted conditioning pixels before committing 13 members:

- Artifact `artifact_d723b6accb4b414d9d26709806b2194f` /
  `rev_7621e6945eb847aa823b47a47d2703a9`;
- Primary `manifests/informative-lineart-extraction-result.json`;
- Raw SHA `sha256:6785d874102293acf85d95e0a4fb3e6f89601a3df6c41de613143b44ce490a3c`;
- Semantic result SHA
  `sha256:6d9a1de1459ab3bf277c716a6dd3292840f6f4fbc8aacdec1b89c09f0c0b5152`.

An actual image-worker-identity replay verified the same 12 members and unchanged receipt with
model resolution and GPU acquisition entry points deliberately denied. Model/GPU/inference
calls were zero, and Torch was not imported. This is actual installed replay evidence, not just
a source fixture. The original inference was neither resubmitted nor concealed as replay.

The primary agent inspected all six original fitted references and all six raw outputs at
832x512 resolution. Broad gray fills/shadows were reduced while keeping the original geometry.
However, **all six are REJECTED AS FINAL PUBLICATION IMAGES**: rough/broken/nonuniform contours,
dense fossil/speaker/mesh texture and source crop artifacts remain. Microscope frame separator,
tree annotations, glove label-erasure blocks and incomplete vessel contour are original-source
issues, not proof that extraction invented or corrected them. Native paired metrics corroborate
lower midtone but increased fragmented/fine detail; those metrics are not quality acceptance.
Independent blind review remains NOT_PERFORMED.

Explicit local viewing materializations are in
`/tmp/eom-informative-lineart-extraction-samples-20261004/`, with `*-reference.png` and
`*-lineart.png` for deciduous_tree, heated_vessel, microscope, protective_glove, radio and trilobite.
These are derivatives for inspection, not newly authored final exam illustrations.

The existing Orchestrator publisher archived the own-review report and eleven sanitized gate
logs as 12 evidence members at `artifact_b28307af2303498f87c9360a8d9b548e` /
`rev_bb6bce2140954114b3f57f14a6dfbca1`, primary
`reports/lineart-extraction-own-review.md`, raw SHA
`sha256:571451bd2f82281e751987bf07fdea7957a59987ef31c0c8c4d458377b6ce47e`.
This evidence publication performed no inference and did not duplicate the canonical PNG set.

Slack milestone `devreport_16ee33b9a86b4b0cbdf67399ee2c0fd6` was SENT/HTTP 200 at
2026-10-04T00:38:26Z. The five real API/Web/Catalog/HWPX/Workflow services remain active; operating
V6 raw configuration SHA is still
`f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`.

Next: an additive comparison that explicitly pins this extraction receipt/conditioning members
and the unchanged baseline prompt/seed/model geometry. Compare learned versus old conditioning
with declared base/LoRA arms inside the remaining bounded budget. Original 30 rejected SDXL
outputs remain preserved; extraction adds **zero SDXL outputs and zero training updates**, so
follow-up control use is still 6/12. Full-data expansion, independent blind review, remaining
matched arms and a quality-passing Item Preview/HWPX canary are open. The whole goal stays ACTIVE.

### 2026-10-04 learned-conditioning BASE/LORA: actual four-output comparison

ADR 0182 and source `2e113a31cc6051fda55847fdef1a61969bda0b79` add a fixed two-arm comparison,
not a generic experiment scheduler. It pins the original six-case baseline, successful extraction
command/result and accepted LoRA training/evaluation provenance. Only two selected conditioning
PNGs and the adapter are materialized after original TRAIN lineage admission; original PNGs are
not copied into this worker. The existing indexed batch reader admits the 46.6 MB adapter with
a 64 MiB member / 128 MiB aggregate ceiling, preserving safe hash/permission/size resolution.
No DB, dependency, queue, privilege, worker-auth or production policy change is involved.

Source gates: isolated image suite **363 PASS**; focused pure contracts/admission/handoff/
compatibility **147 PASS**; dependency boundaries **6 PASS**; strict types eight changed modules
PASS; formatter/linter/shell/diff PASS. These overlapping suites are not summed unique coverage.
Initial fixture exception expectations, an adapter-strength field and explicit Pillow stub
interpreter selection were corrected before final gates, installation and any GPU dispatch.

Immutable build: `/tmp/eom-image-trainer-build/2e113a31cc6051fda55847fdef1a61969bda0b79.vDH1cV`.
Contract wheel SHA `93267b436d8e50b23e09769e95d84be08a729e5d8a81e52dfc33b1fadf7a128b`;
provider SHA `99b6ccda14000e50dd0d7c4e4cb20bd408346bd99db9a8117411e95f77ecdba0`.
Only these two wheels were installed into `eom-image-trainer` under the existing physical GPU
lock after quiescence and exact old-wheel RECORD/rollback checks. Trainer distribution still
comes from `cc2f32e7`; the new trainer wheel was built but not installed. Worker-identity import,
CUDA capability, offline fixed unit and pip checks PASS. Operating inference/V6/models unchanged.

One dispatch `imgsdxllearnedrun_40b8f423c55d449d56005ae59ea7543f` staged 13 members and generated
MICROSCOPE/RADIO x original seed 104729 x BASE/LORA = **four outputs**. Original prompt/negative,
model pins, steps/CFG/T2I strength, geometry and accepted LoRA strength stayed unchanged. A fresh
pipeline per arm avoided adapter leakage into BASE. Actual duration **24,213 ms**; peak allocated
CUDA memory **8,328,740,352 bytes**; no additional training updates or generation retries.

Command Artifact `artifact_0079711dda19493da91a0a5ce9ec4964` /
`rev_1024317bbdfc4c8e92b98fd0a5605ec1`, member `manifests/sdxl-learned-comparison-command.json`,
raw SHA `sha256:9bf333e3620e199349ea9e944fefa90dfcb39c5ea4bd6f3b18134abd130b95d4`.
Result Artifact `artifact_d6de2fc680144395bc0205fb55208004` /
`rev_129ad15be4734368a41ff2df452d5490`, member `manifests/sdxl-learned-comparison-result.json`,
raw SHA `sha256:df7580d32b6d9b37b5428ea42f2b3f934a9f4d485cb27a7d11f71fe50ba4a9ef`,
semantic SHA `sha256:2e434a403ad95782c982ce17d3f0a25aee83e223a28c7c9109cd37dc63ee0326`.
All nine receipt/raw/final members passed source/hash/PNG/mode/dimension/publication-crop checks.
Installed worker replay verified eight image members with model/GPU/adapter entry points denied,
no Torch import and zero inference. The five long-lived services stayed active; GPU returned idle.

Own inspection opened all four new finals, both original fitted references and all four old
same-seed BASE/LORA images at original resolution. All new finals are **REJECTED**: black fill
decreases and broad layout is retained better, but gray canvas/shadow, speaker/platform texture,
embossed contours and inherited source frame remain. Native 800x500 paired metrics verify reduced
dark fill but dominant midtones/border foreground. Old viewing hashes were checked against their
canonical receipts. This two-TRAIN-case observation does not establish unseen-data generalization
or independent blind-review acceptance. Actual images are not replaced with thresholded edits.

Own review and eleven sanitized logs are archived at `artifact_aa350234fb4043dd836617ec6d03b52f` /
`rev_6b24ba1ba7634f139e622bc1aa247170`, primary `reports/learned-comparison-own-review.md`,
SHA `sha256:df365c07d0508751c0f48fb2b10bde8162a89ea790c9a703d88a5c2a02127430`.
Viewing copies: `/tmp/eom-sdxl-learned-samples-20261004/{microscope,radio}-{base,lora}-104729.png`.
Slack `devreport_437729c94ccb4e37b1f7429155019798` was SENT/HTTP 200 at 01:22:39 UTC.

Upstream documents white contours on black for this lineart adapter, matching current conditioning;
do not infer or "fix" polarity just from a gray final. [Pinned primary model card](https://huggingface.co/TencentARC/t2i-adapter-lineart-sdxl-1.0/blob/5f1f33b049b96fa599f0aa3d77b31dbef5095e97/README.md).
Next: inspect the 16 actual TRAIN targets/style distribution and caption-trigger consistency
before increasing training or spending remaining outputs. Changed targets/crops/prompts require
explicit successor lineage; original pixels/receipts remain intact. Actual SDXL own verdicts are
now **34 REJECTED**; follow-up budget **10/12 consumed, 2 remaining**. Six learned-extractor outputs
remain preprocessing, not additional authored SDXL images. Full-data expansion, remaining arms,
independent blind review and a quality-passing Item Preview/HWPX canary remain open. GOAL=ACTIVE.

### 2026-10-04 actual TRAIN target audit and two-output style-prefix control

At source `01402845b65c07c50cf8543ec7c67e0d76f0b898`, the accepted command/result and
16 realized TRAIN targets were resolved by the existing indexed bounded reader. Every viewing
copy matched its canonical PNG hash; all 16 were opened at original resolution. They span
14 TRAIN documents / 13 exam groups. No VAL/HOLDOUT pixels, new copies or training updates.

White outer canvas has border foreground 0/1000, but foreground occupies only 5–35/1000 of pixels
and threshold-245 ink bounding boxes 18–151/1000 of the 768x512 target. Old preparation downscales
without enlarging small objects. Inspection also finds panel lines, annotation/white-mask residue,
incomplete crops, scientific arrows and mixed heavy-tone/fine-texture versus restrained contours.
These are preparation hypotheses, not proof of one generation root cause or rejection of every
institutional source. Preserve original images, crop approvals, masks, partitions and receipt.
A changed fit, crop, mask or caption needs explicit derivative/successor lineage.

All 16 training captions contain the style prefix; none of the six original evaluation prompts
does. A frozen control added it to BOTH BASE and LORA for the original RADIO TRAIN reference/seed
104729. Negative prompt, base/VAE/T2I pins, steps 30, CFG 7, T2I 0.8, adapter 1.0 and geometry
stay unchanged. New prompt/seed content received a new case ID, policy Artifact and baseline;
LORA pins that baseline and the old adapter. Existing contracts/Orchestrator admission, staging,
dispatch and publication suffice: no new core code, dependency, migration, queue, unit, privilege
or operating installation. Source/provider installed revisions remain honestly distinct.

Actual token counts: positive 57/57→63/63, negative 67/67 within 77/77; training captions max 21/21.
Numerical versions and generation-session/conditioning ASTs match across the two installed
environments. Focused applicable regression **108 PASS**; operator formatter/linter/compile PASS.
Early private discovery/invocation/environment mistakes were fixed before model dispatch;
they were not production incidents, authority changes or inference retries.

One BASE dispatch `imgsdxlproberun_57bef754ab3bdb310829939abc626056`: **11,590 ms**,
allocated CUDA peak 8,280,481,280 bytes. Result `artifact_aa80840456b942c5bda63cc633ac555c` /
`rev_dcb24a1016b44cafa8f84c4a47707149`, `manifests/sdxl-lineart-probe-result.json`, raw SHA
`sha256:f98ce43387c2ca47a3cea706c3ac7d81d35bc50e16ae59d2668103618f79b516`.
Only after terminal BASE success, one LORA dispatch `imgsdxlloraevalrun_a02a13fa7e13df8a39dbe267ad3c6919`:
**12,860 ms**, peak 8,328,740,352 bytes. Result `artifact_41da9770a4fa4e4cae2bdc5e158d9c93` /
`rev_2cfdb8ebbcf5499d867aecb7cd2c79f9`, `manifests/sdxl-lora-evaluation-result.json`, raw SHA
`sha256:427e4828d8f0073f5459261d550484001820ea682a6d7e0cb382f77da4c07b01`.
Each established family committed four validated members; conditioning hashes and publication
crop match. Actual worker-identity replay verified receipts/images with model entry points denied,
no Torch import and zero inference. Five services remain active, GPU idle, V6 raw binding unchanged.

Both new/old same-seed RADIO pairs were directly inspected. BASE adds an invented background grid;
LORA is close to its old gray/shadowed/textured output. Both new images are **REJECTED**.
Native BASE dark 176→258, midtone 787→707, border foreground 949→958; LORA 116→112,
879→884, 1000→1000 (per 1000). Viewing hashes were verified. Prefix correction alone does not
fix this one TRAIN case; this is not unseen-data or independent acceptance. All **36 actual SDXL
own verdicts are REJECTED**; follow-up allowance **12/12 consumed, 0 remaining**. No new training,
activation or canary. Six extractor outputs still count only as preprocessing.

Own target-by-target review, eight bounded logs, four operator sources and frozen plan are archived
as 14 evidence members at `artifact_7916bc4397d34f328389c43d02e008ae` /
`rev_c3a32f91027249128c6cbd7b2f4d5447`, primary `reports/target-and-trigger-own-review.md`, SHA
`sha256:1dbabc399b7b7dd2b3e35cbd59240832fb382d519a81444f7f90dd5506aac64b`.
No PNGs were duplicated into this archive. Viewing copies:
`/tmp/eom-sdxl-trigger-control-samples-20261004/radio-{base,lora}-104729.png`.

Next authorized development is explicit target preparation/data admission: object framing/scale,
source mark/crop repair with reviewed derivation, expression-type/caption consistency. Do not
repeat inference under the exhausted control cohort, inflate eligible counts, silently change
its meaning or replace rejected images with thresholded edits. Pin the next command/data/budget
before training. Full-data expansion, remaining arms, independent blind review and a passing
Item Preview/HWPX canary remain open. This diagnostic is PROGRESS; the whole goal stays ACTIVE.

### 2026-10-04 reviewed CPU target preparation implementation

[ADR 0183](../adr/0183-reviewed-sdxl-training-target-preparation.md) introduces an additive
CPU-only command/result and explicit PREPARE/DEFER decisions over the exact original 16 TRAIN
sample IDs. Source crops, source captions, original targets, partitions and previous training
receipts are unchanged. A reviewed frame, exact white masks, expression caption and bounded
rational enlargement produce unreviewed candidate target revisions, not training approval.
Eight raw sources are intended for preparation; the other eight have missing parts, existing
mask damage, dense damaged texture or scientific geometry better owned by native drawing.
The entire raw 16-image snapshot was directly inspected, rather than using only contact sheets.

Orchestrator admits original successful training provenance and all existing corpus lineage
before one bounded batch of only selected TRAIN PNGs. The isolated trainer reads staged local
files; it cannot read models, GPU devices, network, repository, protected configuration or NAS.
Only Orchestrator publishes command/output Artifacts. New command identity, target logical ID,
target revision and raw/semantic hashes are separate. Terminal replay verifies receipt, coverage
and every output file without transforming pixels or loading a model; unreceipted output fails.
There is no new dependency, DB schema, queue, production activation or implicit old-policy change.

Source checks: formatter/linter, strict focused types (six modules), dependency boundaries and
a final combined 182-test suite PASS. Earlier 96- and 43-test runs overlap with this final suite;
they are not additional distinct tests. Installed execution and actual candidate inspection are
pending at this implementation checkpoint. The exhausted diagnostic inference cohort remains
12/12; this CPU path does not grant inference or training budget. Subsequent training must pin
and explicitly admit new target revisions through a successor contract.

### 2026-10-04 actual CPU preparation and individual candidate review

Source implementation `ad1716d6297fa3587c81bf6881a826eb02876999` was built from clean immutable
Git, with wheel contents and installed RECORD verified. Trainer contracts and trainer only were
installed, plus optional `eom-image-sdxl-training-targets@.service`. Provider distribution and
inference environment stayed unchanged; no production service restart or V6 activation occurred.
Rollback wheel paths/hashes are preserved in the install evidence. Installed worker import
loads no Torch; the actual CPU unit enforced private devices/network and blocked model/NAS access.

One preparation dispatch `imgsdxltargetpreprun_2878f3dad9dbc99542603ac9050471c1` staged 13 files
and completed in **387 ms**: eight prepared PNGs and eight declared deferred source IDs, exactly
covering the original 16 TRAIN sample IDs. **Inference calls=0; new training updates=0**.
Command Artifact `artifact_ba16f0bfde954e918b68a2b4f7c399e0`, revision
`rev_1f464f5c5af3421899e0e49088ae0af2`, member `manifests/sdxl-training-target-command.json`,
raw SHA `sha256:146737a5a887949c3dd1bf6bae6c7115f0fd45b2222622a756254abcd4df3abb`.
Result Artifact `artifact_09fe569e204a4443975a5585e0c43b97`, revision
`rev_df085910b56c425e85c2c07283d90735`, member `manifests/sdxl-training-target-result.json`,
raw SHA `sha256:73a4389ecd535d8f4e563883017107c59f63545bb939d4969507b750df11fa80`, semantic
SHA `sha256:649a7e216fbc0e4b4790a7441f9dcfd99f538cf236b055fffc929ec8325dd779`.
This one canonical result contains the receipt and eight PNGs, not changed original source crops.

Installed-role reconstruction reproduced every declared PNG in the pinned Pillow 11.3.0 runtime;
terminal replay with transformations explicitly denied passed. Canonical persisted PNG bytes and
local viewing copies were resolved and hash-checked. All eight original raw crops and prepared
outputs were individually opened. Own assessment is **four promising candidates with notes and
four rework-required**, not independent blind review or automatic data admission:

| Outcome | Cases | Findings |
| --- | --- | --- |
| Promising with notes | heated vessel, prehistoric bird, radio, pigeon/fish | Larger targets; marker/panel cleanup on bird and pair. Vessel upper contour needs complete-page context; radio shading/soft shadow belongs only in a restrained-tone track. |
| Rework required | microscope, flask apparatus, sofa/table, tree | Surviving inner panel rules, interrupted apparatus outlines, context patches or incomplete guide removal/ground-baseline damage. Do not train these as-is. |

Foreground bounding-box area changed from 27–151/1000 to 212–651/1000; surviving panel rules
inflate some measurements, so this is not an object-quality score. All outer 24-pixel borders
remain white, proving that a white-canvas metric alone cannot detect undesirable inner framing.
Upscaling preserves existing source detail; it does not recover missing source parts.
Result state remains `UNREVIEWED_TRAIN_TARGET_CANDIDATES`, activation `FORBIDDEN`.

The first local publication adapter used an incorrect metric property and failed before result
commit. It was corrected and replayed under the same preparation identity; no second preparation
was submitted. Failed invocation logs are preserved with successful source/build/install/publication
evidence. CPU validation reconstruction checks=2 and receipt-only replays=4, distinct from the
single preparation, zero inference calls and zero training updates. The complete source suite is
182 PASS; earlier overlapping 96/43 results are not added as independent tests.

Next is complete-source recovery/framing for the rework cases and document-group-safe approved
TRAIN expansion with explicit reviewed target pointers and caption/expression policy. Do not count
the source pair as two examples, manufacture counts by resizing, retrain on these eight candidates
automatically, or run more inference in the exhausted 12/12 diagnostic cohort. The actual SDXL
authored-output count remains 36, all own-REJECTED; no new model-quality claim. Full-data expansion,
independent blind review and a passing Item/HWPX canary remain open. Whole goal remains ACTIVE.
Viewing copies: `/tmp/eom-sdxl-reviewed-training-targets-20261004/{original-sample-id}.png`.

Own review and fourteen bounded evidence members are archived independently as Artifact
`artifact_fa43c49ee1e14320881d03a32120f77a`, revision
`rev_b3fc0b04a9f84fa6b72d53d05167fdcc`, primary `reports/own-preparation-review.md`, SHA
`sha256:94fe966600600999585404c8e98690d782c7ee0c9dd107dc90a2c1148cfadead`.
No PNG was copied into this evidence archive. Five production services remained active,
the V6 binding raw SHA remained unchanged, and persisted result/view hashes passed.
