# ADR 0132: Separate science-subject route coverage from production visual quality

## Status

Accepted for protocol-first implementation on 2026-09-27 UTC. This decision does not authorize
adapter activation or publication of benchmark images as Item components.

## Responsibility and boundary

The V1 science-subject benchmark proves that every inventoried subject has an executable route,
that exact output cardinality and hashes close, and that forbidden GPU human requests are rejected.
It does not prove that a route diagnostic is a production-ready illustration. In particular, the
bounded deterministic benchmark renderer exercises primitive families; the production path uses a
worker-authored, sanitized SVG through the Catalog compositor. Likewise, a successful BASE/ADAPTER
pair proves generation, not semantic or KICE-style fitness.

This decision adds an immutable engineering quality review after a successful benchmark. The
review classifies each subject as diagnostic-only, base-preferred, adapter-preferred, or neither
acceptable. It remains evidence for refinement and cannot activate a model. A later production
candidate must exercise the real Catalog SVG or local-raster compositor and pass its existing Item,
review, registration, and HWPX gates.

## Canonical source and revision model

The review pins these existing immutable members:

```text
subject inventory Artifact Revision
  + benchmark plan Artifact Revision
  + benchmark result file-set Artifact Revision
  -> immutable subject-quality review Artifact Revision
```

It stores no PNG bytes, prompts, source pages, Item content, or model weights. Every entry uses the
existing subject and case identities. The review self-hash is semantic; the Artifact member hash is
the exact serialized byte hash. Those identities remain separate.

## Access patterns and data structures

The dominant operations are subject-key lookup, case membership, output-variant lookup, and stable
ordered iteration. Validation builds maps keyed by subject ID, case ID, and `(case_id, variant)`,
plus sets for case and reason uniqueness. For at most 256 subjects and 768 outputs, validation is
`O(S + C + O)` time and space. A JSON Artifact is sufficient; no table or index is added.

## Transaction, concurrency, retry, and idempotency

The Orchestrator resolves the three pinned members, validates JSON Schema 2020-12 and Pydantic
semantics, checks the review against their exact case/output sets, then publishes one immutable
control Artifact. The idempotency key is derived from the semantic review hash. Byte-identical replay
returns the same Artifact; a conflicting payload fails closed. No worker writes NAS and no review
changes an existing benchmark result.

## Quality meanings

- `DIAGNOSTIC_ONLY`: execution succeeded, but the result did not exercise the production
  compositor and is not visual-quality evidence.
- `BASE_PREFERRED`: the base output is the stronger current candidate; this does not activate it.
- `ADAPTER_PREFERRED`: the adapter output is the stronger current candidate; it still requires
  multi-seed and bounded production canaries.
- `NEITHER_ACCEPTABLE`: both variants require prompt, data, route, or composition refinement.

The adapter activation recommendation is always `FORBIDDEN` in this contract. Activation requires
a different successor contract after representative production-path and rollback evidence.

## Failure and retry behavior

Missing/stale/hash-mismatched pointers, incomplete subject coverage, unknown or duplicate cases,
impossible verdict/variant combinations, unsorted fields, wrong counts, or any activation request
fail closed. The review does not reinterpret failed generation as success and does not substitute a
latest plan, inventory, result, or adapter.

## Simpler alternative rejected

A prose note beside contact sheets would record observations but could drift from the exact
benchmark and could accidentally be read as activation approval. Adding a boolean `looks_good` to
the benchmark result would mix worker execution with independent assessment and mutate the meaning
of a released result contract. A small immutable review contract is the simplest boundary that
preserves both meanings.

## First accepted review evidence

The first complete benchmark and independent review were published on 2026-09-27 UTC. The run
covered all 87 inventory subjects and produced 69 deterministic diagnostics, 18 BASE/ADAPTER pairs,
and two correctly rejected human-raster negative controls. The pinned review classified 69 entries
as `DIAGNOSTIC_ONLY`, five as `BASE_PREFERRED`, seven as `ADAPTER_PREFERRED`, and six as
`NEITHER_ACCEPTABLE`. Its activation recommendation is `FORBIDDEN`.

The exact review is `imgscisubjectreview_9acf3bcd62e7321eaf20203c8bf6e579`, semantic SHA-256
`sha256:50caf73efdd90f0c5116e47bd022546084d32f69016f71931463b81227e46c46`, stored as Artifact
`artifact_aebc6cf021c149a8bbbe170c7e214dd1` Revision
`rev_89652f7ba9554499aceefb55f9a0da71`. The result and review evidence are summarized in
[Science visual subject benchmark status](../status/SCIENCE_VISUAL_SUBJECT_BENCHMARK_2026-09-27.md).
