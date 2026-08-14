# System Change Log

Bootstrap timestamp: `2026-08-14T04:27:16Z`

Executed as: `root`

## Created Directories

- `/home/eom/EOM`
- `/srv/eom`
- `/srv/eom/jobs`
- `/srv/eom/workspaces`
- `/srv/eom/cache`
- `/srv/eom/staging`
- `/srv/eom/state`
- `/srv/eom/backups`
- `/srv/eom/conda`
- `/srv/eom/conda/envs`
- `/srv/eom/worker-homes`
- `/var/log/eom`
- `/etc/eom`
- `/etc/eom/secrets`
- `/mnt/nas/eom`
- `/mnt/nas/eom/artifacts`
- `/mnt/nas/eom/items`
- `/mnt/nas/eom/images`
- `/mnt/nas/eom/hwpx`
- `/mnt/nas/eom/manifests`
- `/mnt/nas/eom/backups`
- `/mnt/nas/eom/backups/postgresql`
- `/mnt/nas/eom/log-archive`

## Created Linux Users

- `eom-cdx-01`
- `eom-cdx-02`
- `eom-cdx-03`
- `eom-cdx-04`
- `eom-cdx-05`

Each worker has a private primary group, locked password, HOME under `/srv/eom/worker-homes`, and workspace under `/srv/eom/workspaces`.

## Group Membership Changes

The operations user `eom` was added to each worker private group so the orchestrator can access worker workspaces:

- `eom-cdx-01`
- `eom-cdx-02`
- `eom-cdx-03`
- `eom-cdx-04`
- `eom-cdx-05`

Existing login sessions may need re-login to see new supplementary groups.

Workers were not added to `sudo`, `docker`, or `eom`.

## Installed Apt Packages

- `docker-ce 5:29.7.2-1~ubuntu.24.04~noble`
- `docker-ce-cli 5:29.7.2-1~ubuntu.24.04~noble`
- `containerd.io 2.3.3-1~ubuntu.24.04~noble`
- `docker-buildx-plugin 0.36.1-1~ubuntu.24.04~noble`
- `docker-compose-plugin 5.4.0-1~ubuntu.24.04~noble`
- `docker-ce-rootless-extras 5:29.7.2-1~ubuntu.24.04~noble`
- `pigz 2.8-1`

`ca-certificates`, `curl`, and `gnupg` were already installed.

## Added Apt Repository

Docker official apt repository:

```text
deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable
```

Docker key fingerprint observed:

```text
9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88
```

## Created Secret Path

- `/etc/eom/secrets/postgres.env`

Mode: `0640`, owner `root:eom`. Secret values are not recorded in Git or reports.

## Docker State

- Docker daemon: active and enabled
- Compose plugin: v5.4.0
- PostgreSQL container: `eom-postgres`
- Docker network: `eom_backend`
- Docker volume: `eom_postgres_data`
- PostgreSQL bind: `127.0.0.1:5432`

The temporary official `hello-world` image used by the installation smoke test was removed after the test.

## Root Codex Permission Change

- `/root/.codex`: changed from `0755` to `0700`
- `/root/.codex/auth.json`: kept at `0600`

Auth contents were not read.

## Other System File Note

`/root/.gnupg` was created by `gpg --show-keys --fingerprint` while recording the Docker apt key fingerprint. No credential material was written there by EOM.

## Runtime Permission Note

`/srv/eom` is `0711 root:eom`, not the initial recommended `0750`. Reason: worker users must traverse to their own HOME and workspace while remaining outside the `eom` group. The directory is execute-only for others, so workers cannot list `/srv/eom`; sensitive child directories retain restrictive modes.

## Changed But Not Performed

- No reboot
- No OS upgrade or dist-upgrade
- No `/etc/fstab` change
- No UFW rule change
- No NVIDIA Container Toolkit installation
- No Git remote creation
- No Git push
- No Codex worker login
- No EOMIS file modification

## Rollback Pointers

See `docs/operations/INFRA_ROLLBACK.md`. Do not delete `/var/lib/docker` or `/mnt/nas/eom` wholesale.
