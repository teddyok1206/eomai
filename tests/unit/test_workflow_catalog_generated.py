from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.vector_stimulus import RenderedVectorStimulus
from eom_catalog_service.workflow_catalog import (
    ROLE_BY_RESULT_SCHEMA,
    WorkflowCatalogService,
    _validate_generated_vector_artifact_manifest,
)
from eom_hwpx_contracts import ContentTeamImageSlot
from eom_identifiers import content_sha256, sha256_file
from eom_workflow import ArtifactPointer, WorkflowRequest
from eom_workflow.models import CONTENT_TEAM_ILLUSTRATION_PROMPT_PREFIX
from eom_workflow.schemas import ROLE_ALLOWED_RESULT_SCHEMAS
from eom_workflow_runner.models import WorkflowInstanceRecord

WORKFLOW_ID = "workflow_" + "1" * 32
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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
AUTHORING_V4 = _pointer("authoring", "e", "authoring-result@4.0")
IMAGE_V4 = _pointer("image", "f", "image-result@4.0")
AUTHORING_V5 = _pointer("authoring", "6", "authoring-result@5.0")
IMAGE_V5 = _pointer("image", "7", "image-result@5.0")
AUTHORING_V6 = _pointer("authoring", "9", "authoring-result@6.0")
IMAGE_V6 = _pointer("image", "4", "image-result@6.0")
AUTHORING_V8 = _pointer("authoring", "2", "authoring-result@8.0")
IMAGE_V8 = _pointer("image", "3", "image-result@8.0")


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


def _authoring_result_v4() -> dict[str, object]:
    result = json.loads(json.dumps(_authoring_result()))
    result["protocol_version"] = "workflow-role/1.3.0"
    result["job_id"] = AUTHORING_V4.job_id
    result["artifact"]["logical_artifact_id"] = AUTHORING_V4.logical_artifact_id
    result["artifact"]["revision_id"] = AUTHORING_V4.revision_id
    return cast(dict[str, object], result)


def _image_result_v4() -> dict[str, object]:
    result = json.loads(json.dumps(_image_result()))
    result["protocol_version"] = "workflow-role/1.3.0"
    result["job_id"] = IMAGE_V4.job_id
    result["artifact"]["logical_artifact_id"] = IMAGE_V4.logical_artifact_id
    result["artifact"]["revision_id"] = IMAGE_V4.revision_id
    return cast(dict[str, object], result)


def _vector_brief_v5(*, route: str = "DETERMINISTIC_SVG") -> dict[str, object]:
    return {
        "kind": "apparatus",
        "production_route": route,
        "background_style": "WHITE",
        "block_id": "block_image",
        "alt_text": "비커와 온도계를 사용한 가열 실험 장치",
        "scene_description": "비커 안 액체에 온도계를 담그고 아래에서 가열한다.",
        "scientific_constraints": ["온도계 구부가 비커 바닥에 닿지 않는다."],
        "required_labels": ["온도계", "비커"],
        "generation_prompt": "교과서형 흑백 선화 실험 장치를 그린다.",
        "negative_prompt": None,
    }


def _authoring_result_v5(*, route: str = "DETERMINISTIC_SVG") -> dict[str, object]:
    result = json.loads(json.dumps(_authoring_result_v4()))
    result["protocol_version"] = "workflow-role/1.12.0"
    result["job_id"] = AUTHORING_V5.job_id
    result["artifact"]["logical_artifact_id"] = AUTHORING_V5.logical_artifact_id
    result["artifact"]["revision_id"] = AUTHORING_V5.revision_id
    result["output"]["draft"]["image_brief"] = _vector_brief_v5(route=route)
    return cast(dict[str, object], result)


def _image_result_v5(*, route: str = "DETERMINISTIC_SVG") -> dict[str, object]:
    drawing = {
        **_vector_brief_v5(route=route),
        "width_px": 800,
        "height_px": 500,
        "svg_overlay": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
            'viewBox="0 0 800 500">'
            '<rect fill="none" height="220" stroke="#000000" stroke-width="4" '
            'width="280" x="270" y="170"></rect>'
            '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20" '
            'x="445" y="100">온도계</text>'
            '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20" '
            'x="360" y="430">비커</text>'
            "</svg>"
        ),
    }
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.12.0",
        "job_id": IMAGE_V5.job_id,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": "steprun_" + "8" * 32,
        "role": "image",
        "status": "ok",
        "artifact": {
            "logical_artifact_id": IMAGE_V5.logical_artifact_id,
            "revision_id": IMAGE_V5.revision_id,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "output": {"drawing": drawing, "summary": "과학 제약에 맞는 SVG 장치를 설계했다."},
        "completed_at": "2026-08-28T00:00:01Z",
    }


def _vector_brief_v6(*, hybrid: bool = False) -> dict[str, object]:
    return {
        "kind": "natural_scene" if hybrid else "apparatus",
        "production_route": "HYBRID_LOCAL_GENERATIVE" if hybrid else "DETERMINISTIC_SVG",
        "route_reason": "HUMAN_OR_ANIMAL_REQUIRED" if hybrid else "SCIENTIFIC_SCHEMATIC",
        "background_style": "WHITE",
        "block_id": "block_image",
        "alt_text": "학생이 비커와 온도계를 사용해 가열 실험을 관찰한다.",
        "scene_description": "학생과 비커, 온도계가 있는 실험 장면이다.",
        "scientific_constraints": ["온도계 구부가 비커 바닥에 닿지 않는다."],
        "required_labels": ["온도계", "비커"],
        "generation_prompt": "비커를 관찰하는 학생 한 명" if hybrid else None,
        "negative_prompt": "추가 인물" if hybrid else None,
    }


def _authoring_result_v6(*, hybrid: bool = False) -> dict[str, object]:
    result = json.loads(json.dumps(_authoring_result_v4()))
    result["protocol_version"] = "workflow-role/1.13.0"
    result["job_id"] = AUTHORING_V6.job_id
    result["artifact"]["logical_artifact_id"] = AUTHORING_V6.logical_artifact_id
    result["artifact"]["revision_id"] = AUTHORING_V6.revision_id
    result["output"]["draft"]["image_brief"] = _vector_brief_v6(hybrid=hybrid)
    return cast(dict[str, object], result)


def _image_result_v6(*, hybrid: bool = False) -> dict[str, object]:
    drawing = {
        **_vector_brief_v6(hybrid=hybrid),
        "width_px": 800,
        "height_px": 500,
        "svg_overlay": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
            'viewBox="0 0 800 500">'
            '<rect fill="none" height="220" stroke="#000000" stroke-width="4" '
            'width="280" x="270" y="170"></rect>'
            '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20" '
            'x="445" y="100">온도계</text>'
            '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20" '
            'x="360" y="430">비커</text>'
            "</svg>"
        ),
    }
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.13.0",
        "job_id": IMAGE_V6.job_id,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": "steprun_" + "5" * 32,
        "role": "image",
        "status": "ok",
        "artifact": {
            "logical_artifact_id": IMAGE_V6.logical_artifact_id,
            "revision_id": IMAGE_V6.revision_id,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "output": {"drawing": drawing, "summary": "검토된 이미지 계획에 맞는 SVG를 설계했다."},
        "completed_at": "2026-09-01T00:00:01Z",
    }


def _content_team_authoring_result_v8(*, image_count: int = 2) -> dict[str, object]:
    labels = ("(가)", "(나)")[:image_count]
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.17.0",
        "job_id": AUTHORING_V8.job_id,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": "steprun_" + "2" * 32,
        "role": "authoring",
        "status": "ok",
        "artifact": {
            "logical_artifact_id": AUTHORING_V8.logical_artifact_id,
            "revision_id": AUTHORING_V8.revision_id,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "output": {
            "draft": {
                "schema_version": "2.0",
                "renderer_profile": "content-team-hwp-question-editor-v1",
                "authoring_prompt_sha256": (
                    "sha256:62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435"
                ),
                "handoff_archive_sha256": (
                    "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91"
                ),
                "item_number": 11,
                "score_display": "2.5",
                "stem": "제시된 정보를 해석하여 물음에 답하시오.",
                "bottom_stem": "옳은 것만을 있는 대로 고른 것은?",
                "inquiry": None,
                "labeled_blocks": [],
                "visuals": [
                    ContentTeamImageSlot(label=label).model_dump(mode="json") for label in labels
                ],
                "visual_layout": "NONE"
                if image_count == 0
                else ("IMAGE_ONLY" if image_count == 1 else "IMAGE_IMAGE"),
                "statements": [
                    {"label": "ㄱ", "text": "첫째 진술은 자료와 일치한다."},
                    {"label": "ㄴ", "text": "둘째 진술은 자료와 일치하지 않는다."},
                    {"label": "ㄷ", "text": "셋째 진술은 자료와 일치한다."},
                ],
                "choices": [
                    {"number": "①", "text": "ㄱ"},
                    {"number": "②", "text": "ㄴ"},
                    {"number": "③", "text": "ㄱ, ㄷ"},
                    {"number": "④", "text": "ㄴ, ㄷ"},
                    {"number": "⑤", "text": "ㄱ, ㄴ, ㄷ"},
                ],
                "answer": {
                    "answer_kind": "STATEMENT_COMBINATION",
                    "number": "③",
                    "statement_labels": ["ㄱ", "ㄷ"],
                    "answer_content": "ㄱ, ㄷ",
                    "raw_line": "정답 : ③ (ㄱ, ㄷ)",
                },
                "explanations": {
                    "authoring_intent": "제시된 정보의 관계를 해석한다.",
                    "concept_source": "요청에 고정된 교육과정 근거를 사용한다.",
                    "correct_answer": "ㄱ. 자료와 일치한다.\nㄷ. 자료와 일치한다.",
                    "wrong_answer": "ㄴ. 자료와 일치하지 않는다.",
                },
                "equation_sources": [],
            },
            "metadata": {
                "subject": "통합과학",
                "topic": "요청으로 정해지는 주제",
                "difficulty": "medium",
                "knowledge_source_mode": "general_model_knowledge",
            },
        },
        "completed_at": "2026-09-05T00:00:00Z",
    }


def _content_team_image_result_v8() -> dict[str, object]:
    drawing = _image_result_v6()["output"]["drawing"]
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.17.0",
        "job_id": IMAGE_V8.job_id,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": "steprun_" + "3" * 32,
        "role": "image",
        "status": "ok",
        "artifact": {
            "logical_artifact_id": IMAGE_V8.logical_artifact_id,
            "revision_id": IMAGE_V8.revision_id,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "output": {
            "drawings": [
                {
                    "visual_ordinal": ordinal,
                    "label": label,
                    "illustration_prompt": (
                        CONTENT_TEAM_ILLUSTRATION_PROMPT_PREFIX
                        + f"\n{label} 슬롯에 필요한 교과서형 그림을 그린다."
                    ),
                    "drawing": drawing,
                }
                for ordinal, label in enumerate(("(가)", "(나)"))
            ],
            "summary": "팀장 프롬프트가 선택한 두 그림 슬롯을 보존했다.",
        },
        "completed_at": "2026-09-05T00:00:01Z",
    }


class _Artifacts:
    def __init__(self, *, changed_y: bool = False) -> None:
        self.values = {
            AUTHORING.revision_id: _authoring_result(),
            IMAGE.revision_id: _image_result(changed_y=changed_y),
            AUTHORING_V4.revision_id: _authoring_result_v4(),
            IMAGE_V4.revision_id: _image_result_v4(),
            AUTHORING_V5.revision_id: _authoring_result_v5(),
            IMAGE_V5.revision_id: _image_result_v5(),
            AUTHORING_V6.revision_id: _authoring_result_v6(),
            IMAGE_V6.revision_id: _image_result_v6(),
            AUTHORING_V8.revision_id: _content_team_authoring_result_v8(),
            IMAGE_V8.revision_id: _content_team_image_result_v8(),
        }
        self.commits: list[dict[str, Any]] = []
        self.verified: list[dict[str, str]] = []

    def load_json_revision(self, **pointer: str | int) -> dict[str, Any]:
        return cast(dict[str, Any], self.values[str(pointer["revision_id"])])

    def commit_file_set(self, **values: Any) -> SimpleNamespace:
        self.commits.append(values)
        primary = Path(values["files"][values["primary_file"]])
        marker = str(len(self.commits))
        metadata = values.get("file_metadata") or {}
        assert set(metadata) in (set(), set(values["files"]))
        assert all(
            set(member_metadata) == {"schema_ref", "media_type"}
            for member_metadata in metadata.values()
        )
        manifest = {
            "manifest_version": values.get("manifest_version", "catalog-file-set/1.0"),
            "primary_file": values["primary_file"],
            "files": [
                {
                    "file_name": name,
                    "sha256": sha256_file(Path(source)),
                    "bytes": Path(source).stat().st_size,
                    **metadata.get(name, {}),
                }
                for name, source in sorted(values["files"].items())
            ],
        }
        return SimpleNamespace(
            artifact_id="artifact_" + marker * 32,
            revision_id="rev_" + marker * 32,
            content_hash=sha256_file(primary),
            manifest=manifest,
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


def test_content_team_v8_materializes_each_declared_image_as_one_pinned_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, artifacts = _service(tmp_path)
    svg = tmp_path / "content-team.svg"
    png = tmp_path / "content-team.png"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>\n', encoding="utf-8")
    png.write_bytes(b"content-team-png")

    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.render_generated_vector_stimulus",
        lambda *_args, **_kwargs: RenderedVectorStimulus(
            svg,
            png,
            "eom-safe-svg-compositor/1.1",
            "rsvg-convert version 2.58.0",
            "sha256:" + "a" * 64,
            "sha256:" + "b" * 64,
            "sha256:" + "c" * 64,
        ),
    )

    assert service.content_team_image_slot_count(workflow=_workflow(), authoring=AUTHORING_V8) == 2
    pointers = service.materialize_content_team_stimuli(
        workflow=_workflow(), artifacts=(AUTHORING_V8, IMAGE_V8)
    )
    components = service._content_team_image_components(
        _workflow({"content_team_stimuli": [pointer.as_dict() for pointer in pointers]}),
        (AUTHORING_V8, IMAGE_V8),
    )

    assert [(pointer.visual_ordinal, pointer.label) for pointer in pointers] == [
        (0, "(가)"),
        (1, "(나)"),
    ]
    assert len(artifacts.commits) == 2
    assert all(commit["artifact_type"] == "generated-item-stimulus" for commit in artifacts.commits)
    assert all("illustration_prompt" not in commit["result"] for commit in artifacts.commits)
    assert [(component.component_type, component.ordinal) for component in components] == [
        ("IMAGE", 0),
        ("IMAGE", 1),
    ]
    assert [entry["member"] for entry in artifacts.verified] == [
        "generated-stimulus.png",
        "generated-stimulus.png",
    ]


def test_content_team_v8_zero_image_decision_never_materializes_an_artifact(
    tmp_path: Path,
) -> None:
    service, artifacts = _service(tmp_path)
    artifacts.values[AUTHORING_V8.revision_id] = _content_team_authoring_result_v8(image_count=0)

    assert service.content_team_image_slot_count(workflow=_workflow(), authoring=AUTHORING_V8) == 0
    assert service._content_team_image_components(_workflow(), (AUTHORING_V8,)) == ()
    assert artifacts.commits == []


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
    assert content_commit["file_metadata"] == {
        "assessment-item-content.json": {
            "media_type": "application/json",
            "schema_ref": "eom.assessment.item-content/1.0",
        }
    }
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


def test_v4_generated_results_materialize_and_assemble_canonical_content(tmp_path: Path) -> None:
    service, artifacts = _service(tmp_path)
    media = service.materialize_generated_stimulus(
        workflow=_workflow(), artifacts=(AUTHORING_V4, IMAGE_V4)
    )
    workflow = _workflow({"generated_stimulus": media.as_dict()})

    component = service._generated_knowledge_item_content(
        workflow, _request(), (AUTHORING_V4, IMAGE_V4)
    )

    assert component.component_type == "ITEM_CONTENT"
    assert len(artifacts.commits) == 2
    assert artifacts.verified[0]["revision_id"] == media.artifact_revision_id


def test_generated_result_schema_families_cannot_be_mixed(tmp_path: Path) -> None:
    service, artifacts = _service(tmp_path)

    with pytest.raises(ValueError, match="schema versions are mixed"):
        service.materialize_generated_stimulus(
            workflow=_workflow(), artifacts=(AUTHORING, IMAGE_V4)
        )

    assert artifacts.commits == []


def test_v5_generated_result_commits_svg_and_png_together_before_item_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, artifacts = _service(tmp_path)
    svg = tmp_path / "rendered.svg"
    png = tmp_path / "rendered.png"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>\n', encoding="utf-8")
    png.write_bytes(b"bounded-png-fixture")

    def render(*_args: object, **_kwargs: object) -> RenderedVectorStimulus:
        return RenderedVectorStimulus(
            svg,
            png,
            "eom-safe-svg-compositor/1.1",
            "rsvg-convert version 2.58.0",
            "sha256:" + "a" * 64,
            "sha256:" + "b" * 64,
            "sha256:" + "c" * 64,
        )

    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.render_generated_vector_stimulus",
        render,
    )
    media = service.materialize_generated_stimulus(
        workflow=_workflow(), artifacts=(AUTHORING_V5, IMAGE_V5)
    )
    workflow = _workflow({"generated_stimulus": media.as_dict()})
    component = service._generated_knowledge_item_content(
        workflow, _request(), (AUTHORING_V5, IMAGE_V5)
    )

    assert component.component_type == "ITEM_CONTENT"
    stimulus = artifacts.commits[0]
    assert stimulus["primary_file"] == "generated-stimulus.png"
    assert set(stimulus["files"]) == {"generated-stimulus.png", "generated-stimulus.svg"}
    assert stimulus["result"]["renderer_contract"] == "eom-safe-svg-compositor/1.1"
    assert stimulus["result"]["renderer_version"] == "rsvg-convert version 2.58.0"
    assert stimulus["result"]["renderer_sha256"] == "sha256:" + "a" * 64
    assert stimulus["result"]["font_family"] == "SM JGothic Std, Noto Sans CJK KR"
    assert stimulus["result"]["font_sha256"] == "sha256:" + "b" * 64
    assert stimulus["result"]["font_profile"] == "eom-content-team-diagram-fonts/1.0"
    assert stimulus["result"]["font_manifest_sha256"] == "sha256:" + "c" * 64
    assert stimulus["result"]["font_families"] == [
        "Century Old Style",
        "DejaVu Serif",
        "Droid Sans Fallback",
        "SM JGothic Std, Noto Sans CJK KR",
    ]
    assert stimulus["result"]["production_route"] == "DETERMINISTIC_SVG"
    assert stimulus["manifest_version"] == "generated-item-stimulus-file-set/2.0"
    assert stimulus["idempotency_key"].startswith(
        f"generated-stimulus:{WORKFLOW_ID}:{IMAGE_V5.revision_id}:eom-safe-svg-compositor/1.1:"
    )
    assert stimulus["expected_file_sha256"] == {
        name: sha256_file(Path(source)) for name, source in stimulus["files"].items()
    }
    assert stimulus["file_metadata"] == {
        "generated-stimulus.png": {
            "schema_ref": "eom://schemas/generated-item/stimulus-png/2.0",
            "media_type": "image/png",
        },
        "generated-stimulus.svg": {
            "schema_ref": "eom://schemas/generated-item/stimulus-svg/2.0",
            "media_type": "image/svg+xml",
        },
    }


def test_v5_local_background_commits_one_pinned_four_member_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, artifacts = _service(tmp_path)
    artifacts.values[AUTHORING_V5.revision_id] = _authoring_result_v5(
        route="LOCAL_GENERATIVE_BACKGROUND"
    )
    artifacts.values[IMAGE_V5.revision_id] = _image_result_v5(route="LOCAL_GENERATIVE_BACKGROUND")
    service.local_image = cast(Any, object())
    svg = tmp_path / "rendered.svg"
    background = tmp_path / "background.png"
    png = tmp_path / "rendered.png"
    receipt_file = tmp_path / "receipt.json"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>\n', encoding="utf-8")
    background.write_bytes(b"bounded-background-fixture")
    png.write_bytes(b"bounded-final-fixture")
    receipt_file.write_text("{}\n", encoding="utf-8")
    binding = json.loads(
        (REPOSITORY_ROOT / "config/local-image-provider.ssd1b.json").read_text(encoding="utf-8")
    )
    receipt = SimpleNamespace(
        receipt_sha256="sha256:" + "1" * 64,
        generation=SimpleNamespace(
            output=SimpleNamespace(sha256=sha256_file(background)),
            model=SimpleNamespace(model_dump=lambda **_kwargs: binding["model"]),
            runtime=SimpleNamespace(
                model_dump=lambda **_kwargs: {"provider_version": "eom-local-image-provider/1.0"}
            ),
        ),
        compositor=SimpleNamespace(
            model_dump=lambda **_kwargs: {
                "contract": "eom-local-image-compositor/1.0",
                "pillow_version": "11.3.0",
            }
        ),
    )

    def render(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            svg_path=svg,
            background_path=background,
            png_path=png,
            receipt_path=receipt_file,
            receipt=receipt,
            request_sha256="sha256:" + "2" * 64,
            unit_name="eom-image-provider@imgreq_" + "3" * 32 + ".service",
            renderer_contract="eom-safe-svg-compositor/1.1",
            renderer_version="rsvg-convert version 2.58.0",
            renderer_sha256="sha256:" + "a" * 64,
            font_sha256="sha256:" + "b" * 64,
            font_manifest_sha256="sha256:" + "c" * 64,
        )

    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.render_generated_local_vector_stimulus",
        render,
    )
    media = service.materialize_generated_stimulus(
        workflow=_workflow({"local_image_provider": binding}),
        artifacts=(AUTHORING_V5, IMAGE_V5),
    )

    assert media.sha256 == sha256_file(png)
    stimulus = artifacts.commits[0]
    assert stimulus["manifest_version"] == "generated-item-stimulus-file-set/3.0"
    assert set(stimulus["files"]) == {
        "generated-stimulus.png",
        "generated-stimulus.svg",
        "generated-background.png",
        "local-image-receipt.json",
    }
    assert stimulus["result"]["production_route"] == "LOCAL_GENERATIVE_BACKGROUND"
    assert stimulus["result"]["local_image_binding_sha256"] == binding["binding_sha256"]
    assert stimulus["result"]["local_image_request_sha256"] == "sha256:" + "2" * 64
    assert stimulus["result"]["local_image_receipt_sha256"] == "sha256:" + "1" * 64
    assert stimulus["result"]["local_image_unit"] == (
        "eom-image-provider@imgreq_" + "3" * 32 + ".service"
    )
    assert "prompt" not in json.dumps(stimulus["result"]).casefold()


def test_v6_deterministic_plan_never_invokes_the_local_gpu_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, artifacts = _service(tmp_path)
    svg = tmp_path / "rendered-v6.svg"
    png = tmp_path / "rendered-v6.png"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>\n', encoding="utf-8")
    png.write_bytes(b"bounded-deterministic-v6-png")

    def render_vector(*_args: object, **_kwargs: object) -> RenderedVectorStimulus:
        return RenderedVectorStimulus(
            svg,
            png,
            "eom-safe-svg-compositor/1.1",
            "rsvg-convert version 2.58.0",
            "sha256:" + "a" * 64,
            "sha256:" + "b" * 64,
            "sha256:" + "c" * 64,
        )

    def forbidden_gpu(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("deterministic plan attempted to invoke the local GPU")

    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.render_generated_vector_stimulus",
        render_vector,
    )
    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.render_generated_local_vector_stimulus",
        forbidden_gpu,
    )

    service.materialize_generated_stimulus(workflow=_workflow(), artifacts=(AUTHORING_V6, IMAGE_V6))

    stimulus = artifacts.commits[0]
    assert set(stimulus["files"]) == {"generated-stimulus.png", "generated-stimulus.svg"}
    assert stimulus["result"]["production_route"] == "DETERMINISTIC_SVG"
    assert stimulus["result"]["route_reason"] == "SCIENTIFIC_SCHEMATIC"
    assert "local_image_unit" not in stimulus["result"]


def test_v6_hybrid_plan_invokes_one_local_raster_and_commits_a_semantic_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, artifacts = _service(tmp_path)
    artifacts.values[AUTHORING_V6.revision_id] = _authoring_result_v6(hybrid=True)
    artifacts.values[IMAGE_V6.revision_id] = _image_result_v6(hybrid=True)
    service.local_image = cast(Any, object())
    svg = tmp_path / "hybrid.svg"
    raster = tmp_path / "semantic-raster.png"
    png = tmp_path / "hybrid-final.png"
    receipt_file = tmp_path / "hybrid-receipt.json"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>\n', encoding="utf-8")
    raster.write_bytes(b"bounded-semantic-raster")
    png.write_bytes(b"bounded-hybrid-final")
    receipt_file.write_text("{}\n", encoding="utf-8")
    binding = json.loads(
        (REPOSITORY_ROOT / "config/local-image-provider.ssd1b.json").read_text(encoding="utf-8")
    )
    receipt = SimpleNamespace(
        receipt_sha256="sha256:" + "1" * 64,
        generation=SimpleNamespace(
            output=SimpleNamespace(sha256=sha256_file(raster)),
            model=SimpleNamespace(model_dump=lambda **_kwargs: binding["model"]),
            runtime=SimpleNamespace(
                model_dump=lambda **_kwargs: {"provider_version": "eom-local-image-provider/1.0"}
            ),
        ),
        compositor=SimpleNamespace(
            model_dump=lambda **_kwargs: {
                "contract": "eom-local-image-compositor/1.0",
                "pillow_version": "11.3.0",
            }
        ),
    )
    calls = 0

    def render_hybrid(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            svg_path=svg,
            background_path=raster,
            png_path=png,
            receipt_path=receipt_file,
            receipt=receipt,
            request_sha256="sha256:" + "2" * 64,
            unit_name="eom-image-provider@imgreq_" + "3" * 32 + ".service",
            renderer_contract="eom-safe-svg-compositor/1.1",
            renderer_version="rsvg-convert version 2.58.0",
            renderer_sha256="sha256:" + "a" * 64,
            font_sha256="sha256:" + "b" * 64,
            font_manifest_sha256="sha256:" + "c" * 64,
        )

    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.render_generated_local_vector_stimulus",
        render_hybrid,
    )

    service.materialize_generated_stimulus(
        workflow=_workflow({"local_image_provider": binding}),
        artifacts=(AUTHORING_V6, IMAGE_V6),
    )

    assert calls == 1
    stimulus = artifacts.commits[0]
    assert stimulus["manifest_version"] == "generated-item-stimulus-file-set/4.0"
    assert set(stimulus["files"]) == {
        "generated-stimulus.png",
        "generated-stimulus.svg",
        "generated-raster.png",
        "local-image-receipt.json",
    }
    assert stimulus["result"]["production_route"] == "HYBRID_LOCAL_GENERATIVE"
    assert stimulus["result"]["route_reason"] == "HUMAN_OR_ANIMAL_REQUIRED"
    assert stimulus["result"]["local_image_raster_sha256"] == sha256_file(raster)
    assert "local_image_background_sha256" not in stimulus["result"]


def test_prompt_context_revalidates_the_pinned_local_provider_binding(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    binding = json.loads(
        (REPOSITORY_ROOT / "config/local-image-provider.ssd1b.json").read_text(encoding="utf-8")
    )
    workflow = _workflow({"local_image_provider": binding})
    step = cast(
        Any,
        SimpleNamespace(step_key="authoring", worker_role="authoring", attempt=1),
    )

    context = service._prompt_context(workflow, step, _request(), (), "packrel_" + "1" * 32)

    provider = context["local_image_provider"]
    assert set(provider) == {"reviewed_binding_json"}
    assert json.loads(provider["reviewed_binding_json"])["model"] == binding["model"]
    assert content_sha256(context).startswith("sha256:")

    forged = json.loads(json.dumps(binding))
    forged["timeout_seconds"] = 899
    with pytest.raises(ValueError, match="binding hash mismatch"):
        service._prompt_context(
            _workflow({"local_image_provider": forged}),
            step,
            _request(),
            (),
            "packrel_" + "1" * 32,
        )


def test_v5_generated_stimulus_reentry_rejects_a_changed_sidecar_hash() -> None:
    hashes = {
        "generated-stimulus.png": "sha256:" + "a" * 64,
        "generated-stimulus.svg": "sha256:" + "b" * 64,
    }
    metadata = {
        "generated-stimulus.png": {
            "schema_ref": "eom://schemas/generated-item/stimulus-png/2.0",
            "media_type": "image/png",
        },
        "generated-stimulus.svg": {
            "schema_ref": "eom://schemas/generated-item/stimulus-svg/2.0",
            "media_type": "image/svg+xml",
        },
    }
    files = [
        {"file_name": name, "sha256": value, **metadata[name]} for name, value in hashes.items()
    ]
    files[1]["sha256"] = "sha256:" + "c" * 64
    manifest = {
        "manifest_version": "generated-item-stimulus-file-set/2.0",
        "primary_file": "generated-stimulus.png",
        "files": files,
    }

    with pytest.raises(ValueError, match="manifest member"):
        _validate_generated_vector_artifact_manifest(
            manifest,
            expected_file_sha256=hashes,
            file_metadata=metadata,
            content_hash=hashes["generated-stimulus.png"],
        )


def test_generated_item_content_rejects_mixed_result_schema_families(tmp_path: Path) -> None:
    service, artifacts = _service(tmp_path)
    media = service.materialize_generated_stimulus(
        workflow=_workflow(), artifacts=(AUTHORING, IMAGE)
    )

    with pytest.raises(ValueError, match="schema versions are mixed"):
        service._generated_knowledge_item_content(
            _workflow({"generated_stimulus": media.as_dict()}),
            _request(),
            (AUTHORING, IMAGE_V4),
        )

    assert len(artifacts.commits) == 1


def test_catalog_result_schema_roles_match_the_workflow_contract_registry() -> None:
    expected = {
        schema_id: role
        for role, schema_ids in ROLE_ALLOWED_RESULT_SCHEMAS.items()
        for schema_id in schema_ids
    }
    assert expected == ROLE_BY_RESULT_SCHEMA


def test_invalid_v4_authoring_result_never_materializes_an_artifact(tmp_path: Path) -> None:
    service, artifacts = _service(tmp_path)
    invalid = cast(dict[str, Any], artifacts.values[AUTHORING_V4.revision_id])
    invalid["output"]["draft"]["solution"]["accepted_answers"] = ["5 N"]

    with pytest.raises(ValueError, match="accepted_answers"):
        service.materialize_generated_stimulus(
            workflow=_workflow(), artifacts=(AUTHORING_V4, IMAGE_V4)
        )

    assert artifacts.commits == []
