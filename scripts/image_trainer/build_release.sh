#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
PYTHON=/srv/eom/conda/envs/eom-api/bin/python
PIP=/srv/eom/conda/envs/eom-api/bin/pip
OUTPUT_ROOT=/tmp/eom-image-trainer-build

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -ne 0 ]] || fail "LOCAL_IMAGE_TRAINER_BUILD_MUST_NOT_RUN_AS_ROOT"
head_commit=$(git -C "${REPOSITORY}" rev-parse HEAD)
[[ "${head_commit}" =~ ^[0-9a-f]{40}$ ]] || fail "LOCAL_IMAGE_TRAINER_SOURCE_COMMIT_INVALID"
# Wheels are built from the immutable archive below; unrelated untracked operator files cannot
# enter it. Tracked or staged drift remains a hard failure.
[[ -z "$(git -C "${REPOSITORY}" status --porcelain --untracked-files=no)" ]] || \
  fail "LOCAL_IMAGE_TRAINER_SOURCE_TREE_DIRTY"
umask 077
mkdir -p "${OUTPUT_ROOT}"
chmod 0700 "${OUTPUT_ROOT}"
state=$(mktemp -d "${OUTPUT_ROOT}/${head_commit}.XXXXXX")
chmod 0700 "${state}"
mkdir "${state}/source" "${state}/dist"
git -C "${REPOSITORY}" archive "${head_commit}" \
  packages/image_contracts services/image_provider services/image_trainer \
  | tar -x -C "${state}/source"
for project in packages/image_contracts services/image_provider services/image_trainer; do
  "${PIP}" wheel --disable-pip-version-check --no-deps --no-build-isolation \
    --wheel-dir "${state}/dist" "${state}/source/${project}"
done
contract_wheel=$(find "${state}/dist" -maxdepth 1 -type f \
  -name 'eom_image_contracts-*.whl' -print)
provider_wheel=$(find "${state}/dist" -maxdepth 1 -type f \
  -name 'eom_local_image_provider-*.whl' -print)
trainer_wheel=$(find "${state}/dist" -maxdepth 1 -type f \
  -name 'eom_local_image_trainer-*.whl' -print)
for wheel in "${contract_wheel}" "${provider_wheel}" "${trainer_wheel}"; do
  [[ -n "${wheel}" && "${wheel}" != *$'\n'* ]] || \
    fail "LOCAL_IMAGE_TRAINER_WHEEL_INVALID"
done
"${PYTHON}" - "${contract_wheel}" "${provider_wheel}" "${trainer_wheel}" <<'PY'
import sys
import zipfile

contract, provider, trainer = sys.argv[1:]
with zipfile.ZipFile(contract) as archive:
    names = set(archive.namelist())
    required = {
        "eom_image_contracts/informative_lineart.py",
        "eom_image_contracts/sdxl_learned_comparison.py",
        "eom_image_contracts/sdxl_target_comparison.py",
        "eom_image_contracts/sdxl_publication_comparison.py",
        "eom_image_contracts/schemas/local-image-sdxl-publication-comparison-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-publication-comparison-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-target-comparison-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-target-comparison-result-v1.schema.json",
        "eom_image_contracts/sdxl_training_targets.py",
        "eom_image_contracts/sdxl_source_training_targets.py",
        "eom_image_contracts/sdxl_reviewed_micro.py",
        "eom_image_contracts/sdxl_reviewed_evaluation.py",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-command-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-evaluation-result-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-micro-command-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lora-micro-result-v2.schema.json",
        "eom_image_contracts/source_page_crops.py",
        "eom_image_contracts/science_visual_expansion.py",
        "eom_image_contracts/science_visual_pilot_codec.py",
        "eom_image_contracts/schemas/local-image-science-source-page-crop-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-source-page-crop-set-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-source-page-crop-review-v2.schema.json",
        "eom_image_contracts/schemas/local-image-science-source-page-crop-set-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-training-target-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-training-target-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-training-target-command-v2.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-training-target-result-v2.schema.json",
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
        "eom_image_contracts/schemas/local-image-sdxl-lineart-prompt-policy-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lineart-probe-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lineart-probe-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-sdxl-lineart-stack-v1.schema.json",
        "eom_image_contracts/schemas/local-image-style-dataset-split-v1.schema.json",
        "eom_image_contracts/schemas/local-image-crop-locator-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-crop-locator-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-training-eligibility-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-training-crop-proposal-set-v1.schema.json",
        "eom_image_contracts/schemas/local-image-training-crop-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-checkpoint-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-training-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-training-worker-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-micro-probe-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-micro-probe-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-micro-adapter-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-micro-probe-worker-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-micro-evaluation-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-micro-evaluation-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-corpus-visual-pilot-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-corpus-visual-pilot-command-v2.schema.json",
        "eom_image_contracts/schemas/local-image-science-corpus-visual-pilot-command-v3.schema.json",
        "eom_image_contracts/schemas/local-image-science-corpus-visual-pilot-command-v4.schema.json",
        "eom_image_contracts/schemas/local-image-science-corpus-visual-pilot-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-corpus-visual-pilot-plan-v2.schema.json",
        "eom_image_contracts/schemas/local-image-science-corpus-visual-pilot-plan-v3.schema.json",
        "eom_image_contracts/schemas/local-image-science-corpus-visual-pilot-plan-v4.schema.json",
        "eom_image_contracts/schemas/local-image-science-corpus-visual-pilot-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-campaign-pattern-inventory-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-campaign-review-batch-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-campaign-review-batch-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-crop-set-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-crop-set-v2.schema.json",
        "eom_image_contracts/schemas/local-image-science-raster-suitability-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-raster-suitability-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-raster-refinement-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-raster-refinement-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-campaign-crop-set-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-object-line-art-suitability-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-object-line-art-crop-set-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-lora-micro-probe-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-lora-micro-probe-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-lora-micro-adapter-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-lora-micro-probe-worker-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-probe-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-probe-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-adapter-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-probe-worker-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-evaluation-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-evaluation-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-probe-plan-v2.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-probe-command-v2.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-adapter-manifest-v2.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-probe-worker-result-v2.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-evaluation-command-v2.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-evaluation-result-v2.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-probe-plan-v3.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-probe-command-v3.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-adapter-manifest-v3.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-probe-worker-result-v3.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-evaluation-command-v3.schema.json",
        "eom_image_contracts/schemas/local-image-science-campaign-lora-micro-evaluation-result-v3.schema.json",
        "eom_image_contracts/schemas/local-image-science-lora-micro-evaluation-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-lora-micro-evaluation-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-subject-inventory-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-subject-benchmark-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-subject-benchmark-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-subject-benchmark-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-subject-multiseed-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-subject-multiseed-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-subject-multiseed-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-subject-multiseed-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-science-visual-subject-refinement-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-institutional-style-evaluation-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-institutional-style-evaluation-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-institutional-style-evaluation-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-institutional-style-review-packet-v1.schema.json",
        "eom_image_contracts/schemas/local-image-institutional-style-answer-key-v1.schema.json",
    }
    if not required.issubset(names):
        raise SystemExit("LOCAL_IMAGE_TRAINER_CONTRACT_WHEEL_INVALID")
with zipfile.ZipFile(provider) as archive:
    if not {
        "eom_image_provider/provider.py",
        "eom_image_provider/sdxl_lora_evaluation.py",
        "eom_image_provider/sdxl_learned_comparison.py",
        "eom_image_provider/sdxl_target_comparison.py",
        "eom_image_provider/sdxl_target_source_io.py",
        "eom_image_provider/sdxl_publication_comparison.py",
        "eom_image_provider/sdxl_comparison_command.py",
        "eom_image_provider/sdxl_pair_inference.py",
        "eom_image_provider/sdxl_lora_material.py",
        "eom_image_provider/informative_lineart_acquisition.py",
        "eom_image_provider/informative_lineart_backend.py",
        "eom_image_provider/informative_lineart_extraction.py",
        "eom_image_provider/informative_lineart_installation.py",
        "eom_image_provider/informative_lineart_download.py",
        "eom_image_provider/informative_lineart_model.py",
        "eom_image_provider/informative_lineart_resolution.py",
        "eom_image_provider/notices/informative-drawings-MIT.txt",
    }.issubset(archive.namelist()):
        raise SystemExit("LOCAL_IMAGE_TRAINER_PROVIDER_WHEEL_INVALID")
with zipfile.ZipFile(trainer) as archive:
    names = set(archive.namelist())
    required = {
        "eom_image_trainer/checkpoints.py",
        "eom_image_trainer/cli.py",
        "eom_image_trainer/crop_locator.py",
        "eom_image_trainer/crop_locator_runner.py",
        "eom_image_trainer/crop_processing.py",
        "eom_image_trainer/dataset_builder.py",
        "eom_image_trainer/diffusers_backend.py",
        "eom_image_trainer/sdxl_lora_backend.py",
        "eom_image_trainer/sdxl_micro_runner.py",
        "eom_image_trainer/sdxl_training_target_runner.py",
        "eom_image_trainer/micro_probe_runner.py",
        "eom_image_trainer/science_micro_probe_runner.py",
        "eom_image_trainer/science_campaign_micro_probe_runner.py",
        "eom_image_trainer/science_campaign_micro_evaluation_runner.py",
        "eom_image_trainer/micro_evaluation_runner.py",
        "eom_image_trainer/science_micro_evaluation_runner.py",
        "eom_image_trainer/proposal_builder.py",
        "eom_image_trainer/runner.py",
        "eom_image_trainer/science_corpus_visual_runner.py",
        "eom_image_trainer/science_subject_benchmark_runner.py",
        "eom_image_trainer/science_subject_multiseed_runner.py",
        "eom_image_trainer/institutional_style_metrics.py",
        "eom_image_trainer/institutional_style_evaluator.py",
    }
    if not required.issubset(names):
        raise SystemExit("LOCAL_IMAGE_TRAINER_WHEEL_INVALID")
PY
printf 'SOURCE_COMMIT=%s\n' "${head_commit}"
printf 'BUILD_STATE=%s\n' "${state}"
for variable_and_wheel in \
  "CONTRACT:${contract_wheel}" \
  "PROVIDER:${provider_wheel}" \
  "TRAINER:${trainer_wheel}"; do
  variable=${variable_and_wheel%%:*}
  wheel=${variable_and_wheel#*:}
  sha=$(sha256sum "${wheel}" | cut -d' ' -f1)
  printf '%s_WHEEL=%s\n' "${variable}" "${wheel}"
  printf '%s_WHEEL_SHA256=%s\n' "${variable}" "${sha}"
done
