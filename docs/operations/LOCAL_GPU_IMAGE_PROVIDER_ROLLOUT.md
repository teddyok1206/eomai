# Local GPU image provider rollout

Status: reviewed V1 rollout; source contracts and isolated provider are implemented

Last reviewed: 2026-09-01 UTC

## Boundary

This rollout prepares EOM to run a local open-source image model for non-authoritative background
generation. Operator authorization is still required for package/model installation and the local
GPU smoke. This document never authorizes a live Item workflow, HWPX build, production route
activation, service restart, or hosted inference API.

The first candidate is `segmind/SSD-1B`. `FLUX.1-schnell` is a later quality target after the
provider contract is proven with the lighter model.

## Non-negotiable constraints

- Do not modify `/home/eom/EOMIS`.
- Do not use external LLM or hosted image APIs.
- Do not install PyTorch, Diffusers, or model packages into `eom-api`, `eom-web`, or `eom-hwpx`.
- Use the dedicated `eom-image` Conda environment.
- Do not let workers access provider credentials, NAS writes, DB writes, or peer workers.
- Do not commit model files, generated PNGs, long logs, tokens, `.env` files, or Hugging Face
  credentials.
- Do not interrupt Slot 5 textbook analysis. The GPU provider uses its own one-lease capacity
  boundary.
- Keep deterministic SVG as the authoritative science layer.

## Server facts to record before installation

Record these in a protected operator evidence directory, not in Git:

```bash
git -C /home/eom/EOM rev-parse HEAD
git -C /home/eom/EOM status --short --branch
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free,compute_cap --format=csv,noheader
/srv/eom/conda/envs/eom-image/bin/python - <<'PY'
import importlib.util
for name in ("torch", "diffusers", "transformers", "accelerate", "safetensors", "PIL"):
    print(f"{name}={importlib.util.find_spec(name) is not None}")
PY
```

Expected current baseline before provider installation:

- GPU: NVIDIA GeForce RTX 5080, 16 GiB VRAM, compute capability 12.0.
- `eom-image`: no PyTorch/Diffusers provider stack yet.
- Existing EOM services remain active; no service restart is required for the design phase.

## Installation plan

Use a protected plan file before doing any network or package installation:

```text
/tmp/EOM_LOCAL_GPU_IMAGE_PROVIDER_DEPLOY_<SHORT_HEAD>.md
mode 0600
```

The plan must include:

1. immutable source preflight;
2. Slot 5 and active worker no-interruption check;
3. exact candidate model ID and license/provenance review;
4. `eom-image` package plan with Python, PyTorch CUDA 12.8 compatible wheel, Diffusers,
   Transformers, Accelerate, Safetensors, and Pillow;
5. protected model-store root and ownership;
6. download method that never logs tokens;
7. model file manifest with SHA-256 for every required file;
8. local-files-only smoke test;
9. GPU memory and timeout limits;
10. artifact/provenance receipt schema;
11. rollback plan that removes only provider runtime/model-store additions.

## Model-store contract

The reviewed root is `/srv/eom/models/image`. It contains no mutable `latest` pointer:

```text
/srv/eom/models/image/
  <model_id>/
    <model_revision_id>/
      manifest.json
      files/
```

Directory policy:

- model-store root owned by an operator-controlled service identity;
- application workers cannot modify model files;
- model files are readable only by the local image provider service identity and the operator group
  that performs deployment;
- no symlink traversal;
- no mutable `latest` path in workflow history.

The manifest records upstream model ID, local revision ID, source URL, license identifier, accepted
license timestamp if applicable, required file list, file sizes, SHA-256 hashes, and runtime
contract version.

## Package installation boundary

For RTX 5080/Blackwell, use PyTorch 2.7.1 from the official CUDA 12.8 wheel index, followed by the
exact versions recorded in `services/image_provider/pyproject.toml`. Do not rely on an older CUDA
wheel simply because the host driver is new. Install the contracts and provider from locally built,
hash-recorded wheels with `--no-deps` after the reviewed dependency set is present.

The installation command set must be reviewed as an operator block before execution. It should not
use `curl | sh`, random third-party binaries, or ambient `pip`. It must use the explicit
`/srv/eom/conda/envs/eom-image` interpreter.

## Local smoke, not an item workflow

After model files and packages exist, run one disposable smoke outside the production workflow:

1. verify `torch.cuda.is_available()`;
2. verify GPU name and capability;
3. load the reviewed model revision with `local_files_only=True`;
4. generate one small fixed-seed background image;
5. save it to a protected temporary evidence file;
6. compute SHA-256;
7. verify dimensions, mode, file metadata, and no symlink;
8. delete the disposable image unless it is intentionally retained in the protected evidence
   directory.

This smoke must not create an Item, Artifact, HWPX build, workflow, or NAS commit.

## Provider acceptance before production use

Before enabling `LOCAL_GENERATIVE_BACKGROUND` in a Content Pack or workflow:

- add JSON Schema 2020-12 for model revision manifest and provider receipt;
- add Pydantic models;
- add Catalog adapter tests for missing model, stale revision, hash mismatch, route disabled, OOM,
  timeout, invalid output, and idempotent replay;
- add a GPU-lease test proving only one provider job runs on the RTX 5080;
- add tests proving workers cannot call the provider directly;
- add tests proving generated pixels cannot carry required labels or equations;
- add artifact tests proving background, SVG overlay, final PNG, and HWPX pointer hashes remain
  separate;
- run Ruff, formatter, strict mypy, focused unit/integration tests, package checks, shell syntax,
  and repository boundary scan.

## Runtime enablement order

After source gates pass:

1. install provider runtime into `eom-image`;
2. install model revision into the protected model store;
3. run local smoke;
4. deploy schema and Catalog adapter code;
5. enable route capability in a new immutable Content Pack release;
6. run one non-production item workflow with explicit one-shot authorization;
7. inspect the resulting Item image pointer and HWPX output;
8. keep deterministic SVG-only fallback available by choosing a deterministic profile.

## Rollback

Rollback should:

- disable the local provider route in the active Content Pack/preset pointer;
- leave all model revision manifests and generated artifacts immutable;
- stop only the provider service if one was introduced;
- avoid touching API, Web, HWPX, PostgreSQL, Slot 5, port 8000, or `/home/eom/EOMIS`;
- preserve deterministic SVG generation.

Do not delete model files until no immutable provider receipt references them.

## Open questions for the execution phase

- Exact model-store path and service identity.
- Whether the first smoke should use pure Diffusers or a ComfyUI-compatible adapter.
- Whether FLUX should use CPU offload, quantization, or wait for a measured SSD-1B baseline.
- Whether generated backgrounds require a human review state before use in high-stakes exam
  deliverables.
