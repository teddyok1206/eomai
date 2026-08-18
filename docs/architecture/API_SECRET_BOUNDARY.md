# Application API Secret Boundary

## Responsibility

`/etc/eom/secrets` is a shared operator-controlled boundary and remains `root:eom:0750`.
Application API installation must not add other-user traversal or add `eom-api` to the `eom`
group. The canonical secrets are the three values in `/etc/eom/secrets/api.env`; no runtime copy or
database copy is created.

systemd PID 1 reads `EnvironmentFile=/etc/eom/secrets/api.env` before executing the service as
`eom-api`. The process validates the injected database URL and HMAC values but does not read, stat,
or traverse the source file. Non-secret settings live in `/etc/eom-api/api.yaml`, owned
`root:eom-api:0640` beneath a `root:eom-api:0750` directory.

## Verification

The runtime doctor checks configuration parsing, required environment values, database identity,
migration head, and RBAC seed. The root-owned deployment verifier checks path type, symlink state,
owner, group, mode, exact environment variable names, unit references, and absence of `eom` group
membership. Neither check prints a value.

This split preserves least privilege. An ACL, a second plaintext copy, an `eom` group membership,
or a `0751` secret directory would make runtime file inspection convenient but would expand the
secret exposure boundary and is rejected.
