# Observability Console Setup

## Install Environment

The intended Conda definition is `infra/conda/eom-observe.environment.yml`:

```bash
/home/eom/miniconda3/bin/conda env create \
  --prefix /srv/eom/conda/envs/eom-observe \
  --file infra/conda/eom-observe.environment.yml
/srv/eom/conda/envs/eom-observe/bin/python -m pip install \
  --requirement infra/conda/eom-observe.requirements.lock
```

The lock installs only fully pinned third-party runtime, build, and test dependencies. It does not
install observer source in editable mode and does not install the production `eom-platform`
distribution. Build tools are present solely to create the observer wheel in this prefix.

If the configured Conda channels reject noninteractive creation because their Terms of Service have
not been accepted, do not repeatedly change channels or accept terms implicitly. Create the isolated
prefix with the existing Conda-managed Python 3.12 and install only through that prefix's pip:

```bash
/srv/eom/conda/envs/eom-core/bin/python -m venv --copies /srv/eom/conda/envs/eom-observe
```

This fallback does not install anything into `eom-core` or system Python.

## Build And Deploy A Release

Commit the intended release and ensure the working tree is clean. Build artifacts are kept under
`/tmp/eom-observe-build/<commit>/` and are not added to Git:

```bash
scripts/observe/deploy_release.sh --dry-run
scripts/observe/deploy_release.sh --build-only
sudo scripts/observe/deploy_release.sh --install
scripts/observe/deploy_release.sh --verify
```

The install action verifies wheel content before stopping the service, removes only a known previous
editable observer distribution, performs a non-editable force reinstall, installs the reviewed unit,
and checks health, authenticated assets, SSE, read-only DB behavior, and sandbox restrictions. It
never uses system Python or `eom-core`.

The installed release imports from
`/srv/eom/conda/envs/eom-observe/lib/python3.12/site-packages`. Its working directory is
`/var/lib/eom-observe`; `/home/eom/EOM` is inaccessible inside the service. Do not add `PYTHONPATH`,
repository symlinks, `.pth` source mappings, or editable installs.

## Database Role

Run as an operations account. The bootstrap script loads the existing PostgreSQL admin secret without
printing it and leaves a temporary 0600 password handoff file under `/run`:

```bash
scripts/observe/bootstrap_readonly_role.sh
scripts/observe/verify_readonly_role.sh
```

Delete the handoff file immediately after constructing the observer database URL. Do not put the URL
on a command line.

## Account And Files

Create `eom-observe` as a system user/group with `/var/lib/eom-observe` and `nologin`. Do not add it to
sudo, Docker, worker, or `eom` groups. Install:

- `/etc/eom/observe.yaml`: `root:eom-observe`, 0640
- `/etc/eom/secrets/observe.env`: `root:eom-observe`, 0640
- `/var/lib/eom-observe`: `eom-observe:eom-observe`, 0700
- `/etc/systemd/system/eom-observe.service`: root-owned, 0644

The secret file contains only `EOM_OBSERVE_DATABASE_URL`, `EOM_OBSERVE_ACCESS_TOKEN_HASH`, and
`EOM_OBSERVE_SESSION_SECRET`. Generate at least 32 random token bytes and a separate session secret.
Store only the scrypt token hash. Write the plain token once to
`/home/eom/.eom-observe-initial-token` as `eom:eom` 0600.

## Start

```bash
systemd-analyze verify /etc/systemd/system/eom-observe.service
systemctl daemon-reload
systemctl enable --now eom-observe.service
systemctl is-active eom-observe.service
systemctl is-enabled eom-observe.service
ss -lntp 'sport = :8780'
```

The only acceptable listener is `127.0.0.1:8780`.

## Rollback

Each install writes a 0600 deployment record and copies the prior unit below
`/var/lib/eom-observe/deployments/`. To roll back, stop the service, reinstall a previously retained
and inspected wheel with the same non-editable pip command, restore its recorded unit if necessary,
reload systemd, start the service, and run `deploy_release.sh --verify`. Never point the unit at a Git
checkout as a rollback mechanism.
