from __future__ import annotations

import hashlib
import inspect
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service.vector_stimulus import validate_vector_drawing_label_layout
from eom_catalog_service.workflow_catalog import _enforces_svg_label_layout
from eom_image_contracts import (
    SVG_LABEL_LAYOUT_PACK_BUNDLE_SHA256,
    SvgLabelLayoutValidationError,
    SvgLabelLayoutValidationReceipt,
    load_schema,
    validate_svg_label_layout,
)
from eom_orchestrator.orchestrator import Orchestrator
from eom_orchestrator.svg_label_layout_validation import (
    validate_image_result_svg_label_layout,
)
from eom_workflow.models import ContentTeamImageRoleResultV12, GeneratedVectorDrawingV6
from jsonschema import Draft202012Validator
from pydantic import ValidationError

_SHA = "sha256:" + "a" * 64


def _render(svg: bytes) -> bytes:
    return subprocess.run(
        ["/usr/bin/rsvg-convert", "--format=png", "--width=800", "--height=500"],
        input=svg,
        capture_output=True,
        timeout=15,
        check=True,
    ).stdout


def _validate(overlay: str, required_labels: tuple[str, ...]) -> SvgLabelLayoutValidationReceipt:
    return validate_svg_label_layout(
        overlay=overlay,
        required_labels=required_labels,
        render_svg=_render,
        renderer_version="rsvg-convert version 2.58.0",
        renderer_sha256=_SHA,
        font_manifest_sha256=_SHA,
    )


def _safe_svg(*, p_x: int = 240, q_x: int = 530) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
        'viewBox="0 0 800 500">'
        '<rect fill="#d9d9d9" height="150" stroke="#000000" stroke-width="2" '
        'width="200" x="300" y="180"></rect>'
        f'<text fill="#000000" font-family="Century Old Style" font-size="24" '
        f'x="{p_x}" y="230">P</text>'
        f'<text fill="#000000" font-family="Century Old Style" font-size="24" '
        f'x="{q_x}" y="230">Q</text>'
        "</svg>"
    )


def _drawing(overlay: str) -> GeneratedVectorDrawingV6:
    return GeneratedVectorDrawingV6(
        kind="apparatus",
        production_route="DETERMINISTIC_SVG",
        route_reason="SCIENTIFIC_SCHEMATIC",
        background_style="WHITE",
        alt_text="두 전극이 있는 장치",
        scene_description="서로 떨어진 두 전극 P와 Q가 있다.",
        scientific_constraints=("P와 Q는 서로 다른 전극이다.",),
        required_labels=("P", "Q"),
        generation_prompt=None,
        negative_prompt=None,
        width_px=800,
        height_px=500,
        svg_overlay=overlay,
    )


def _result(drawing: GeneratedVectorDrawingV6) -> ContentTeamImageRoleResultV12:
    return ContentTeamImageRoleResultV12.model_construct(
        completed_at=datetime(2026, 10, 1, tzinfo=UTC),
        output=SimpleNamespace(
            drawings=(SimpleNamespace(visual_ordinal=0, drawing=drawing),),
        ),
    )


def test_safe_label_layout_has_schema_valid_self_hashed_receipt() -> None:
    receipt = _validate(_safe_svg(), ("P", "Q"))

    Draft202012Validator(load_schema("svg-label-layout-validation-receipt")).validate(
        receipt.model_dump(mode="json")
    )
    assert tuple(label.text for label in receipt.labels) == ("P", "Q")
    assert receipt.clearance_px == 8

    changed = receipt.model_dump(mode="json")
    changed["receipt_sha256"] = "sha256:" + "b" * 64
    with pytest.raises(ValidationError):
        SvgLabelLayoutValidationReceipt.model_validate(changed)

    changed = receipt.model_dump(mode="json")
    changed["renderer_version"] = "rsvg-convert version 2.59.0"
    with pytest.raises(ValidationError):
        SvgLabelLayoutValidationReceipt.model_validate(changed)


def test_observed_p_over_conductor_is_rejected() -> None:
    overlay = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
        'viewBox="0 0 800 500">'
        '<line stroke="#000000" stroke-width="3" x1="357" x2="357" '
        'y1="155" y2="90"></line>'
        '<text fill="#000000" font-family="Century Old Style" font-size="24" '
        'x="348" y="145">P</text>'
        "</svg>"
    )

    with pytest.raises(SvgLabelLayoutValidationError) as caught:
        _validate(overlay, ("P",))
    assert caught.value.code == "SVG_LABEL_GEOMETRY_COLLISION"


def test_required_label_must_occur_exactly_once() -> None:
    duplicate = _safe_svg()[:-6] + (
        '<text fill="#000000" font-family="Century Old Style" font-size="24" '
        'x="650" y="230">P</text></svg>'
    )

    with pytest.raises(SvgLabelLayoutValidationError) as caught:
        _validate(duplicate, ("P", "Q"))
    assert caught.value.code == "SVG_REQUIRED_LABEL_CARDINALITY_INVALID"


def test_rendered_transform_and_label_to_label_clearance_are_enforced() -> None:
    transformed = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
        'viewBox="0 0 800 500"><g transform="translate(100,0)">'
        '<line stroke="#000000" stroke-width="3" x1="257" x2="257" '
        'y1="155" y2="90"></line>'
        '<text fill="#000000" font-family="Century Old Style" font-size="24" '
        'x="248" y="145">P</text></g></svg>'
    )
    with pytest.raises(SvgLabelLayoutValidationError) as transformed_error:
        _validate(transformed, ("P",))
    assert transformed_error.value.code == "SVG_LABEL_GEOMETRY_COLLISION"

    close_labels = _safe_svg(p_x=240, q_x=260)
    with pytest.raises(SvgLabelLayoutValidationError) as label_error:
        _validate(close_labels, ("P", "Q"))
    assert label_error.value.code == "SVG_LABEL_LABEL_COLLISION"


def test_label_near_canvas_edge_is_rejected() -> None:
    overlay = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
        'viewBox="0 0 800 500">'
        '<text fill="#000000" font-family="Century Old Style" font-size="24" '
        'x="1" y="24">P</text></svg>'
    )
    with pytest.raises(SvgLabelLayoutValidationError) as caught:
        _validate(overlay, ("P",))
    assert caught.value.code == "SVG_LABEL_OUT_OF_BOUNDS"


def test_vector_without_text_produces_an_empty_but_verifiable_receipt() -> None:
    overlay = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
        'viewBox="0 0 800 500"><circle cx="400" cy="250" fill="none" '
        'r="80" stroke="#000000" stroke-width="3"></circle></svg>'
    )
    receipt = _validate(overlay, ())
    assert receipt.required_labels == ()
    assert receipt.labels == ()
    Draft202012Validator(load_schema("svg-label-layout-validation-receipt")).validate(
        receipt.model_dump(mode="json")
    )


def test_uniform_light_fill_axis_label_and_korean_label_are_not_false_positives() -> None:
    overlay = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
        'viewBox="0 0 800 500">'
        '<rect fill="#d9d9d9" height="160" stroke="#000000" stroke-width="2" '
        'width="260" x="270" y="90"></rect>'
        '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" '
        'font-size="20" text-anchor="middle" x="400" y="180">용액</text>'
        '<line stroke="#000000" stroke-width="3" x1="100" x2="700" '
        'y1="400" y2="400"></line>'
        '<text fill="#000000" font-family="Century Old Style" font-size="20" '
        'text-anchor="middle" x="400" y="450">time</text>'
        "</svg>"
    )
    receipt = _validate(overlay, ("time", "용액"))
    assert tuple(label.text for label in receipt.labels) == ("time", "용액")


def test_predecessor_pack_is_not_reinterpreted_but_successor_is_enforced() -> None:
    result = _result(_drawing(_safe_svg()))
    predecessor = {"content_pack_sha256": "sha256:" + "b" * 64}
    assert (
        validate_image_result_svg_label_layout(
            result=result,
            result_schema="image-result@12.0",
            plan_document=predecessor,
        )
        == ()
    )

    receipts = validate_image_result_svg_label_layout(
        result=result,
        result_schema="image-result@12.0",
        plan_document={"content_pack_sha256": SVG_LABEL_LAYOUT_PACK_BUNDLE_SHA256},
    )
    assert len(receipts) == 1
    assert receipts[0]["visual_ordinal"] == 0


def test_orchestrator_validates_layout_before_staging_and_commits_receipt_atomically() -> None:
    source = inspect.getsource(Orchestrator.submit_workflow_role)
    validation = source.index("validate_image_result_svg_label_layout(")
    assert validation < source.index("stage_structured_artifact(")
    assert validation < source.index("commit_file_set_artifact(")
    assert validation < source.index("commit_artifact(")

    transaction = source.index("with transaction(self.sessions) as session:", validation)
    atomic_commit = source[transaction : source.index("except WorkflowSchemaError", transaction)]
    assert atomic_commit.index("create_artifact_records(") < atomic_commit.index(
        "**svg_label_layout_event_data(svg_label_layout_receipts)"
    )
    assert atomic_commit.index(
        "**svg_label_layout_event_data(svg_label_layout_receipts)"
    ) < atomic_commit.index("transition_job(")


def test_catalog_repeats_validation_only_for_exact_successor_pack_identity() -> None:
    exact = SimpleNamespace(
        runtime_context={
            "content_pack": {
                "version": "1.20.14",
                "release_sha256": SVG_LABEL_LAYOUT_PACK_BUNDLE_SHA256,
            }
        }
    )
    stale = SimpleNamespace(
        runtime_context={
            "content_pack": {
                "version": "1.20.14",
                "release_sha256": "sha256:" + "b" * 64,
            }
        }
    )
    assert _enforces_svg_label_layout(exact)
    assert not _enforces_svg_label_layout(stale)

    receipt = validate_vector_drawing_label_layout(_drawing(_safe_svg()))
    assert receipt.policy_revision == "eom-svg-label-layout/1.0"


def test_pack_successor_is_additive_and_predecessor_bytes_are_frozen() -> None:
    root = Path("content/packs/generated-knowledge-item")
    assert hashlib.sha256((root / "1.20.13/pack.yaml").read_bytes()).hexdigest() == (
        "a8ee075d8e779d313a7a3a780d026b8f53964313d310298d22f0bf182ecdb4e5"
    )
    assert (
        hashlib.sha256((root / "1.20.13/prompt-templates/image.md").read_bytes()).hexdigest()
        == "abc071da64257ff6caf8d1945420d9ec379f8e8de2dba0cfe25bc8da0a69ee51"
    )
    successor = (root / "1.20.14/prompt-templates/image.md").read_text(encoding="utf-8")
    assert "최소 8 pixel" in successor
    assert "도선·장치 외곽선" in successor
    assert "흰 사각형·halo로 충돌을 가리지 말고" in successor


def test_receipt_schema_has_byte_exact_canonical_and_packaged_mirrors() -> None:
    canonical = Path("schemas/image-provider/svg-label-layout-validation-receipt-v1.schema.json")
    packaged = Path(
        "packages/image_contracts/eom_image_contracts/schemas/"
        "svg-label-layout-validation-receipt-v1.schema.json"
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    Draft202012Validator.check_schema(load_schema("svg-label-layout-validation-receipt"))
