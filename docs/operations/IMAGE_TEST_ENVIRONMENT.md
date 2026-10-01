# Image Unit-Test Environment

EOM image inference and LoRA training intentionally remain in isolated Python 3.11 CUDA
environments. Repository source and contract tests require Python 3.12. Importing either CUDA
environment from the repository test process is unsupported: it crosses Python ABI boundaries and
would make test collection depend on GPU runtime packages.

The test-only `eom-image-test` environment closes that boundary. It contains the ordinary API test
dependencies plus exactly two raster dependencies:

- Pillow exercises the real bounded PNG transformations;
- NumPy exercises crop detection and reference composition.

Torch, Diffusers, CUDA libraries, model weights, and production service entry points are excluded.
Unit tests inject fake GPU backends behind the existing adapter interfaces. The environment cannot
change inference latency or production model behavior.

## Provision

```bash
scripts/infra/provision_image_test_environment.sh
```

The script creates `/srv/eom/conda/envs/eom-image-test` as the unprivileged `eom` user, installs the
pinned requirements, and verifies Python and the important package versions. It never edits
`eom-image`, `eom-image-trainer`, `eom-api`, or `eom-hwpx`.

## Run

```bash
scripts/infra/test_repository_non_live.sh image
scripts/infra/test_repository_non_live.sh all
```

`config/testing/image-unit-tests.txt` is the explicit routing manifest. A unit test derives the
direct Pillow, NumPy, and image-runtime imports from the test AST in O(files + syntax nodes) time and
requires exact manifest equality. New image tests therefore cannot silently fall back to the API
environment. Runtime/GPU tests marked `image_trainer_runtime` remain opt-in and are not part of this
non-live unit boundary.

This is a test harness boundary only. Generated test files remain in pytest temporary directories;
no image artifacts, model files, or environment directories belong in Git.
