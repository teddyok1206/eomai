# Local-image human exclusion clauses

Status: accepted

Last reviewed: 2026-09-12 UTC

## Responsibility and canonical source

The Catalog-owned local image adapter enforces the fixed GPU subject policy before invoking the
provider. The canonical subject remains the exact `generation_prompt` pinned in the validated image
result. Human subjects remain forbidden; a mention of a human term is allowed only when a bounded
sentence clause explicitly excludes it and contains no earlier affirmative human action.

## Access pattern and data structure

The adapter performs ordered regular-expression scans over a prompt bounded to 4,000 characters.
Each human match examines at most 128 following and 24 preceding characters, so time is O(n), space
is O(1), and ordering is stable. A parser framework or persisted derived flag would add complexity
without another use case and would risk separating policy from the immutable source text.

## Concurrency, retry, and failure

The prompt-policy revision advances to `local-gpu-image-prompt-policy/1.1`; it participates in the
deterministic provider request identity, so historical requests cannot be confused with the new
semantics. A positive human request, an ambiguous mention, mixed positive action followed by an
unrelated exclusion, or malformed text still fails with `LOCAL_IMAGE_INPUT_INVALID` before any GPU
unit starts. Provider, artifact, and NAS transaction boundaries are unchanged.

## Dependency direction and alternative

The rule remains in the Catalog infrastructure adapter that owns GPU invocation. Workers neither
invoke the provider nor write to NAS. Removing the human check would weaken safety, while matching a
bare noun rejects valid instructions such as “사람, 문자는 포함하지 않는다”; bounded exclusion-clause
recognition is the smallest expression that preserves both requirements.
