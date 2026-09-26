# ADR 0121: Science raster refinement and exploratory LoRA selection

- Status: Accepted for protocol-first implementation
- Date: 2026-09-26 UTC
- Scope: internal assessment-image data; evaluation-only SSD-1B adapters

## Context

ADR 0120 correctly prevented whole panel montages, labels, masks, and deterministic
assessment diagrams from becoming LoRA inputs. Its first review left only seven clean
single-subject rasters. Treating every multi-photo crop as permanently unusable would
throw away useful internal science imagery and make the dataset too small to improve a
local model.

The problem is not that a source page contains multiple photographs. The problem is
training on the **unseparated page layout**: that teaches the model to emit panels,
captions, answer marks, and geometry rather than a reusable science subject.

## Decision

EOM keeps three hard boundaries:

1. answer-bearing diagrams, axes, labels, tables, formulas, and deterministic geometry
   remain Python/SVG evidence, not raster training data;
2. untrimmed panel layouts, redactions, and text-contaminated crops never enter a
   training set; and
3. no adapter becomes active without a separate evaluation and release decision.

For natural photographs, fossils, astronomical scenes, microscopic textures, and
non-authoritative geologic textures, EOM adds a successor **raster-refinement** path.
It derives one or more panel-level crops from a pinned parent candidate using an exact
normalized bounding box. Each refined crop has a distinct logical ID, immutable output
revision, image SHA-256, parent-candidate pointer, caption, and review decision.

The refiner may trim blank borders and split a visible panel boundary. It may not erase
or synthesize content, infer a missing subject, or crop away answer-bearing information
to make a diagram look photographic. If a clean natural-photo panel cannot be isolated,
it remains excluded.

## Dataset policy

The dataset is deliberately tiered rather than all-or-nothing:

```text
high-confidence single-subject raster
  -> validation / holdout preferred

verified refined natural-photo panel
  -> train-only by default

diagram / labelled science structure
  -> Python/SVG renderer evidence
```

This maximizes useful image variety without weakening the independent holdout. A small
exploratory probe may use a separately versioned contract with at least five distinct
TRAIN groups, one VALIDATION group, and one HOLDOUT group. It remains
`EVALUATION_ONLY` and `FORBIDDEN` from activation. The existing 12/1/2 micro-probe
contract is not changed or reinterpreted.

## Ownership and invariants

```text
pinned pilot result + pattern inventory + raster review
  -> immutable refinement plan
  -> isolated local crop worker
  -> orchestrator-committed refinement artifact
  -> reviewed exploratory or full crop set
```

The worker receives only staged parent PNGs and the schema-validated refinement plan;
it never accesses PostgreSQL, NAS, the network, or another worker. The Orchestrator
validates output size/type/hash, parent identity, crop bounds, and canonical manifest
before committing a single Artifact file set.

Primary operations are parent-candidate key lookup and ordered proposal iteration, so
validators use maps/sets and run in `O(n)` time and space for at most 512 parents and
1024 refined crops. No binary payload is stored in PostgreSQL; the manifest contains
only typed pointers and hashes.

## Failure and alternatives

Missing parent, stale/hash-mismatched review, non-positive/out-of-bounds crop, duplicate
derived bytes, attempted label/diagram route, or mismatched caption fails closed. A
failed refinement is a new terminal attempt; it does not rewrite the parent candidate
or historical crop set.

The simpler alternative—accepting whole multi-panel candidates as LoRA images—would
increase count but train the exact layout artifacts that EOM is trying to avoid.
Conversely, rejecting every panel indefinitely would waste useful source diversity and
keep the local model underfit. Explicit, pinned panel refinement is the smaller durable
middle boundary.
