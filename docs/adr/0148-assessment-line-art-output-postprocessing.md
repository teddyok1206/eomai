# ADR 0148: Assessment line-art output postprocessing

## Status

Accepted on 2026-09-28 UTC.

## Context and responsibility

The V4 base-model route proved that an approved visual reference can be resolved, simplified,
passed through local SSD-1B inference, and committed with exact receipts.  A real trilobite Item
canary also showed a remaining publication defect: grayscale conversion preserved photographic
substrate cracks and frame lines.  Prompt text cannot prove their removal, and changing V4 output
bytes in place would make one pinned request produce different results under the same contract.

The image provider therefore owns one deterministic post-inference conversion from the raw local
model raster to an assessment line-art raster.  Catalog remains responsible for resolving pointers,
staging the exact reference, starting the provider, validating its receipt, and committing the
validated Artifact.  Workers continue to provide only the semantic drawing intent and never write
to NAS.

## Decision

Introduce the additive V5 family:

- `local-image-provider-binding/5.0`;
- `local-image-reference-conditioned-composite-request/5.0`;
- `local-image-reference-conditioned-composite-receipt/5.0`;
- route `eom-local-morphology-conditioned-base-line-art/5.0`.

The binding and request pin an immutable `local-image-assessment-line-art-postprocess/1.0` value.
It records the input smoothing, broad foreground-mask construction, fixed output tone thresholds,
and protected canvas margins.  The receipt records output foreground, border foreground, and edge
density plus the exact Pillow runtime.  The postprocessor rejects empty, excessively filled,
border-cluttered, or excessively detailed outputs before any Artifact commit.

The canonical generation output member contains the postprocessed bytes.  Raw model bytes are an
ephemeral provider value and are neither registered nor copied to PostgreSQL.  Existing V1--V4
requests, receipts, bindings, Artifacts, and schema bytes remain unchanged.

## Data flow and pointer model

```text
pinned visual-reference Artifact Revision
  -> bounded workspace materialization
  -> deterministic V3 reference simplification
  -> local SSD-1B img2img inference
  -> deterministic V5 assessment line-art postprocess
  -> composite + V5 receipt
  -> orchestrator-validated immutable stimulus Artifact Revision
```

Logical IDs, revision IDs, member paths, schemas, media types, and SHA-256 values remain separate.
The workspace is temporary materialization; the registered Artifact Revision is canonical.

## Access patterns and structures

The dominant operations are immutable pointer lookup, one ordered raster scan, fixed-radius Pillow
filters, histogram counts, and append-only receipt commit.  Frozen typed models and manifests are
used for ordered output; keyed DB lookups retain their existing indexes.  For a fixed 800x500
canvas, processing is `O(W*H)` time and `O(W*H)` transient memory.  No table, queue, cache, index,
or binary DB value is introduced.

## Transaction, failure, retry, and idempotency

The provider writes outputs exclusively inside one isolated workspace.  Any input hash mismatch,
unsupported policy, invalid raster, metric violation, or existing partial output fails closed with
a stable provider error before Catalog commit.  Exact completed V5 receipts may be replayed only
after all pinned inputs and output hashes validate.  Terminal Workflow failures are historical and
are not rewritten; a corrected Item canary uses a fresh Workflow identity.

## Alternatives

Prompt-only cleanup is insufficient because the model may still reproduce texture.  Activating the
conditioning PNG directly would discard useful model reconstruction.  Mutating V4 is simpler in
code but violates reproducibility.  A general image-processing framework is unnecessary; the V5
successor adds only the policy and metrics required by this observed production defect.
