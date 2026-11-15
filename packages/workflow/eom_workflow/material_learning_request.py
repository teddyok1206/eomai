"""Isolated material purpose; historical WorkflowRequest bytes/fields are unchanged."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Self

from eom_catalog_contracts.material_learning import MaterialExtractionWork, MaterialLearningWork
from eom_catalog_contracts.material_native_files import material_native_printed_number
from eom_catalog_contracts.material_native_visual_preparation import (
    MaterialNativeQuestionVisualScope,
)
from eom_catalog_contracts.models import FrozenModel
from eom_catalog_contracts.source_score import PrintedSourceScoreV2
from pydantic import model_validator


class MaterialLearningWorkerRequest(FrozenModel):
    request_name: Literal["MATERIAL_LEARNING_REQUEST"] = "MATERIAL_LEARNING_REQUEST"
    work_input: MaterialLearningWork


class MaterialLearningWorkflowRequest(FrozenModel):
    request_name: Literal["MATERIAL_LEARNING_REQUEST"] = "MATERIAL_LEARNING_REQUEST"
    execution_preset_key: Literal["material-learning"] = "material-learning"
    work_input: MaterialLearningWork

    def worker_request(self) -> MaterialLearningWorkerRequest:
        return MaterialLearningWorkerRequest(work_input=self.work_input)


def require_material_learning_native_scope(
    work: MaterialLearningWork, scope: MaterialNativeQuestionVisualScope | None
) -> None:
    """Pure coherence only; Catalog independently determines whether scope is required."""
    if scope is None:
        return
    if not isinstance(work, MaterialExtractionWork):
        raise ValueError("MATERIAL_LEARNING_NATIVE_SCOPE_TASK_INVALID")
    role = work.question.anchors[0].source_role
    sources = {source.source_role: source for source in work.sources}
    source = sources.get(role)
    if (
        scope.item_number != material_native_printed_number(work.question.printed_label)
        or source is None
        or source.actual_format not in {"HWP", "HWPX"}
        or source.office_catalog is None
        or source.office_catalog.sha256 != scope.source_catalog_sha256
    ):
        raise ValueError("MATERIAL_LEARNING_NATIVE_SCOPE_INPUT_MISMATCH")


class MaterialLearningWorkerRequestV2(FrozenModel):
    request_name: Literal["MATERIAL_LEARNING_REQUEST"] = "MATERIAL_LEARNING_REQUEST"
    work_input: MaterialLearningWork
    native_visual_scope: MaterialNativeQuestionVisualScope | None

    @model_validator(mode="after")
    def coherent_scope(self) -> Self:
        require_material_learning_native_scope(self.work_input, self.native_visual_scope)
        return self


class MaterialLearningWorkflowRequestV2(FrozenModel):
    request_name: Literal["MATERIAL_LEARNING_REQUEST"] = "MATERIAL_LEARNING_REQUEST"
    execution_preset_key: Literal["material-learning"] = "material-learning"
    work_input: MaterialLearningWork
    native_visual_scope: MaterialNativeQuestionVisualScope | None

    @model_validator(mode="after")
    def coherent_scope(self) -> Self:
        require_material_learning_native_scope(self.work_input, self.native_visual_scope)
        return self

    def worker_request(self) -> MaterialLearningWorkerRequestV2:
        return MaterialLearningWorkerRequestV2(
            work_input=self.work_input, native_visual_scope=self.native_visual_scope
        )


def require_material_native_printed_score(
    scope: MaterialNativeQuestionVisualScope | None, score: PrintedSourceScoreV2 | None
) -> None:
    """A small observed value must be tied to a Native question, never inferred for a PDF."""
    if (scope is None) != (score is None):
        raise ValueError("MATERIAL_LEARNING_NATIVE_SCORE_SCOPE_MISMATCH")


class MaterialLearningWorkerRequestV3(MaterialLearningWorkerRequestV2):
    native_printed_score: PrintedSourceScoreV2 | None

    @model_validator(mode="after")
    def coherent_score(self) -> Self:
        require_material_native_printed_score(self.native_visual_scope, self.native_printed_score)
        return self


class MaterialLearningWorkflowRequestV3(MaterialLearningWorkflowRequestV2):
    native_printed_score: PrintedSourceScoreV2 | None

    @model_validator(mode="after")
    def coherent_score(self) -> Self:
        require_material_native_printed_score(self.native_visual_scope, self.native_printed_score)
        return self

    def worker_request(self) -> MaterialLearningWorkerRequestV3:
        return MaterialLearningWorkerRequestV3(
            work_input=self.work_input,
            native_visual_scope=self.native_visual_scope,
            native_printed_score=self.native_printed_score,
        )


type MaterialLearningWorkerRequestFamily = (
    MaterialLearningWorkerRequest
    | MaterialLearningWorkerRequestV2
    | MaterialLearningWorkerRequestV3
)
type MaterialLearningWorkflowRequestFamily = (
    MaterialLearningWorkflowRequest
    | MaterialLearningWorkflowRequestV2
    | MaterialLearningWorkflowRequestV3
)


def parse_material_learning_worker_request(value: object) -> MaterialLearningWorkerRequestFamily:
    if isinstance(value, (MaterialLearningWorkerRequest, MaterialLearningWorkerRequestV2)):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping) and "native_printed_score" in value:
        return MaterialLearningWorkerRequestV3.model_validate(value)
    if isinstance(value, Mapping) and "native_visual_scope" in value:
        return MaterialLearningWorkerRequestV2.model_validate(value)
    return MaterialLearningWorkerRequest.model_validate(value)


def parse_material_learning_workflow_request(
    value: object,
) -> MaterialLearningWorkflowRequestFamily:
    if isinstance(value, (MaterialLearningWorkflowRequest, MaterialLearningWorkflowRequestV2)):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping) and "native_printed_score" in value:
        return MaterialLearningWorkflowRequestV3.model_validate(value)
    if isinstance(value, Mapping) and "native_visual_scope" in value:
        return MaterialLearningWorkflowRequestV2.model_validate(value)
    return MaterialLearningWorkflowRequest.model_validate(value)


@dataclass(frozen=True, slots=True)
class MaterialLearningContractProfile:
    definition_version: str
    role_protocol: str
    result_schema: str
    plan_schema_version: str
    plan_schema_key: str
    resolver_version: str


_MATERIAL_CONTRACTS = MappingProxyType(
    {
        "1.0.0": MaterialLearningContractProfile(
            "1.0.0",
            "workflow-role/1.37.0",
            "material-learning-result@1.0",
            "resolved-execution-plan/33.0",
            "resolved-execution-plan-v33",
            "33.0.0",
        ),
        "2.0.0": MaterialLearningContractProfile(
            "2.0.0",
            "workflow-role/1.39.0",
            "material-learning-result@2.0",
            "resolved-execution-plan/40.0",
            "resolved-execution-plan-v40",
            "40.0.0",
        ),
        "3.0.0": MaterialLearningContractProfile(
            "3.0.0",
            "workflow-role/1.40.0",
            "material-learning-result@3.0",
            "resolved-execution-plan/41.0",
            "resolved-execution-plan-v41",
            "41.0.0",
        ),
    }
)


def material_learning_contract_for_definition(version: str) -> MaterialLearningContractProfile:
    try:
        return _MATERIAL_CONTRACTS[version]
    except KeyError as error:
        raise ValueError("MATERIAL_LEARNING_DEFINITION_UNSUPPORTED") from error


def material_learning_contract(
    request: MaterialLearningWorkerRequestFamily | MaterialLearningWorkflowRequestFamily,
) -> MaterialLearningContractProfile:
    if isinstance(request, (MaterialLearningWorkerRequestV3, MaterialLearningWorkflowRequestV3)):
        return _MATERIAL_CONTRACTS["3.0.0"]
    if isinstance(request, (MaterialLearningWorkerRequestV2, MaterialLearningWorkflowRequestV2)):
        return _MATERIAL_CONTRACTS["2.0.0"]
    if isinstance(request, (MaterialLearningWorkerRequest, MaterialLearningWorkflowRequest)):
        return _MATERIAL_CONTRACTS["1.0.0"]
    raise ValueError("MATERIAL_LEARNING_REQUEST_UNSUPPORTED")
