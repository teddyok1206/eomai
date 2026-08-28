# Standard Item Guidance Runtime V2

Status: reviewed implementation design

Decision date: 2026-08-28 UTC

## 1. Responsibility and boundary

This change makes two reviewed content-team sources affect future `standard-item` one-item jobs
through the existing Control Plane. It does not add a prompt registry, a worker-to-worker channel,
a mutable repository mount, or a second launcher. The Orchestrator continues to resolve one
released Execution Preset Revision and materialize only its pinned Instruction and Reference
Bundle members.

The mock-exam source contains form-level constraints that cannot be applied literally to one item.
Its existing assembly derivative remains the canonical form-level guide. A separate reviewed
single-item derivative preserves only item-applicable authoring and review principles and pins the
same protected intake source hash. The illustration derivative remains the canonical visual guide.

## 2. Canonical sources and revision model

```text
protected intake source (untracked, immutable evidence)
  -> reviewed Git guidance Markdown revision
  -> approved control Markdown Artifact Revision
  -> released role-specific Reference Bundle Revision
  -> released standard-item Execution Preset Revision
  -> immutable Resolved Execution Plan step
  -> disposable job-local references/guidance/*.md
```

The reviewed Git guidance document is publication input, not runtime identity. Runtime history
pins the Artifact logical ID, Artifact Revision ID, schema/media type and SHA-256 separately. A
new edit creates a new guidance, bundle and preset revision; V1 bytes and historical workflow plans
remain unchanged.

## 3. Role selection

The successor preset uses a role-keyed map:

| Role | Pinned references |
| --- | --- |
| `authoring` | general-knowledge provenance, single-item authoring, illustration |
| `image` | general-knowledge provenance, illustration |
| `review` | general-knowledge provenance, single-item authoring, illustration |
| `item_management` | general-knowledge provenance only |

Each role Instruction Bundle names the exact materialized paths it must consult. References remain
lower-trust data and cannot override `AGENTS.md`, the typed request, JSON Schema, sandbox or tool
policy. `item_management` stays registration-only.

## 4. Access patterns and structures

- Role policy lookup uses the existing role-keyed preset map: expected `O(1)`, four production
  roles.
- Reference definition lookup uses a manifest-local dictionary keyed by `reference_key`: expected
  `O(1)`, three definitions.
- Duplicate keys and paths use sets: `O(n)` for at most three definitions per role.
- Materialization remains one verified streaming read/write and hash pass per member: `O(bytes)`;
  PostgreSQL stores only metadata and pointers.
- Reference ordering is a deterministic tuple sorted by the reviewed manifest declaration, so
  bundle hashes and workspaces are reproducible.

No cache or derived database column is added. Existing bundle and preset indexes and unique
constraints continue to own key lookup, revision uniqueness and concurrent publication.

## 5. Transaction, concurrency and idempotency

Artifact publication, bundle publication, evaluation recording and preset release keep their
existing short transactions. Publication identities include exact content hashes. Replaying the
same bytes and manifest returns the same revisions even when a later source commit pins those same
bytes; the first publication provenance remains immutable. The same immutable identity with
different bytes fails closed. Unchanged fixed-host capacity policy V1 is likewise reused only after
its full operational fields, pool/slot map, current pointer and document hash are revalidated.
Preset publication locks the logical preset row and advances only to a newer released revision.

Existing workflows retain their pinned V1 plan. Only workflows resolved after V2 activation use
the successor bundle pointers. Worker execution remains one-shot and no retry policy changes.

## 6. Failure behavior

Publication stops before preset release when a source is missing, symlinked, world-writable,
oversized, malformed, non-UTF-8, not `REVIEWED`, not applicable to the assigned role, duplicated,
or hash-inconsistent. Materialization fails before worker start on missing/stale pointers, wrong
media/schema, lifecycle mismatch, unsafe path, symlink, size mismatch or SHA mismatch.

The simpler alternative—copying both full source prompts into every role's `AGENTS.md`—is rejected
because it mixes reference data with instruction authority, applies form-level rules to one item,
increases prompt-injection scope, duplicates bytes and gives registration workers irrelevant
authoring policy.

## 7. Slot 5 isolation and rollout

The active textbook-analysis workflow is pinned to its own `knowledge-analysis` preset and slot05.
This source change does not modify that preset, its bundles, its jobs or its workspace. Non-live
tests must not claim workers. Runtime activation may use the credential-free Control Plane
publication boundary only after proving it requires no service restart and no mutation of the
active batch; otherwise activation waits for the batch's terminal coverage checkpoint.

## 8. Acceptance

- V1 bootstrap files and released revisions remain byte- and hash-stable.
- V2 publishes distinct role-specific Reference Bundles and one successor preset revision.
- Authoring and review materialize both reviewed source derivatives; image materializes the visual
  derivative; item management receives neither content guide.
- Job-local `AGENTS.md` names the relevant paths without concatenating guide bytes.
- Forged role/reference mappings, stale pointers and changed-byte replays fail closed.
- A future one-item plan pins exact V2 preset/bundle/artifact revisions and hashes.
