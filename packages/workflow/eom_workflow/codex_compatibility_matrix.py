"""Bounded operator selections, not account authority or execution evidence.

An ordered tuple preserves operator intent; a set rejects duplicate triples in O(n).
The server pins current account identities when producing the existing V1 request.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from eom_workflow.control_plane import FrozenModel, ReasoningEffort
from eom_workflow.control_schemas import validate_control_contract


class CompatibilitySelection(FrozenModel):
    slot_id: Literal["01", "02", "03", "04", "05", "06"]
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_effort: ReasoningEffort


class CompatibilityMatrix(FrozenModel):
    schema_version: Literal["codex-compatibility-matrix/1.0"] = "codex-compatibility-matrix/1.0"
    selections: tuple[CompatibilitySelection, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_selections(self) -> CompatibilityMatrix:
        triples = {
            (selection.slot_id, selection.model, selection.reasoning_effort)
            for selection in self.selections
        }
        if len(triples) != len(self.selections):
            raise ValueError("compatibility selections must have unique slot/model/effort triples")
        return self


def load_compatibility_matrix(document: object) -> CompatibilityMatrix:
    validate_control_contract("codex-compatibility-matrix", document)
    return CompatibilityMatrix.model_validate(document)
