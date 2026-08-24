# Codex Knowledge Control Plane Phase 12 Rollout

Status: reviewed hardening and rollout procedure

Date: 2026-08-24 UTC

## Responsibility and boundary

Phase 12 activates only source and persistence behavior already accepted in Phases 8–11. It does
not reinterpret a historical workflow, preset, graph snapshot, Item Revision, Product Revision, or
Usage Record. Application API and Catalog remain the transaction owners for their existing use
cases. The trusted `eomctl` operator adapter may invoke Catalog application services, but it may not
parse a workbook itself, issue arbitrary SQL, choose an implicit current revision, or bypass review.

The rollout is deliberately split into four independently reversible boundaries:

1. install dual-read code that can still read every historical V1/V2 contract;
2. apply additive migrations and reconcile exact runtime grants;
3. activate reviewed presets and derived graph state without a Codex invocation;
4. enable user-visible opt-in only after pointer, retrieval, and capacity evidence passes.

No phase combines a database restore, schema downgrade, live Codex call, graph publication, legacy
workbook import, and GUI activation into one irreversible operation.

## Canonical source and pointer model

The rollout pins the repository commit, release wheel hashes, Alembic revision, workflow definition
hash, Content Pack Release, Execution Preset Revision, capacity policy revision, retrieval access
policy revision, Knowledge Corpus Revision, Graph Snapshot Revision, and every Artifact Revision
hash. Paths are materialization locations only. A runtime must never use a checkout path or a
mutable `latest` pointer to reconstruct historical work.

The canonical chains are:

```text
Execution Preset -> immutable Preset Revision -> instruction/reference bundle revisions
                 -> capacity policy revision -> exact model/effort policy

Knowledge Corpus -> immutable Corpus Revision -> Graph Snapshot Revision
                 -> projection/manifest Artifact Revisions -> exact source revisions

Legacy workbook Artifact Revision -> mapping-contract revision -> reviewed import
                                  -> Product/Form/Assembly/Publication revisions
                                  -> append-only Usage Record V1
```

The graph and Markdown projections are rebuildable derived artifacts. Item Registry, Content
Intake, Product/Form/Assembly/Publication, and Usage rows remain canonical.

## Access patterns and capacity decision

The host currently has 16 logical CPUs, 30 GiB RAM, 8 GiB swap, five fixed Codex identities, a
global active-Codex ceiling of three, a GPU ceiling of one, and one support/knowledge-analysis
slot. The dominant scheduling operation is concurrent claim under a fixed global limit, so the
existing indexed lease queue and database uniqueness constraints remain the correct structure.
Excess jobs queue; the rollout does not add slots or raise concurrency.

Graph retrieval remains indexed PostgreSQL lookup and adjacency traversal. Legacy usage reverse
lookup remains an indexed exact Item Revision query. Proposal browsing is ordered by the unique
`(legacy_usage_import_id, source_row_number)` key with a bounded cursor. No operator endpoint
accepts raw graph query text, raw SQL, a NAS path, or an arbitrary host path.

The current hardware does not justify `max_active_codex > 3`, more than five configured slots, or a
dedicated graph backend. Any such change requires a new throughput, memory, queue-latency, and
security review.

## Source gate

Before any runtime mutation, require all of the following from one clean commit:

- focused contract/domain/application tests;
- full unit, workflow, Catalog, Item Registry, Usage, API, GUI, and non-live worker tests;
- disposable PostgreSQL upgrade, one-step downgrade, re-upgrade, metadata comparison, concurrency,
  idempotency, immutable-trigger, and runtime-role tests;
- Ruff, formatter, strict mypy, shell syntax, JSON Schema/resource parity, and `git diff --check`;
- repository boundary and secret scan after all files are tracked;
- isolated API/platform and GUI wheel builds with embedded commit provenance;
- historical schema and protocol hash pins; and
- proof that default tests make no live Codex call and persist no workbook/image/HWPX bytes in DB.

The source gate stops at its first real failure. It never suppresses a detector, alters a historical
schema byte, installs a dependency, or points a test at the deployed database.

## Database backup and migration gate

Before the production migration:

1. record the clean source commit and installed API/GUI source commits;
2. run `scripts/infra/postgres_backup.sh` with protected PostgreSQL configuration;
3. verify the emitted backup and manifest are regular, non-symlink files under the fixed NAS backup
   root and that their SHA-256 values agree;
4. run `scripts/infra/postgres_restore_dry_run.sh` against that exact dump;
5. confirm services and canonical counts are unchanged; and
6. stop if the restore proof fails.

Apply Alembic only through `scripts/api/migrate_release.sh --upgrade <EXPECTED_COMMIT>`. The
wrapper pins a clean reviewed commit, supplies the complete source package roots needed before the
new wheel is installed, removes any ambient database URL, uses the fixed protected PostgreSQL
configuration, and proves the connected database identity owns the `app` schema. API, Catalog,
worker, and GUI runtime roles never own DDL. After migration, reconcile the Application API and
Catalog runtime roles from the reviewed source matrices. Catalog receives only the precise legacy
usage table privileges:

- read and insert on immutable Form/Assembly/Publication/Usage/import rows;
- update only on logical current-revision headers and the import state header;
- read-only access to existing Deliverable/Revision pointers; and
- no delete, truncate, DDL, role, extension, bypass-RLS, database-create, or temp-table privilege.

The migration rollback boundary is restore from the verified backup, not reinterpretation of
committed immutable rows. A schema downgrade is acceptable only before new Phase 11 rows exist and
only when the reviewed migration downgrade test remains applicable.

## Application and GUI deployment order

Use repository-owned installers only:

1. build and inspect the current API/platform/contracts release;
2. apply migration with the commit-pinned wrapper and reconcile exact runtime roles;
3. install the reviewed API release and verify installed imports/provenance;
4. restart only `eom-api.service` through the installer;
5. restart `eom-catalog-application-runner.service` because it imports Catalog models/services;
6. verify API and Catalog readiness;
7. build and inspect the current Scientific Studio wheel;
8. install the reviewed GUI wheel and restart only `eom-web-gui.service`;
9. run the GUI smoke test through the existing HTTPS/BFF boundary; and
10. verify HWPX Manager, Observability, workflow runner, PostgreSQL, and port 8000 were not changed.

Do not restart workers, HWPX services, Observability, PostgreSQL, Caddy, or port 8000 for this source
deployment. Do not install or upgrade dependencies.

## Preset and graph rollout

The historical `standard-item` V1 and `knowledge-analysis` presets remain intact. A knowledge-backed
item uses the separate `knowledge-grounded-item` V2 identity and pins one released retrieval access
policy. It must fail closed unless the requested corpus has one published current Graph Snapshot
and all policy, preset, graph, source, and Artifact hashes resolve exactly.

The first graph rollout is deliberately small:

1. select one already accepted Knowledge Analysis result and its exact approved source revision;
2. publish one immutable graph snapshot under a reviewed corpus key;
3. issue the three closed query kinds against fixed acceptance fixtures;
4. compare provenance precision, duplicate rate, curriculum coverage, latency, and context-token
   count to the existing lexical/reference baseline;
5. publish no replacement snapshot if any pointer, rights, answer-bearing, or quality gate fails;
6. activate the V2 preset only after the access-policy and graph pointers agree; and
7. keep the GUI knowledge-grounding flag false by default.

Publishing a graph or preset does not authorize a live Codex invocation. A live one-item acceptance
requires a separate one-shot authorization and a fresh workflow. The acceptance must preserve
human approval, Item Registry, HWPX, and secure download behavior.

## Legacy workbook rollout

One reviewed workbook batch is the maximum initial rollout. The operator sequence is:

1. register the original workbook through Content Intake and approve the exact Artifact Revision;
2. release one schema-valid mapping-contract revision;
3. submit a typed legacy import command pinning source, mapping, schemas, media type, and hashes;
4. inspect bounded counts and page every proposal by source row number;
5. approve only exact resolved rows and explicitly reject every quarantined row;
6. commit once with a unique idempotency key;
7. reconcile workbook row counts, approved/rejected counts, placement and projection hashes;
8. verify reverse lookup for exact Item Revisions; and
9. publish a new graph snapshot only through the existing graph publication boundary.

Operator commands are under `eomctl usage legacy`. They accept contract JSON or stable IDs, never a
raw SQL statement or arbitrary workbook path. A failed or incomplete review creates no canonical
Form, Assembly, Publication, Usage, or graph row.

## Security acceptance

Require the following after deployment:

- secrets absent from Git, DB documents, manifests, API/GUI responses, logs, Slack, and artifacts;
- installed imports originate below the reviewed environment `site-packages`, not the checkout;
- workers retain no DB, NAS, sudo, Docker, `eom` group, or cross-worker-home authority;
- API, Observability, and Studio remain loopback-only behind Caddy;
- Caddy exposes only the Studio BFF and does not proxy ports 5432, 8000, 8765, 8780, or 8790;
- graph retrieval respects requester role, source class, answer-bearing policy, exact snapshot, and
  evidence budget;
- student identity, answers, scores, and attempts remain absent from the general graph;
- XLSX formula, macro, external-link, traversal, symlink, oversized, and malformed input fails;
- Catalog runtime can write only the reviewed immutable/intake tables; and
- Slack reporting remains redacted, milestone-only, and non-blocking.

## Rollback

Code rollback reinstalls the previous three API release wheels and previous GUI wheel by their
recorded SHA-256/commit, then restarts only their owning services. Preset rollback changes only the
mutable current preset pointer or disables the opt-in capability; historical preset revisions and
plans remain. Graph rollback changes only the current corpus snapshot pointer by a reviewed new
revision or disables retrieval; published snapshots are never edited or deleted. Legacy import
rollback stops before commit or uses a corrected new source/mapping/import revision; committed Usage
history is never deleted or rewritten.

Database restore is the final rollback only when the migration boundary itself failed and before
post-migration canonical writes are accepted. Never restore over newer accepted Item, HWPX,
workflow, Product, or Usage state without a separate incident decision.

## Stop conditions and remaining human inputs

Stop and report `BLOCKED` when any of these is absent:

- a verified production backup and restore dry run;
- a clean reviewed release commit and matching local wheels;
- exact runtime-role reconciliation after migration;
- one accepted analysis result for the first graph snapshot;
- a reviewed retrieval access policy and graph acceptance fixture;
- a separately authorized live Codex workflow; or
- one reviewed legacy workbook, mapping contract, and row-by-row decision set.

Source hardening and dual-read deployment may complete without those content-specific inputs. They
must not be replaced with invented production data or a synthetic value presented as canonical.
