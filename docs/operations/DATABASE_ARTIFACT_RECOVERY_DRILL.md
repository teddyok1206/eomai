# Database and Artifact recovery drill

## Purpose

An EOM restore is accepted only when one PostgreSQL backup and one immutable Artifact-store
snapshot are verified as a pair. A successful `pg_restore` by itself is insufficient because the
database contains pinned Artifact revision IDs and hashes rather than large files.

This runbook never restores over production, never treats `/mnt/nas/eom/artifacts` as a snapshot,
and never repairs a dangling pointer by choosing a newer revision. It implements
[ADR 0169](../adr/0169-database-artifact-recovery-pair.md).

## Required inputs

- one dump and matching manifest directly below `/mnt/nas/eom/backups/postgresql`;
- one storage-level, immutable copy of the complete Artifact root;
- a disposable restored database named `eom_restore_*` or `eom_test_*`;
- the explicit `eom-api` Conda interpreter.

The storage owner creates the Artifact snapshot. The verifier does not copy production bytes and
does not invent a local backup policy. A snapshot on the same failure domain as the live Artifact
root is useful for consistency testing but is not evidence of NAS-loss recovery.

## Snapshot manifest

After the storage snapshot is complete and no writer can modify it, generate its manifest. The
snapshot root may contain only `artifact_<id>/rev_<id>/...` directories and the fixed manifest
member.

```bash
snapshot_root=/absolute/immutable/artifact-snapshot
/srv/eom/conda/envs/eom-api/bin/python \
  scripts/infra/verify_recovery_pair.py snapshot-manifest "${snapshot_root}" \
  --captured-at 2026-10-02T00:00:00Z \
  --label storage-snapshot-id \
  > "${snapshot_root}/snapshot-manifest.json"
```

Write the output through a storage-owned atomic publication step in production. Shell redirection
above is illustrative for an isolated drill directory; it must not overwrite an existing snapshot
manifest.

## Restore and verify

Restore the exact dump into a guarded disposable database by the existing PostgreSQL restore
procedure. Export its URL through a private environment variable and run:

```bash
export EOM_RECOVERY_DATABASE_URL='postgresql+psycopg://.../eom_restore_example'
/srv/eom/conda/envs/eom-api/bin/python \
  scripts/infra/verify_recovery_pair.py verify \
  --backup-dump /mnt/nas/eom/backups/postgresql/eom_<identity>.dump \
  --backup-manifest /mnt/nas/eom/backups/postgresql/eom_<identity>.manifest.json \
  --snapshot-root /absolute/immutable/artifact-snapshot \
  --snapshot-manifest /absolute/immutable/artifact-snapshot/snapshot-manifest.json \
  --sample-size 64 \
  --full
```

The canonical JSON receipt binds the dump hash, backup-manifest hash, snapshot self-hash, restored
database identity, exact full inventory hash, total Artifact revision count, verification mode, and
deterministic first/last evidence revisions.  Every run compares the full DB and snapshot metadata
inventory.  `--full` also validates every member byte; without it only the deterministic byte sample
is checked and the receipt says `SAMPLED`.  For each byte-verified revision it validates the DB
manifest, on-disk manifest, member paths, media metadata carried by the manifest, file sizes,
primary content identity, and every member hash.

## Stop conditions

Stop without repair when any of these occurs:

- database identity is not explicitly disposable;
- the supplied root is live Artifact storage, a descendant, or an ancestor containing it;
- snapshot count or inventory hash differs from its manifest;
- database and snapshot Artifact revision counts differ;
- database and snapshot ordered inventory hashes differ;
- a path is absolute, traverses upward, is a symlink, or changes while open;
- restored and snapshotted manifest metadata, identity, size, or SHA-256 differs;
- the PostgreSQL and Artifact captures cannot be assigned one documented recovery point.

Destroy the disposable database only through its guarded cleanup procedure. Preserve the recovery
receipt and elapsed RTO measurement as operational evidence; do not commit backup bytes, Artifact
bytes, URLs, secrets, or long logs to Git.
