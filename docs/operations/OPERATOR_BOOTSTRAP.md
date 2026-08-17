# Operator Bootstrap

Apply migration `20260817_0006` before bootstrap. The command is allowed only while the Operator
table is empty and concurrent calls are serialized in PostgreSQL.

```bash
/srv/eom/conda/envs/eom-core/bin/eomctl operator bootstrap-admin \
  --username admin \
  --display-name "EOM Administrator"
```

The command does not print the password. It creates `/home/eom/.eom-api-initial-admin` as an
owner-only `0600` file containing the Operator ID, username, one-time password, and UTC timestamp.
The first login is restricted until `POST /api/v1/auth/change-password` succeeds. Password change
rotates the current token pair and revokes other sessions.

Delete the one-time file after the first password change and confirm the account can log in again.
Do not archive, paste, log, or send the file through Slack. API startup never creates an account.
