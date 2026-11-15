"""Exact-score Registry/Artifact transactions on guarded disposable PostgreSQL.

Worker/source admission and Native binding selection are the explicitly synthetic
ports from the existing fixtures. Source score reads, Registry, released Packs,
Artifact hashes, concurrency and replay use the real owners. No live AI calls.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from eom_catalog_contracts.material_item_lineage import (
    MATERIAL_ITEM_LINEAGE_V3_REF,
    MaterialItemLineageV3,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRevisionRecord
from eom_identifiers import content_sha256
from eom_workflow.models import MaterialLearningRoleResultV3
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_material_coverage_registration_storage import (
    controls as controls,
)
from tests.integration.test_material_coverage_registration_storage import (
    coverage_registration as coverage_registration,
)
from tests.integration.test_material_coverage_registration_storage import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_material_coverage_registration_storage import (
    material_intake as material_intake,
)
from tests.integration.test_material_coverage_registration_storage import (
    registration_case as registration_case,
)
from tests.integration.test_material_native_registration_storage import (
    native_registration_case as native_registration_case,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
SCORES = [{"family": 3, "points": points} for points in ("1.5", "2.5", 2)]


def assert_exact_registration(creative_engine, service, resolved, registered, count):
    assert isinstance(registered.lineage, MaterialItemLineageV3)
    assert registered.lineage.role_result == resolved.result_pointer
    assert registered.lineage.result_sha256 == content_sha256(
        resolved.role.output.learning_result.model_dump(mode="json")
    )
    with Session(creative_engine) as session:
        revision = session.get(ItemRevisionRecord, registered.item_revision_id)
        assert revision.revision_state == "APPROVED"
        components = {
            (row.component_type, row.ordinal): row
            for row in session.scalars(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == registered.item_revision_id
                )
            )
        }
        assert len(components) == count
        assert components[("SOURCE_REFERENCE", 0)].schema_ref == MATERIAL_ITEM_LINEAGE_V3_REF
        expected = resolved.role.output.learning_result.proposal.content.score.points
        component = components[("ITEM_CONTENT", 0)]
        assert component.schema_ref == (
            "eom.assessment.item-content/1.1"
            if isinstance(expected, str)
            else "eom.assessment.item-content/1.0"
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ItemRevisionRecord)
                .where(ItemRevisionRecord.registration_key == revision.registration_key)
            )
            == 1
        )
    content = service.registry.load_item_content(registered.item_revision_id)
    assert content.score.points == expected
    assert type(content.score.points) is type(expected)
    assert content.solution == resolved.role.output.learning_result.proposal.content.solution


@pytest.mark.parametrize("coverage_registration", SCORES, indirect=True)
def test_exact_score_concurrent_general_registration_replays_one_revision(
    creative_engine, coverage_registration
):
    create, resolved = coverage_registration
    barrier = Barrier(2)

    def register(_):
        service = create()
        barrier.wait(timeout=10)
        return service.register_completed(
            task_id=resolved.task_id, operator_id=resolved.operator_id
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(register, range(2))
    assert first.item_revision_id == second.item_revision_id
    assert sum((first.created, second.created)) == 1
    assert_exact_registration(creative_engine, create(), resolved, first, 3)
    replay = create().register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    assert not replay.created and replay.lineage == first.lineage


@pytest.mark.parametrize("coverage_registration", [SCORES[0]], indirect=True)
def test_exact_score_post_commit_interruption_recovers_without_duplicate(
    creative_engine, coverage_registration
):
    create, resolved = coverage_registration
    service = create()
    register = service.registry.register

    def interrupted(command):
        register(command)
        raise RuntimeError("synthetic exact-score post-commit interruption")

    service.registry.register = interrupted
    with pytest.raises(RuntimeError, match="post-commit interruption"):
        service.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    replay = create().register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    assert not replay.created
    assert_exact_registration(creative_engine, create(), resolved, replay, 3)


@pytest.mark.parametrize("native_registration_case", SCORES, indirect=True)
def test_exact_native_score_keeps_both_editable_documents_metadata_and_replay(
    creative_engine, native_registration_case
):
    create, resolved, binding = native_registration_case
    service = create()
    registered = service.register_completed(
        task_id=resolved.task_id, operator_id=resolved.operator_id
    )
    assert_exact_registration(creative_engine, service, resolved, registered, 6)
    with Session(creative_engine) as session:
        revision = session.get(ItemRevisionRecord, registered.item_revision_id)
        assert revision.metadata_json["external_number"] == binding.source_metadata.external_number
        assert revision.metadata_json["source_kind"] == "EXTERNAL"
        for key, value in binding.source_metadata.model_dump(mode="json").items():
            assert revision.metadata_json[key] == value
        for ordinal, source in enumerate((binding.question, binding.solution)):
            component = session.scalar(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == revision.item_revision_id,
                    ItemComponentRecord.component_type == "OTHER",
                    ItemComponentRecord.ordinal == ordinal,
                )
            )
            assert (component.artifact_id, component.artifact_revision_id, component.sha256) == (
                source.document.artifact_id,
                source.document.artifact_revision_id,
                source.document.sha256,
            )
    replay = create().register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    assert not replay.created and replay.lineage == registered.lineage


@pytest.mark.parametrize("native_registration_case", [SCORES[0]], indirect=True)
@pytest.mark.parametrize("wrong", [0, 15, 2, None])
def test_native_original_score_blocks_wrong_cached_proposal_before_registry_write(
    creative_engine, native_registration_case, monkeypatch, wrong
):
    from eom_catalog_service import material_item_registration as owner

    create, resolved, _binding = native_registration_case
    body = resolved.role.model_dump(mode="json")
    body["output"]["learning_result"]["proposal"]["content"]["score"] = {
        "state": "UNPRINTED" if wrong is None else "PRINTED",
        "points": wrong,
    }
    altered = replace(resolved, role=MaterialLearningRoleResultV3.model_validate(body))
    monkeypatch.setattr(owner, "resolve_completed_material_task", lambda *_a, **_k: altered)
    with Session(creative_engine) as session:
        before = session.scalar(select(func.count()).select_from(ItemRevisionRecord))
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_SCORE_MISMATCH"):
        create().register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    with Session(creative_engine) as session:
        assert session.scalar(select(func.count()).select_from(ItemRevisionRecord)) == before
