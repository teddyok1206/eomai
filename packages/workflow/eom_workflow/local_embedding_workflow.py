"""One non-Codex Workflow purpose; pointers and audit pins grant no source access."""

from __future__ import annotations

import copy
import json
from functools import cache
from importlib.resources import files
from typing import Annotated, Any, Literal

from eom_catalog_contracts import KnowledgeGraphSnapshotPointer, catalog_schema_registry
from eom_catalog_contracts.inference_transfer_embedding import (
    INPUT_SCHEMA_REF,
    EmbeddingSpace,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity.contracts import OperatorId
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ConfigDict, Field, model_validator

from eom_workflow.models import TerminalStep, WorkflowLimits

LOCAL_EMBEDDING_WORKFLOW_KEY = "local-embedding-index"
LOCAL_EMBEDDING_WORKFLOW_VERSION = "1.0.0"
LOCAL_EMBEDDING_EXECUTION_PROTOCOL = "local-embedding/1.0"
LOCAL_EMBEDDING_RESULT_SCHEMA = "incremental-embedding-result@1.0"
LOCAL_EMBEDDING_INPUT_SCHEMA_REF = INPUT_SCHEMA_REF
LOCAL_EMBEDDING_REQUEST_SCHEMA_REF = "eom://schemas/workflow/local-embedding-workflow-request/1.0"
MAX_LOCAL_EMBEDDING_WORKFLOW_BYTES = 64 * 1024
_DEFINITION_FILE = "workflow-definition-v1_1.schema.json"
_REQUEST_FILE = "local-embedding-workflow-request-v1.schema.json"
_MAX_SCHEMA_BYTES = 64 * 1024


class LocalEmbeddingWorkflowContractError(ValueError):
    """Fixed content-free parser failure; never include source or request contents."""


class _LocalEmbeddingContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")


class LocalEmbeddingStep(_LocalEmbeddingContract):
    key: Literal["encode_batch"] = "encode_batch"
    type: Literal["application"] = "application"
    operation: Literal["BUILD_LOCAL_EMBEDDINGS"] = "BUILD_LOCAL_EMBEDDINGS"
    result_schema: Literal["incremental-embedding-result@1.0"] = "incremental-embedding-result@1.0"
    on_success: Literal["complete"] = "complete"


type LocalEmbeddingStepDefinition = Annotated[
    LocalEmbeddingStep | TerminalStep, Field(discriminator="type")
]


class LocalEmbeddingWorkflowDefinition(_LocalEmbeddingContract):
    """A fixed two-step purpose, not an arbitrary application execution graph."""

    schema_version: Literal["1.1"] = "1.1"
    definition_key: Literal["local-embedding-index"] = "local-embedding-index"
    definition_version: Literal["1.0.0"] = "1.0.0"
    start_step: Literal["encode_batch"] = "encode_batch"
    limits: WorkflowLimits
    steps: tuple[LocalEmbeddingStepDefinition, ...] = Field(min_length=2, max_length=2)

    @model_validator(mode="before")
    @classmethod
    def strict_limits(cls, value: Any) -> Any:
        if isinstance(value, dict):
            limits = value.get("limits")
            if isinstance(limits, WorkflowLimits):
                limits = limits.model_dump(mode="json")
            if not isinstance(limits, dict) or any(
                type(limits.get(key)) is not int or limits[key] != expected
                for key, expected in (("max_rework_cycles", 0), ("max_step_attempts", 1))
            ):
                raise ValueError("local embedding definition limits differ")
        return value

    @model_validator(mode="after")
    def exact_purpose(self) -> LocalEmbeddingWorkflowDefinition:
        first, terminal = self.steps
        if isinstance(terminal, TerminalStep):
            TerminalStep.model_validate(terminal.model_dump(mode="json"))
        if (
            not isinstance(first, LocalEmbeddingStep)
            or not isinstance(terminal, TerminalStep)
            or terminal.key != "complete"
            or self.limits.max_rework_cycles != 0
            or self.limits.max_step_attempts != 1
        ):
            raise ValueError("local embedding definition purpose differs")
        return self


class LocalEmbeddingWorkflowRequest(_LocalEmbeddingContract):
    """Server-captured immutable work intent; actual admission remains with its owner.

    No source-admission Artifact or boolean is invented here. The input member
    must be resolved against actual Catalog authority and protected runtime pins
    before a future owner creates a Job or claim. These fields alone are not proof.
    """

    schema_version: Literal["local-embedding-workflow-request/1.0"] = (
        "local-embedding-workflow-request/1.0"
    )
    request_name: Literal["LOCAL_EMBEDDING_WORKFLOW_REQUEST"] = "LOCAL_EMBEDDING_WORKFLOW_REQUEST"
    workflow_definition_key: Literal["local-embedding-index"] = "local-embedding-index"
    workflow_definition_version: Literal["1.0.0"] = "1.0.0"
    requested_by_operator_id: OperatorId
    requester_permissions_sha256: Sha256
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    space: EmbeddingSpace
    input_artifact: ArtifactMemberPointer
    input_set_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_bounded_pins(self) -> LocalEmbeddingWorkflowRequest:
        # model_copy on a frozen nested value is not a validation boundary.
        EmbeddingSpace.model_validate(self.space.model_dump(mode="json"))
        pointer = ArtifactMemberPointer.model_validate(self.input_artifact.model_dump(mode="json"))
        graph = KnowledgeGraphSnapshotPointer.model_validate(
            self.graph_snapshot.model_dump(mode="json")
        )
        if (
            pointer.member_path != "input.json"
            or pointer.schema_ref != LOCAL_EMBEDDING_INPUT_SCHEMA_REF
            or pointer.media_type != "application/json"
            or graph.manifest_sha256 != graph.manifest_artifact.sha256
        ):
            raise ValueError("local embedding Workflow pointer pins differ")
        document = self.model_dump(mode="json")
        if len(canonical_json_bytes(document)) > MAX_LOCAL_EMBEDDING_WORKFLOW_BYTES:
            raise ValueError("local embedding Workflow request exceeds its byte bound")
        if self.request_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"request_sha256"})
        ):
            raise ValueError("local embedding Workflow request hash differs")
        return self


@cache
def _schema(name: str) -> dict[str, Any]:
    try:
        payload = files("eom_workflow").joinpath("resources", name).read_bytes()
        if not 0 < len(payload) <= _MAX_SCHEMA_BYTES:
            raise ValueError("installed schema byte bound differs")
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise ValueError("installed schema root differs")
        Draft202012Validator.check_schema(raw)
        return raw
    except Exception:
        raise LocalEmbeddingWorkflowContractError(
            "LOCAL_EMBEDDING_WORKFLOW_SCHEMA_UNAVAILABLE"
        ) from None


def load_local_embedding_definition_schema() -> dict[str, Any]:
    return copy.deepcopy(_schema(_DEFINITION_FILE))


def load_local_embedding_workflow_request_schema() -> dict[str, Any]:
    return copy.deepcopy(_schema(_REQUEST_FILE))


def _validated(value: object, name: str) -> None:
    try:
        encoded = canonical_json_bytes(value)
        if len(encoded) > MAX_LOCAL_EMBEDDING_WORKFLOW_BYTES:
            raise ValueError("request exceeds its byte bound")
        validator = Draft202012Validator(
            _schema(name), format_checker=FormatChecker(), registry=catalog_schema_registry()
        )
        if not validator.is_valid(value):
            raise ValueError("closed schema differs")
    except Exception:
        raise LocalEmbeddingWorkflowContractError("LOCAL_EMBEDDING_WORKFLOW_INVALID") from None


def parse_local_embedding_workflow_definition(value: object) -> LocalEmbeddingWorkflowDefinition:
    _validated(value, _DEFINITION_FILE)
    try:
        return LocalEmbeddingWorkflowDefinition.model_validate(value)
    except Exception:
        raise LocalEmbeddingWorkflowContractError("LOCAL_EMBEDDING_WORKFLOW_INVALID") from None


def parse_local_embedding_workflow_request(value: object) -> LocalEmbeddingWorkflowRequest:
    _validated(value, _REQUEST_FILE)
    try:
        return LocalEmbeddingWorkflowRequest.model_validate(value)
    except Exception:
        raise LocalEmbeddingWorkflowContractError("LOCAL_EMBEDDING_WORKFLOW_INVALID") from None
