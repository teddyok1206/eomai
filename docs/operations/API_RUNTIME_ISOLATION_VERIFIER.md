# Application API Runtime-Isolation Verifier

## Responsibility and boundary

The verifier observes the installed `eom-api.service` boundary. It does not configure the unit,
restart the service, change permissions, or mutate application data. Host metadata and listener
checks remain privileged host checks. Filesystem decisions come only from fixed probes executed as
the validated service identity inside the pinned service mount namespace.

The installed systemd unit is the canonical sandbox declaration. The running `MainPID`, its
`/proc` identity, and its namespace descriptors are the authoritative runtime state. The verifier
accepts no PID, UID, path, command, or probe arguments from an operator.

## Execution-context trace

| Check | Previous subject | Previous namespace | Required subject | Authoritative result | Previous defect |
|---|---|---|---|---|---|
| unit properties, service state, listener | host root | host | `HOST_ROOT` | systemd and `ss` | none |
| denied filesystem paths | host root | service mount | `SERVICE_CONTEXT` | fixed access syscall | root credentials produced a false failure |
| installed package imports | `eom-api` | host mount | `SERVICE_CONTEXT` | fixed import probe | host namespace omitted the sandbox |
| corrected access inventory | `eom-api` UID/GID/groups, zero capabilities | pinned service mount | `SERVICE_CONTEXT` | child probe result plus before/after process validation | corrected |

The current unit uses `User=eom-api`, `Group=eom-api`, no configured supplementary groups,
`PrivateUsers=no`, `PrivateNetwork=no`, an empty capability bounding set, and a private mount
namespace created by its filesystem sandbox directives. The service process has no effective,
permitted, inheritable, bounding, or ambient capabilities and has `NoNewPrivileges` enabled.

## Context acquisition and race handling

The installed helper reads `MainPID` directly from systemd and requires an active/running service
with PID greater than one. It opens the `/proc/<MainPID>` directory, a pidfd, and the mount namespace
before probing. The proc and namespace descriptors stay open, so PID reuse cannot redirect a probe
to another process. It validates the fixed ExecStart, command line, installed Python executable,
UID/GID/groups, working directory, root, user namespace, mount namespace, capabilities, and unit
hardening properties.

The child enters only the pinned mount namespace. `setpriv` then establishes the validated service
UID, GID, exact supplementary group set, empty inheritable/ambient/bounding capabilities,
`NoNewPrivileges`, a reset environment, and the fixed service working directory. The helper checks
the pidfd, `MainPID`, process start time, service state, and namespace again after all probes. Any
change is `FAIL_SERVICE_RESTART_RACE`; there is no host-root fallback.

## Fixed probe inventory

| Logical name | Expected | Subject | Namespace | Operation | Reason |
|---|---|---|---|---|---|
| `config_read` | ALLOWED | service | service mount | read fixed config | runtime configuration |
| `api_environment_read` | ALLOWED | service | service mount | read protected API environment | configured service boundary |
| `state_write` | ALLOWED | service | service mount | create/write/delete fixed-prefix 0600 probe | service-owned state |
| `installed_import` | ALLOWED | service | service mount | import fixed packages | no checkout dependency |
| `repository_read` | DENIED | service | service mount | list directory | source isolation |
| `eomis_read` | DENIED | service | service mount | list directory | repository boundary |
| `root_codex_auth_read` | DENIED | service | service mount | list directory | authentication isolation |
| `worker_home_read` | DENIED | service | service mount | list directory | worker isolation |
| `worker_auth_read` | DENIED | service | service mount | list fixed worker auth directory | worker authentication isolation |
| `nas_read` | DENIED | service | service mount | list directory | orchestrator-only storage boundary |
| `docker_socket_connect` | DENIED | service | service mount | connect without sending data | Docker denial |
| `postgres_secret_read` | DENIED | service | service mount | read file | unrelated deployment secret |
| `slack_secret_read` | DENIED | service | service mount | read file | optional adapter isolation |
| `observe_secret_read` | DENIED | service | service mount | read file | service secret isolation |

Probe output contains only logical names, `PASS_ALLOWED`, `PASS_DENIED`, or a fixed failure class.
It never emits file contents, environment values, command lines, or secret values.

## Data and failure model

The inventory is an immutable tuple and a keyed map enforces exact membership and uniqueness.
Frequent operations are one context capture, ordered probe execution, key lookup, and one stability
comparison. The fixed inventory is O(n) time and O(n) output space with n currently 14; there is no
persistent state, database access, cache, retry, or concurrent claim. The only temporary mutation is
a unique fixed-prefix 0600 file under `/var/lib/eom-api`, removed in a `finally` boundary.

Failures are fail-closed: unavailable context, identity mismatch, namespace mismatch, unexpected
allow/deny, and restart race are distinct. Re-running after an inconclusive restart race is safe and
idempotent. A simpler host `runuser` probe is insufficient because it misses the service mount
namespace; mount-only `nsenter` is insufficient because it retains host-root credentials.

## Installed command

After an authorized deployment, run only:

```bash
sudo -n /usr/local/libexec/eom-api/verify-runtime-isolation
```

The root-owned shell performs host metadata checks and calls the non-editable wheel entry point
`/srv/eom/conda/envs/eom-api/bin/eom-api-runtime-isolation`. Privileged integration remains opt-in
and must never be combined with a live Codex or workflow run.
