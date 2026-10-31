"""Real temporary publication plus synthetic current controls/QUERY; no live authority."""

from types import SimpleNamespace

from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_identifiers import content_sha256
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_orchestrator.similarity_context_artifact import PublishedPublicSolutionSimilarityContext
from eom_workflow.public_similarity_control import PreparedPublicSimilarityPlan
from eom_workflow_runner.item_similarity_preparation import (
    PreparedPublicItemSimilarity,
    validate_public_item_similarity_scope,
)

from tests.unit.item_similarity_start_fixtures import start_source
from tests.unit.public_similarity_materialization_fixtures import public_materialization_case
from tests.unit.test_public_solution_context_artifact import public_publish


def promote_public_source(data, tmp_path, monkeypatch, *, ordinary=False, registered=False):
    place = tmp_path / "public-reference"
    place.mkdir()
    case = public_materialization_case(place, monkeypatch, ordinary=ordinary, registered=registered)
    source = data.source
    source.resolution = source.resolution.model_copy(
        update={
            "content_pack_version": "1.20.18",
            "content_pack_bundle_sha256": SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.18"],
        }
    )
    data.runtime["content_pack"].update(
        version="1.20.18", release_sha256=SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.18"]
    )
    validate_public_item_similarity_scope(
        workflow_request=source.request,
        expected_resolution=source.resolution,
        evidence=source.evidence,
        preset=source.preset,
        context_request=case["context"].request,
    )
    publication = public_publish(source.publisher, case["context"])
    selection = CompletedSimilarityQuerySelection(
        workflow_id="workflow_" + "f" * 32,
        workflow_request_sha256="sha256:" + "a" * 64,
        context_request_sha256=case["context"].request.request_sha256,
    )
    prepared = PreparedPublicItemSimilarity(
        PreparedPublicSimilarityPlan(publication.delivery, case["context"]),
        PublishedPublicSolutionSimilarityContext(
            publication.owner_job_id, publication.delivery, publication.manifest_sha256
        ),
        content_sha256(source.request.model_dump(mode="json")),
        source.evidence.result_sha256,
        source.preset.content_sha256,
        source.resolution,
        selection,
        data.actor.actor_id,
    )
    return SimpleNamespace(
        data=data,
        source=source,
        case=case,
        prepared=prepared,
        publication=publication,
        selection=selection,
    )


def public_start_source(tmp_path, monkeypatch, *, ordinary=False, registered=False):
    source_root = tmp_path / "source"
    source_root.mkdir()
    data = start_source(source_root, monkeypatch, ordinary=ordinary)
    return promote_public_source(
        data, tmp_path, monkeypatch, ordinary=ordinary, registered=registered
    )
