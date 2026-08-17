# Application API Smoke Test

The health-only test contains no credentials:

```bash
scripts/api/smoke_test.sh --health-only
```

For an authenticated smoke, place only the Operator password in a temporary 0600 file. Do not use a
password command-line argument:

```bash
chmod 0600 /secure/path/api-smoke-password
EOM_API_SMOKE_USERNAME=admin \
EOM_API_SMOKE_PASSWORD_FILE=/secure/path/api-smoke-password \
scripts/api/smoke_test.sh
```

The test checks live, ready, login, `auth/me`, access-and-refresh rotation, logout, and denial of the
revoked access token. It never prints token or password values. A bootstrap Administrator whose
password change is still required can authenticate and inspect `auth/me`, but the full acceptance
run should first change the temporary password and remove the one-time credential file.

Run the installed-service pytest only after systemd installation and bootstrap:

```bash
EOM_RUN_API_SERVICE_LIVE=1 \
/srv/eom/conda/envs/eom-api/bin/python -m pytest -q tests/api/test_api_service_live.py
```

The broader acceptance sequence uses separate AUTHOR, REVIEWER, EDITOR, and VIEWER accounts. Keep
their temporary passwords in separate 0600 files and delete them after password changes. Do not
emit request/response bodies while testing authentication or Operator creation.
