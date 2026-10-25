"""Canonical bulk metadata IO with synthetic source/IAM leaves; no model or live corpus writes."""

from dataclasses import replace

import pytest
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from eom_identifiers import canonical_json_bytes
from eom_workflow.embedding_batch_plan import MAX_BATCH_PLAN_BYTES
from eom_workflow.embedding_batch_plan_v11 import BATCH_SELECTION_V11_SCHEMA_REF
from eom_workflow_runner.embedding_batch_plan_admission import CatalogEmbeddingBatchPlanAdmission

from tests.unit.embedding_bulk_plan_fixtures import bulk_planning_case
from tests.unit.test_embedding_batch_plan_admission import source_case


@pytest.fixture
def admitted(tmp_path, monkeypatch):
    value = source_case(tmp_path, monkeypatch, planned=bulk_planning_case())
    yield value
    value.engine.dispose()


def test_bulk_canonical_metadata_is_read_with_current_original_source_closure(admitted):
    value = admitted
    assert value.request.selection_manifest.schema_ref == BATCH_SELECTION_V11_SCHEMA_REF
    with (
        value.publisher.sessions.begin() as session,
        value.owner.admit(session, value.request) as current,
    ):
        assert len(current.selection.anchors) == len(current.sources.sources) == 520
        assert current.selection == value.selection
    assert (
        value.controls.publish_batch_selection(value.selection, idempotency_key=value.selection_key)
        == value.saved_selection
    )
    assert len(canonical_json_bytes(value.request.model_dump(mode="json"))) < 16384


@pytest.mark.parametrize("fault", ("denied", "missing_source", "changed_source"))
def test_bulk_replay_does_not_cache_authority_or_replace_missing_source(admitted, fault):
    value = admitted
    with value.publisher.sessions.begin() as session, value.owner.admit(session, value.request):
        pass
    if fault == "denied":
        value.denied = True
    elif fault == "missing_source":
        value.current = replace(value.current, sources=value.current.sources[:-1])
    else:
        source = value.current.sources[-1]
        changed = type(source).model_validate(
            source.model_dump(mode="json") | {"item_id": "item_" + "f" * 32}
        )
        value.current = replace(value.current, sources=(*value.current.sources[:-1], changed))
    with (
        pytest.raises(ValueError),
        value.publisher.sessions.begin() as session,
        value.owner.admit(session, value.request),
    ):
        pytest.fail("invalid bulk source entered admission")


def test_bulk_contract_does_not_expand_actual_owner_source_cap(admitted):
    value = admitted
    scope = replace(value.scope, maximum_sources=64)
    owner = CatalogEmbeddingBatchPlanAdmission(
        value.catalog, value.caller, replace(value.owner.configuration, source_scope=scope)
    )
    # Only the metadata scope ceiling is changed in this isolated synthetic leaf.
    value.catalog.authorize_scope = lambda session, caller, lookup: None
    with (
        pytest.raises(EmbeddingRegistryError),
        value.publisher.sessions.begin() as session,
        owner.admit(session, value.request),
    ):
        pytest.fail("bulk metadata bypassed source cap")


def test_bulk_canonical_read_accepts_a_genuine_metadata_member_above_legacy_byte_cap(
    tmp_path, monkeypatch
):
    value = source_case(tmp_path, monkeypatch, planned=bulk_planning_case(1024))
    try:
        assert (
            len(canonical_json_bytes(value.selection.model_dump(mode="json")))
            > MAX_BATCH_PLAN_BYTES
        )
        with (
            value.publisher.sessions.begin() as session,
            value.owner.admit(session, value.request) as current,
        ):
            assert len(current.selection.anchors) == len(current.sources.sources) == 1024
    finally:
        value.engine.dispose()
