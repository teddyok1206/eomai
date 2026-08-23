# Kordoc HWPX Renderer V0

Status: accepted implementation design for `feat/kordoc-hwpx-renderer-v0`.

## Responsibility and boundary

The Kordoc renderer converts one validated, immutable Markdown artifact revision into one HWPX
artifact revision. The HWPX manager owns the use case, idempotency, platform job, validation, and
artifact commit. The isolated `eom-hwpx` process owns materialization only. Kordoc is an internal
renderer dependency; it is not exposed as an MCP server and does not communicate with workers.

The existing `template-bind-v1` renderer remains unchanged. Kordoc uses the separate
`kordoc-markdown-v1` profile because its generated packages do not contain EOM template markers or
the fixed placeholder image required by the template validator.

## Canonical source and revision model

The canonical input is a registered artifact revision, identified by logical artifact ID,
immutable artifact revision ID, schema ID/version, media type, and SHA-256. The workspace Markdown
file is a temporary materialization. The generated HWPX is committed once as a new logical
artifact and immutable artifact revision; PostgreSQL retains pointers and hashes, not document
bytes.

Resolution verifies that the source artifact and pinned revision exist, are approved, have the
expected hash and media type contract, and resolve to the staged regular file. Missing, stale, or
hash-mismatched references fail explicitly. No implicit latest revision is allowed.

## Protocol

The JSON Schema 2020-12 contracts are:

- `hwpx-kordoc-render-request-v1.schema.json`
- `hwpx-kordoc-build-result-v1.schema.json`

The request pins Kordoc `4.9.0`, its npm integrity, the source pointer, a fixed renderer profile,
and exact expected equation/table counts. Paths and commands are closed literals. Pydantic models
mirror the schemas and forbid unknown fields.

## Access patterns and structures

Frequent operations are key lookup by artifact/revision ID, idempotency-key lookup, fixed workspace
file lookup, and ordered ZIP-entry validation. Existing indexed DB columns and unique idempotency
constraints serve the first two. A map keyed by ZIP entry name provides O(1) part lookup; ordered
tuples preserve deterministic package order. Equation and table counts require one bounded scan of
Markdown and XML, O(n) time and O(1) auxiliary state aside from parsed bounded XML.

Expected V0 scale is at most 1 MiB of Markdown, 32 display equations, 20 tables, 20 columns per
table, and the existing 50 MiB HWPX package limit.

## Transaction and concurrency boundary

The manager creates an idempotent platform job before materialization. An existing idempotency key
with a different request hash fails; an existing completed job resolves its pinned artifact rather
than rendering again. Builder execution occurs outside a DB transaction. Artifact records and the
final job transition are committed together after validation and immutable NAS commit.

## Dependency direction and isolation

Contracts contain only schemas and typed value objects. The manager application service depends on
those contracts and existing orchestrator interfaces. The builder is an infrastructure adapter.
Kordoc runs under the existing `eom-hwpx` systemd sandbox with private networking, no NAS, no source
checkout, no worker homes, no Docker socket, and only its workspace writable.

The runtime pins Node.js 22.23.2 and `kordoc==4.9.0`. The npm lock is installed with optional OCR/PDF
dependencies omitted. `KORDOC_OFFLINE=1` and `KORDOC_ROOT=<workspace>` are mandatory. There is no
`npx`, runtime package download, arbitrary command, or caller-selected executable/module/path.
Kordoc is MIT licensed; its installed package retains `LICENSE`, `NOTICE`, and `THIRD_PARTY` files.

## Validation and determinism

Markdown is untrusted input. The V0 grammar permits text, headings, lists, GFM tables, and bounded
display LaTeX. It rejects control characters, raw HTML, images, external links/URLs, and dangerous
TeX command names. The source bytes must match the pinned SHA-256.

The Kordoc profile performs the common hardened ZIP/XML/manifest/spine/active-content checks without
weakening the existing template validator. It additionally requires Kordoc validation and parse
success plus exact native equation/table counts. ZIP timestamps are normalized to 1980-01-01 while
preserving entry order and compression so identical inputs produce identical bytes.

## Failure, retry, and idempotency

Missing runtime, unsupported Node/Kordoc version, unsafe Markdown, dependency mismatch, timeout,
parse/validation failure, count mismatch, or output hash mismatch returns a stable sanitized error.
No raw document body is logged. Failed jobs are preserved. There is no automatic retry and no
plain filesystem or direct-NAS fallback.

## Simpler alternative considered

Invoking `npx kordoc generate` directly was rejected because it permits runtime dependency drift and
network access and bypasses typed pointers, orchestrator idempotency, sandboxed staging, common HWPX
validation, deterministic packaging, and canonical artifact commit. Replacing the existing template
renderer was also rejected because the two profiles have different structural invariants.
