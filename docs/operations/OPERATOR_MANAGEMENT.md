# Operator Management

Routine management uses the versioned API. `eomctl operator` is retained for bootstrap and
emergency local operation. All mutating CLI commands require an active ADMIN `--actor-id`; password
input is an owner-only regular file and never a command argument.

```bash
eomctl operator list
eomctl operator inspect <OPERATOR_ID>
eomctl operator roles <OPERATOR_ID>
eomctl operator assign-role <OPERATOR_ID> --role REVIEWER --actor-id <ADMIN_OPERATOR_ID>
eomctl operator revoke-role <OPERATOR_ID> --role REVIEWER \
  --actor-id <ADMIN_OPERATOR_ID> --reason "role no longer required"
eomctl operator disable <OPERATOR_ID> --actor-id <ADMIN_OPERATOR_ID> --reason "offboarded"
eomctl operator enable <OPERATOR_ID> --actor-id <ADMIN_OPERATOR_ID>
eomctl operator revoke-sessions <OPERATOR_ID> --actor-id <ADMIN_OPERATOR_ID>
```

Create a password file with owner `eom`, mode `0600`, one password and at most one terminating
newline. Whitespace inside the password is preserved.

```bash
eomctl operator create --username review01 --display-name "Reviewer" --role REVIEWER \
  --temporary-password-file <PROTECTED_PATH> --actor-id <ADMIN_OPERATOR_ID>
```

Operators are not physically deleted. Role removal and disable keep event history. The final active
ADMIN cannot be disabled or lose ADMIN; `OPERATOR_LAST_ADMIN` is an invariant failure, not a retry.
