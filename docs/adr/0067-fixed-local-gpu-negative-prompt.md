# ADR 0067: Fixed local-GPU negative prompt

## Decision

The fixed local SSD-1B provider receives one compact, ordered negative denylist owned by the
Catalog prompt policy. A worker-authored `negative_prompt` remains part of the validated drawing and
therefore its immutable drawing hash, review evidence, and request identity, but it is not appended
to the provider's 77-token negative encoder input.

The fixed denylist covers the reviewed renderer prohibitions: color and gray background, framing,
gradients and shadows, photographic/3D/perspective styles, scenery and decoration, extra or
duplicate objects, collage/crop, and generated text, labels, numbers, symbols, and equations.
Authoritative marks remain in the deterministic SVG overlay.

## Structure and complexity

The denylist is an immutable ordered tuple and joins once in O(n) time and output space. The worker
field is neither reparsed nor copied across the provider boundary. The drawing hash and policy
revision remain in the generation request's idempotency preimage, so a provenance or policy change
cannot adopt a prior request.

## Failure and alternatives

Both provider tokenizers still enforce their 77-token limits without truncation. Appending free-form
Korean worker text made a live negative prompt 106 tokens even though the fixed denylist was only 45
and already contained the same prohibitions. Token truncation was rejected because it can silently
remove a safety term; loading tokenizers into Catalog was rejected because it inverts the GPU
adapter boundary.
