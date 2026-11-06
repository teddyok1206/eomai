"""Read-only administrator Graph index, not a worker retrieval grant."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.models import FrozenModel

MapNodeId = Annotated[str, Field(pattern=r"^knode_[0-9a-f]{32}(?:[0-9a-f]{32})?$")]
MapEdgeId = Annotated[str, Field(pattern=r"^kedge_[0-9a-f]{32}(?:[0-9a-f]{32})?$")]
MapHash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
MapLayer = Literal["TEXTBOOK", "PAST_EXAM", "CREATIVE", "AI", "CURRICULUM", "GUIDE", "UNKNOWN"]


def require_closed_map_neighborhood(
    node_ids: tuple[str, ...],
    edge_ids: tuple[str, ...],
    endpoints: tuple[tuple[str, str], ...],
    *,
    focus_node_id: str | None,
    selected_edge_id: str | None,
    total_nodes: int,
    total_edges: int,
) -> None:
    nodes, edges = set(node_ids), set(edge_ids)
    if len(nodes) != len(node_ids) or len(edges) != len(edge_ids):
        raise ValueError("Graph view has duplicate identities")
    if any(left not in nodes or right not in nodes for left, right in endpoints):
        raise ValueError("Graph view has dangling endpoints")
    if focus_node_id is not None and focus_node_id not in nodes:
        raise ValueError("focus node must be present")
    if selected_edge_id is not None and selected_edge_id not in edges:
        raise ValueError("selected edge must be present")
    if total_nodes < len(node_ids) or total_edges < len(edge_ids):
        raise ValueError("Graph counts differ from the snapshot")


class KnowledgeMapNode(FrozenModel):
    node_id: MapNodeId
    node_type: str = Field(min_length=1, max_length=48)
    label: str = Field(min_length=1, max_length=1024)
    layers: tuple[MapLayer, ...] = Field(max_length=7)

    @model_validator(mode="after")
    def unique_layers(self) -> Self:
        if self.layers != tuple(sorted(set(self.layers))):
            raise ValueError("node layers must be sorted and unique")
        return self


class KnowledgeMapEdge(FrozenModel):
    edge_id: MapEdgeId
    from_node_id: MapNodeId
    to_node_id: MapNodeId
    edge_type: str = Field(min_length=1, max_length=48)


class KnowledgeMapSource(FrozenModel):
    source_revision_id: str = Field(min_length=1, max_length=128)
    source_class: Literal["TEXTBOOK", "PAST_EXAM", "APPROVED_ITEM", "CURRICULUM", "INTERNAL_GUIDE"]
    layer: MapLayer
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


class KnowledgeMapView(FrozenModel):
    schema_version: Literal["knowledge-map-view/1.0"] = "knowledge-map-view/1.0"
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_sha256: MapHash
    nodes: tuple[KnowledgeMapNode, ...] = Field(max_length=120)
    edges: tuple[KnowledgeMapEdge, ...] = Field(max_length=240)
    sources: tuple[KnowledgeMapSource, ...] = Field(max_length=20)
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
        return self
