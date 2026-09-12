# ADR 0066: Zero-based content-team visual slots

## Decision

Content-team image output uses the zero-based position of an IMAGE member in the authoring draft's
ordered `visuals` tuple. It does not use a human-facing ordinal or an IMAGE-only counter. The image
worker copies `(visual array index, label)` exactly. Catalog remains the authoritative fail-closed
validator and rejects any different tuple before GPU materialization or artifact commit.

## Structure and complexity

The authoring draft is an immutable ordered tuple. One linear enumeration produces the expected
ordered IMAGE slots in O(v) time and O(i) space for at most two visuals. Direct tuple comparison is
stable and avoids an extra map because order itself is part of the contract.

## Failure and retry

A mismatch fails before side effects. It is corrected by a new immutable Content Pack release and a
new workflow request; historical worker results and pack releases are not rewritten.
