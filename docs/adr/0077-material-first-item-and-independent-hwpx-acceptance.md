# ADR 0077: Material-first Item requests and independent HWPX acceptance

## Status

Accepted for implementation.

## Responsibility and boundary

The public Item request chooses the required **student-visible material form**. Authoring owns the
typed material, the image role owns only IMAGE slots, the HWPX Builder materializes the approved
Item, and the HWPX Manager independently accepts or rejects the resulting package before the
orchestrator commits it to NAS. A Builder-authored `PASS` value is diagnostic evidence, not an
authorization decision.

The supported material forms are `AUTO`, `TEXT`, `DATA`, `TABLE`, `IMAGE`, `MIXED`, and `INQUIRY`.
`TABLE` means one native editable table unless the reviewed Brief explicitly requires two. It does
not imply a PNG, an image worker invocation, an empty visual placeholder, or a `(가)/(나)` label.

## Canonical source and revision model

The canonical source is the approved immutable Item Revision:

```text
Item -> approved Item Revision -> Item Manifest -> ITEM_CONTENT Artifact Revision
                                           -> zero, one, or two IMAGE Artifact Revisions
```

The request pins a material policy value. The authored Item Content pins the ordered visual tuple.
An HWPX build pins the Item Revision, ITEM_CONTENT Artifact Revision, optional IMAGE Artifact
Revisions, renderer protocol, and immutable Handoff Revision. Paths are temporary materialization
locations only.

Historical request, role-result, Content Pack, HWPX, and mock-exam contracts remain byte-stable.
Incompatible wire changes use additive successor versions.

## Pointers and resolution checks

Before rendering, the Manager validates every logical ID, immutable revision ID, member name,
schema/version, media type, lifecycle state, size, and SHA-256. Before committing the output it
stable-opens the HWPX, independently validates the bounded ZIP and XML graph, and compares a
source-derived structural fingerprint with the materialized package. The fingerprint contains:

- Item Revision identity and canonical visual layout;
- ordered native table headers, rows, alignment policy, and their canonical hash;
- ordered IMAGE slot ordinals/labels and exact PNG hashes;
- equation and labeled-block counts;
- for an exam, the same data keyed by placement position and Item Revision.

The Manager validates package and renderer-report JSON against JSON Schema 2020-12 and Pydantic,
but never treats those files as proof of the HWPX bytes.

## Access patterns and data structures

Frequent operations are ordered iteration of at most two visual entries, key lookup of ZIP members,
membership and duplicate detection, and position-keyed comparison of at most 200 exam Items.
ZIP members and exam expectations therefore use maps keyed by member name and position; duplicate
identities use sets; ordered output remains tuples. Package verification is `O(entries + XML nodes
+ Items + cells)` time and `O(entries + Items + cells)` bounded space. No repeated per-Item scan of
the whole exam or quadratic deduplication is permitted.

No new database index is required: the change persists one small validation receipt in the
existing immutable Artifact result and does not store HWPX or PNG bytes in PostgreSQL.

## Transaction, concurrency, retry, and idempotency

Rendering occurs outside the database transaction in a private workspace. Independent validation
must finish before the existing NAS staging/commit boundary. Artifact metadata and the successful
Job transition remain in one transaction. A failed structural check produces a stable
`HWPX_RESULT_INVALID` failure and no Artifact Revision. Existing build idempotency keys and pinned
request identities are unchanged; replay may adopt only the already committed exact result.

## Dependency direction

Public UI/API contracts call the application use case. Domain material rules live in typed
contracts. The HWPX Manager owns the independent filesystem/ZIP/XML adapter and does not import the
Builder implementation. Workers still communicate only through the orchestrator and never write
NAS.

## Release and verification gates

Agent-visible JSON Schema and Pydantic acceptance must agree on a shared positive/negative corpus.
Release acceptance must materialize the immutable Handoff Artifact and fail if it is unavailable;
local developer tests may remain explicitly skippable. Authenticated post-deploy smoke validates
the GUI-critical typed list/detail endpoints, not only login. The latest single-Item material
contract reaches 25-Item production through an additive production-plan successor.

Required acceptance cases are `TEXT`, `DATA`, `TABLE`, deterministic `IMAGE`, hybrid `IMAGE`,
`IMAGE_TABLE`, `TABLE_IMAGE`, `IMAGE_IMAGE`, `TABLE_TABLE`, and `INQUIRY`. In particular:

```text
TABLE_ONLY = zero generated PNGs + one editable native table + no panel label + no image placeholder
```

Negative tests alter one table cell, swap two Item sections, forge a `PASS` report, supply arbitrary
bytes, introduce an external reference, or mismatch a pinned image hash; every case fails before
commit.

## Simpler alternative considered

Keeping `image_required: true` and inferring tables from free-form guidance is insufficient because
it conflates worker capability with required output and already makes TABLE-only requests
unrepresentable. Trusting Builder counts is insufficient because the Builder and its output are one
untrusted boundary. Aggregate exam counts are insufficient because an extra table in one Item can
mask a missing table in another. A typed material policy and per-Item independent verification are
the smallest changes that close those gaps.
