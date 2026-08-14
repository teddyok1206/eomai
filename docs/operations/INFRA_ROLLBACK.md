# Infrastructure Rollback

This document describes rollback procedures only. Do not run them unless an operator explicitly approves the rollback scope.

## Level 1: Application Files Only

1. Confirm the current Git root is `/home/eom/EOM`.
2. Review `git status --short`.
3. Preserve any required reports before removing the repository.
4. If no runtime data or uncommitted work must be kept, remove `/home/eom/EOM`.
5. Do not touch `/home/eom/EOMIS`.

## Level 2: PostgreSQL Service Rollback

1. Confirm backups exist under `/mnt/nas/eom/backups/postgresql`.
2. Stop only the EOM Compose service:

   ```bash
   docker compose --env-file /etc/eom/secrets/postgres.env -f /home/eom/EOM/infra/compose/compose.yml down
   ```

3. Preserve `eom_postgres_data` unless a verified backup and restore are no longer needed.
4. Deleting the volume destroys primary DB data:

   ```bash
   docker volume rm eom_postgres_data
   ```

5. Keep or remove `/etc/eom/secrets/postgres.env` according to the incident scope.

## Level 3: Worker User Rollback

1. Confirm no worker processes are running.
2. Remove worker users only after preserving any needed workspace output.
3. Remove worker HOME and workspace paths only for the corresponding worker.
4. Remove `eom` supplementary membership from worker private groups.

Example shape:

```bash
userdel eom-cdx-01
rm -rf /srv/eom/worker-homes/eom-cdx-01
rm -rf /srv/eom/workspaces/eom-cdx-01
```

## Level 4: Docker Rollback

1. Confirm no non-EOM containers or volumes depend on Docker.
2. Remove only EOM containers, network, and volume first.
3. Package removal, if approved:

   ```bash
   apt-get remove docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras
   ```

4. Do not delete `/var/lib/docker` wholesale unless a full host-level rollback has been approved and all other container workloads are accounted for.

## Level 5: NAS Rollback

1. Never run `rm -rf /mnt/nas/eom`.
2. Delete only known empty directories from this bootstrap if no artifact, backup, manifest, or log exists inside.
3. Preserve PostgreSQL backups unless a replacement backup has been verified.
4. `_infra-test` paths created by smoke tests should already be cleaned up.
