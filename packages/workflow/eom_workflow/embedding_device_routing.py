"""Pure GPU-preferred routing values; no allocation, source authority or activation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any, Literal

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.embedding_model_recipe import same_embedding_payload_recipe
from eom_catalog_contracts.embedding_reference_query_v11 import EmbeddingReferenceQueryInputV11
from eom_catalog_contracts.embedding_work_batch import (
    EmbeddingWorkBatchInput,
    parse_embedding_work_batch_input,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing import Resource

from eom_workflow.local_embedding_execution_policy import LocalEmbeddingRuntimeProfile
from eom_workflow.native_embedding_backend_selection import (
    NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
    NativeEmbeddingBackendSelection,
    native_embedding_backend_selection_schema,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry

EMBEDDING_DEVICE_ROUTING_SCHEMA_REF = "eom://schemas/workflow/embedding-device-routing/1.0"
EMBEDDING_DEVICE_ROUTING_SCHEMA_SHA256 = (
    "sha256:48ab3ff78c426fd6cae670a513a705eb74ca7c51c88897942bd180f8eb5b3348"
)
MAX_EMBEDDING_DEVICE_ROUTING_BYTES = 64 * 1024
_RESOURCE = "embedding-device-routing-v1.schema.json"


class EmbeddingDeviceRoutingError(ValueError):
    def __init__(self) -> None:
        super().__init__("EMBEDDING_DEVICE_ROUTING_INVALID")


@lru_cache(maxsize=1)
def _schema_raw() -> bytes:
    with files("eom_workflow").joinpath("resources", _RESOURCE).open("rb") as stream:
        raw = stream.read(MAX_EMBEDDING_DEVICE_ROUTING_BYTES + 1)
    if (
        not 0 < len(raw) <= MAX_EMBEDDING_DEVICE_ROUTING_BYTES
        or sha256_bytes(raw) != EMBEDDING_DEVICE_ROUTING_SCHEMA_SHA256
    ):
        raise EmbeddingDeviceRoutingError()
    return raw


def embedding_device_routing_schema() -> dict[str, Any]:
    """An isolated copy of a packaged schema, never an ambient file/remote schema."""
    value: dict[str, Any] = json.loads(_schema_raw())
    if value.get("$id") != EMBEDDING_DEVICE_ROUTING_SCHEMA_REF:
        raise EmbeddingDeviceRoutingError()
    return value


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = embedding_device_routing_schema()
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resource(
        NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
        Resource.from_contents(native_embedding_backend_selection_schema()),
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


class _RoutingValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> Any:
        return raw_similarity_contract_value(value)


class _RoutingMessage(_RoutingValue):
    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_EMBEDDING_DEVICE_ROUTING_BYTES:
                raise EmbeddingDeviceRoutingError()
            _validator().validate(document)
            return document
        except Exception:
            raise EmbeddingDeviceRoutingError() from None


def _require_hash(value: _RoutingValue, name: str) -> None:
    if getattr(value, name) != content_sha256(value.model_dump(mode="json", exclude={name})):
        raise EmbeddingDeviceRoutingError()


class EmbeddingDeviceRuntimeBinding(_RoutingValue):
    """Exact owner configuration plus DOCUMENT runtime; still not installed admission."""

    backend: NativeEmbeddingBackendSelection
    profile: LocalEmbeddingRuntimeProfile

    @model_validator(mode="after")
    def exact_device(self) -> EmbeddingDeviceRuntimeBinding:
        if self.backend.device != self.profile.resource_profile.device:
            raise EmbeddingDeviceRoutingError()
        return self


class EmbeddingDeviceRoutingPolicy(_RoutingMessage):
    schema_version: Literal["embedding-device-routing/1.0"]
    message_type: Literal["POLICY"]
    policy_id: str = Field(pattern=r"^embeddingroutingpolicy_[0-9a-f]{32}$")
    policy_revision_id: str = Field(pattern=r"^embeddingroutingpolicyrev_[0-9a-f]{32}$")
    purpose: Literal["INDEX", "REFERENCE_QUERY", "PRIVATE_CHAT_QUERY"]
    preferred_device: Literal["CUDA"]
    fallback_device: Literal["CPU"]
    fallback_on: Literal["PRE_EXECUTION_ALLOCATION_UNAVAILABLE"]
    view_recipe_sha256: Sha256
    cpu: EmbeddingDeviceRuntimeBinding
    cuda: EmbeddingDeviceRuntimeBinding
    created_at: UtcDatetime
    policy_sha256: Sha256

    @model_validator(mode="after")
    def exact_pair(self) -> EmbeddingDeviceRoutingPolicy:
        cpu, cuda = self.cpu.profile, self.cuda.profile
        if (
            self.cpu.backend.device != "CPU"
            or self.cuda.backend.device != "CUDA"
            or self.cpu.backend.purpose != self.purpose
            or self.cuda.backend.purpose != self.purpose
            or not same_embedding_payload_recipe(cpu.space.model_spec, cuda.space.model_spec)
            or cpu.resource_profile.batch_size != cuda.resource_profile.batch_size
            or cpu.resource_profile.threads != cuda.resource_profile.threads
            or cpu.space.runtime.execution_runtime_sha256
            == cuda.space.runtime.execution_runtime_sha256
            or cpu.space.space_sha256 == cuda.space.space_sha256
            or cpu.runtime_bundle.bundle_revision_id == cuda.runtime_bundle.bundle_revision_id
            or cpu.runtime_bundle.manifest_member.artifact_revision_id
            == cuda.runtime_bundle.manifest_member.artifact_revision_id
            or (
                cpu.space.model_spec.model_revision_id == cuda.space.model_spec.model_revision_id
                and cpu.space.model_spec.manifest_sha256 != cuda.space.model_spec.manifest_sha256
            )
        ):
            raise EmbeddingDeviceRoutingError()
        _require_hash(self, "policy_sha256")
        return self


class EmbeddingGpuAllocationObservation(_RoutingMessage):
    """Asserted root-adapter outcome, not proof a live lease is held or transferable.

    The concrete owner must validate the referenced allocation record and lifetime.
    Closed NOT_STARTED outcomes deliberately cannot express partial/unknown execution.
    """

    schema_version: Literal["embedding-device-routing/1.0"]
    message_type: Literal["ALLOCATION_OBSERVATION"]
    allocation_attempt_id: str = Field(pattern=r"^embeddingallocation_[0-9a-f]{32}$")
    request_sha256: Sha256
    policy_sha256: Sha256
    phase: Literal["PRE_EXECUTION"]
    cuda_launch_state: Literal["NOT_STARTED"]
    status: Literal["ACQUIRED", "BUSY", "CAPACITY_UNAVAILABLE"]
    allocation_reference_sha256: Sha256
    observed_at: UtcDatetime
    observation_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> EmbeddingGpuAllocationObservation:
        _require_hash(self, "observation_sha256")
        return self


class EmbeddingDeviceRoutingDecision(_RoutingMessage):
    """Pinned pure decision candidate; no request mutation or compute grant."""

    schema_version: Literal["embedding-device-routing/1.0"]
    message_type: Literal["DECISION"]
    request_sha256: Sha256
    policy_sha256: Sha256
    allocation_attempt_id: str = Field(pattern=r"^embeddingallocation_[0-9a-f]{32}$")
    allocation_observation_sha256: Sha256
    reason: Literal["GPU_ALLOCATION_ACQUIRED", "GPU_BUSY_CPU_FALLBACK", "GPU_CAPACITY_CPU_FALLBACK"]
    selected: EmbeddingDeviceRuntimeBinding
    decision_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> EmbeddingDeviceRoutingDecision:
        expected_device = "CUDA" if self.reason == "GPU_ALLOCATION_ACQUIRED" else "CPU"
        if self.selected.backend.device != expected_device:
            raise EmbeddingDeviceRoutingError()
        _require_hash(self, "decision_sha256")
        return self


_ALLOCATION_ROUTES: Mapping[str, tuple[Literal["CPU", "CUDA"], str]] = MappingProxyType(
    {
        "ACQUIRED": ("CUDA", "GPU_ALLOCATION_ACQUIRED"),
        "BUSY": ("CPU", "GPU_BUSY_CPU_FALLBACK"),
        "CAPACITY_UNAVAILABLE": ("CPU", "GPU_CAPACITY_CPU_FALLBACK"),
    }
)


def plan_embedding_device_route(
    policy: EmbeddingDeviceRoutingPolicy, observation: EmbeddingGpuAllocationObservation
) -> EmbeddingDeviceRoutingDecision:
    """O(1) pure planning before reservations; owner must authenticate both input origins."""
    try:
        policy = EmbeddingDeviceRoutingPolicy.model_validate(raw_similarity_contract_value(policy))
        observation = EmbeddingGpuAllocationObservation.model_validate(
            raw_similarity_contract_value(observation)
        )
        if observation.policy_sha256 != policy.policy_sha256:
            raise EmbeddingDeviceRoutingError()
        device, reason = _ALLOCATION_ROUTES[observation.status]
        selected = policy.cuda if device == "CUDA" else policy.cpu
        body = {
            "schema_version": "embedding-device-routing/1.0",
            "message_type": "DECISION",
            "request_sha256": observation.request_sha256,
            "policy_sha256": policy.policy_sha256,
            "allocation_attempt_id": observation.allocation_attempt_id,
            "allocation_observation_sha256": observation.observation_sha256,
            "reason": reason,
            "selected": selected.model_dump(mode="json"),
        }
        return EmbeddingDeviceRoutingDecision.model_validate(
            body | {"decision_sha256": content_sha256(body)}
        )
    except Exception:
        raise EmbeddingDeviceRoutingError() from None


def validate_embedding_device_route_replay(
    policy: EmbeddingDeviceRoutingPolicy,
    observation: EmbeddingGpuAllocationObservation,
    original: EmbeddingDeviceRoutingDecision,
) -> EmbeddingDeviceRoutingDecision:
    """Revalidate the original immutable allocation, not a newly observed GPU availability."""
    try:
        original = EmbeddingDeviceRoutingDecision.model_validate(
            raw_similarity_contract_value(original)
        )
        if plan_embedding_device_route(policy, observation) != original:
            raise EmbeddingDeviceRoutingError()
        return original
    except Exception:
        raise EmbeddingDeviceRoutingError() from None


def validate_embedding_device_batch_profile(
    policy: EmbeddingDeviceRoutingPolicy,
    decision: EmbeddingDeviceRoutingDecision,
    batch: EmbeddingWorkBatchInput,
) -> EmbeddingWorkBatchInput:
    """One numerical profile invariant for planning and actual index-route composition."""
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy)
    decision = EmbeddingDeviceRoutingDecision.model_validate(decision)
    batch = parse_embedding_work_batch_input(batch)
    selected = decision.selected
    profile, resources = selected.profile, selected.profile.resource_profile
    if (
        decision.policy_sha256 != policy.policy_sha256
        or selected != (policy.cuda if selected.backend.device == "CUDA" else policy.cpu)
        or batch.purpose
        != {"INDEX": "DOCUMENT", "REFERENCE_QUERY": "REFERENCE_QUERY"}.get(policy.purpose)
        or batch.routing_decision_sha256 != decision.decision_sha256
        or batch.resource_profile_sha256 != resources.resource_profile_sha256
        or batch.timeout_seconds > resources.timeout_seconds
        or batch.expected_vector_bytes >= resources.output_max_bytes
    ):
        raise EmbeddingDeviceRoutingError()
    for child in batch.children:
        request = child.request
        if (
            child.space.model_spec != profile.space.model_spec
            or child.space.runtime != profile.space.runtime
            or request.batch_size != resources.batch_size
            or request.threads != resources.threads
        ):
            raise EmbeddingDeviceRoutingError()
        if isinstance(request, EmbeddingReferenceQueryInputV11):
            if (
                request.spaces.document != profile.space
                or request.recipe.recipe_sha256 != policy.view_recipe_sha256
            ):
                raise EmbeddingDeviceRoutingError()
        elif request.space != profile.space:
            raise EmbeddingDeviceRoutingError()
    return batch
