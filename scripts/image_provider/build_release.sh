#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
PYTHON=/srv/eom/conda/envs/eom-api/bin/python
PIP=/srv/eom/conda/envs/eom-api/bin/pip
OUTPUT_ROOT=/tmp/eom-image-provider-build

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
git -C "${REPOSITORY}" archive "${head_commit}" packages/image_contracts services/image_provider \
  | tar -x -C "${state}/source"
"${PIP}" wheel --disable-pip-version-check --no-deps --no-build-isolation \
  --wheel-dir "${state}/dist" "${state}/source/packages/image_contracts"
"${PIP}" wheel --disable-pip-version-check --no-deps --no-build-isolation \
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
        "eom_image_provider/sdxl_photo_style_sources.py",
        "eom_image_provider/sdxl_reference_metadata.py",
        "eom_image_provider/sdxl_reference_pixels.py",
        "eom_image_provider/sdxl_reference_transform_verification.py",
        "eom_image_provider/sdxl_model_resolution.py",
        "eom_image_provider/staged_file_io.py",
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
printf 'SOURCE_COMMIT=%s\n' "${head_commit}"
printf 'BUILD_STATE=%s\n' "${state}"
printf 'CONTRACT_WHEEL=%s\n' "${contract_wheel}"
printf 'CONTRACT_WHEEL_SHA256=%s\n' "${contract_sha}"
printf 'PROVIDER_WHEEL=%s\n' "${provider_wheel}"
printf 'PROVIDER_WHEEL_SHA256=%s\n' "${provider_sha}"
