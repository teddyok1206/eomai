from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from eom_image_contracts import (
    LocalImageVisualReferencePointer,
    LocalImageVisualReferencePublicationReceipt,
    VisualReferenceBundleManifestPointer,
    VisualReferencePngArtifactPointer,
    content_sha256,
    text_sha256,
)
from eom_orchestrator.orchestrator import Orchestrator
from eom_orchestrator.settings import Settings
from eom_orchestrator.visual_reference_acquisition import (
    VisualReferenceCoordinatorError,
    _discovery_query_terms,
)
from eom_workflow.models import ContentTeamImageRoleResultV12, GeneratedVectorDrawingV6


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _reference_pointer() -> LocalImageVisualReferencePointer:
    return LocalImageVisualReferencePointer(
        bundle_id="imgrefbundle_" + "1" * 32,
        bundle_revision_id="imgrefbundlerev_" + "2" * 32,
        bundle_manifest=VisualReferenceBundleManifestPointer(
            artifact_id="artifact_" + "3" * 32,
            artifact_revision_id="rev_" + "4" * 32,
            sha256=_sha("5"),
            size_bytes=123,
        ),
        primary_reference_id="imgref_" + "6" * 32,
        reference_member=VisualReferencePngArtifactPointer(
            artifact_id="artifact_" + "3" * 32,
            artifact_revision_id="rev_" + "4" * 32,
            sha256=_sha("7"),
            size_bytes=456,
        ),
    )


def _drawing(*, hybrid: bool = True) -> GeneratedVectorDrawingV6:
    return GeneratedVectorDrawingV6(
        kind="natural_scene" if hybrid else "diagram",
        production_route="HYBRID_LOCAL_GENERATIVE" if hybrid else "DETERMINISTIC_SVG",
        route_reason="ORGANIC_OBJECT_REQUIRED" if hybrid else "SCIENTIFIC_SCHEMATIC",
        background_style="WHITE",
        alt_text="one compact car in side view isolated on white",
        scene_description="자동차 한 대의 옆모습",
        scientific_constraints=("자동차는 한 대이다.",),
        required_labels=(),
        generation_prompt="검토된 팀장 프롬프트" if hybrid else None,
        negative_prompt=None,
        width_px=800,
        height_px=500,
        svg_overlay=(
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
            'viewBox="0 0 800 500"><rect x="1" y="1" width="1" height="1"/></svg>'
        ),
    )


def _result(drawing: GeneratedVectorDrawingV6) -> ContentTeamImageRoleResultV12:
    return ContentTeamImageRoleResultV12.model_construct(
        completed_at=datetime(2026, 9, 27, 18, 0, tzinfo=UTC),
        output=SimpleNamespace(
            drawings=(SimpleNamespace(visual_ordinal=0, drawing=drawing),),
        ),
    )


class _Coordinator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def discover_and_acquire(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            discovery_command=SimpleNamespace(command_sha256=_sha("8")),
            discovery_result=SimpleNamespace(result_sha256=_sha("9")),
            intent=SimpleNamespace(intent_sha256=_sha("a")),
            published=SimpleNamespace(
                command=SimpleNamespace(command_sha256=_sha("b")),
                acquisition_result=SimpleNamespace(result_sha256=_sha("c")),
                pointer=_reference_pointer(),
            ),
        )


def _orchestrator(coordinator: _Coordinator | None) -> Orchestrator:
    value = object.__new__(Orchestrator)
    value.settings = Settings(runtime_source_commit="d" * 40)
    value.visual_reference_coordinator = coordinator
    return value


def test_hybrid_image_publication_binds_exact_result_and_reference() -> None:
    coordinator = _Coordinator()
    orchestrator = _orchestrator(coordinator)
    drawing = _drawing()

    event_data = orchestrator._publish_visual_references(
        result=_result(drawing),
        result_schema="image-result@12.0",
        workflow_id="workflow_" + "1" * 32,
        step_run_id="steprun_" + "2" * 32,
        job_id="job_" + "3" * 32,
        artifact_id="artifact_" + "4" * 32,
        revision_id="rev_" + "5" * 32,
        content_hash=_sha("6"),
    )

    receipt = LocalImageVisualReferencePublicationReceipt.model_validate(
        event_data["visual_reference_publication_receipt"]
    )
    assert receipt.image_result_artifact.logical_artifact_id == "artifact_" + "4" * 32
    assert receipt.image_result_artifact.revision_id == "rev_" + "5" * 32
    assert receipt.image_result_artifact.content_hash == _sha("6")
    assert receipt.entries[0].drawing_sha256 == content_sha256(drawing.model_dump(mode="json"))
    assert receipt.entries[0].subject_sha256 == text_sha256(drawing.alt_text)
    assert receipt.entries[0].visual_reference == _reference_pointer()
    assert coordinator.calls[0]["subject"] == drawing.alt_text
    assert coordinator.calls[0]["source_commit"] == "d" * 40
    replay = orchestrator._publish_visual_references(
        result=_result(drawing),
        result_schema="image-result@12.0",
        workflow_id="workflow_" + "1" * 32,
        step_run_id="steprun_" + "2" * 32,
        job_id="job_" + "3" * 32,
        artifact_id="artifact_" + "4" * 32,
        revision_id="rev_" + "5" * 32,
        content_hash=_sha("6"),
    )
    assert replay == event_data
    assert coordinator.calls[1]["observed_at"] == coordinator.calls[0]["observed_at"]


def test_nonhybrid_and_legacy_results_do_not_publish_references() -> None:
    orchestrator = _orchestrator(None)
    assert (
        orchestrator._publish_visual_references(
            result=_result(_drawing(hybrid=False)),
            result_schema="image-result@12.0",
            workflow_id="workflow_" + "1" * 32,
            step_run_id="steprun_" + "2" * 32,
            job_id="job_" + "3" * 32,
            artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
            content_hash=_sha("6"),
        )
        == {}
    )
    assert (
        orchestrator._publish_visual_references(
            result=object(),
            result_schema="image-result@11.0",
            workflow_id="workflow_" + "1" * 32,
            step_run_id="steprun_" + "2" * 32,
            job_id="job_" + "3" * 32,
            artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
            content_hash=_sha("6"),
        )
        == {}
    )


def test_hybrid_image_fails_closed_without_publication_route() -> None:
    orchestrator = _orchestrator(None)
    with pytest.raises(VisualReferenceCoordinatorError, match="VISUAL_REFERENCE_ROUTE_UNAVAILABLE"):
        orchestrator._publish_visual_references(
            result=_result(_drawing()),
            result_schema="image-result@12.0",
            workflow_id="workflow_" + "1" * 32,
            step_run_id="steprun_" + "2" * 32,
            job_id="job_" + "3" * 32,
            artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
            content_hash=_sha("6"),
        )


@pytest.mark.parametrize(
    ("subject", "expected"),
    (
        (
            "one compact passenger car in full side view with its front facing right, "
            "isolated on white",
            (
                "compact passenger car side view",
                "compact passenger car side view illustration",
            ),
        ),
        (
            "one trilobite fossil isolated on white",
            ("trilobite fossil", "trilobite fossil illustration"),
        ),
        (
            "a flower in cross-section on white",
            ("flower cross-section", "flower cross-section illustration"),
        ),
        (
            "one large front view ammonite fossil with spiral shell and chamber sutures",
            (
                "ammonite fossil front view",
                "ammonite fossil front view illustration",
            ),
        ),
    ),
)
def test_discovery_query_preserves_morphology_and_removes_presentation_clauses(
    subject: str,
    expected: tuple[str, ...],
) -> None:
    assert _discovery_query_terms(subject) == expected
