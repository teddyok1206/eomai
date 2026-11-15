"""Explicit small receipt versions; full role output stays in its Artifact."""

from collections.abc import Mapping
from typing import Literal, Self

from pydantic import model_validator

from eom_catalog_contracts.material_learning import MaterialLearningRoleReceipt
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

MATERIAL_LEARNING_ROLE_RECEIPT_V2_REF = "eom://schemas/material-learning/role-receipt/2.0"


class MaterialLearningRoleReceiptV2(FrozenModel):
    """Same five identity fields; result hash binds the whole V2 role envelope."""

    schema_version: Literal["material-learning-role-receipt/2.0"] = (
        "material-learning-role-receipt/2.0"
    )
    result_schema: Literal["material-learning-result@2.0"] = "material-learning-result@2.0"
    task_kind: Literal["DISCOVER", "EXTRACT_ITEM"]
    input_sha256: Sha256
    result_sha256: Sha256

    @model_validator(mode="after")
    def installed_receipt(self) -> Self:
        validate_contract("material-learning-role-receipt-v2", self.model_dump(mode="json"))
        return self


type MaterialLearningRoleReceiptFamily = MaterialLearningRoleReceipt | MaterialLearningRoleReceiptV2


def parse_material_learning_role_receipt(value: object) -> MaterialLearningRoleReceiptFamily:
    """Select only a declared version; an invalid declared family never falls back."""
    if isinstance(value, (MaterialLearningRoleReceipt, MaterialLearningRoleReceiptV2)):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise ValueError("MATERIAL_LEARNING_ROLE_RECEIPT_DOCUMENT_INVALID")
    version = value.get("schema_version")
    if version == "material-learning-role-receipt/1.0":
        return MaterialLearningRoleReceipt.model_validate(value)
    if version == "material-learning-role-receipt/2.0":
        return MaterialLearningRoleReceiptV2.model_validate(value)
    raise ValueError("MATERIAL_LEARNING_ROLE_RECEIPT_SCHEMA_UNSUPPORTED")
