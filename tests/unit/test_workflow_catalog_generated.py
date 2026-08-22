from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identifiers import sha256_file
from eom_workflow import ArtifactPointer, WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord

WORKFLOW_ID = "workflow_" + "1" * 32


def _pointer(step: str, marker: str, schema: str) -> ArtifactPointer:
    return ArtifactPointer(
        step_key=step,
        attempt=1,
        job_id="job_" + marker * 32,
        logical_artifact_id="artifact_" + marker * 32,
        revision_id="rev_" + marker * 32,
        content_hash="sha256:" + marker * 64,
        result_schema=schema,
    )


AUTHORING = _pointer("authoring", "a", "authoring-result@3.0")
IMAGE = _pointer("image", "b", "image-result@3.0")


def _image_brief() -> dict[str, object]:
    return {
        "kind": "line_graph",
        "block_id": "block_image",
        "alt_text": "시간에 따라 거리가 일정하게 증가하는 선그래프",
        "x_axis_label": "time(s)",
        "y_axis_label": "distance(m)",
        "series_label": "object-A",
        "x_values": [1, 2, 3],
        "y_values": [5, 10, 15],
    }


def _authoring_result() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.2.0",
        "job_id": AUTHORING.job_id,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": "steprun_" + "c" * 32,
        "role": "authoring",
        "status": "ok",
        "artifact": {
            "logical_artifact_id": AUTHORING.logical_artifact_id,
            "revision_id": AUTHORING.revision_id,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "output": {
            "draft": {
                "schema_version": "1.0",
                "locale": "ko-KR",
                "title": "등속 운동 자료 해석",
                "stem": {
                    "block_id": "block_stem",
                    "type": "paragraph",
                    "purpose": "stem",
                    "text": "다음 자료를 보고 물음에 답하시오.",
                },
                "data_table": {
                    "block_id": "block_data",
                    "type": "table",
                    "purpose": "data",
                    "caption": "측정 결과",
                    "headers": ["시간", "거리", "속력"],
                    "rows": [["2", "10", "5"]],
                },
                "image_brief": _image_brief(),
                "equation": {
                    "block_id": "block_equation",
                    "type": "equation",
                    "purpose": "stimulus",
                    "notation": "hancom-equation-script",
                    "source": "v=d/t",
                },
                "prompt": {
                    "block_id": "block_prompt",
                    "type": "paragraph",
                    "purpose": "prompt",
                    "text": "옳은 것만을 고른 것은?",
                },
                "statements": {
                    "block_id": "block_claims",
                    "type": "statement_set",
                    "purpose": "claims",
                    "statements": [
                        {"statement_id": "statement_g", "label": "ㄱ", "text": "속력은 5이다."},
                        {
                            "statement_id": "statement_n",
                            "label": "ㄴ",
                            "text": "거리는 시간에 비례한다.",
                        },
                        {
                            "statement_id": "statement_d",
                            "label": "ㄷ",
                            "text": "시간이 4이면 거리는 20이다.",
                        },
                    ],
                },
                "interaction": {
                    "type": "single_choice",
                    "choices": [
                        {"choice_id": "choice_1", "label": "1", "text": "ㄱ"},
                        {"choice_id": "choice_2", "label": "2", "text": "ㄴ"},
                        {"choice_id": "choice_3", "label": "3", "text": "ㄱ, ㄴ"},
                        {"choice_id": "choice_4", "label": "4", "text": "ㄴ, ㄷ"},
                        {"choice_id": "choice_5", "label": "5", "text": "ㄱ, ㄴ, ㄷ"},
                    ],
                },
                "solution": {
                    "correct_choice_ids": ["choice_5"],
                    "accepted_answers": [],
                    "explanation": "거리와 시간의 비가 5로 일정하다.",
                    "authoring_intent": "비례 관계와 속력의 의미를 평가한다.",
                    "statement_explanations": [
                        {"statement_id": "statement_g", "text": "10/2=5이므로 옳다."},
                        {"statement_id": "statement_n", "text": "속력이 일정하므로 옳다."},
                        {"statement_id": "statement_d", "text": "5*4=20이므로 옳다."},
                    ],
                },
                "score": {"points": 3},
            },
            "metadata": {
                "subject": "일반 과학",
                "topic": "등속 운동",
                "difficulty": "medium",
                "knowledge_source_mode": "general_model_knowledge",
            },
        },
        "completed_at": "2026-08-22T00:00:00Z",
    }


def _image_result(*, changed_y: bool = False) -> dict[str, object]:
    drawing = {
        **_image_brief(),
        "width_px": 800,
        "height_px": 500,
        "stroke_color": "blue",
        "point_style": "circle",
    }
    if changed_y:
        drawing["y_values"] = [5, 11, 15]
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.2.0",
        "job_id": IMAGE.job_id,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": "steprun_" + "d" * 32,
        "role": "image",
        "status": "ok",
        "artifact": {
            "logical_artifact_id": IMAGE.logical_artifact_id,
            "revision_id": IMAGE.revision_id,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "output": {"drawing": drawing, "summary": "문항 자료에 맞는 선그래프를 설계했다."},
        "completed_at": "2026-08-22T00:00:01Z",
    }


class _Artifacts:
    def __init__(self, *, changed_y: bool = False) -> None:
        self.values = {
            AUTHORING.revision_id: _authoring_result(),
            IMAGE.revision_id: _image_result(changed_y=changed_y),
        }
        self.commits: list[dict[str, Any]] = []
        self.verified: list[dict[str, str]] = []

    def load_json_revision(self, **pointer: str | int) -> dict[str, Any]:
        return cast(dict[str, Any], self.values[str(pointer["revision_id"])])

    def commit_file_set(self, **values: Any) -> SimpleNamespace:
        self.commits.append(values)
        primary = Path(values["files"][values["primary_file"]])
        marker = str(len(self.commits))
        return SimpleNamespace(
            artifact_id="artifact_" + marker * 32,
            revision_id="rev_" + marker * 32,
            content_hash=sha256_file(primary),
        )

    def verify_file_pointer(self, **pointer: str) -> None:
        self.verified.append(pointer)


def _settings(tmp_path: Path) -> CatalogSettings:
    staging = tmp_path / "catalog"
    registry = staging / "registry"
    staging.mkdir(mode=0o750)
    registry.mkdir(mode=0o750)
    staging.chmod(0o750)
    registry.chmod(0o750)
    return CatalogSettings(staging_root=staging, nas_artifact_root=tmp_path / "nas")


def _service(
    tmp_path: Path, *, changed_y: bool = False
) -> tuple[WorkflowCatalogService, _Artifacts]:
    service = object.__new__(WorkflowCatalogService)
    artifacts = _Artifacts(changed_y=changed_y)
    service.settings = _settings(tmp_path)
    service.artifacts = cast(Any, artifacts)
    return service, artifacts


def _workflow(runtime_context: dict[str, object] | None = None) -> WorkflowInstanceRecord:
    return cast(
        WorkflowInstanceRecord,
        SimpleNamespace(workflow_id=WORKFLOW_ID, runtime_context=runtime_context or {}),
    )


def _request() -> WorkflowRequest:
    return WorkflowRequest.model_validate(
        {
            "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
            "image_mode": "required",
            "content_pack": {"pack_key": "generated-knowledge-item", "environment": "test"},
            "profiles": {
                "authoring": "generated-knowledge-authoring",
                "review": "generated-knowledge-review",
                "image": "generated-stimulus-drawing",
                "registration": "generated-structured-registration",
            },
            "source_intake": {"batch_ids": []},
            "registry_intent": {"mode": "CREATE_ITEM"},
            "item_brief": {
                "subject": "일반 과학",
                "topic": "등속 운동",
                "task_type": "data_interpretation",
                "difficulty": "medium",
                "quality_profile": "balanced",
                "original_request_sha256": "e" * 64,
            },
        }
    )


def test_image_role_materializes_one_pinned_png_without_payload_in_result(tmp_path: Path) -> None:
    service, artifacts = _service(tmp_path)
    pointer = service.materialize_generated_stimulus(
        workflow=_workflow(), artifacts=(AUTHORING, IMAGE)
    )

    assert pointer.source_result_revision_id == IMAGE.revision_id
    assert pointer.media_type == "image/png"
    assert (pointer.width_px, pointer.height_px) == (800, 500)
    assert len(artifacts.commits) == 1
    commit = artifacts.commits[0]
    assert commit["artifact_type"] == "generated-item-stimulus"
    assert commit["primary_file"] == "generated-stimulus.png"
    assert set(commit["result"]) == {"drawing_sha256"}
    assert "png" not in json.dumps(_image_result()).casefold()


def test_image_role_cannot_change_the_authoring_drawing_contract(tmp_path: Path) -> None:
    service, artifacts = _service(tmp_path, changed_y=True)
    with pytest.raises(ValueError, match="changed the authoring image brief"):
        service.materialize_generated_stimulus(workflow=_workflow(), artifacts=(AUTHORING, IMAGE))
    assert artifacts.commits == []


def test_generated_item_pins_verified_media_revision_in_canonical_content(tmp_path: Path) -> None:
    service, artifacts = _service(tmp_path)
    media = service.materialize_generated_stimulus(
        workflow=_workflow(), artifacts=(AUTHORING, IMAGE)
    )
    workflow = _workflow({"generated_stimulus": media.as_dict()})

    component = service._generated_knowledge_item_content(workflow, _request(), (AUTHORING, IMAGE))

    assert component.component_type == "ITEM_CONTENT"
    assert artifacts.verified == [
        {
            "artifact_id": media.artifact_id,
            "revision_id": media.artifact_revision_id,
            "content_hash": media.sha256,
            "member": media.artifact_member,
        }
    ]
    content_commit = artifacts.commits[1]
    content = json.loads(
        Path(content_commit["files"]["assessment-item-content.json"]).read_text(encoding="utf-8")
    )
    image = content["body"][2]
    assert image["type"] == "image"
    assert image["artifact"]["artifact_revision_id"] == media.artifact_revision_id
    assert image["artifact"]["sha256"] == media.sha256


def test_generated_item_rejects_a_stale_materialized_image_pointer(tmp_path: Path) -> None:
    service, artifacts = _service(tmp_path)
    media = service.materialize_generated_stimulus(
        workflow=_workflow(), artifacts=(AUTHORING, IMAGE)
    ).as_dict()
    media["source_result_revision_id"] = "rev_" + "f" * 32
    with pytest.raises(ValueError, match="missing or stale"):
        service._generated_knowledge_item_content(
            _workflow({"generated_stimulus": media}), _request(), (AUTHORING, IMAGE)
        )
    assert len(artifacts.commits) == 1
