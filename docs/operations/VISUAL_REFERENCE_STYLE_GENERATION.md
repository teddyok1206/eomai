# Visual-reference-grounded local image generation

This runbook operates the ADR 0135 path. It keeps the two image responsibilities separate:

- a human-approved local LoRA release supplies the black-and-white Korean assessment style; and
- a pinned public-domain or CC0 Wikimedia Commons reference supplies object morphology.

The content-team prompt remains authoritative and unchanged. Reference titles, captions, EXIF, and
web content are untrusted data and never enter the prompt. Scientific labels, values, arrows, axes,
answer-bearing geometry, and `(가)/(나)` remain deterministic SVG or editable HWPX content.
The provider-facing positive and negative prompts use the bounded
`local-gpu-image-prompt-policy/1.7`; the complete team-lead instructions remain pinned as
provenance outside the two 77-token CLIP inputs and are never silently truncated.

## Implemented boundary

```text
image-result@12 HYBRID drawing
  -> bounded English morphology subject in alt_text
  -> Orchestrator discovery command
  -> trusted Commons discovery adapter
  -> immutable visual-reference intent
  -> trusted acquisition + normalization
  -> Orchestrator-owned reference bundle Artifact Revision
  -> image ARTIFACT_COMMITTED event publication receipt
  -> Catalog exact receipt/pointer/hash resolution
  -> provider-binding/2.0 exact released LoRA pointer
  -> isolated reference-style provider
  -> image Artifact manifest with reference and style provenance
```

Workers do not access the Internet, PostgreSQL, or NAS. The discoverer and acquirer have a bounded
Wikimedia-only network policy. The generator has `PrivateNetwork=true`. Only the Orchestrator
publishes intent and bundle bytes, and only the Catalog stages the exact verified normalized PNG
into the fixed provider workspace.

The dominant operations are exact ID/hash lookup, candidate membership, and ordered candidate
selection. Contracts use keyed maps and sets in `O(C)` time and space with `C <= 5`; Artifact and
event reads use indexed immutable identities. No new DB table, queue, cache, or migration exists.

## Source compatibility

Commons `imageinfo` currently appends one fixed tracking tuple to original upload URLs and may emit
legacy HTTP/localized license deed URLs. The trusted adapter:

- accepts only the exact ordered `utm_source=commons.wikimedia.org`,
  `utm_campaign=imageinfo`, `utm_content=original` tuple;
- strips that tuple before download and persistence;
- rejects every other query parameter;
- maps accepted `cc0` and public-domain identifiers to fixed canonical HTTPS license URLs; and
- independently rechecks page revision, title, canonical page URL, MIME type, byte/pixel bounds,
  original bytes, and normalized PNG hash.

## Activation gate

Do not activate `provider-binding/2.0` merely because source tests or evaluation samples pass.
Activation requires all of the following:

1. A `local-image-production-style-adapter-release/1.0` value in `RELEASED` state that pins exact
   adapter Artifact, Artifact Revision, manifest member, config, weights, and human review.
2. A review that authorizes the requested subject scope. The current expanded science adapter
   remains `EVALUATION_ONLY`; the global three-seed decision is `GLOBAL_ADAPTER_ACTIVATION_FORBIDDEN`.
3. Exact adapter files installed under `/srv/eom/models/image-style` and verified against the release
   before any GPU execution.
4. A root-owned `local-image-provider-binding/2.0` selecting that release, the unchanged approved
   SSD-1B model, reference policy strength `0.35`, and LoRA scale `0.8`.
5. Coordinated image contracts/provider, Orchestrator, Catalog, workflow runner, and Application API
   deployment from one reviewed compatible source set. `EOM_RUNTIME_SOURCE_COMMIT` must equal the
   installed source commit.
6. Installed and verified discoverer, acquirer, reference provider, and reference-style provider
   units; no active image job while replacing their wheels or unit files.
7. One bounded approved Item canary through Preview, HWPX package-internal image embedding, and
   authenticated download before expanding the authorized subject scope.

If any release, pointer, lifecycle, schema, media type, source page, normalized member, prompt,
receipt, or output hash differs, stop. Never synthesize a release from evaluation weights, silently
downgrade V2 to V1, retry with a different reference, or substitute a latest revision.

## Evaluation samples

Evaluation samples are explicitly labeled `EVALUATION_SAMPLE`. They may use the current immutable
evaluation adapter to compare the combined path, but they do not create a production release or
binding. A sample record pins:

- Commons page ID, page revision, canonical URL, original byte hash, license, and normalized PNG;
- adapter logical/revision IDs and adapter-manifest hash;
- unchanged assessment prompt-policy hash, negative-prompt hash, seed, conditioning strength, and
  LoRA scale;
- model revision and runtime identity; and
- output member and SHA-256.

Automobiles, organisms, and natural specimens are appropriate morphology-grounding samples.
Authoritative laboratory apparatus, circuits, axes, tables, labels, and numeric geometry remain on
the Python/SVG route even if a raster comparison is useful for research.

The bounded 2026-09-27 evaluation also established an activation limitation. Raw photographic
conditioning at strength `0.35` preserved morphology but copied color and background detail. A
deterministic monochrome edge-conditioning experiment removed color and produced a useful isolated
organism drawing, but cluttered automobile and rock references still leaked background structure;
raising evaluation-only strength to `0.65` increased unwanted synthesis. These are evaluation
results, not a new production policy. A future successor must pin a candidate-suitability decision
and the exact derived conditioning member/hash before changing the released `0.35` policy. Until
that successor and its review exist, the current adapter remains `EVALUATION_ONLY` and global
activation stays forbidden.

## Rollback

Rollback selects the previous immutable base-only V1 binding and restarts only the coordinated
compatible runtime set. It does not delete reference bundles, adapters, receipts, Item revisions, or
historical images. In-flight V2 work retains its pinned binding and must finish or fail explicitly;
it is never reinterpreted as V1.

## Verification

Before merge or deployment run the JSON Schema/Pydantic contract suite, discovery/acquisition
negatives, Orchestrator publication tests, Catalog receipt and pointer tests, provider reference and
style tests, wheel inventory, Ruff, strict mypy, and `diff --check`. Live reference acquisition and
GPU executions remain bounded and opt-in because they consume network/GPU resources.
