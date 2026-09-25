# ADR 0117: Expanded science-assessment visual learning loop

- Status: Accepted for staged implementation
- Date: 2026-09-25 UTC
- Scope: internal local-image evaluation and deterministic science-figure rendering

## Decision

EOM will use the validated KICE and education-authority science-assessment PDF corpus as a new
source population for two separate improvement loops:

1. a reviewed, non-authoritative raster-crop dataset for bounded SSD-1B LoRA evaluation; and
2. a typed visual-pattern inventory that improves deterministic Python/SVG science figures.

The corpus is a Content Intake dataset, not an automatically activated training dataset. PDF pages,
item regions, visual crops, captions, train/holdout membership, LoRA adapters, pattern statistics,
renderer rules, and generated samples are separate immutable revisions. No PDF is modified and no
released Content Pack, team-lead guidance, base model, or provider binding is overwritten.

The existing content-team authorities remain primary:

- `content-team-integrated-science-authoring-v05.md`;
- `content-team-hwp-question-editor-handoff-v1.md`; and
- the reviewed KICE illustration guide used by the active image role.

Corpus observations may refine the implementation that satisfies those authorities. They may not
rewrite, summarize away, or silently replace them.

## Responsibility and system boundary

Catalog owns selection of exact corpus source pointers and construction of immutable page,
visual-pattern, and candidate-crop manifests. The Orchestrator resolves and stages those pointers.
Isolated PDF/image workers read only staged local members and return typed local results. Workers do
not read PostgreSQL or NAS and do not write canonical artifacts. Only the Orchestrator validates and
commits derived manifests, review decisions, datasets, adapters, evaluation results, and renderer
fixtures to NAS.

The image trainer remains offline and cannot contact an external model or model hub. The production
image provider stays inference-only. Training and image inference retain the existing mutually
exclusive GPU lease.

## Canonical source and revision model

```text
science-assessment corpus revision
  -> exact Content Intake PDF Artifact Revision
  -> deterministic page-image revision
  -> locator proposal revision
  -> human-reviewed visual crop / typed pattern observation revision
     ├─ rights-approved non-authoritative crop dataset revision
     │    -> immutable training plan -> evaluation-only LoRA revision
     │    -> fixed holdout evaluation -> optional successor provider binding
     └─ deterministic visual-pattern inventory revision
          -> typed Python/SVG renderer-rule successor
          -> fixed fixture renders and HWPX/Preview regression evidence
```

Every edge pins the logical ID, immutable revision ID, Artifact ID, Artifact Revision ID, schema,
media type, lifecycle state, and SHA-256 needed for safe resolution. Paths are temporary storage
locations rather than identities. The corpus manifest, raw acquisition hash, metadata-resolution
hash, and policy hash remain part of every derived population identity.

## Dataset eligibility and leakage prevention

The LoRA branch continues the safety boundary from ADRs 0113 and 0114. Eligible crops are limited to
non-authoritative raster style such as nonhuman organisms, fossils, natural textures, astronomical
or geologic scenes, and other imagery whose pixels do not determine the answer. Exact graphs,
tables, maps, apparatus, particle models, axes, values, arrows, labels, boundaries, panel labels,
and answer-bearing geometry remain deterministic SVG or native HWPX content.

Public download availability is not by itself training authorization. A typed rights-policy
revision must explicitly cover internal derivative model training and `LORA_ADAPTER_ONLY` output.
Ambiguous sources remain eligible for RAG/Content Intake only and are excluded from training.

Train, validation, and holdout partitions are grouped before selection by source PDF hash, exam
administration identity, item/source anchor, and perceptual-duplicate cluster. No group may cross a
partition. Exact duplicate hashes use a set/map; perceptual candidates use the existing bounded
Hamming-band index. This prevents a repeated or mirrored exam image from appearing in both training
and evaluation.

The first run over the expanded corpus is another bounded feasibility gate, not a production
activation. It first inventories and reviews proposals. It then selects the smallest diverse sample
that can answer whether the larger corpus improves the base-versus-adapter evaluation. A later
production-candidate dataset must still satisfy the existing minimum, rights, review, deduplication,
and holdout contracts; sample duplication or augmentation cannot be used to reach the minimum.

## Deterministic Python/SVG improvement loop

The pattern inventory records structure rather than copied page imagery. Each observation classifies
the authored visual route and bounded features such as:

- single image, two-image panel, image/table mixed order, or editable table-only material;
- coordinate axes, curves, vectors, arrows, force diagrams, rays, boundaries, legends, and labels;
- apparatus, circuit, particle, cell, geologic section, orbital/astronomical, and map layouts;
- stroke hierarchy, dash pattern, marker shape, grayscale fill, hatching, whitespace, margins, and
  label anchoring;
- whether geometry is authoritative and therefore forbidden from generative pixels.

Counts and layout measurements are aggregate evidence. The renderer receives typed parameters from
the item/image worker; it does not choose scientific values by copying a source problem. Existing
team-lead prompts determine the requested subject, count, relation, placement, and HWPX ownership.
The implementation may add typed primitives and layout strategies only when at least two reviewed
real patterns need them. One-off visual resemblance is insufficient.

Generated PNGs remain 800 by 500 composites with a white background, bounded grayscale palette,
wide margins, and deterministic SVG overlays for scientific labels and geometry. One IMAGE has no
panel label. Two IMAGE members remain separate PNGs and HWPX writes editable `(가)` and `(나)` text.
TABLE remains native editable content and is never rasterized merely because a nearby item has an
image.

## Access patterns and data structures

Dominant operations are exact revision/hash lookup, ordered page and visual iteration, membership,
deduplication, grouped partitioning, pattern aggregation, and immutable manifest assembly.

- revision, source, and pattern lookup use indexed IDs and maps;
- exact uniqueness and partition membership use sets and DB unique constraints;
- stable output uses tuples sorted by source revision, page, anchor, and visual ordinal;
- source/exam groups use a map from group identity to a tuple of candidate IDs;
- perceptual duplicates use the existing four-band Hamming index rather than all-pairs comparison;
- pattern aggregation is one pass over reviewed observations, expected `O(v)` time and `O(k)` space
  for `v` visuals and `k` bounded pattern keys;
- artifact assembly uses typed manifests; PostgreSQL stores only small pointers, state, hashes, and
  indexed relations, never PDF/PNG/model bytes.

No new database index is added without an observed access pattern and query-plan evidence. Repeated
JSON parsing, file hashing, and source resolution are avoided by pinning immutable member hashes and
building one map per run.

## Transaction, concurrency, retry, and idempotency

Each derivation command binds the exact corpus, locator/policy, rights authorization, partition plan,
prompt/guidance revisions, code release, and input member hashes. The identity is replay-stable.
Same-key/different-input conflicts fail closed. A failed attempt stays failed; a retry creates a new
attempt for the same immutable plan.

Page rendering and visual location may run in bounded parallel jobs, but each source page and
proposal population is claimed once through the existing queue/lease boundary. Dataset publication,
training, evaluation, and renderer-rule release are distinct transitions. Completion of one never
implicitly activates the next. Provider activation requires a successor binding, fixed comparison,
human review, and a bounded item canary. Rollback selects the previous binding or renderer rule and
does not delete historical artifacts.

## Evaluation

LoRA evaluation reuses identical subjects, seeds, sampler, dimensions, negative prompt, and fixed
holdout inputs for base and adapter. It measures subject/count/state fidelity, irrelevant people or
text, exam-style preference, grayscale/line readability, crop completeness, and nearest-training
image similarity. Any holdout contamination, memorization, person/text leakage, or scientific
mismatch blocks activation.

Deterministic renderer evaluation uses reviewed fixtures spanning graph, vector, apparatus,
particle, cell, geologic, astronomical, single-image, dual-image, image/table, and table-only cases.
Tests validate typed inputs, safe SVG, exact labels, stable ordering, pixel dimensions, HWPX member
embedding, and Preview/HWPX parity. Human visual review is recorded separately from structural test
success.

## Simpler alternatives rejected

Training directly from full PDF pages would teach publisher text, answers, layouts, and unrelated
content while destroying crop provenance. Sending full team-lead prompts to the raster model would
also mix authoritative semantics with non-authoritative style. Hard-coding one renderer template per
observed figure would copy examples without producing a maintainable grammar. The selected split
keeps generative style, deterministic scientific geometry, and editable publication layout under
separate contracts while reusing the existing trainer, locator, compositor, and HWPX boundaries.
