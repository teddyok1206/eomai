# Content-team statement marker normalization

Status: implementation decision, 2026-09-09 UTC

## Decision

Treat one exact standalone terminal `<보기>` line in `draft.stem` as a source-format projection
when, and only when, the same draft has a nonempty typed `statements` tuple and the marker is
separated from nonempty stem content by one source-format line break or its single blank-line
variant. Remove that redundant terminal line and only its adjacent separator before the existing
Pydantic and Markdown materialization checks. The serializer remains the authority that emits
exactly one standalone marker from the typed statements.

Inline text such as `<보기>에서` is authored content and is unchanged. Zero or multiple exact
markers, leading or middle markers, noncanonical marker spelling/whitespace, excessive separator
lines, and markers outside `stem` are not normalized and remain subject to the existing serializer's
fail-closed checks. The normalizer removes only the terminal marker and its adjacent source-format
separator; unrelated leading newlines and all semantic text remain byte-preserved. It does not infer
statements or alter any other draft field.

## Boundary and invariants

- The HWPX contracts package owns the named pure normalizer alongside the existing duplicate item
  number and score-marker normalizers. Workflow result validation calls it for authoring result
  V7, V8, and V9 only through their shared canonicalization path.
- Canonical content remains the typed `statements` values. The standalone marker is renderer syntax,
  not a second semantic statement container. The existing serializer emits it and proves a lossless
  parse round trip.
- No JSON Schema, protocol, preset, workflow, Artifact, database record, ID, pointer, or hash format
  changes. Historical results are untouched. The correction is deterministic, pure, and linear in
  the bounded stem length.
- A retry may retain its exact pinned V11 preset after the corrected packages are installed and all
  importing services are restarted, because neither instruction nor preset semantics changed.

## Verification

Unit tests cover exact terminal removal, idempotency, inline preservation, absent-marker replay,
leading-newline preservation, and leaving leading, middle, excessive-separator, noncanonical,
repeated, or statement-less cases untouched for fail-closed serialization. Authoring V7/V8/V9
projected results each validate, canonicalize, serialize with one standalone marker, and round-trip
through the correct Markdown parser version.
