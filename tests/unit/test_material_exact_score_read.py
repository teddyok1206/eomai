"""Exact-score canonical/visual socket reads with a declared synthetic Registry port."""

import hashlib
import json
import threading
from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts import AssessmentItemContentV1_1
from eom_catalog_contracts.application import catalog_application_schema_route
from eom_catalog_contracts.creative_visual_presentation import ItemVisualPresentation
from eom_catalog_contracts.material_item_lineage import (
    MaterialItemLineageV3,
    parse_material_item_lineage,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from eom_workflow.schemas import role_schema_bundle_hash
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_assessment_item_content import item_content
from tests.unit.test_catalog_application_boundary import FakeRegistry, _client, _server
from tests.unit.test_creative_visual_presentation import pointer
from tests.unit.test_material_item_registration_versions import resolved_case


def content(points):
    value = item_content()
    value.update(schema_version="1.1", score={"points": points})
    return AssessmentItemContentV1_1.model_validate(value)


@pytest.mark.parametrize("points", ["1.5", "2.5"])
def test_both_canonical_and_visual_socket_roundtrip_preserve_score_body_and_image(tmp_path, points):
    canonical = content(points)
    source = pointer("assessment-item-content.json", "eom.assessment.item-content/1.1")
    source = source.model_copy(update={"sha256": content_sha256(canonical.model_dump(mode="json"))})
    view = ItemVisualPresentation(
        item_id="item_" + "1" * 32,
        item_revision_id="itemrev_" + "2" * 32,
        source_content=source,
        display_content=source,
        content=canonical,
    )

    class Registry(FakeRegistry):
        def load_item_content(self, revision_id):
            assert revision_id == view.item_revision_id
            return canonical

        def load_item_visual_presentation(self, revision_id):
            assert revision_id == view.item_revision_id
            return view

    server = _server(tmp_path, registry=Registry())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = _client(server)
        for _ in range(2):
            assert client.load_item_content(view.item_revision_id) == canonical
            assert client.load_item_visual_presentation(view.item_revision_id) == view
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert canonical.score.points == points
    assert canonical.body == content(points).body


def test_exact_read_uses_new_response_only_and_does_not_widen_historical_import_request():
    from eom_api_contracts.items import StructuredItemContentImportRequest
    from eom_catalog_contracts.application import ReviewedItemContentImportCommand

    route = catalog_application_schema_route("GET_ITEM_CONTENT", content_schema_version="1.1")
    assert (route.request_schema, route.response_schema) == (
        "catalog-application-request-v10",
        "catalog-application-response-v19",
    )
    value = {
        "status": "OK",
        "operation": "GET_ITEM_CONTENT",
        "content": content("1.5").model_dump(mode="json"),
    }
    validate_contract(route.response_schema, value)
    for old in (
        "catalog-application-response-v10",
        "catalog-application-response-v12",
        "catalog-application-response-v13",
    ):
        with pytest.raises(SchemaError):
            validate_contract(old, value)
    assert catalog_application_schema_route(
        "IMPORT_REVIEWED_ITEM_CONTENT", content_schema_version="1.1"
    ) == catalog_application_schema_route("IMPORT_REVIEWED_ITEM_CONTENT")
    with pytest.raises(ValueError):
        StructuredItemContentImportRequest(
            reviewed=True,
            review_reason="원문 그대로의 배점과 그림 등록 전용입니다.",
            content=content("1.5"),
        )
    with pytest.raises(ValueError):
        ReviewedItemContentImportCommand(
            base_revision_id="itemrev_" + "1" * 32,
            expected_version=1,
            reviewed_by="operator_test_admin",
            review_reason="원문 그대로의 배점과 그림 등록 전용입니다.",
            content=content("1.5"),
        )
    for wrong in (15, 0, 1.5, "1.50"):
        tampered = deepcopy(value)
        tampered["content"]["score"]["points"] = wrong
        if type(wrong) is int:
            # Integer values are legal in canonical1.1; the Native source owner,
            # not the generic content read schema, rejects a wrong source score.
            validate_contract(route.response_schema, tampered)
        else:
            with pytest.raises(SchemaError):
                validate_contract(route.response_schema, tampered)


def test_lineage3_pins_exact_result_family_and_hash_not_only_a_version_label(monkeypatch):
    from eom_catalog_service.material_item_registration import material_item_lineage

    resolved, canonical = resolved_case(monkeypatch, exact_score=True)
    lineage = material_item_lineage(resolved, canonical)
    assert parse_material_item_lineage(lineage.model_dump(mode="json")) == lineage
    for schema in ("material-learning-result@1.0", "material-learning-result@2.0"):
        body = lineage.model_dump(mode="json")
        body["role_result"]["schema_ref"] = schema
        body["lineage_sha256"] = content_sha256(
            {k: v for k, v in body.items() if k != "lineage_sha256"}
        )
        with pytest.raises((ValueError, SchemaError)):
            MaterialItemLineageV3.model_validate(body)
    body = lineage.model_dump(mode="json")
    body["registered_content_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError):
        MaterialItemLineageV3.model_validate(body)


@pytest.mark.parametrize(
    "relative",
    [
        "material-learning/item-lineage-v3.schema.json",
        "material-learning/visual-set-v2.schema.json",
        "catalog-application/catalog-application-response-v19.schema.json",
        "item-registry/catalog-item-visual-presentation-response-v2.schema.json",
    ],
)
def test_new_read_and_lineage_schemas_have_exact_installed_mirrors(relative):
    root = Path(__file__).resolve().parents[2]
    original = (root / "schemas" / relative).read_bytes()
    assert (
        original
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts/resources" / relative
        ).read_bytes()
    )
    assert json.loads(original)["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_all_forty_pre_score_role_bundles_keep_the_reviewed_baseline_hashes():
    """Baseline6607eed1: new registered/read resources must not enter old closures."""
    versions = ["workflow-role/1.0.1", *(f"workflow-role/1.{i}.0" for i in range(1, 40))]
    values = [{"protocol": value, "hash": role_schema_bundle_hash(value)} for value in versions]
    payload = json.dumps(values, sort_keys=True, separators=(",", ":")) + "\n"
    assert hashlib.sha256(payload.encode()).hexdigest() == (
        "cae5d6b976b54e27f797b90c84d7b367b1c08257154acf0dfa91c6eb8f5e16f8"
    )
