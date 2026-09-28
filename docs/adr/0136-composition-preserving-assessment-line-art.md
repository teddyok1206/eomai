# ADR 0136: Preserve reference composition while applying assessment line-art style

## Status

Accepted for an evaluation-only implementation on 2026-09-27 UTC. This decision does not activate
an evaluation adapter, change the released `provider-binding/2.0`, or authorize generated labels,
answer-bearing geometry, tables, graphs, circuits, or laboratory apparatus.

## Responsibility and boundary

When an exact visual reference is present, EOM treats local raster generation as a constrained
style conversion rather than a new scene-generation task. The reference owns subject count,
silhouette, relative position, scale, viewpoint, direction, overlap, and framing. The approved LoRA
may change only assessment-page presentation: monochrome line work, sparse gray tone, simplified
texture, and white background.

The content-team prompt remains byte-stable and authoritative. Reference metadata remains
untrusted data and never enters that prompt. Scientific labels, values, arrows, axes, answer-bearing
geometry, tables, graphs, circuits, and exact apparatus are still produced through validated
Python/SVG or editable HWPX content. The raster path may supply only non-authoritative morphology.

## Canonical source and revision model

```text
approved reference bundle revision
  -> exact normalized reference PNG
  -> deterministic monochrome edge-conditioning member
  -> reference-conditioned candidate PNG
  -> immutable composition-evaluation result
  -> human line-art quality review
  -> evaluation-only adapter decision
```

The bundle, conditioning member, candidate member, evaluation result, and adapter revision retain
separate IDs and SHA-256 hashes. A workspace copy is temporary materialization. If the composition
gate fails, EOM does not increase diffusion strength, invent another pose, or silently select the
latest reference. It fails closed and requires a different approved reference or a deterministic
renderer route.

## Exam-image style families

The reviewed exam pages contain three different visual families that must not be mixed into one
training target:

1. `EXAM_OBJECT_LINE_ART`: isolated cars, people, bottles, bicycles, safety equipment, specimens,
   and similar objects with accurate silhouette, thin dark outlines, sparse gray faces, and a white
   background. This is the new evaluation-only LoRA target.
2. `GRAYSCALE_RASTER_TEXTURE`: astronomy, rock, fossil, and microscopy imagery where texture is
   meaningful. The existing raster-oriented evaluation adapter remains separate.
3. `DETERMINISTIC_SCIENCE_DIAGRAM`: labels, plots, circuits, apparatus, arrows, measured geometry,
   tables, and answer-bearing layouts. These stay on Python/SVG/HWPX and are excluded from LoRA.

Training examples are selected from immutable crop proposals. One source anchor contributes at most
one selected crop, captions describe only visible morphology and style, and all outputs remain
`EVALUATION_ONLY` with activation `FORBIDDEN`. A small 12--18 sample micro-probe is intentionally
used before expanding the dataset.

## Access patterns and data structures

Composition evaluation performs one bounded pairwise comparison at 800x504 pixels. Pixel masks are
fixed-size arrays; keyed member lookup uses maps; failure-reason deduplication uses a set followed by
stable sorting. Runtime is `O(W*H)` and memory is `O(W*H)`. Training selection validates proposal and
anchor uniqueness with maps and sets in `O(P+S)` time, where the proposal contract bounds `P` and the
micro-probe bounds `12 <= S <= 18`. No database table, index, queue, or cache is added.

## Composition evaluation contract

The additive `local-image-reference-composition-evaluation/1.0` result pins the exact reference
bundle pointer, conditioning PNG, candidate PNG, deterministic evaluator revision, fixed thresholds,
measured metrics, sorted failure reasons, UTC timestamp, and self-hash. JSON Schema 2020-12 validates
the wire shape and Pydantic validates cross-field meaning.

The evaluator measures dilated edge precision/recall/F1, foreground bounding-box overlap, normalized
center displacement, width and height scale ratios, foreground edge-occupancy change, and mean RGB
chroma. The initial fail-closed thresholds were calibrated only against the bounded low-strength and
high-strength evaluation samples. They are a structural regression gate, not proof that a drawing
is scientifically correct. A human must still review recognizable morphology, exam style, and
absence of invented details before any future adapter release.

## Transaction, concurrency, retry, and idempotency

The Orchestrator stages exact immutable inputs, invokes the isolated evaluator, validates the result,
and alone commits the file set. Workers have no NAS or database access. Result identity is derived
from the exact reference pointer, input hashes, evaluator revision, and metrics; byte-identical
replay is idempotent. A conflicting replay fails rather than overwriting an evaluation.

Training continues to use the existing evaluation-only micro-probe claim, workspace, checkpoint,
and result contracts. Concurrent training of the same immutable plan is prevented by its existing
plan/run identities and orchestration boundary. Failed historical probes remain failed records.

## Failure behavior

Missing or stale pointers, schema/media/lifecycle mismatches, hash drift, unsafe paths, undecodable
images, size mismatch, excessive color, or composition threshold failure stop before activation.
There is no fallback to text-only generation, higher conditioning strength, another reference, or
an implicit latest adapter. References with distracting backgrounds may be rejected during human
candidate review; the evaluator must not pretend that foreground segmentation is certain.

## Dependency direction

The schema and frozen value models live in `eom_image_contracts`. Pixel measurement is a pure image
provider utility using the already pinned Pillow and NumPy runtime; it has no HTTP, PostgreSQL, NAS,
or model dependency. Staging and publication remain Orchestrator responsibilities. No new dependency
is introduced.

## Simpler alternatives rejected

Prompt text alone cannot prove preservation. Increasing img2img strength was already observed to
invent or simplify structure. Training photographs and line drawings in one adapter confuses texture
with page style. A general semantic-vision service or new database would be disproportionate for one
fixed-size structural comparison. The additive result contract plus deterministic evaluator is the
smallest implementation that makes the user's composition-preservation rule testable.

## 2026-09-28 micro-probe decision

The 14-anchor, 200-step micro-probe produced adapter revision
`imgadapterrev_2a6a18afca40230d82aa6cd479125d11`. Its manifest remains
`EVALUATION_ONLY` with activation policy `FORBIDDEN`.

The exact three-case BASE/ADAPTER text holdout completed successfully at the runtime boundary, but
human inspection found semantic failures that a style metric cannot excuse: duplicate isolated
specimens, a non-white astronomy background, and an automobile that did not reliably express the
requested collision state. The adapter is therefore not eligible for text-only production.

Reference-conditioned evaluation kept conditioning strength at `0.35` and tested LoRA scales `0.8`
and `1.0`. All three bounded morphology cases passed the deterministic composition thresholds at both
scales. At scale `1.0`, edge recall ranged from `0.854391` to `0.978040`, foreground bounding-box IoU
from `0.988207` to `1.0`, and mean chroma ratio from `0.003018` to `0.003594`.

Those structural passes do not constitute a release decision. A clean isolated organism reference
produced a useful exam-style line drawing, while automobile and rock references retained background
objects, numbers, and source markings. The new low-strength outputs were also visually close to the
predecessor adapter outputs, so superiority has not been demonstrated. Before another activation
candidate is considered, the evaluation population must include more diverse approved exam line-art
anchors and the reference-selection boundary must reject or replace non-isolated source images.

## 2026-09-28 object-line-art successor probe

The additive object-line-art workflow reviewed all 768 campaign candidates independently, selected
24 exact literal crops, and preserved source-group partitions as 16 training, 4 validation, and 4
holdout members. The resulting 200-step run
`imgscicampaignmicrotrainrun_e10cb0aadfbcc6cdd0617632d7aa5c5e` produced adapter revision
`imgadapterrev_9a2817825a8fc67e9811fafb542de34f`, with manifest SHA-256
`sha256:2051f43272fac4ed9c984cad3e312cc27fe758a8c02feeca5190384e7380e594`. Its activation
policy remains `FORBIDDEN`.

The exact BASE/ADAPTER evaluation
`imgscicampaignmicroevalrun_57710f49f4214129af1dd55dbe9d3666` covered four unseen source groups:
three seated students, a fossil shell, two laboratory heating assemblies, and a car body/front
wheel. Its immutable result SHA-256 is
`sha256:b4acf6fd6575e686c79dfc6f775d5b6a112f65cd7d6beb076f8373858fccc4fe`.

Human comparison found a clear style effect: adapter outputs used sparser gray backgrounds,
stronger isolation, simpler composition, and smaller PNG encodings. The fossil became a useful
isolated specimen and the automobile became closer to a compact exam-page silhouette. Those gains
did not establish semantic fidelity. The three-student prompt produced four people, and the two
laboratory assemblies contained synthesized non-authoritative structure. Laboratory-equipment
morphology was included in this bounded probe to test the routing boundary; the result reinforces
that exact apparatus remains a deterministic Python/SVG/HWPX responsibility.

This successor is therefore useful evidence that the selected examples teach assessment line-art
presentation, but it is not an activation candidate. The next experiment must keep object-family
coverage balanced, test count and silhouette preservation against exact references, and keep
answer-bearing or mechanically exact structure outside the generative raster path.
