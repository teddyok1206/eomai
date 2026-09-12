# ADR 0069: Bind typed bottom stems at the HWPX handoff

## Status

Accepted.

## Boundary and canonical source

The approved Item Revision and its immutable Item Content Artifact Revision are the canonical source
for `stem`, `bottom_stem`, and `score_display`. The HWPX workspace is a temporary materialization;
the renderer must not alter the Item Revision or persist a second source document.

The immutable HwpQuestionEditor handoff reparses serialized Markdown and recognizes a bottom stem
through a small Korean phrase regular expression. A valid V3 item used a different reviewed phrase,
so the parser left the typed bottom stem after a labeled CONDITION block as a second paragraph and
rejected the otherwise supported layout.

## Decision

After parsing, the EOM HWPX adapter compares the parser result with the exact typed bottom stem and
rendered score marker. If the parser already produced the exact value, it remains unchanged. If the
parser produced no bottom stem, the adapter splits only an exact, unique terminal Markdown suffix of
`<typed bottom_stem> [<score_display>점]`. Any non-terminal, duplicate, partially matching, or
conflicting value fails closed as `HWPX_REFERENCE_UNSAFE`.

The approved wording and source hashes remain unchanged. The renderer report records whether this
boundary projection was needed. A failed build remains immutable; recovery creates a new build ID
and idempotency key after deployment.

## Data structures, complexity, and ownership

This is an O(n) bounded suffix and uniqueness check over one small question string with O(1)
additional state. It adds no database table, index, queue, cache, dependency, protocol version, or
NAS write path. The HWPX infrastructure adapter owns the compatibility binding; domain contracts do
not import renderer infrastructure.

Tests cover exact suffix recovery, rejection of unproven boundaries, existing recognized phrases,
and a full labeled-block render whose bottom-stem wording is outside the handoff phrase vocabulary.
