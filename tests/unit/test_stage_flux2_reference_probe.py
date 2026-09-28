from __future__ import annotations

import hashlib
import json
import struct
import sys
from typing import Any

import pytest
from eom_image_contracts import ImageEvaluationArtifactMember, LocalImageModelCandidateManifest

from scripts.image_candidate import stage_reference_probe
from tests.unit.test_flux2_reference_probe_contracts import _manifest_value


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 800, 504)


class _Engine:
    disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_stage_preflight_is_read_only_and_checks_all_cases(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = LocalImageModelCandidateManifest.model_validate(_manifest_value())
    payload = _png()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    metrics = {
        "source_foreground_ratio": 0.02,
        "conditioning_foreground_ratio": 0.03,
        "border_foreground_ratio": 0.0,
        "source_edge_density": 0.01,
        "conditioning_edge_density": 0.02,
        "edge_density_ratio": 2.0,
    }
    cases: list[dict[str, Any]] = []
    for key in stage_reference_probe.CASES:
        cases.append(
            {
                "case_id": key,
                "source_path": (
                    "/mnt/nas/eom/artifacts/artifact_"
                    + "11" * 16
                    + "/rev_"
                    + "22" * 16
                    + "/crops/imgsciviscandidate_"
                    + "33" * 16
                    + ".png"
                ),
                "source_sha256": "sha256:" + "44" * 32,
                "normalized_sha256": digest,
                "conditioning_sha256": digest,
                "metrics": metrics,
            }
        )
    fixture = {"cases": cases}
    engine = _Engine()
    resolved: list[str] = []
    monkeypatch.setattr(stage_reference_probe, "_require_release", lambda _commit: None)
    monkeypatch.setattr(
        stage_reference_probe,
        "_load_manifest",
        lambda: (manifest, b"manifest"),
    )
    monkeypatch.setattr(stage_reference_probe, "_load_fixture", lambda: (fixture, b"fixture"))
    monkeypatch.setattr(stage_reference_probe, "build_engine", lambda: engine)
    monkeypatch.setattr(stage_reference_probe, "_read", lambda *_args, **_kwargs: payload)

    def resolve(_engine: object, case: dict[str, object]) -> ImageEvaluationArtifactMember:
        resolved.append(str(case["case_id"]))
        return ImageEvaluationArtifactMember(
            artifact_id="artifact_" + "11" * 16,
            artifact_revision_id="rev_" + "22" * 16,
            member_path="crops/imgsciviscandidate_" + "33" * 16 + ".png",
            schema_ref=stage_reference_probe.SOURCE_CROP_SCHEMA_REF,
            media_type="image/png",
            sha256="sha256:" + "44" * 32,
        )

    monkeypatch.setattr(stage_reference_probe, "_source_pointer", resolve)
    monkeypatch.setattr(
        stage_reference_probe,
        "ControlFileSetPublisher",
        lambda *_args, **_kwargs: pytest.fail("preflight attempted publication"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["stage_reference_probe.py", "--source-commit", "a" * 40, "--preflight-only"],
    )

    assert stage_reference_probe.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PREFLIGHT_PASS"
    assert result["case_count"] == 3
    assert sorted(resolved) == sorted(stage_reference_probe.CASES)
    assert engine.disposed is True


def test_stage_png_probe_parses_canvas_and_rejects_invalid_header() -> None:
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 801, 504)

    assert stage_reference_probe._png_dimensions(payload) == (801, 504)
    with pytest.raises(stage_reference_probe.Flux2ProbeStageError):
        stage_reference_probe._png_dimensions(b"not-a-png")


def test_flux2_probe_prompts_keep_reference_crop_as_layout_constraint() -> None:
    assert stage_reference_probe.INPUT_PUBLICATION_SOURCE_COMMIT == (
        "54408b28cf5c587a95efeb4b78a62cb11d8548ef"
    )
    assert "strict layout constraint" in stage_reference_probe.STYLE_PREFIX
    assert "keep it cropped" in stage_reference_probe.STYLE_PREFIX
    assert "never complete hidden portions" in stage_reference_probe.STYLE_PREFIX
    assert "do not complete the vehicle" in stage_reference_probe.CASES["car"][1]
    assert "no flowers" in stage_reference_probe.CASES["plant"][1]
    assert "without inventing anatomy" in stage_reference_probe.CASES["fossil"][1]
