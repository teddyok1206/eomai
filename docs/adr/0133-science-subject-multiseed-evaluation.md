# ADR 0133: Re-evaluate raster science subjects across fixed additional seeds

## Status

Accepted for protocol-first implementation on 2026-09-27 UTC. This decision does not authorize
adapter activation, additional training, or publication of generated images as Item components.

## Responsibility and boundary

The first subject benchmark evaluated all 18 raster-generating subjects at one deterministic seed.
That is enough to prove the execution route, but not enough to distinguish a stable adapter effect
from seed variance. This successor evaluates the same pinned base model and adapter at exactly two
additional deterministic seeds per subject. It changes neither the V1 benchmark nor its review.

The Orchestrator resolves and stages the exact subject inventory, V1 quality review, adapter
manifest, adapter files, and plan. The isolated image worker reads only staged inputs and writes
bounded local BASE/ADAPTER PNG pairs plus a typed result. Only the Orchestrator validates and
commits a result file set to NAS. No worker reads PostgreSQL or NAS.

## Canonical sources and revision model

```text
subject inventory Artifact Revision
  + V1 quality-review Artifact Revision
  + pinned base-model revision
  + evaluation-only adapter Artifact Revision
  -> immutable multi-seed plan Artifact Revision
  -> immutable multi-seed result file-set Artifact Revision
  -> immutable multi-seed visual review Artifact Revision
```

Every pointer pins logical identity, immutable revision, schema, media type, and SHA-256. The plan
contains prompts, prompt hashes, seeds, and small metadata but no model weights or PNG bytes.

## Access patterns and data structures

The dominant operations are subject lookup, review lookup, case lookup, and `(case, variant)` output
membership. Validators use dictionaries and sets and preserve sorted tuples. For 18 subjects, 36
additional cases, and 72 outputs, validation is `O(S + C + O)` time and space. No database table or
index is justified; the plan, result, and review are immutable JSON Artifacts.

## Transaction, concurrency, retry, and idempotency

Case IDs bind subject, seed ordinal, and exact seed. Seeds are derived from the subject key and
ordinal and cannot repeat the original V1 seed. A retry reuses the same plan and command. Result
publication uses the run ID as an idempotency identity; same bytes replay and conflicting bytes fail
closed. One exclusive GPU lease covers the isolated run.

## Validation and review

- exactly the 18 V1 raster-generating subjects are included;
- every subject has exactly two additional cases with ordinals 1 and 2;
- BASE and ADAPTER use identical prompt, negative prompt, seed, model, dimensions, steps, and
  guidance for each case;
- output cardinality is exactly two per successful case;
- a later review compares the original case and both additional cases, records per-seed preference,
  and classifies the subject as stable base, stable adapter, mixed, or neither acceptable;
- activation remains `FORBIDDEN` regardless of the aggregate preference.

## Failure and rollback

Missing or stale pointers, hash/schema/media mismatch, a non-raster subject, incomplete review
coverage, repeated or original seeds, output drift, GPU runtime drift, or unexpected output members
fail closed. The current production binding remains base-only, so rollback is no activation rather
than weight deletion. All prior plans, results, reviews, and failed attempts remain immutable.

## Simpler alternative rejected

Editing the V1 plan builder to vary its seed would change a released one-case-per-subject contract.
Running untracked local prompts would lose exact model, adapter, review, and output provenance. A
small additive multi-seed protocol is the simplest reproducible way to measure variance without
creating a new training or queue framework.
