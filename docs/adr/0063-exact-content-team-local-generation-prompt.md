# Exact content-team local-generation prompt

Status: accepted for the generated-knowledge-item 1.15.3 successor

Last reviewed: 2026-09-12 UTC

## Decision and boundary

For a `HYBRID_LOCAL_GENERATIVE` drawing, the image worker must copy the authoring worker's
`illustration_prompt` into `drawing.generation_prompt` byte-for-byte. The image worker may choose only
the typed route, overlay, and negative constraints allowed by the existing contracts; it may not
translate, summarize, reorder, prefix, suffix, or otherwise rewrite the content-team prompt. The local
provider continues to receive the validated `generation_prompt` through the Catalog application
boundary. Workers do not contact the provider or write to NAS.

The canonical source is the ordered IMAGE slot in the pinned authoring Artifact Revision. The image
result carries the small immutable prompt value rather than an image payload or storage path. The
existing Pydantic cross-field validator is authoritative and fails before provider invocation or
artifact commit when the two values differ. JSON Schema 2020-12 continues to validate each field's
shape; cross-field equality remains a semantic model invariant.

## Access pattern and structures

The check is one O(1) equality comparison per drawing over a tuple bounded to two entries, with O(n)
time in the prompt length and no persistent index, cache, DB schema, or queue change. Logical image,
revision, artifact revision, and content hash identities remain separate.

## Concurrency, retry, and alternative

The successor release and profile hashes are pinned before execution. A mismatch fails closed before
the GPU side effect. A failed historical workflow is preserved; verification uses a fresh workflow and
idempotency key. Silently repairing the result in the orchestrator would hide worker drift, while
mutating 1.15.2 would violate immutable execution history, so an explicit successor prompt is the
simplest safe change.
