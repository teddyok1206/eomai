# ADR 0103: Orchestrator-derived PDF review quote hashes

## Context

`pdf-document-review-result@1.0` stores an optional exact quote beside each immutable page-image
anchor. The canonical result also stores `quote_sha256`, defined as EOM canonical JSON SHA-256 of
that quote. Requiring a language-model worker to calculate this deterministic serialization hash
caused a valid review to fail after worker completion. The digest adds no independent semantic
judgment: its only canonical source is the quote in the same result.

## Decision

Keep the released JSON Schema, Pydantic model, stored Artifact shape, API projection, and
`workflow-role/1.25.0` identity unchanged. Change only the worker projection and trusted validation
adapter:

1. the worker-only Structured Outputs schema omits `quote_sha256`;
2. the worker emits the exact bounded quote or `null`;
3. before canonical JSON Schema and Pydantic validation, the orchestrator deep-copies the result and
   fills an absent hash with `content_sha256(quote)`, or `null` when the quote is `null`;
4. an explicitly supplied hash is never replaced, so a mismatched supplied digest still fails;
5. the canonical committed Artifact continues to contain both quote and hash.

The fixed and role prompts state this ownership explicitly. Existing valid V1 results remain valid,
and failed historical Jobs remain immutable.

## Boundaries and data structures

The quote is the canonical small immutable value. The page Artifact Revision and page-image hash
remain the source-location pointer. PostgreSQL stores no PDF or image bytes. Result collections are
bounded tuples after validation; canonicalization performs one ordered pass over targets,
candidates, findings, and their anchor arrays. For `A` bounded anchor occurrences, time is `O(A)`
and the existing defensive deep copy is `O(result size)`. No new table, index, queue, dependency, or
cross-service message is introduced.

## Transactions, failure, retry, and compatibility

Derivation occurs before the existing canonical result boundary and before any Artifact commit.
Malformed quotes, supplied mismatched hashes, invalid page pointers, and all other result errors
still fail closed as `WORKER_RESULT_INVALID`. Commit, event, idempotency, lease, and NAS ownership
remain unchanged. The simpler alternative of improving prompt wording while retaining a
worker-authored digest is insufficient because it continues to assign deterministic serialization
work to a probabilistic worker. Silently overwriting a supplied mismatch is also rejected because it
would hide a contradictory worker result.
