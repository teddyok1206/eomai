# ADR 0058: Project General Multiline Stems at the HWPX Handoff

## Status

Accepted.

## Context

The canonical `assessment-item-content` V2/V3 contracts allow a prose `stem` containing paragraph
boundaries. The reviewed, immutable HwpQuestionEditor handoff accepts a multiline `Q_STEM` only for
its own typed table, labeled-block, visual-slot, and inquiry layouts. Those structures already live
in separate typed Item Content fields. Passing an otherwise ordinary multiline prose stem to the
handoff therefore fails before package construction.

The canonical source remains the approved Item Revision and its pinned Item Content Artifact
Revision. The HWPX workspace is only a bounded materialization boundary; it must not rewrite that
Artifact or persist another canonical copy.

## Decision

The EOM HWPX adapter deterministically projects general prose stem paragraph separators to one
space before invoking the immutable handoff. It preserves non-empty line text and order. Typed
tables, labeled blocks, visual slots, inquiry content, statements, choices, and explanations remain
separate and unchanged. The renderer report records that the handoff projection occurred and its
SHA-256 while the request and output manifest retain the original immutable source pointers and
hashes.

This is an O(n) transformation over a bounded stem and requires no database, protocol, schema, or
index change. A terminal failed build remains immutable; recovery uses a new idempotency key and a
new build after deployment.

## Alternatives

Changing the existing Item Content schema to forbid paragraph boundaries would reject valid
canonical content and violate protocol-first compatibility. Modifying the external handoff archive
would change its immutable identity. Cloning the full `Q_STEM` HWPX paragraph duplicates embedded
template objects and invalidates layout-cache validation. The adapter projection is the smallest
boundary-local behavior consistent with the existing contracts.
