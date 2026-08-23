# Kordoc HWPX Renderer V0 Operations

Status: implementation prepared; production deployment requires a separately authorized HWPX
builder release. Application API V0 acceptance and its release tag do not depend on this adapter.

## Fixed runtime contract

- Node.js: `22.23.2` from `/srv/eom/conda/envs/eom-hwpx`
- Kordoc: `4.9.0`, installed from the committed npm lock with optional dependencies omitted
- Runtime root: `/srv/eom/conda/envs/eom-hwpx/share/eom-kordoc`
- Builder identity: `eom-hwpx` in the existing transient systemd sandbox
- Network: private/offline
- Writable path: the unique builder workspace only

The bridge has no caller-selected executable, module, command, source path, or output path. The HWPX
manager is the supported entry point: it resolves an approved pinned Markdown Artifact Revision,
stages `input/document.md`, invokes `render-kordoc`, validates the result, and commits it through the
orchestrator. Do not call the bridge directly and do not let a worker write to NAS.

## Deployment preparation

From a clean, reviewed feature tip, an operator first updates the explicit Conda environment from
`infra/conda/eom-hwpx.environment.yml`. The deployment script then rebuilds the Python wheels and
Kordoc runtime from the checked-out commit; it does not reuse an arbitrary npm directory.

```bash
scripts/hwpx/deploy_builder.sh --dry-run
scripts/hwpx/deploy_builder.sh --build-only
```

The install step is privileged because it writes the fixed Conda environment and runtime prefix.
Run it only under a separately reviewed operator plan. It installs non-editable wheels, normalizes
the two Python distributions, console script, and Node runtime to operator-owned service-readable
modes, rejects symlinks, retains Kordoc license notices, and verifies the installed capability. If
verification fails, it preserves the failed runtime under the commit-specific evidence name and
restores the prior Kordoc runtime when one exists; it does not retry.

```bash
scripts/hwpx/deploy_builder.sh --install
scripts/hwpx/deploy_builder.sh --verify
```

No Application API, workflow, Codex, or canonical acceptance rerun is part of this deployment.

## Read-only readiness

After installation, the following commands expose only sanitized dependency status. They do not
render a document and do not access NAS.

```bash
/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx kordoc-capabilities
/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx doctor
```

Expected capability fields are `status=READY`, `node_major=22`, `kordoc_version=4.9.0`, and
`offline_required=true`. Any missing or mismatched dependency fails closed.

## Input and output acceptance

The source pointer must contain a logical Artifact ID, immutable Artifact Revision ID, schema and
media type, and the exact SHA-256. The persisted artifact and revision must exist, be approved, and
match the hash. The V0 Markdown profile is bounded to 1 MiB, 32 display equations, and 20 tables.
External references, raw HTML, images, unsafe XML characters, multiline equations, and unsupported
TeX commands are rejected before Kordoc starts.

Successful output remains `PENDING_MANUAL_HANCOM_VALIDATION`; Kordoc generation does not replace the
separate human Hancom quality boundary. Automated acceptance requires:

- Kordoc validation and parse success;
- an output hash matching the bridge report;
- the exact declared native equation and table counts;
- common hardened ZIP/XML/active-content checks;
- deterministic ZIP metadata and a validated file-set manifest.

Failures retain the platform job and a stable error code. There is no automatic retry or fallback
to a host process, source checkout, direct NAS write, or another renderer.
