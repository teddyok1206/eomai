"""External provenance in the same shared Graph; released Map V1 stays unchanged."""

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.knowledge_map import (
    KnowledgeMapEdge,
    MapEdgeId,
    MapHash,
    MapNodeId,
    require_closed_map_neighborhood,
)
from eom_catalog_contracts.models import FrozenModel
from eom_catalog_contracts.validation import validate_contract

MapLayerV2 = Literal[
    "TEXTBOOK", "PAST_EXAM", "CREATIVE", "EXTERNAL", "AI", "CURRICULUM", "GUIDE", "UNKNOWN"
]


class KnowledgeMapNodeV2(FrozenModel):
    node_id: MapNodeId
    node_type: str = Field(min_length=1, max_length=48)
    label: str = Field(min_length=1, max_length=1024)
    layers: tuple[MapLayerV2, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def unique_layers(self) -> Self:
        if self.layers != tuple(sorted(set(self.layers))):
            raise ValueError("node layers must be sorted and unique")
        return self


class KnowledgeMapSourceV2(FrozenModel):
    source_revision_id: str = Field(min_length=1, max_length=128)
    source_class: Literal["TEXTBOOK", "PAST_EXAM", "APPROVED_ITEM", "CURRICULUM", "INTERNAL_GUIDE"]
    layer: MapLayerV2
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    source_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    source_sha256: MapHash
    anchor_id: str = Field(min_length=1, max_length=128)
    excerpt_sha256: MapHash
    available: bool
    title: str = Field(max_length=512)
    item_id: str | None = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_manifest_sha256: MapHash | None

    @model_validator(mode="after")
    def item_identity_pair(self) -> Self:
        if (self.item_id is None) != (self.item_manifest_sha256 is None):
            raise ValueError("Item identity and manifest must be paired")
        return self


class KnowledgeMapViewV2(FrozenModel):
    schema_version: Literal["knowledge-map-view/2.0"] = "knowledge-map-view/2.0"
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_sha256: MapHash
    nodes: tuple[KnowledgeMapNodeV2, ...] = Field(max_length=120)
    edges: tuple[KnowledgeMapEdge, ...] = Field(max_length=240)
    sources: tuple[KnowledgeMapSourceV2, ...] = Field(max_length=20)
    focus_node_id: MapNodeId | None
    selected_edge_id: MapEdgeId | None
    truncated: bool
    total_nodes: int = Field(ge=0)
    total_edges: int = Field(ge=0)

    @model_validator(mode="after")
    def closed_neighborhood(self) -> Self:
        require_closed_map_neighborhood(
            tuple(row.node_id for row in self.nodes),
            tuple(row.edge_id for row in self.edges),
            tuple((row.from_node_id, row.to_node_id) for row in self.edges),
            focus_node_id=self.focus_node_id,
            selected_edge_id=self.selected_edge_id,
            total_nodes=self.total_nodes,
            total_edges=self.total_edges,
        )
        validate_contract("knowledge-map-view-v2", self.model_dump(mode="json"))
        return self
