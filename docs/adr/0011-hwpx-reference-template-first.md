# ADR 0011: HWPX Reference-Template-First Rendering

Status: Accepted

## Context

HWPX is an open XML-based package, but practical Hancom compatibility depends on the consistency of
the complete package: namespaces, version declarations, styles, object IDs, relationships, binary
parts, manifest, and spine. Generating every OWPML object from first principles would make this first
POC claim compatibility that Linux structural checks cannot establish.

## Decision

- Use a real HWPX saved by the laboratory's Hancom version as the only production reference.
- Analyze it as an untrusted archive and compile unique marker/object bindings tied to its SHA-256.
- Replace known text, table-cell text, image bytes, equation source, and bounded metadata only.
- Preserve unknown XML, package entries, object IDs, namespaces, version profile, entry order, and
  compression methods wherever the bound replacement does not require a change.
- Normalize ZIP timestamps to a fixed value for deterministic POC output; semantic and package hashes
  remain separate. Compatibility of this normalization is part of the manual Hancom gate.
- Never reuse a binding manifest with another template revision.
- Treat actual open/edit/save/reopen in the declared Hancom version as the final compatibility gate.

## Consequences

V0 supports one fixed combined item-and-solution layout. It is safer than an unconstrained writer but
cannot proceed beyond code-complete without a reference. General OWPML object generation is deferred.
