"""Small BFF validation projection; Catalog owns Graph and source invariants."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_web_gui.contracts import WebModel

NodeId = Annotated[str, Field(pattern=r"^knode_[0-9a-f]{32}(?:[0-9a-f]{32})?$")]
EdgeId = Annotated[str, Field(pattern=r"^kedge_[0-9a-f]{32}(?:[0-9a-f]{32})?$")]
MapHash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
MapLayer = Literal[
    "TEXTBOOK", "PAST_EXAM", "CREATIVE", "EXTERNAL", "AI", "CURRICULUM", "GUIDE", "UNKNOWN"
]


class MapNode(WebModel):
    node_id: NodeId
    node_type: str = Field(min_length=1, max_length=48)
    label: str = Field(min_length=1, max_length=1024)
    layers: tuple[MapLayer, ...] = Field(max_length=8)


class MapEdge(WebModel):
    edge_id: EdgeId
    from_node_id: NodeId
    to_node_id: NodeId
    edge_type: str = Field(min_length=1, max_length=48)


class MapSource(WebModel):
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


class KnowledgeMapView(WebModel):
    schema_version: Literal["knowledge-map-view/1.0", "knowledge-map-view/2.0"]
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_sha256: MapHash
    nodes: tuple[MapNode, ...] = Field(max_length=120)
    edges: tuple[MapEdge, ...] = Field(max_length=240)
    sources: tuple[MapSource, ...] = Field(max_length=20)
    focus_node_id: NodeId | None
    selected_edge_id: EdgeId | None
    truncated: bool
    total_nodes: int = Field(ge=0)
    total_edges: int = Field(ge=0)

    @model_validator(mode="after")
    def released_version_scope(self) -> Self:
        if self.schema_version == "knowledge-map-view/1.0" and (
            any("EXTERNAL" in node.layers or len(node.layers) > 7 for node in self.nodes)
            or any(source.layer == "EXTERNAL" for source in self.sources)
        ):
            raise ValueError("external provenance requires Map V2")
        return self
