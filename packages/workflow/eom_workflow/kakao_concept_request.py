"""Small shared-Workflow pointers; optional Kakao behavior is loaded only for this purpose."""

from __future__ import annotations

import copy
import json
from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING, Literal, Self

from eom_catalog_contracts.models import FrozenModel
from eom_identifiers import sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from pydantic import Field, model_validator

if TYPE_CHECKING:
    from eom_kakao_archive_contracts.concepts import ConceptComposeRequest, ConceptPlanRequest

WORK_SCHEMA_ID = "eom://schemas/workflow/kakao-concept-work/1.0"
WORK_SCHEMA_SHA256 = "sha256:1c65bc31f7ffa82ec7a0bd3230db4744e79981d098867d124cdf9dd7f9c159f4"
CONCEPT_REQUEST_REF = "eom://schemas/kakao-archive/concept-assistance/1.0"
QUESTION_MANIFEST_REF = "eom://schemas/kakao-archive/question-manifest-v1/1.0"
CONCEPT_ROLE_PROTOCOL = "workflow-role/1.41.0"
CONCEPT_RESULT_SCHEMA = "kakao-concepts-result@1.0"


@cache
def _work_schema() -> dict[str, object]:
    raw = (
        files("eom_workflow")
        .joinpath("resources/control-plane/kakao-concept-work-v1.schema.json")
        .read_bytes()
    )
    if sha256_bytes(raw) != WORK_SCHEMA_SHA256:
        raise ValueError("KAKAO_CONCEPT_WORK_SCHEMA_INVALID")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("$id") != WORK_SCHEMA_ID:
        raise ValueError("KAKAO_CONCEPT_WORK_SCHEMA_INVALID")
    Draft202012Validator.check_schema(value)
    return value


def load_kakao_concept_work_schema() -> dict[str, object]:
    # The registry receives its own value; no caller can mutate the pinned cache.
    return copy.deepcopy(_work_schema())


class KakaoConceptFile(FrozenModel):
    relative_path: str = Field(pattern=r"^[A-Za-z0-9_-]+(?:[/.][A-Za-z0-9_-]+)*$", max_length=240)
    source: ArtifactMemberPointer
    size_bytes: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)
    width_pixels: int = Field(strict=True, ge=1, le=30_000)
    height_pixels: int = Field(strict=True, ge=1, le=30_000)

    @model_validator(mode="after")
    def safe_local_image(self) -> Self:
        if (
            any(part in {"", ".", ".."} for part in self.relative_path.split("/"))
            or self.source.media_type not in {"image/png", "image/jpeg", "image/webp"}
            or self.width_pixels * self.height_pixels > 64_000_000
        ):
            raise ValueError("KAKAO_CONCEPT_WORK_FILE_INVALID")
        return self


class KakaoConceptWork(FrozenModel):
    schema_version: Literal["kakao-concept-work/1.0"] = "kakao-concept-work/1.0"
    task_id: str = Field(pattern=r"^kakaoconcepttask_[0-9a-f]{32}$")
    phase: Literal["PLAN", "COMPOSE"]
    source_binding_id: str = Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")
    question_revision_id: str = Field(pattern=r"^kakaoquestionrev_[0-9a-f]{32}$")
    question_manifest: ArtifactMemberPointer
    request_member: ArtifactMemberPointer
    request_bytes: int = Field(strict=True, ge=1, le=262144)
    files: tuple[KakaoConceptFile, ...] = Field(max_length=72)

    @model_validator(mode="after")
    def bounded_pointer_work(self) -> Self:
        if (
            self.question_manifest.schema_ref != QUESTION_MANIFEST_REF
            or self.question_manifest.media_type != "application/json"
            or self.request_member.schema_ref != CONCEPT_REQUEST_REF
            or self.request_member.media_type != "application/json"
            or len({file.relative_path for file in self.files}) != len(self.files)
            or sum(file.size_bytes for file in self.files) > 128 * 1024 * 1024
            or sum(file.width_pixels * file.height_pixels for file in self.files) > 256_000_000
        ):
            raise ValueError("KAKAO_CONCEPT_WORK_POINTER_INVALID")
        schema = load_kakao_concept_work_schema()
        schema.pop("oneOf")
        schema["$ref"] = "#/$defs/work"
        Draft202012Validator(schema).validate(self.model_dump(mode="json"))
        return self


class KakaoConceptWorkerRequest(FrozenModel):
    request_name: Literal["KAKAO_CONCEPT_REQUEST"] = "KAKAO_CONCEPT_REQUEST"
    work_input: KakaoConceptWork


class KakaoConceptWorkflowRequest(FrozenModel):
    request_name: Literal["KAKAO_CONCEPT_REQUEST"] = "KAKAO_CONCEPT_REQUEST"
    execution_preset_key: Literal["kakao-concepts"] = "kakao-concepts"
    work_input: KakaoConceptWork

    def worker_request(self) -> KakaoConceptWorkerRequest:
        return KakaoConceptWorkerRequest(work_input=self.work_input)


def validate_kakao_concept_request_bytes(
    work: KakaoConceptWork, payload: bytes
) -> ConceptPlanRequest | ConceptComposeRequest:
    """Exact immutable input coherence only; current access remains the application owner's job."""
    from eom_kakao_archive_contracts import canonical_bytes
    from eom_kakao_archive_contracts.concepts import concept_input_members, parse_concept_request

    if len(payload) != work.request_bytes or sha256_bytes(payload) != work.request_member.sha256:
        raise ValueError("KAKAO_CONCEPT_WORK_REQUEST_HASH_MISMATCH")
    request = parse_concept_request(json.loads(payload))
    if canonical_bytes(request.model_dump(mode="json")) != payload or (
        request.task_id,
        request.phase,
        request.question.question_revision_id,
        request.question.question_manifest_sha256,
    ) != (work.task_id, work.phase, work.question_revision_id, work.question_manifest.sha256):
        raise ValueError("KAKAO_CONCEPT_WORK_REQUEST_MISMATCH")
    members = {
        member.relative_path: (member.sha256, member.size_bytes, member.media_type)
        for member in concept_input_members(request)
    }
    expected = {
        member.relative_path: (member.source.sha256, member.size_bytes, member.source.media_type)
        for member in work.files
    }
    if members != expected:
        raise ValueError("KAKAO_CONCEPT_WORK_MEMBER_SET_MISMATCH")
    if request.phase == "COMPOSE":
        dimensions = {
            file.relative_path: (file.width_pixels, file.height_pixels) for file in work.files
        }
        if any(
            dimensions[page.member.relative_path] != (page.width_pixels, page.height_pixels)
            for page in request.context.pages
        ):
            raise ValueError("KAKAO_CONCEPT_WORK_PAGE_DIMENSIONS_MISMATCH")
    return request
