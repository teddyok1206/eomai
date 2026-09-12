# Image worker reviewed-Brief propagation

Status: accepted for the generated-knowledge-item 1.15.2 successor

Last reviewed: 2026-09-12 UTC

## Decision

The image worker must receive the same canonical reviewed Item Brief that was supplied to the
authoring worker. The Brief remains untrusted content data: it may constrain the requested visual,
but it cannot change the role schema, sandbox, prompt hierarchy, provider policy, or persistence
boundary. The two existing content-team guidance files remain byte-identical and authoritative.

This change is shipped as a new Content Pack release. Historical 1.15.1 resources and workflow
snapshots are immutable. The successor image profile adds `brief.reviewed_item_brief_json` to its
required context and renders that canonical JSON in a delimited block before the authoring result.
It also names the exact allowed SVG font families so a worker cannot invent a near-match such as
`Noto Sans KR` that the deterministic sanitizer correctly rejects.

## Boundary and canonical source

The canonical request is the pinned `ContentTeamItemBrief` already stored in the Workflow runtime
context. `WorkflowCatalogService._prompt_context` is the existing application boundary that
serializes it once as canonical JSON. The image prompt references that small immutable value; it
does not copy image bytes, Evidence files, or NAS paths. The authoring Artifact Revision remains the
canonical source for ordered IMAGE slots, while the Brief supplies the operator-reviewed visual
intent that led to those slots.

## Access pattern and structures

Prompt rendering performs O(1) keyed lookups in the existing context map and one ordered pass over
the bounded JSON value. IMAGE slots remain an immutable tuple of at most two entries. Font policy is
an explicit finite allowlist owned by the existing SVG sanitizer; the prompt merely exposes those
exact accepted values. No DB table, index, cache, queue, or unbounded scan is added.

## Concurrency, failure, and retry

The Content Pack release and profile hashes are pinned before execution. Missing Brief context,
template drift, an invalid route, a non-exact illustration/generation prompt, or an unsupported SVG
font fails before Catalog commits a stimulus Artifact. Existing workflow and provider idempotency
keys remain unchanged. A failed historical workflow is not retried; verification uses a fresh
workflow and release pointer.

## Dependency direction and alternative

The change stays in the Content Pack plus Catalog admission. Workers still return typed local
results, Catalog invokes the isolated GPU adapter, and only Catalog/orchestrator commits validated
artifacts to NAS. Adding route hints to a side channel or silently repairing invalid SVG would lose
reviewed intent and weaken reproducibility. Mutating 1.15.1 would break immutable history, so a
successor release is the smallest safe option.
