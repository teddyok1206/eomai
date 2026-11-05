"""Small source-fidelity references for a registered uploaded question."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_authorization import (
    MaterialLearningAuthorizationRequest,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

MATERIAL_ITEM_LINEAGE_REF = "eom://schemas/material-learning/item-lineage/1.0"
MATERIAL_ITEM_TYPE = "uploaded-material-item"
MATERIAL_ITEM_PACK = "uploaded-material-item"


class MaterialItemLineage(FrozenModel):
    schema_version: Literal["material-learning-item-lineage/1.0"] = (
        "material-learning-item-lineage/1.0"
    )
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    task_id: str = Field(pattern=r"^materialtask_[0-9a-f]{32}$")
    unit_key: str = Field(min_length=1, max_length=128)
    selection: MaterialLearningAuthorizationRequest
    work_input: MaterialArtifactMember
    role_result: ArtifactMemberPointer
    input_sha256: Sha256
    result_sha256: Sha256
    proposed_content_sha256: Sha256
    registered_content_sha256: Sha256
    source_answer_mode: Literal["EDITORIAL_SOURCE", "MODEL_PROPOSAL_UNVERIFIED", "NOT_APPLICABLE"]
    warning_codes: tuple[str, ...] = Field(max_length=64)
    registration_policy: Literal["PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1"] = (
        "PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1"
    )
    requested_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime
    lineage_sha256: Sha256

    @model_validator(mode="after")
    def exact_source_fidelity(self) -> Self:
        validate_contract("material-learning-item-lineage-v1", self.model_dump(mode="json"))
        if (
            self.selection.input_sha256 != self.input_sha256
            or self.work_input.schema_ref != "eom://schemas/material-learning/extraction-work/1.0"
            or self.work_input.member_path != "material/work.json"
            or self.role_result.schema_ref != "material-learning-result@1.0"
            or self.role_result.member_path != "result.json"
            or self.role_result.media_type != "application/json"
            or self.warning_codes != tuple(sorted(set(self.warning_codes)))
            or self.lineage_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"lineage_sha256"}))
        ):
            raise ValueError("MATERIAL_ITEM_LINEAGE_INVALID")
        return self


def material_item_registration_key(material_revision_id: str, unit_key: str) -> str:
    """Indexed revision-local identity, independent of file names or printed labels."""
    return (
        "material-item:"
        + content_sha256({"material_revision_id": material_revision_id, "unit_key": unit_key})[7:]
    )
