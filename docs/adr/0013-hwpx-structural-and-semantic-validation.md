# ADR 0013: Separate Structural, Semantic, And Hancom Validation

## Status

Accepted.

## Decision

Use three independent compatibility gates:

1. Structural validation checks bounded ZIP/XML safety, core package references, marker removal,
   image and equation bindings, IDs, and active content.
2. Semantic round-trip extracts a canonical field view and compares it with the validated input
   using exact comparison or CRLF-to-LF normalization only.
3. Manual Hancom validation records Windows open, edit, save, reopen, and re-saved semantic compare.

Package byte SHA-256 and semantic SHA-256 remain separate. Preview content is non-authoritative and
may produce a warning without converting an otherwise valid Linux result into a success claim for
Hancom compatibility.

## Consequences

Synthetic fixtures can validate security and deterministic transforms, but never establish Hancom
compatibility. Linux automation can reach `LINUX_POC_VALIDATED`; only recorded human results can
reach `HWPX_POC_V0_COMPLETE`.
