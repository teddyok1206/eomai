# Content-team authoring prompt V5 design

## Boundary and canonical source

The content team's 52,274-byte Markdown is untrusted reviewed reference input. V5 preserves its
exact bytes and SHA-256 as a CONFIG reference and materializes it into authoring and review worker
workspaces. The released instruction-bundle revision, not the Markdown itself, remains execution
authority.

## Identity and access pattern

The source prompt, typed Markdown adapter, instruction bundle revision, and output item revision are
separate immutable identities. Runtime access is one hash-checked key lookup by `reference_key`;
roles receive a keyed reference bundle rather than copied prompt text inside requests. Five small
references are bounded well below the existing 512 KiB member limit, so lookup and verification are
O(1) per reference and storage is O(reference bytes) per immutable bundle revision.

## Transaction, failure, and compatibility

Bootstrap publishes all reference artifacts before the V5 preset can be released. Missing files,
hash drift, unsafe paths, unused references, or a changed role-reference map fail before runtime.
V5 retains workflow-role/1.13.0 because the worker protocol is unchanged; only the immutable
instruction/reference bundle revision advances. Replaying identical V5 inputs is idempotent through
existing content hashes and bootstrap keys.

## Output adaptation

The source prompt's HwpQuestionEditor Markdown rules are projection requirements, while canonical
AssessmentItemContent remains presentation-neutral. Decimal `2.5` scoring is not representable by
the current integer score contract and therefore fails explicitly instead of being rounded. A later
decimal-score protocol revision must update item, preview, authoring, and HWPX schemas together.

The simpler alternative—mentioning the staging path from an instruction—was rejected because worker
workspaces cannot access staging and it would not pin bytes, provenance, or revision identity.
