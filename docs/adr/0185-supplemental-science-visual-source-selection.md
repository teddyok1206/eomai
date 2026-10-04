# ADR 0185: Supplemental science-visual source selection

## Status and evidence

Accepted for bounded internal data preparation on 2026-10-04 UTC, not model activation. The approved
corpus has 1,251 PDFs / 5,218 pages; the original three-shard campaign selected 108 PDFs. Its 503
TRAIN candidate regions are mostly tables, graphs or annotated material, not 503 eligible drawings.
Twenty-three literal source candidates are now registered, but full-data readiness is insufficient.
A read-only probe of the existing public V3 selector confirms that increasing limits reselects up
to all 108 old PDFs. Filtering the corpus before grouping would instead change group ranks and
could leak previously used TRAIN material into validation/holdout.

## Responsibility, canonical source and identity

Catalog owns deterministic selection; Orchestrator resolves approved pointers, stages local inputs
and commits validated results. The isolated existing CPU pilot owns only PDF rendering/discovery.
The original approved corpus and complete predecessor plan snapshots remain canonical. An additive
plan/command V1.3 pins those plan Artifact Revisions and excludes their document/PDF identities
without changing the corpus, common seed or prior source/group partitions. Its logical campaign
identity includes the predecessor pointers; the plan/attempt identity also binds its exact inputs,
limits, guidance, tools and UTC timestamp. Raw file SHA, semantic SHA and revision IDs stay distinct.
V1.0–V1.2 contracts, selection algorithms, receipts and bytes are not reinterpreted.

Staging, worker admission and result admission reuse one closed, immutable version table/codec.
It has no registration/plugin API. Legacy command reconstruction is checked against its exact
existing serialized bytes; mismatched or unsupported plan/command versions are rejected, not
upgraded. Optional V1.3 publisher type annotations do not impose a new runtime import on unrelated
historical publisher CLIs using an older compatible installed contract package.

New plans keep the two team-lead prompt authorities and KICE illustration guide. They do not change
the original authorization or grant permission for external APIs, source export or model activation.
Later reviewed crops must pin the supplemental plan/result/page lineage; they cannot invent old
candidate IDs or attach new candidates to the original inventory. This later crop-admission boundary
is separate from the present selector/worker protocol checkpoint.

## Pointers and resolution

Before any PDF bytes are staged, resolve the complete existing approved lineage. Validate corpus,
authorization, predecessor plan schema/media/member/hash, campaign completeness, chronology, seed
and all exact document/PDF metadata. Build the partition map from the **whole original corpus**.
Check every predecessor against that map, then exclude old document IDs and hashes. New selections
must equal the deterministic selection from those frozen inputs. Missing, stale, mismatched,
incomplete or conflicting predecessors fail explicitly; never resolve latest or silently reassign.

## Access patterns, structures and scale

Dominant operations are keyed source lookup, set membership/exclusion, stable stratified iteration
and immutable snapshots. Reuse maps for document/group resolution, sets for identity exclusion and
the existing sorted per-stratum pools with offsets for bounded selection. Apply exclusions after
whole-corpus group assignment and shard ranking, not before. Time is O(n log n + h), space O(n + h)
for at most 5,000 corpus documents and four predecessor plans; h is their bounded source count.
Per-worker bounds remain at most 96 PDFs, 384 pages and 512 candidates. There is no new DB, index,
queue, cache, dependency, daemon or worker credential.

## Transactions, concurrency and dependency direction

The contract contains small frozen metadata/pointers, not image/PDF payloads. Pure contract checks
do not import infrastructure. Catalog application planning consumes resolved typed values; existing
Orchestrator adapters own DB/NAS resolution, idempotent publication and staging. Use the existing
command/workspace identity and sequential isolated systemd execution to bound CPU/memory pressure.
Only worker input/workspace/output boundaries materialize bytes. Old PDFs/pages are not copied or
republished merely to expand a campaign. Existing whole result closure and publication semantics
stay unchanged; the original page and candidate result contract can be reused.

## Failure, retry and extension

Validate every source before dispatch. A terminal failure preserves its receipt and partial local
work without claiming a successful dataset. Ambiguous start/publication is inspected before replay;
same identity is not replaced to bypass failure. Additional worker stop is the rollback; the old
source corpus, source sets and V6 operating model are untouched. New discovery regions still need
literal source review, captions, expression/scale preparation and duplicate grouping before training.
Automatic discovery is not a quality approval. Reserved pixels are not viewed for TRAIN tuning.

## Simpler alternative

Increasing existing V3 limits repeats old extraction/storage; filtering or reseeding would change
the partition semantics, while silently replacing V3 selected sources would misstate its released
algorithm. A small successor selection boundary with pinned predecessors is sufficient. Replacing
the extractor, adding a scheduling framework or expanding all legacy inventory families is not.
