"""Original pointer-only QUERY preparation; actual source/session admission stays outside."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_operator_identity.contracts import OperatorId
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from eom_workflow.embedding_batch_plan_v12 import (
    EmbeddingBatchPlanRequestV12,
    embedding_batch_query_plan_schema_registry,
)
from eom_workflow.embedding_batch_plan_v14 import (
    EmbeddingBatchPlanRequestV14,
    embedding_batch_public_query_plan_schema_registry,
)
from eom_workflow.embedding_batch_plan_v15 import (
    EmbeddingBatchPlanRequestV15,
    embedding_batch_registered_public_query_plan_schema_registry,
)
from eom_workflow.embedding_batch_plan_values import EmbeddingBatchPlanRequestValues

ROUTED_QUERY_PREPARATION_SCHEMA_REF = (
    "eom://schemas/workflow/reference-query-routed-preparation/1.0"
)
ROUTED_QUERY_PREPARATION_SCHEMA_SHA256 = (
    "sha256:553d18f13c5815c9074952fe7c6c4457901590b3bcec57947a7e760dfa812e3d"
)
PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_REF = (
    "eom://schemas/workflow/reference-query-routed-preparation/2.0"
)
PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_SHA256 = (
    "sha256:38d7d03387d13d57e55a07c2dee96846f8fde13b86e8ca4daf93533ca9db92ba"
)
REGISTERED_PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_REF = (
    "eom://schemas/workflow/reference-query-routed-preparation/3.0"
)
REGISTERED_PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_SHA256 = (
    "sha256:1043a7e13c85943154506580c1beeef912c3bf4ee1a3c45361622d98c2d19d01"
)
MAX_ROUTED_QUERY_PREPARATION_BYTES = 64 * 1024


def reference_query_routed_preparation_schema() -> dict[str, Any]:
    with (
        files("eom_workflow")
        .joinpath("resources/reference-query-routed-preparation-v1.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_ROUTED_QUERY_PREPARATION_BYTES + 1)
    if sha256_bytes(raw) != ROUTED_QUERY_PREPARATION_SCHEMA_SHA256:
        raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_SCHEMA_INVALID")
    schema: dict[str, Any] = json.loads(raw)
    if schema.get("$id") != ROUTED_QUERY_PREPARATION_SCHEMA_REF:
        raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_SCHEMA_INVALID")
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = reference_query_routed_preparation_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=embedding_batch_query_plan_schema_registry(),
        format_checker=FormatChecker(),
    )


@lru_cache(maxsize=1)
def _public_validator() -> Draft202012Validator:
    with (
        files("eom_workflow")
        .joinpath("resources/reference-query-routed-preparation-v2.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_ROUTED_QUERY_PREPARATION_BYTES + 1)
    if sha256_bytes(raw) != PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_SHA256:
        raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_SCHEMA_INVALID")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=embedding_batch_public_query_plan_schema_registry(),
        format_checker=FormatChecker(),
    )


@lru_cache(maxsize=1)
def _registered_public_validator() -> Draft202012Validator:
    with (
        files("eom_workflow")
        .joinpath("resources/reference-query-routed-preparation-v3.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_ROUTED_QUERY_PREPARATION_BYTES + 1)
    if sha256_bytes(raw) != REGISTERED_PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_SHA256:
        raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_SCHEMA_INVALID")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=embedding_batch_registered_public_query_plan_schema_registry(),
        format_checker=FormatChecker(),
    )


class _RoutedPreparationFields(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always", hide_input_in_errors=True
    )

    operator_id: str = Field(strict=True, pattern=r"^operator_[0-9a-f]{32}$")
    idempotency_key: str = Field(
        strict=True, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]{8,128}$"
    )
    intent_sha256: Sha256
    owner_configuration_sha256: Sha256
    preparation_sha256: Sha256

    def _require_parent_intent(self, parent: EmbeddingBatchPlanRequestValues) -> None:
        if (
            parent.scope.actor_kind != "OPERATOR"
            or parent.scope.actor_id != self.operator_id
            or parent.parent_request_sha256 != self.intent_sha256
            or self.preparation_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"preparation_sha256"}))
        ):
            raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID")


class RoutedReferenceQueryPreparation(_RoutedPreparationFields):
    schema_version: Literal["reference-query-routed-preparation/1.0"]
    parent: EmbeddingBatchPlanRequestV12

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_ROUTED_QUERY_PREPARATION_BYTES:
                raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID")
            _validator().validate(document)
            return document
        except Exception:
            raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID") from None

    @model_validator(mode="after")
    def exact_intent(self) -> Self:
        self._require_parent_intent(self.parent)
        return self


class PublicRoutedReferenceQueryPreparation(_RoutedPreparationFields):
    schema_version: Literal["reference-query-routed-preparation/2.0"]
    parent: EmbeddingBatchPlanRequestV14

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_ROUTED_QUERY_PREPARATION_BYTES:
                raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID")
            _public_validator().validate(document)
            return document
        except Exception:
            raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID") from None

    @model_validator(mode="after")
    def exact_intent(self) -> Self:
        self._require_parent_intent(self.parent)
        return self


class RegisteredPublicRoutedReferenceQueryPreparation(_RoutedPreparationFields):
    schema_version: Literal["reference-query-routed-preparation/3.0"]
    parent: EmbeddingBatchPlanRequestV15

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_ROUTED_QUERY_PREPARATION_BYTES:
                raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID")
            _registered_public_validator().validate(document)
            return document
        except Exception:
            raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID") from None

    @model_validator(mode="after")
    def exact_intent(self) -> Self:
        self._require_parent_intent(self.parent)
        return self


type SupportedRoutedReferenceQueryPreparation = (
    RoutedReferenceQueryPreparation
    | PublicRoutedReferenceQueryPreparation
    | RegisteredPublicRoutedReferenceQueryPreparation
)


def validate_supported_routed_reference_query_preparation(
    value: object,
) -> SupportedRoutedReferenceQueryPreparation:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict) and document.get("schema_version") == (
        "reference-query-routed-preparation/3.0"
    ):
        return RegisteredPublicRoutedReferenceQueryPreparation.model_validate(document)
    if isinstance(document, dict) and document.get("schema_version") == (
        "reference-query-routed-preparation/2.0"
    ):
        return PublicRoutedReferenceQueryPreparation.model_validate(document)
    return RoutedReferenceQueryPreparation.model_validate(document)


def parse_supported_reference_query_routed_preparation(
    raw: bytes,
) -> SupportedRoutedReferenceQueryPreparation:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_ROUTED_QUERY_PREPARATION_BYTES:
        raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID")
    prepared = validate_supported_routed_reference_query_preparation(json.loads(raw))
    if canonical_json_bytes(prepared) != raw:
        raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID")
    return prepared


def routed_reference_query_preparation_key(operator_id: str, idempotency_key: str) -> str:
    """An indexed publication identity, never authority or a request-hash substitute."""
    # Do not let a new metadata helper broaden the existing closed human/key syntax.
    operator_id = TypeAdapter(OperatorId).validate_python(operator_id, strict=True)
    if (
        type(idempotency_key) is not str
        or re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", idempotency_key) is None
    ):
        raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID")
    return "routed-query-prepare:" + content_sha256(
        {"operator_id": operator_id, "idempotency_key": idempotency_key}
    ).removeprefix("sha256:")


def parse_reference_query_routed_preparation(raw: bytes) -> RoutedReferenceQueryPreparation:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_ROUTED_QUERY_PREPARATION_BYTES:
            raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID")
        parsed = RoutedReferenceQueryPreparation.model_validate(json.loads(raw))
        if canonical_json_bytes(parsed) != raw:
            raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID")
        return parsed
    except Exception:
        raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID") from None
