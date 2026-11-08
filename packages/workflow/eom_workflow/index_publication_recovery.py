"""Explicit selection for publication-only recovery; never a source or execution grant."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Literal, Self

from eom_catalog_contracts.models import Sha256
from eom_identifiers import content_sha256, sha256_bytes
from eom_operator_identity import LocalIndexingServiceReference
from jsonschema import Draft202012Validator
from pydantic import Field, model_validator

from eom_workflow.schemas import NativeEmbeddingContract


@cache
def _validator() -> Draft202012Validator:
    raw = (
        files("eom_workflow")
        .joinpath("resources", "index-publication-recovery-v1.schema.json")
        .read_bytes()
    )
    if (
        sha256_bytes(raw)
        != "sha256:20b7fa8e884903d5e9ad28cd0b2c22dc018ea89115fcea682f20e422147c0352"
    ):
        raise ValueError("INDEX_PUBLICATION_RECOVERY_SCHEMA_UNAVAILABLE")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


class IndexPublicationRecoveryCommand(NativeEmbeddingContract):
    schema_version: Literal["index-publication-recovery/1.0"] = "index-publication-recovery/1.0"
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_request_sha256: Sha256
    native_intent_sha256: Sha256
    registration_request_sha256: Sha256
    current_service: LocalIndexingServiceReference
    current_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    current_policy_sha256: Sha256
    command_sha256: Sha256

    @model_validator(mode="after")
    def validate_command(self) -> Self:
        value = self.model_dump(mode="json")
        _validator().validate(value)
        if self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("INDEX_PUBLICATION_RECOVERY_COMMAND_INVALID")
        return self
