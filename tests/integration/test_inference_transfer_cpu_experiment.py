"""Opt-in real CPU/CLI smoke with synthetic data; never corpus or human acceptance."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from eom_catalog_contracts.inference_transfer_experiment import (
    InferenceTransferExperimentRequest,
    InferenceTransferExperimentResult,
    validate_experiment_result,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfilePointer,
    LocalEmbeddingModelSpec,
)
from eom_identifiers import canonical_json_bytes, content_sha256

from tests.unit.inference_transfer_experiment_fixtures import entry, experiment_request

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    os.environ.get("EOM_INFERENCE_TRANSFER_CPU_TEST") != "1",
    reason="opt-in local numerical runtime/model required; no download or corpus access",
)
def test_pinned_cpu_model_runs_three_views_once_on_synthetic_pool(tmp_path: Path) -> None:
    required = (
        "EOM_INFERENCE_TRANSFER_MODEL_STORE",
        "EOM_INFERENCE_TRANSFER_MODEL_MANIFEST",
        "EOM_INFERENCE_TRANSFER_CPU_PYTHON",
    )
    if any(not os.environ.get(name) for name in required):
        pytest.fail("opt-in CPU smoke requires explicit model store, manifest and interpreter")
    store, manifest, interpreter = (Path(os.environ[name]) for name in required)
    if any(not path.is_absolute() for path in (store, manifest, interpreter)):
        pytest.fail("opt-in CPU smoke paths must be absolute")
    if manifest.is_symlink() or manifest.stat().st_size > 128 * 1024:
        pytest.fail("bounded, nonsymlink model manifest required")
    spec = LocalEmbeddingModelSpec.model_validate_json(manifest.read_bytes())
    staged = experiment_request(
        *(entry(seed) for seed in "abcdef123"),
        top_k=4,
        minimum_common_candidates=8,
        maximum_encoded_texts=27,
        threads=4,
        batch_size=4,
    )
    body = staged.model_dump(mode="json", exclude={"request_sha256"})
    body["model_spec"] = spec.model_dump(mode="json")
    body["queries"] = [
        InferenceTransferProfilePointer.from_profile(value.profile).model_dump(mode="json")
        for value in staged.entries[:3]
    ]
    request = InferenceTransferExperimentRequest.model_validate(
        body | {"request_sha256": content_sha256(body)}
    )
    (tmp_path / "request.json").write_bytes(
        canonical_json_bytes(request.model_dump(mode="json")) + b"\n"
    )
    (tmp_path / "request.json").chmod(0o600)
    command = (
        str(interpreter),
        str(ROOT / "scripts/embedding/run_inference_transfer_experiment.py"),
        "--workspace",
        str(tmp_path),
        "--request-sha256",
        request.request_sha256,
        "--model-store",
        str(store),
        "--model-owner-uid",
        str(os.geteuid()),
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    document = json.loads((tmp_path / "result.json").read_bytes())
    result = InferenceTransferExperimentResult.model_validate(document)
    validate_experiment_result(request, result)
    assert result.status == "MEASURED"
    assert result.backend_kind == "PINNED_MODEL"
    assert result.data_provenance == "TEST_ONLY_SYNTHETIC"
    assert result.current_authorization == "NOT_VERIFIED_BY_HARNESS"
    assert result.human_transfer_review == "NOT_EVALUATED"
    assert result.production_activation == "NOT_PERFORMED"
    assert result.baseline_status == "NOT_MATERIALIZED"
    assert result.actual_model_manifest_sha256 == spec.manifest_sha256
    assert len(result.common_profiles) == 9
    assert len(result.coverage) == 27
    assert all(row.status == "ENCODABLE" for row in result.coverage)
    assert len(result.query_results) == 9
    assert all(len(row.ranks) == 4 for row in result.query_results)
    assert result.measurements.encoding_requests_started == 3
    assert result.measurements.encoding_requests_completed == 3
    assert result.measurements.encoded_text_count == 27
    assert result.measurements.requested_text_count == 27
    assert result.measurements.peak_rss_kib_linux > 0
    assert "DATA_PROVENANCE=TEST_ONLY_SYNTHETIC" in completed.stdout
    assert "HUMAN_TRANSFER_REVIEW=NOT_EVALUATED" in completed.stdout
