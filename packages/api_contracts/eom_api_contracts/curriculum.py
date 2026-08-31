"""Read-only curriculum capability projections."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, Sha256


class CurriculumGraphCapabilityView(ApiModel):
    schema_version: Literal["curriculum-graph-capability/1.0"] = "curriculum-graph-capability/1.0"
    corpus_key: Literal["integrated-science-textbooks"] = "integrated-science-textbooks"
    outline_key: Literal["eom-integrated-science-editorial-outline"] = (
        "eom-integrated-science-editorial-outline"
    )
    outline_revision: Literal["1.0"] = "1.0"
    outline_sha256: Sha256
    capability_state: Literal["READY", "UNAVAILABLE"]
    graph_grounding_available: bool
    reason: Literal[
        "READY",
        "CORPUS_UNAVAILABLE",
        "SNAPSHOT_UNAVAILABLE",
        "CURRICULUM_MAPPING_INCOMPLETE",
        "CURRENT_POINTER_CHANGED",
    ]
    graph_snapshot_revision_id: str | None = Field(default=None, pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_sha256: Sha256 | None = None
    framework_revision_id: str | None = Field(default=None, pattern=r"^curriculumrev_[0-9a-f]{32}$")
    unit_count: int = Field(ge=0, le=100_000)
    closure_count: int = Field(ge=0, le=1_000_000)

    @model_validator(mode="after")
    def exact_ready_or_closed_unavailable(self) -> Self:
        pointers = (
            self.graph_snapshot_revision_id,
            self.snapshot_sha256,
            self.framework_revision_id,
        )
        if self.capability_state == "READY":
            if (
                not self.graph_grounding_available
                or self.reason != "READY"
                or any(pointer is None for pointer in pointers)
                or self.unit_count != 43
                or self.closure_count != 119
            ):
                raise ValueError("READY curriculum capability requires exact published pointers")
        elif (
            self.graph_grounding_available
            or self.reason == "READY"
            or any(pointer is not None for pointer in pointers)
        ):
            raise ValueError("unavailable curriculum capability must fail closed")
        return self
