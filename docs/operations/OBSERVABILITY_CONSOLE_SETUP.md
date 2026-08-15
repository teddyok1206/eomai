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

The lock installs only the local `eom-observe-contracts` and `eom-observe` distributions plus their
fully pinned dependencies. It does not install the production `eom-platform` distribution.

If the configured Conda channels reject noninteractive creation because their Terms of Service have
not been accepted, do not repeatedly change channels or accept terms implicitly. Create the isolated
prefix with the existing Conda-managed Python 3.12 and install only through that prefix's pip:

```bash
/srv/eom/conda/envs/eom-core/bin/python -m venv --copies /srv/eom/conda/envs/eom-observe
```

This fallback does not install anything into `eom-core` or system Python.

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
