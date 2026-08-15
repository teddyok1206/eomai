# ADR 0012: Isolate The HWPX Builder

## Status

Accepted.

## Decision

Install `eom-hwpx-builder` and `eom-hwpx-contracts` as non-editable wheels in the dedicated Python
3.12 environment `/srv/eom/conda/envs/eom-hwpx`. Run builds as the locked `eom-hwpx` system user in
a transient systemd unit with a fresh assigned workspace and no network.

The builder exchanges only `request.json`, `template.hwpx`, `template-bindings.json`, `input/`,
`output/`, and `result.json`. It does not import eom-core and cannot access PostgreSQL, NAS, Docker,
Codex authentication, worker homes, the Git checkout, or system secrets. The eom-core adapter owns
staging, database transitions, schema validation, artifact commit, and failure recording.

## Consequences

Branch changes cannot alter the installed builder. A deployment script must build, inspect, and
install both wheels without editable metadata. systemd policy and filesystem ownership become part
of the acceptance tests. Builder stdout remains bounded diagnostics and never becomes the result.
