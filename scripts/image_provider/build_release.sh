#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
PYTHON=/srv/eom/conda/envs/eom-api/bin/python
PIP=/srv/eom/conda/envs/eom-api/bin/pip
OUTPUT_ROOT=/tmp/eom-image-provider-build
DEPENDENCY_VERIFIER_SHA256=44f7e11f4e43f7fe78b485ced65f5e006b36d0c991b1822d40911104a52d00e8

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -ne 0 ]] || fail "LOCAL_IMAGE_BUILD_MUST_NOT_RUN_AS_ROOT"
head_commit=$(git -C "${REPOSITORY}" rev-parse HEAD)
[[ "${head_commit}" =~ ^[0-9a-f]{40}$ ]] || fail "LOCAL_IMAGE_SOURCE_COMMIT_INVALID"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain)" ]] || \
  fail "LOCAL_IMAGE_SOURCE_TREE_DIRTY"
umask 077
mkdir -p "${OUTPUT_ROOT}"
chmod 0700 "${OUTPUT_ROOT}"
state=$(mktemp -d "${OUTPUT_ROOT}/${head_commit}.XXXXXX")
chmod 0700 "${state}"
mkdir "${state}/source" "${state}/dist"
git -C "${REPOSITORY}" archive "${head_commit}" \
  packages/image_contracts packages/gpu_lease services/image_provider \
  scripts/image_provider/verify_release_dependency.py \
  | tar -x -C "${state}/source"
"${PIP}" wheel --disable-pip-version-check --no-index --no-deps --no-build-isolation \
  --wheel-dir "${state}/dist" "${state}/source/packages/gpu_lease"
"${PIP}" wheel --disable-pip-version-check --no-index --no-deps --no-build-isolation \
  --wheel-dir "${state}/dist" "${state}/source/packages/image_contracts"
"${PIP}" wheel --disable-pip-version-check --no-index --no-deps --no-build-isolation \
  --wheel-dir "${state}/dist" "${state}/source/services/image_provider"
contract_wheel=$(find "${state}/dist" -maxdepth 1 -type f \
  -name 'eom_image_contracts-*.whl' -print)
provider_wheel=$(find "${state}/dist" -maxdepth 1 -type f \
  -name 'eom_local_image_provider-*.whl' -print)
[[ -n "${contract_wheel}" && "${contract_wheel}" != *$'\n'* ]] || \
  fail "LOCAL_IMAGE_CONTRACT_WHEEL_INVALID"
[[ -n "${provider_wheel}" && "${provider_wheel}" != *$'\n'* ]] || \
  fail "LOCAL_IMAGE_PROVIDER_WHEEL_INVALID"
"${PYTHON}" - "${contract_wheel}" "${provider_wheel}" <<'PY'
import sys
import zipfile

contract, provider = sys.argv[1:]
with zipfile.ZipFile(contract) as archive:
    names = set(archive.namelist())
    required = {
        "eom_image_contracts/sdxl_ip_style.py",
        "eom_image_contracts/sdxl_ip_style_comparison.py",
        "eom_image_contracts/schemas/local-image-sdxl-ip-style-comparison-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-ip-style-model-manifest-v1.schema.json",
        "eom_image_contracts/sdxl_native_evaluation.py",
        "eom_image_contracts/sdxl_native_geometry.py",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-command-v4.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-result-v4.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-command-v5.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-result-v5.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-command-v6.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-result-v6.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-canny-reference-command-v4.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-canny-reference-result-v4.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-plan-v6.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-command-v6.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-result-v6.schema.json",
        "eom_image_contracts/sdxl_native_canny_reference.py",
        "eom_image_contracts/schemas/local-image-sdxl-canny-reference-command-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-canny-reference-result-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-canny-reference-command-v3.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-canny-reference-result-v3.schema.json",
        "eom_image_contracts/sdxl_evaluation_codec.py",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-command-v3.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-result-v3.schema.json",
        "eom_image_contracts/sdxl_validation_comparison.py",
        "eom_image_contracts/sdxl_photo_style.py",
        "eom_image_contracts/sdxl_photo_style_execution.py",
        "eom_image_contracts/sdxl_photo_style_result.py",
        "eom_image_contracts/photo_object_support.py",
        "eom_image_contracts/sdxl_photo_object_support_plan.py",
        "eom_image_contracts/sdxl_photo_object_support_lineage.py",
        "eom_image_contracts/schemas/local-image-photo-object-support-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-plan-v7.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-command-v7.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-result-v7.schema.json",
        "eom_image_contracts/sdxl_photo_region_review.py",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-plan-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-command-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-result-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-plan-v3.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-command-v3.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-result-v3.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-plan-v4.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-command-v4.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-result-v4.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-plan-v5.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-command-v5.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-photo-style-result-v5.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-validation-comparison-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-validation-comparison-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-validation-comparison-command-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-validation-comparison-result-v2.schema.json",
        "eom_image_contracts/source_page_crops.py",
        "eom_image_contracts/source_pdf_crops.py",
        "eom_image_contracts/schemas/local-image-science-source-pdf-render-request-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-source-pdf-render-result-v1.schema.json",
        "eom_image_contracts/sdxl_native_training_targets.py",
        "eom_image_contracts/schemas/local-image-sdxl-training-target-command-v3.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-training-target-result-v3.schema.json",
        "eom_image_contracts/schemas/local-image-science-source-pdf-crop-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-source-pdf-crop-set-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-source-page-crop-review-v3.schema.json",
        "eom_image_contracts/schemas/local-image-science-source-page-crop-set-v3.schema.json",
        "eom_image_contracts/informative_lineart.py",
        "eom_image_contracts/sdxl_learned_comparison.py",
        "eom_image_contracts/schemas/local-image-sdxl-learned-comparison-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-learned-comparison-result-v1.schema.json",
        "eom_image_contracts/informative_lineart_extraction.py",
        "eom_image_contracts/schemas/local-image-informative-lineart-extraction-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-informative-lineart-extraction-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-informative-lineart-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-micro-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-micro-adapter-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-micro-result-v1.schema.json",
        "eom_image_contracts/sdxl_native_lora.py",
        "eom_image_contracts/schemas/local-image-sdxl-native-lora-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-native-lora-command-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-native-lora-command-v3.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-native-lora-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-native-lora-adapter-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lineart-prompt-policy-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lineart-probe-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lineart-probe-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lineart-stack-v1.schema.json",
        "eom_image_contracts/schemas/local-image-style-dataset-split-v1.schema.json",
        "eom_image_contracts/schemas/local-image-crop-locator-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-crop-locator-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-provider-binding-v1.schema.json",
        "eom_image_contracts/schemas/local-image-provider-binding-v2.schema.json",
        "eom_image_contracts/schemas/local-image-provider-binding-v3.schema.json",
        "eom_image_contracts/schemas/local-image-provider-binding-v4.schema.json",
        "eom_image_contracts/schemas/local-image-provider-binding-v5.schema.json",
        "eom_image_contracts/schemas/local-image-provider-binding-v6.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-request-v6.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-receipt-v6.schema.json",
        "eom_image_contracts/schemas/local-image-provider-binding-v7.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-request-v7.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-receipt-v7.schema.json",
        "eom_image_contracts/schemas/local-image-institutional-style-evaluation-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-institutional-style-evaluation-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-institutional-style-evaluation-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-institutional-style-review-packet-v1.schema.json",
        "eom_image_contracts/schemas/local-image-institutional-style-answer-key-v1.schema.json",
        "eom_image_contracts/schemas/local-image-composite-request-v1.schema.json",
        "eom_image_contracts/schemas/local-image-composite-receipt-v1.schema.json",
        "eom_image_contracts/schemas/local-image-quality-evaluation-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-quality-evaluation-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-training-authorization-v1.schema.json",
        "eom_image_contracts/schemas/local-image-training-candidate-inventory-v1.schema.json",
        "eom_image_contracts/schemas/local-image-training-crop-proposal-set-v1.schema.json",
        "eom_image_contracts/schemas/local-image-training-crop-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-training-dataset-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-training-eligibility-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-training-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-adapter-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-checkpoint-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-training-receipt-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-training-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-training-worker-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-visual-reference-intent-v1.schema.json",
        "eom_image_contracts/schemas/local-image-visual-reference-bundle-v1.schema.json",
        "eom_image_contracts/schemas/local-image-visual-reference-discovery-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-visual-reference-discovery-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-visual-reference-acquisition-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-visual-reference-acquisition-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-request-v1.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-receipt-v1.schema.json",
        "eom_image_contracts/schemas/local-image-style-adapter-release-v1.schema.json",
        "eom_image_contracts/schemas/local-image-style-adapter-release-v2.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-request-v2.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-receipt-v2.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-request-v3.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-receipt-v3.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-request-v4.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-receipt-v4.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-request-v5.schema.json",
        "eom_image_contracts/schemas/local-image-reference-conditioned-composite-receipt-v5.schema.json",
    }
    if not required.issubset(names):
        raise SystemExit("LOCAL_IMAGE_CONTRACT_WHEEL_INVALID")
with zipfile.ZipFile(provider) as archive:
    names = set(archive.namelist())
    if not {
        "eom_image_provider/cli.py",
        "eom_image_provider/provider.py",
        "eom_image_provider/diffusers_backend.py",
        "eom_image_provider/reference_acquisition.py",
        "eom_image_provider/reference_simplification.py",
        "eom_image_provider/sdxl_lineart_backend.py",
        "eom_image_provider/sdxl_native_geometry.py",
        "eom_image_provider/sdxl_lineart_probe.py",
        "eom_image_provider/sdxl_learned_comparison.py",
        "eom_image_provider/sdxl_validation_comparison.py",
        "eom_image_provider/sdxl_photo_style.py",
        "eom_image_provider/sdxl_photo_conditioning.py",
        "eom_image_provider/photo_object_support_conditioning.py",
        "eom_image_provider/photo_object_support_pixels.py",
        "eom_image_provider/sdxl_photo_style_sources.py",
        "eom_image_provider/sdxl_reference_metadata.py",
        "eom_image_provider/sdxl_reference_pixels.py",
        "eom_image_provider/sdxl_reference_transform_verification.py",
        "eom_image_provider/sdxl_model_resolution.py",
        "eom_image_provider/staged_file_io.py",
        "eom_image_provider/sdxl_ip_style_io.py",
        "eom_image_provider/sdxl_ip_style_pixels.py",
        "eom_image_provider/sdxl_ip_style_encoder_input.py",
        "eom_image_provider/sdxl_ip_style_routing.py",
        "eom_image_provider/informative_lineart_acquisition.py",
        "eom_image_provider/informative_lineart_backend.py",
        "eom_image_provider/informative_lineart_extraction.py",
        "eom_image_provider/informative_lineart_installation.py",
        "eom_image_provider/informative_lineart_download.py",
        "eom_image_provider/informative_lineart_model.py",
        "eom_image_provider/informative_lineart_resolution.py",
        "eom_image_provider/notices/informative-drawings-MIT.txt",
        "eom_image_provider/prompt_capacity.py",
    }.issubset(names):
        raise SystemExit("LOCAL_IMAGE_PROVIDER_WHEEL_INVALID")
PY
contract_sha=$(sha256sum "${contract_wheel}" | cut -d' ' -f1)
provider_sha=$(sha256sum "${provider_wheel}" | cut -d' ' -f1)
gpu_lease_wheel=${state}/dist/eom_gpu_lease-0.1.0-py3-none-any.whl
[[ -f "${gpu_lease_wheel}" && ! -L "${gpu_lease_wheel}" ]] || \
  fail "LOCAL_IMAGE_GPU_LEASE_WHEEL_REQUIRED"
chmod 0600 "${contract_wheel}" "${provider_wheel}" "${gpu_lease_wheel}"
gpu_lease_sha=$(sha256sum "${gpu_lease_wheel}" | cut -d' ' -f1)
dependency_verifier=${state}/source/scripts/image_provider/verify_release_dependency.py
[[ "$(sha256sum "${dependency_verifier}" | cut -d' ' -f1)" == "${DEPENDENCY_VERIFIER_SHA256}" ]] || \
  fail "LOCAL_IMAGE_DEPENDENCY_VERIFIER_MISMATCH"
"${PYTHON}" -I -B "${dependency_verifier}" build --profile provider \
  --stage "${state}" --source-root "${state}/source" --source-commit "${head_commit}" \
  --contract-wheel "${contract_wheel}" --contract-sha256 "${contract_sha}" \
  --provider-wheel "${provider_wheel}" --provider-sha256 "${provider_sha}" \
  --gpu-lease-wheel "${gpu_lease_wheel}" --gpu-lease-sha256 "${gpu_lease_sha}"
printf 'SOURCE_COMMIT=%s\n' "${head_commit}"
printf 'BUILD_STATE=%s\n' "${state}"
printf 'CONTRACT_WHEEL=%s\n' "${contract_wheel}"
printf 'CONTRACT_WHEEL_SHA256=%s\n' "${contract_sha}"
printf 'PROVIDER_WHEEL=%s\n' "${provider_wheel}"
printf 'PROVIDER_WHEEL_SHA256=%s\n' "${provider_sha}"
printf 'GPU_LEASE_WHEEL=%s\n' "${gpu_lease_wheel}"
printf 'GPU_LEASE_WHEEL_SHA256=%s\n' "${gpu_lease_sha}"
printf 'GPU_SHARED_LEASE_MIGRATION_VERIFIED=NO\n'
