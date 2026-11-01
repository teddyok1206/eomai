"""Small immutable commit evidence; neither recovery permission nor an Artifact copy."""

import json
from functools import lru_cache
from importlib.resources import files
from typing import Literal, Self

from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field, ModelWrapValidatorHandler, model_validator

from eom_protocol.models import ArtifactId, JobId, RevisionId, Sha256, UtcDatetime

CATALOG_COMMIT_INTENT_SCHEMA = "catalog-file-set-commit-intent/1.0"


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(
        files("eom_protocol")
        .joinpath("schemas/catalog-file-set-commit-intent-v1.schema.json")
        .read_text()
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


class CatalogArtifactRecoveryBasis(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    kind: Literal["PINNED_KNOWLEDGE_ACCEPTANCE"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    source_basis_sha256: Sha256


class CatalogFileSetCommitIntent(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    schema_version: Literal["catalog-file-set-commit-intent/1.0"]
    job_id: JobId
    artifact_id: ArtifactId
    artifact_revision_id: RevisionId
    request_sha256: Sha256
    result_sha256: Sha256
    manifest_sha256: Sha256
    manifest_created_at: UtcDatetime
    recovery_basis: CatalogArtifactRecoveryBasis | None
    intent_sha256: Sha256

    @model_validator(mode="wrap")
    @classmethod
    def schema_first(cls, value: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        try:
            if isinstance(value, cls):
                if set(value.__dict__) - set(cls.model_fields):
                    raise ValueError()
                basis = value.recovery_basis
                if basis is not None and set(basis.__dict__) - set(type(basis).model_fields):
                    raise ValueError()
                value = value.model_dump(mode="json")
            if not isinstance(value, dict) or len(canonical_json_bytes(value)) > 65536:
                raise ValueError()
            _validator().validate(value)
            return handler(value)
        except Exception:
            raise ValueError("CATALOG_ARTIFACT_COMMIT_INTENT_INVALID") from None

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.intent_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"intent_sha256"})
        ):
            raise ValueError("CATALOG_ARTIFACT_COMMIT_INTENT_INVALID")
        return self
