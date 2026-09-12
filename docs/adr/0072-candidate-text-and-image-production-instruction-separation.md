# ADR 0072: Candidate text and image-production instruction separation

## Status

Accepted.

## Context and responsibility

The content-team authoring result contains candidate-visible editorial fields and an ordered IMAGE
slot, while the later image result owns the internal `illustration_prompt` and typed drawing
constraints. A worker can nevertheless express a production instruction as ordinary DATA text;
JSON Schema correctly accepts that string, and the HWPX renderer correctly preserves it. This is
an editorial boundary violation rather than a rendering failure.

The immutable team-lead guidance files remain authoritative and byte-frozen. A successor Content
Pack clarifies their projection into two channels: candidate-visible factual content in the Item,
and worker-only production instructions in the image result.

## Decision

1. Candidate-visible fields contain only facts, observations, relationships, assumptions, and the
   question. Image-related facts use observational wording, not commands to draw, place, render,
   style, or generate content.
2. The authoring worker emits only typed IMAGE slots. The image worker derives and owns
   `illustration_prompt`, `scene_description`, `scientific_constraints`, and `required_labels` from
   the exact typed draft and the two pinned guidance files.
3. The review worker reports `CANDIDATE_VISIBLE_IMAGE_INSTRUCTION` when production language leaks
   into candidate text. Trusted application validation and Catalog admission apply the same
   authoritative deterministic rule before artifact or Item commit.
4. Existing Items and Content Pack 1.15.7 remain immutable. The rule applies to new workflow
   results and the successor pack.

## Data structure and complexity

Validation performs one stable ordered traversal of the bounded candidate text fields and tests a
small immutable tuple of compiled patterns. Runtime is O(total candidate text bytes) and auxiliary
space is O(1), apart from the bounded violation tuple. No content copy or derived database value is
persisted.

## Safety, failure, and retry

The deterministic guard intentionally recognizes only production-specific vocabulary and active
image-production clauses. Observational exam wording such as “the figure shows” remains valid. A
violation fails before NAS commit with a stable code; retry requires a new corrected worker result
under the same immutable inputs. Review and Catalog independently enforce the boundary, so a worker
finding omission cannot publish the content.

## Alternatives

A word blacklist alone is too broad and would reject legitimate scientific statements. Adding a
new authoring wire field would duplicate information already derived and typed by the image role
and would require a new workflow protocol family. Prompt-only guidance would reduce frequency but
could not fail closed. The successor prompt plus one shared narrow domain rule is the smallest
boundary that both guides generation and prevents publication.
