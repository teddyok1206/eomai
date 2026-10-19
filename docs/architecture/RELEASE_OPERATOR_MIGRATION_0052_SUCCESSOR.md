# Exact migration 0052 release-operator successor

2026-10-12 UTC. Source-only proposal/implementation; no release, privileged
callback, DB migration, role change or deployment is activated by this note.

The existing closed root operator boundary pins protected source/archive/wheels,
runtime, context and admission identities. Its 1.0 context and
`MIGRATION_VERIFY` / `MIGRATION_UPGRADE_0051` retain target `20261010_0051`, with
upgrade permitted only from `20261009_0050`. Existing schema bytes/SHA and
`migrate_release.sh` semantics are historical contracts, not latest-head aliases.

Add JSON Schema 2020-12 context/admission 1.1 in a separate hash-pinned resource.
Both carry only the literal migration target `20261012_0052`; no arbitrary target,
command, role, secret path or authority override is accepted. Preserve all other
protected pointers/limits. A parsed context's version and target are immutable
admission pins; an exact receipt must match them as well as source/runtime/FD
identities. Missing/changed schema, unknown version or cross-version receipt fails.

The two new callback literals are `MIGRATION_VERIFY_0052` and
`MIGRATION_UPGRADE_0052`. A fixed enum-to-target/predecessor map selects 0052 and
upgrade predecessor `20261010_0051`. No `head`, current-source-derived target,
arbitrary command or retry fallback exists. The context target and wheel's
`CURRENT_MIGRATION_REVISION` must equal the chosen literal before DB construction.
All existing root/private-stage/hash/owner/search-path/timeout gates remain.

Current `deploy_release.sh` chooses only `MIGRATION_VERIFY_0052` and admits source
head 0052. It never calls the historical 0051 migration wrapper for this release.
An archived 0051 wheel/source/context remains readable and admissible with its
original callbacks; a current 0052 source under that old context is rejected.

Lookup is constant-time over four fixed migration callback literals; schemas are
bounded read-only local resources, not a registry or remote resolver. Admission
is an O_EXCL immutable receipt; migration transaction/replay behavior remains
owned by native Alembic and the exact owner preflight. Timeout stays uncertain,
never an automatic retry. Shells remain presentation/admission adapters.

Source tests pin old/new raw schema SHA, closed target fields, callback-specific
predecessors, wrong source/head/version, root/private-stage denial and receipt
identity. Fake DB/child ports test command intent only. Real privileged execution,
installed/archive operational acceptance and live DB effects remain separate gates.
Changing the original 1.0 target would be simpler but would reinterpret released
history; a bounded 1.1 successor preserves that evidence without broadening authority.

## Exact0058 registered-review migration delta — 2026-10-19 UTC

1. Boundary: extend the same closed release operator; this note does not execute a
   migration, install, credential read or production action.
2. Canonical source: reviewed0058 Alembic source and the three admitted release
   wheels; source/build-only/installed evidence remain distinct.
3. Identity: additive context/admission1.7 pins literal `20261019_0058`; all released
   1.0–1.6 bytes and their historical targets remain unchanged.
4. Resolution: canonical schema and operator-local mirror have identical SHA;
   existing protected path, single-link, bounded read, context/runtime/source/wheel
   hashes and immutable admission epochs remain mandatory.
5. Access: exact callback lookup and single schema-version dispatch, not arbitrary
   migration strings, commands, roles, paths or `head`.
6. Structure: append the two0058 literals to the existing enum, immutable callback
   map and both shell allowlists; no registry, queue or new persistence.
7. Cost: O(1) dispatch and the existing bounded schema/metadata reads; unchanged
   source/wheel admission scans and native migration cost.
8. Transaction: the existing real database-owner/search-path preflight permits
   upgrade only0057→0058; verify or replay at0058 performs no upgrade.
9. Ownership: the public `load_context` owns schema dispatch; native Alembic owns
   the migration. The shell remains a fixed presentation/admission boundary.
10. Failure: wrong source head, context target, predecessor, owner or receipt fails
    closed; timeout is uncertain without retry. Existing0057 callbacks are not aliases
    for0058, and `migrate_release.sh` remains the historical0051 wrapper.
11. Alternative: changing context1.6 or using old callbacks would reinterpret
    history. A separate1.7 resource preserves prior acceptance and supports the
    required0058 installation. Tests prove intent with fake ports only; actual
    migration and compatible forward recovery remain explicit operating gates.
