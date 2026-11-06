"""The BFF preserves graph pins and the existing administrator boundary."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
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


def test_map_layer_passes_to_backend_and_rejects_unknown():
    gateway = MapGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        login(client)
        assert (
            client.get("/studio/api/v1/knowledge-map", params={"layer": "CREATIVE"}).status_code
            == 200
        )
        assert gateway.map_calls[-1]["layer"] == "CREATIVE"
        count = len(gateway.map_calls)
        assert (
            client.get("/studio/api/v1/knowledge-map", params={"layer": "NOT_A_LAYER"}).status_code
            == 422
        )
        assert len(gateway.map_calls) == count


def test_map_browser_layers_cross_layer_nodes_and_stale_responses():
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE") or shutil.which("node") is None:
        pytest.skip("Opt-in browser requires the existing Playwright installation")
    path = Path(__file__).with_name("knowledge_map_browser_checks.mjs")
    result = subprocess.run(
        [shutil.which("node"), str(path)], capture_output=True, text=True, timeout=90, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "MAP_BROWSER=PASS" in result.stdout
