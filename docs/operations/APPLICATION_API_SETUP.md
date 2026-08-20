# Application API Setup

## Prerequisites

Run repository builds as `eom` on branch `feat/application-api-v0`. Root access is used only for
the system identity, protected configuration, database runtime role, and systemd installation. The
API never runs Alembic. Apply migrations with the existing migration owner before starting it.

## Isolated Python Environment

Create the Python 3.12 prefix and install the exact third-party lock with the prefix's pip:

```bash
/home/eom/miniconda3/condabin/conda env create \
  --prefix /srv/eom/conda/envs/eom-api \
  --file infra/conda/eom-api.environment.yml
/srv/eom/conda/envs/eom-api/bin/python -m pip install \
  --requirement infra/conda/eom-api.requirements.lock
```

If the Conda environment already exists, retain it and use only its pip. Do not install API
dependencies into system Python or `eom-core`. The runtime distributions are three non-editable
wheels: `eom-platform`, `eom-api-contracts`, and `eom-application-api`. The API dependencies are
kept out of the core distribution.

FastAPI and Uvicorn implement the HTTP adapter; Pydantic validates stable DTOs; pwdlib with
argon2-cffi implements Argon2id; SQLAlchemy and psycopg implement PostgreSQL transactions; HTTPX is
used by the isolated smoke tests. PyYAML loads the reviewed configuration. These dependencies are
version-pinned because the API and OpenAPI surfaces are persistent contracts.

## System Identity And Database Role

Run only these installation boundaries from a reviewed interactive operator shell. The scripts
themselves do not acquire credentials or invoke nested sudo:

```bash
sudo -n scripts/api/bootstrap_service_user.sh
sudo -n scripts/api/bootstrap_runtime_role.sh
```

The first command creates locked `eom-api:eom-api` with `nologin`, no supplementary groups, a 0700
`/var/lib/eom-api`, and a root-owned service-specific `/etc/eom-api` directory. It verifies, but
never changes, the existing `/etc/eom/secrets` `root:eom:0750` boundary. It does not add the service
to the `eom` group. The second command creates or reconciles
`eom_api_runtime`, verifies the prohibited operations, and atomically writes
`/etc/eom/secrets/api.env` as `root:eom-api` 0640. Existing token and fingerprint keys are retained
on repeat execution. It removes role memberships and all prior database, schema, table, sequence,
and function grants before applying reviewed table DML and only sequences owned by INSERT tables.
It also revokes the database's PUBLIC temporary-table privilege; the database owner retains its
implicit owner privilege. A rollback-only INSERT must succeed, while CREATE, ALTER, DROP, TRUNCATE,
extension and role management, and migration metadata mutation must fail. The script never prints a
password, HMAC key, or database URL.

No default privileges are granted. After every migration, rerun this bootstrap so a new table is
denied until its exact access pattern is reviewed and added. `DELETE` is not granted because current
application services use append/revoke state rather than physical deletion.

Install the reviewed configuration:

```bash
sudo -n install -o root -g eom-api -m 0640 \
  config/api.example.yaml /etc/eom-api/api.yaml
```

Do not add secrets to `api.yaml`. The runtime process reads this non-secret file directly. systemd
reads `/etc/eom/secrets/api.env` before changing to `eom-api` and injects the environment; the
runtime does not traverse or stat the protected secret directory. The only secret keys are `EOM_API_DATABASE_URL`,
`EOM_API_TOKEN_HASH_KEY`, and `EOM_API_FINGERPRINT_KEY` in the protected environment file.

## Build And Install

Commit the release and require a clean tree before building:

```bash
scripts/api/deploy_release.sh --build-only
scripts/api/deploy_release.sh --install
```

The install command runs as `eom`. Before building it requires `sudo -n true`; failure causes no
system change. It builds and inspects all three wheels and installs them without editable metadata
as `eom`, then uses only `sudo -n` for system files, systemd, and the rollback record. It never runs
`sudo -v` or waits for a password prompt. The installed imports must resolve below
`/srv/eom/conda/envs/eom-api/lib/python3.12/site-packages`, never the repository.

The build inspection also treats the workflow JSON Schemas as required release resources. It
requires the canonical `schemas/workflow` definition and eight role schemas to match the
`eom_workflow/resources` wheel members byte-for-byte, verifies the wheel `RECORD`, imports directly
from an isolated target installation with a `/tmp` working directory, and compiles
`generic-item-development@1.1.0`. A missing or stale schema stops `--build-only` before any
privileged installation.

The first service start can pass readiness before an Administrator exists. Bootstrap the initial
Administrator, change its temporary password, then run the authenticated smoke test as documented
in `API_SMOKE_TEST.md`. Delete `/home/eom/.eom-api-initial-admin` after the password change is
confirmed.

## Service Verification

```bash
systemctl is-active eom-api.service
systemctl is-enabled eom-api.service
ss -lnt 'sport = :8765'
sudo -n /usr/local/libexec/eom-api/verify-runtime-isolation
sudo -n /usr/local/libexec/eom-api/verify-deployment-metadata
```

The only valid listener is `127.0.0.1:8765`. The unit denies the checkout, EOMIS, NAS, Docker,
worker homes, Codex authentication, and unrelated secret files. `eom-api` is not a member of sudo,
Docker, `eom`, or worker groups.

The root-owned metadata verifier checks the secret directory and file ownership/mode, exact
environment key names, service config metadata, unit paths, and group isolation without printing
secret values. Runtime `eom-api doctor` checks the injected environment format and database role;
it deliberately does not inspect secret filesystem metadata.

## Rollback

Deployment records are 0600 files in `/var/lib/eom-api/deployments`. Stop the service, reinstall the
three retained wheels for the prior source commit with the isolated pip, restore the reviewed prior
unit if it changed, reload systemd, restart, and run `deploy_release.sh --verify`. Never make the
unit import a Git checkout as a rollback mechanism. Database rollback is a separately reviewed
migration-owner operation and must not be performed by the API role.
