# ADR 0158: Review semantic-pointer final scan

## Status

Accepted for implementation.

## Decision

The review result contract intentionally permits only student-facing semantic draft roots.  A live
exact-source variation review used `/equation_sources/0`: it was an existing scalar leaf, but it is
renderer provenance rather than assessed content, so trusted commit validation correctly rejected
it.  Content Pack 1.20.10 is an immutable successor that requires a final recursive scan of every
review `draft_json_paths` array and explicitly redirects equation reasoning to the corresponding
statement, labeled block, or explanation leaf.

The canonical source remains the exact authoring Artifact Revision.  Pointer resolution is bounded
tree traversal and set membership in the nine allowed roots, O(P * D) time for P bounded pointers
and pointer depth D, with O(P) output validation state.  No schema, database, workflow state machine,
or Artifact is rewritten.  Existing Orchestrator validation remains authoritative and fail-closed.

## Alternative rejected

Allowing `equation_sources` because it happens to contain a string would weaken the semantic
evidence policy and let derived renderer metadata stand in for student-visible content.  Repairing a
submitted worker result would create a false attestation.  A prompt successor is the smallest safe
change.
