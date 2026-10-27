"""Legacy source DB BFF and visible-key boundary."""

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.web_gui.helpers import login, make_client

ROOT = Path(__file__).resolve().parents[2]


def test_db_list_and_detail_are_available_to_a_logged_in_operator() -> None:
    client, _gateway = make_client()
    with client:
        login(client)
        listing = client.get("/studio/api/v1/item-db/external-sources")
        assert listing.status_code == 200
        entry = listing.json()["values"][0]
        assert entry["external_number"] == "12345"
        assert entry["graph_state"] == "NOT_PUBLISHED"
        assert entry["similarity_state"] == "NOT_INDEXED"
        detail = client.get(f"/studio/api/v1/item-db/external-sources/{entry['source_id']}")
        assert detail.status_code == 200
        assert detail.json()["entry"]["source_revision_id"] == entry["source_revision_id"]
        assert len(detail.json()["cells"]) == 32


def test_db_graph_search_uses_published_candidate_contract_without_archive_promotion() -> None:
    client, _gateway = make_client()
    with client:
        login(client)
        path = "/studio/api/v1/item-db/graph-items"
        assert client.get(path, params={"source_class": "CREATED"}).status_code == 422
        for source_class in ("PAST_EXAM", "APPROVED_ITEM"):
            response = client.get(path, params={"source_class": source_class})
            assert response.status_code == 200
            entry = response.json()["values"][0]
            assert entry["source_class"] == source_class
            assert entry["graph_snapshot_revision_id"].startswith("graphrev_")
            assert entry["source_display_label"]
            assert "external_number" not in entry


def test_db_advanced_filter_search_is_bounded_and_session_protected() -> None:
    client, _gateway = make_client()
    with client:
        session = login(client)
        body = {
            "schema_version": "external-item-db-filter/1.0",
            "match_mode": "ALL",
            "conditions": [{"field": "U", "operator": "EQ", "value": "12345"}],
            "limit": 50,
            "cursor": None,
        }
        path = "/studio/api/v1/item-db/external-sources/search"
        assert client.post(path, json=body).status_code == 403
        response = client.post(path, json=body, headers={"X-CSRF-Token": session["csrf_token"]})
        assert response.status_code == 200
        assert response.json()["values"][0]["external_number"] == "12345"


def test_db_document_filename_link_download_proxies_original_bytes() -> None:
    client, _gateway = make_client()
    with client:
        login(client)
        response = client.get(
            "/studio/api/v1/item-db/external-sources/"
            + "extitem_"
            + "1" * 32
            + "/editions/3/download",
            params={"source_revision_id": "extitemrev_" + "2" * 32},
        )
        assert response.status_code == 200
        assert response.content == b"test-hwp"
        assert response.headers["content-disposition"].startswith("attachment;")


def test_db_pdf_preview_preparation_needs_csrf_and_download_is_inline() -> None:
    client, _gateway = make_client()
    path = (
        "/studio/api/v1/item-db/external-sources/" + "extitem_" + "1" * 32 + "/editions/3/preview"
    )
    params = {"source_revision_id": "extitemrev_" + "2" * 32}
    with client:
        session = login(client)
        assert client.post(path, params=params).status_code == 403
        prepared = client.post(path, params=params, headers={"X-CSRF-Token": session["csrf_token"]})
        pdf = client.get(path + ".pdf", params=params)
    assert prepared.status_code == 200
    assert prepared.json()["sha256"].startswith("sha256:")
    assert pdf.status_code == 200
    assert pdf.content == b"%PDF-1.7\n%%EOF"
    assert pdf.headers["content-disposition"].startswith("inline;")
    assert "PDF 미리보기 준비" in (ROOT / "apps/web_gui/eom_web_gui/static/item-db.js").read_text(
        encoding="utf-8"
    )


def test_db_excel_export_uses_same_filter_and_csrf_boundary() -> None:
    client, _gateway = make_client()
    with client:
        session = login(client)
        body = {
            "schema_version": "external-item-db-filter/1.0",
            "match_mode": "ANY",
            "conditions": [{"field": "Z", "operator": "EQ", "value": "화학"}],
            "limit": 50,
            "cursor": None,
        }
        path = "/studio/api/v1/item-db/external-sources/export"
        assert client.post(path, json=body).status_code == 403
        response = client.post(path, json=body, headers={"X-CSRF-Token": session["csrf_token"]})
        assert response.status_code == 200
        assert response.content.startswith(b"PK\x03\x04")
        assert response.headers["x-eom-row-count"] == "1"
        assert response.headers["content-disposition"] == (
            "attachment; filename=EOM-item-database.xlsx"
        )


def test_db_ordered_selection_save_requires_session_csrf_and_retry_key() -> None:
    client, _gateway = make_client()
    path = "/studio/api/v1/item-db/assemblies"
    body = {"schema_version": "curated-document-assembly-draft/1.0", "placements": [{}]}
    with client:
        session = login(client)
        assert client.post(path, json=body).status_code == 403
        missing_key = client.post(path, json=body, headers={"X-CSRF-Token": session["csrf_token"]})
        saved = client.post(
            path,
            json=body,
            headers={
                "X-CSRF-Token": session["csrf_token"],
                "Idempotency-Key": "curated-web-key-1",
            },
        )
    assert missing_key.status_code == 422
    assert saved.status_code == 200
    assert saved.json()["state"] == "INPUT_PINNED"
    assert saved.json()["placement_count"] == 1
    assert "document_artifact" not in saved.json()


def test_db_screen_shows_business_number_but_hides_internal_db_ids() -> None:
    html = (ROOT / "apps/web_gui/eom_web_gui/static/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "apps/web_gui/eom_web_gui/static/item-db.js").read_text(encoding="utf-8")
    application = (ROOT / "apps/web_gui/eom_web_gui/static/app.js").read_text(encoding="utf-8")
    assert 'data-view="item-db"' in html
    assert html.index(">데이터</p>") < html.index('data-view-target="item-db"')
    assert html.index('data-view-target="item-db"') < html.index('data-view-target="learning"')
    assert html.index('data-view-target="learning"') < html.index('data-view-target="explorer"')
    assert html.index('data-view-target="explorer"') < html.index(">운영 도구</p>")
    assert html.count('data-view-target="item-db"') == 1
    assert 'id="item-db-filter-rows"' in html
    assert 'id="item-db-match-mode"' in html
    assert 'id="item-db-source"' in html
    assert 'id="item-db-graph-unit"' in html
    assert html.index('id="item-db-detail-panel"') < html.index('id="item-db-results"')
    assert 'id="item-db-detail-panel" class="panel item-db-detail-panel" tabindex="-1"' in html
    assert 'panel.scrollIntoView({block: "start"});' in javascript
    assert "panel.focus({preventScroll: true});" in javascript
    assert "/item-db/graph-items?" in javascript
    assert (
        'canReadSource: () => hasPermission(state.operator, "content_intake:read")' in application
    )
    assert '"U", "Q", "R", "Z"' in javascript
    assert 'method: "POST", mutation: true' in javascript
    assert "entry.external_number" in javascript
    assert "detail.entry.source_revision_id" in javascript  # pinned only in authenticated URL
    assert 'node(document, "p", "", detail.entry.source_revision_id)' not in javascript
    assert 'if (["U", "L", "M", "N"].includes(cell.column)) continue;' in javascript


def test_db_assembly_draft_distinguishes_original_files_from_registered_items() -> None:
    html = (ROOT / "apps/web_gui/eom_web_gui/static/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "apps/web_gui/eom_web_gui/static/item-db.js").read_text(encoding="utf-8")
    draft = (ROOT / "apps/web_gui/eom_web_gui/static/item-db-draft.js").read_text(encoding="utf-8")
    assert 'id="item-db-draft-list"' in html
    assert "아직 합본 파일을 만들거나 문항을 승인하지 않습니다." in html
    assert 'placement_kind: "EXTERNAL_SOURCE_DOCUMENT"' in draft
    assert '"PAST_EXAM_ITEM_REVISION" : "REGISTERED_ITEM_REVISION"' in javascript
    assert "source_revision_id: detail.entry.source_revision_id" in draft
    assert "graph_snapshot_revision_id: entry.graph_snapshot_revision_id" in javascript
    assert "createItemDbDraft()" in javascript
    assert "const keys = new Set()" in draft
    assert "ordered.splice(index, 1)" in draft


def test_db_assembly_draft_order_and_deduplication_in_browser_model() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node runtime is unavailable")
    completed = subprocess.run(
        [node, "--experimental-default-type=module", "tests/web_gui/item_db_draft_checks.mjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "item_db_draft=PASS" in completed.stdout
