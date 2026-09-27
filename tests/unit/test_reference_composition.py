from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageReferenceCompositionEvaluation,
    LocalImageVisualReferencePointer,
    content_sha256,
    validate_contract,
)
from eom_image_provider.reference_composition import (
    ReferenceCompositionEvaluationError,
    evaluate_reference_composition,
)
from PIL import Image, ImageDraw
from pydantic import ValidationError


def _visual_reference() -> LocalImageVisualReferencePointer:
    return LocalImageVisualReferencePointer.model_validate(
        {
            "bundle_id": "imgrefbundle_" + "1" * 32,
            "bundle_revision_id": "imgrefbundlerev_" + "2" * 32,
            "bundle_manifest": {
                "artifact_id": "artifact_" + "3" * 32,
                "artifact_revision_id": "rev_" + "4" * 32,
                "member_path": "manifests/visual-reference-bundle.json",
                "schema_ref": (
                    "eom://schemas/image-provider/local-image-visual-reference-bundle/1.0"
                ),
                "media_type": "application/json",
                "sha256": "sha256:" + "5" * 64,
                "size_bytes": 2048,
            },
            "primary_reference_id": "imgref_" + "6" * 32,
            "reference_member": {
                "artifact_id": "artifact_" + "3" * 32,
                "artifact_revision_id": "rev_" + "4" * 32,
                "member_path": "references/primary.png",
                "schema_ref": "eom://schemas/image-provider/normalized-visual-reference/1.0",
                "media_type": "image/png",
                "sha256": "sha256:" + "7" * 64,
                "size_bytes": 4096,
            },
        }
    )


def _drawing(
    path: Path,
    *,
    height: int = 504,
    offset_x: int = 0,
    color: tuple[int, int, int] = (0, 0, 0),
) -> None:
    image = Image.new("RGB", (800, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (180 + offset_x, 145, 620 + offset_x, 365),
        radius=60,
        outline=color,
        width=8,
    )
    draw.ellipse(
        (245 + offset_x, 315, 335 + offset_x, 405),
        outline=color,
        width=8,
    )
    draw.ellipse(
        (470 + offset_x, 315, 560 + offset_x, 405),
        outline=color,
        width=8,
    )
    image.save(path, format="PNG", optimize=False)


def test_identical_line_art_passes_schema_and_semantic_contract(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    candidate = tmp_path / "candidate.png"
    _drawing(reference)
    _drawing(candidate, height=500)

    result = evaluate_reference_composition(
        reference_path=reference,
        candidate_path=candidate,
        visual_reference=_visual_reference(),
        source_commit="a" * 40,
        evaluated_at=datetime(2026, 9, 27, tzinfo=UTC),
    )

    assert result.outcome == "PASS"
    assert result.failure_reasons == ()
    assert result.metrics.edge_recall == 1
    validate_contract("reference-composition-evaluation", result.model_dump(mode="json"))


def test_shifted_colored_candidate_fails_closed(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    candidate = tmp_path / "candidate.png"
    _drawing(reference)
    _drawing(candidate, height=500, offset_x=100, color=(220, 20, 20))

    result = evaluate_reference_composition(
        reference_path=reference,
        candidate_path=candidate,
        visual_reference=_visual_reference(),
        source_commit="b" * 40,
        evaluated_at=datetime(2026, 9, 27, tzinfo=UTC),
    )

    assert result.outcome == "FAIL"
    assert "COLOR_REMAINS" in result.failure_reasons
    assert "CENTER_SHIFT_HIGH" in result.failure_reasons
    assert "FOREGROUND_BBOX_IOU_LOW" in result.failure_reasons


def test_semantic_contract_rejects_repaired_outcome(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    candidate = tmp_path / "candidate.png"
    _drawing(reference)
    _drawing(candidate, height=500, offset_x=100)
    result = evaluate_reference_composition(
        reference_path=reference,
        candidate_path=candidate,
        visual_reference=_visual_reference(),
        source_commit="c" * 40,
        evaluated_at=datetime(2026, 9, 27, tzinfo=UTC),
    )
    value = result.model_dump(mode="json")
    value["outcome"] = "PASS"
    value["failure_reasons"] = []
    value["evaluation_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "evaluation_sha256"}
    )

    with pytest.raises(ValidationError, match="failure reasons differ"):
        LocalImageReferenceCompositionEvaluation.model_validate(value)


def test_evaluator_rejects_symlinked_input(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    candidate = tmp_path / "candidate.png"
    _drawing(reference)
    _drawing(candidate, height=500)
    linked = tmp_path / "linked.png"
    linked.symlink_to(reference)

    with pytest.raises(ReferenceCompositionEvaluationError) as error:
        evaluate_reference_composition(
            reference_path=linked,
            candidate_path=candidate,
            visual_reference=_visual_reference(),
            source_commit="d" * 40,
        )

    assert error.value.code == "IMAGE_COMPOSITION_INPUT_INVALID"
