# Embedding benchmark v1.2 launch path — 2026-10-23

## Finding

The protected CPU and CUDA numerical prefixes are intentionally immutable and do not
contain the v1.2 1200-second entrypoint modules. Those modules are present in the pinned
owner release, but the v1.2 systemd templates used `python -m` against the numerical
prefix. The templates were not installed, so the Orchestrator could not launch either
device. This was an installation/composition gap, not a GPU compute failure.

## Correction

The 1200-second units now keep the exact fixed CPU/CUDA interpreter and execution
identity, add only the immutable owner release as a read-only import source, and invoke
the exact device-specific module through `runpy`. The owner admits SHA-256 pins for the
four imported v1.2 modules before launch. A separate narrow Polkit rule allows only the
workflow runner to start an exact CPU/CUDA v1.2 benchmark unit instance. Older 180- and
600-second paths and numerical runtime prefixes are unchanged.

This does not authorize direct service invocation or bypass the Orchestrator's source,
operator, job, lease, artifact and publication checks. The unit installation and actual
CPU/GPU runs remain pending until this compatible release is installed and a fresh
Orchestrator execution is admitted.

## Verification

- Focused launch, unit-policy and budget-runtime tests: 84 passed.
- `systemd-analyze verify` passed for both v1.2 service/socket templates.
- Ruff check and `git diff --check` passed.
- Numeric CPU/CUDA prefixes remain untouched; GPU utilization was idle at inspection.

## Next

Install the compatible owner/API release plus the four v1.2 systemd templates and the
narrow Polkit rule. Then start a fresh admitted benchmark request using the existing
pinned CPU/GPU configuration and the same source window; preserve all prior failed
attempts as history. Do not change the production embedding default until numerical,
ranking, timing, GPU memory and coexistence checks pass.
