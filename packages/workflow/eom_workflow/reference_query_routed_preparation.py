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

ROUTED_QUERY_PREPARATION_SCHEMA_REF = (
    "eom://schemas/workflow/reference-query-routed-preparation/1.0"
)
ROUTED_QUERY_PREPARATION_SCHEMA_SHA256 = (
    "sha256:553d18f13c5815c9074952fe7c6c4457901590b3bcec57947a7e760dfa812e3d"
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


class RoutedReferenceQueryPreparation(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always", hide_input_in_errors=True
    )

    schema_version: Literal["reference-query-routed-preparation/1.0"]
    operator_id: str = Field(strict=True, pattern=r"^operator_[0-9a-f]{32}$")
    idempotency_key: str = Field(
        strict=True, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]{8,128}$"
    )
    intent_sha256: Sha256
    owner_configuration_sha256: Sha256
    parent: EmbeddingBatchPlanRequestV12
    preparation_sha256: Sha256

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
        if (
            self.parent.scope.actor_kind != "OPERATOR"
            or self.parent.scope.actor_id != self.operator_id
            or self.parent.parent_request_sha256 != self.intent_sha256
            or self.preparation_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"preparation_sha256"}))
        ):
            raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_INVALID")
        return self


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
