"""Categories and approval are independent; creative rows preserve source metadata."""

from types import SimpleNamespace
from unittest.mock import Mock

from eom_api.services.pagination import PageResult
from eom_api_contracts.item_db_registration import CreativeItemDbEntryView, ItemDbRegistrationView

from tests.api.test_external_item_db_routes import _client, _entry


def _registration(state="APPROVED"):
    return ItemDbRegistrationView(
        item_id="item_" + "1" * 32,
        item_revision_id="itemrev_" + "2" * 32,
        item_manifest_sha256="sha256:" + "3" * 64,
        approval_state=state,
        item_type_key="external-creative-multiple-choice",
    )


def _filters():
    return {
        "schema_version": "external-item-db-filter/1.0",
        "match_mode": "ANY",
        "conditions": [{"field": "AD", "operator": "CONTAINS", "value": "선생님"}],
        "limit": 50,
        "cursor": None,
    }


def test_creative_search_retains_metadata_and_independent_approval_filter():
    client, services, reads = _client()
    reads.creative_list = Mock(
        return_value=PageResult(
            (CreativeItemDbEntryView(source=_entry(), registration=_registration()),), None, False
        )
    )
    try:
        with client:
            response = client.post(
                "/api/v1/item-db/creative/search?approval_state=APPROVED", json=_filters()
            )
        assert response.status_code == 200
        value = response.json()["data"][0]
        assert value["source"]["external_number"] == "12345"
        assert value["registration"]["approval_state"] == "APPROVED"
        assert reads.creative_list.call_args.args[0].conditions[0].field == "AD"
        assert reads.creative_list.call_args.args[1] == "APPROVED"
    finally:
        services.engine.dispose()


def test_creative_metadata_is_not_available_without_source_permission():
    client, services, reads = _client(allow_intake=False)
    reads.creative_list = Mock()
    try:
        with client:
            response = client.post("/api/v1/item-db/creative/search", json=_filters())
        assert response.status_code == 403
        reads.creative_list.assert_not_called()
    finally:
        services.engine.dispose()


def test_invalid_approval_filter_does_not_reach_catalog():
    client, services, reads = _client()
    reads.creative_list = Mock()
    try:
        with client:
            response = client.post(
                "/api/v1/item-db/creative/search?approval_state=AI", json=_filters()
            )
        assert response.status_code == 422
        reads.creative_list.assert_not_called()
    finally:
        services.engine.dispose()


def test_ai_category_can_show_pending_approval_without_intake_permission():
    from eom_api_contracts.item_db_registration import AiItemDbEntryView

    client, services, _reads = _client(allow_intake=False)
    services.queries.ai_item_db_entries = Mock(
        return_value=PageResult(
            (AiItemDbEntryView(registration=_registration("IN_REVIEW"), title="AI 생성 문항"),),
            None,
            False,
        )
    )
    try:
        with client:
            response = client.get("/api/v1/item-db/ai?approval_state=IN_REVIEW")
        assert response.status_code == 200
        entry = response.json()["data"][0]
        assert entry["registration"]["approval_state"] == "IN_REVIEW"
        assert "source" not in entry
        services.queries.ai_item_db_entries.assert_called_once_with(
            approval_state="IN_REVIEW", limit=50, cursor=None
        )
    finally:
        services.engine.dispose()


def test_graph_navigation_checks_the_exact_manifest_and_does_not_promote_pending_items():
    client, services, _reads = _client()
    registration = _registration()
    candidate = SimpleNamespace(
        item_manifest_sha256=registration.item_manifest_sha256, item_revision_state="IN_REVIEW"
    )
    services.queries.production_item_candidates = Mock(
        return_value=PageResult((candidate,), None, False)
    )
    try:
        path = f"/api/v1/item-db/registrations/{registration.item_revision_id}/graph"
        with client:
            pending = client.get(
                path, params={"manifest_sha256": registration.item_manifest_sha256}
            )
            stale = client.get(path, params={"manifest_sha256": "sha256:" + "f" * 64})
        assert pending.status_code == 200 and pending.json()["data"] is None
        assert stale.status_code == 409
        assert (
            services.queries.production_item_candidates.call_args.kwargs["selected_revision_id"]
            == registration.item_revision_id
        )
    finally:
        services.engine.dispose()


def test_registered_db_schema_is_packaged_and_matches_the_typed_projection():
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    root = Path(__file__).resolve().parents[2]
    names = ("external-item-db-view-v1", "item-db-registration-v1", "item-db-registered-view-v1")
    documents = {}
    for name in names:
        source = root / "schemas/api/v1" / f"{name}.schema.json"
        packaged = root / "packages/api_contracts/eom_api_contracts/schemas" / source.name
        assert source.read_bytes() == packaged.read_bytes()
        document = json.loads(source.read_text())
        Draft202012Validator.check_schema(document)
        documents[document["$id"]] = document
    registry = Registry().with_resources(
        (key, Resource.from_contents(value)) for key, value in documents.items()
    )
    view = documents["eom://schemas/api/item-db-registered-view/1.0"]
    Draft202012Validator(view["$defs"]["creative"], registry=registry).validate(
        CreativeItemDbEntryView(source=_entry(), registration=_registration()).model_dump(
            mode="json"
        )
    )
