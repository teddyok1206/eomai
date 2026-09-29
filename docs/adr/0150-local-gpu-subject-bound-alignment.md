# ADR 0150: Align the local GPU subject bound with the released Pack contract

## Decision

The assessment local-image prompt policy accepts an English semantic subject of 3 through 180
ASCII characters. The reference-composition policy revision advances from
`local-gpu-image-prompt-policy/1.9` to `local-gpu-image-prompt-policy/1.9.1` so request identity
continues to pin the exact policy that accepted the input.

Released Content Packs from `generated-knowledge-item@1.20.0` onward already instruct the image
worker to use this 180-character bound. The Catalog implementation retained an older 96-character
constant. A valid 101-character image result therefore committed successfully and acquired its
pinned visual reference, but deterministic GPU handoff rejected it afterward. The worker contract
and the consuming application boundary must use one bound.

## Boundary and data flow

The image worker remains the canonical source of the bounded semantic subject. The orchestrator
continues to route the result and publish the immutable visual-reference receipt. Catalog validates
the subject, composes the derived model prompt, and includes the prompt-policy revision and prompt
hash in the local provider request identity. Workers do not write to NAS, and this change adds no
database, queue, schema, or storage mutation.

The dominant operations are one regular-expression validation and one prompt concatenation over at
most 180 characters, both `O(n)` time and bounded `O(n)` transient space. No index or persistent data
structure changes are required.

## Failure, retry, and compatibility

Non-ASCII input, forbidden content, an unsupported production route, or a subject longer than 180
characters still fails closed. No subject is truncated or silently translated. Existing request
and artifact identities remain immutable; the new policy revision gives newly composed requests a
distinct deterministic identity. Historical failed workflows remain failed and are not replayed or
rewritten.

The simpler alternative of shortening the Pack instruction back to 96 characters would require a
new Pack release and would still leave already accepted results between 97 and 180 characters
unconsumable. Aligning the stale application constant with the existing released contract is the
smallest coherent correction.
