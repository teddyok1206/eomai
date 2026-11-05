"""The BFF preserves graph pins and the existing administrator boundary."""

from eom_web_gui.knowledge_map_contracts import KnowledgeMapView

from tests.unit.test_knowledge_map_read import view_document
from tests.web_gui.helpers import FakeGateway, login, make_client


class MapGateway(FakeGateway):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.map_calls = []

    async def knowledge_map(self, session, **kwargs):
        self.map_calls.append(kwargs)
        return KnowledgeMapView.model_validate(view_document())


def test_map_routes_pinned_read_and_preserves_no_cache():
    gateway = MapGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        login(client)
        value = view_document()
        response = client.get(
            "/studio/api/v1/knowledge-map",
            params={
                "graph_snapshot_revision_id": value["graph_snapshot_revision_id"],
                "snapshot_sha256": value["snapshot_sha256"],
                "node_id": value["focus_node_id"],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json() == value
        assert (
            gateway.map_calls[0]["graph_snapshot_revision_id"]
            == value["graph_snapshot_revision_id"]
        )
        assert gateway.map_calls[0]["snapshot_sha256"] == value["snapshot_sha256"]


def test_map_is_not_a_new_viewer_grant():
    gateway = MapGateway(roles=["VIEWER"])
    client, _ = make_client(gateway=gateway)
    with client:
        login(client)
        assert client.get("/studio/api/v1/knowledge-map").status_code == 403
        assert not gateway.map_calls
