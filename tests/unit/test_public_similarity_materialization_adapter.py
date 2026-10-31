"""Actual SQLite/temporary context member IO; current QUERY/source results are synthetic."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.public_similarity_materialization import resolve_public_similarity_materials
from eom_workflow.public_similarity_control import bind_public_similarity_execution_plan
from eom_workflow_runner import public_similarity_materialization_adapter as module
from eom_workflow_runner.public_similarity_materialization_adapter import (
    CatalogPublicSimilarityMaterializationReader,
)
from pydantic import TypeAdapter

from tests.unit.public_similarity_materialization_fixtures import public_materialization_case
from tests.unit.test_public_solution_context_artifact import public_publish
from tests.unit.test_similarity_context_artifact import publisher_for


@pytest.fixture(params=(False, True))
def reading(tmp_path, monkeypatch, request):
    base = tmp_path / "base"
    base.mkdir()
    case = public_materialization_case(base, monkeypatch, registered=request.param)
    place = tmp_path / "publication"
    place.mkdir()
    publisher = publisher_for(place)
    receipt = public_publish(publisher, case["context"])
    plan = bind_public_similarity_execution_plan(case["base"], receipt.delivery, case["context"])
    caller = EmbeddingRegistryCaller(case["bound"].operator_id)
    selection = CompletedSimilarityQuerySelection(
        workflow_id="workflow_" + "f" * 32,
        workflow_request_sha256="sha256:" + "0" * 64,
        context_request_sha256=case["context"].request.request_sha256,
    )
    owner = SimpleNamespace(settings=publisher.settings, catalog=object())
    selected = Mock(return_value=SimpleNamespace(context_request=case["context"].request))
    current = Mock(return_value=case["context"])
    material = Mock(return_value=case["references"])
    monkeypatch.setattr(module, "select_completed_reference_query_request", selected)
    monkeypatch.setattr(
        module, "select_completed_reference_query_read_owner", lambda original, request: original
    )
    monkeypatch.setattr(module, "read_completed_public_solution_similarity_in_session", current)
    monkeypatch.setattr(
        module,
        "CatalogPublicSolutionMaterialsRead",
        lambda catalog: SimpleNamespace(read_in_session=material),
    )
    bound = replace(
        case["bound"], reader=CatalogPublicSimilarityMaterializationReader(owner, caller, selection)
    )
    return case | dict(
        publisher=publisher,
        receipt=receipt,
        plan=plan,
        bound=bound,
        selected=selected,
        current=current,
        material=material,
        owner=owner,
        caller=caller,
        selection=selection,
    )


def read(case, session, **changes):
    values = dict(
        plan=case["plan"],
        step_key="authoring",
        context=case["bound"],
        original_source=TypeAdapter(PopulationSource).validate_python(case["original_source"]),
        canonical_artifact_root=case["publisher"].settings.nas_artifact_root,
        authorized_artifact_revision_ids=frozenset(
            {case["receipt"].delivery.context_member.artifact_revision_id}
        ),
    )
    return resolve_public_similarity_materials(session, **(values | changes))


def test_actual_member_read_is_between_two_current_checks_in_one_root(reading):
    case = reading
    primary = next(case["publisher"].settings.nas_artifact_root.rglob("context.json"))
    before = primary.stat()
    with case["publisher"].sessions.begin() as session:
        root = session.get_transaction()
        assert read(case, session) == case["payload"]
        assert session.get_transaction() is root and not session.new and not session.dirty
        assert [call.args for call in case["current"].call_args_list] == [
            (session, case["owner"], case["caller"], case["selection"])
        ] * 2
    assert primary.stat() == before and case["material"].call_count == 1


@pytest.mark.parametrize("late", (False, True))
@pytest.mark.parametrize(
    "code", ("SOURCE_REVOKED", "AUTHORITY_UNAVAILABLE", "QUERY_RESULT_INVALID")
)
def test_denial_before_or_after_io_never_returns_saved_permission(reading, late, code):
    case = reading
    error = SimilarityContextReadError(code)
    case["current"].side_effect = [case["context"], error] if late else error
    with case["publisher"].sessions.begin() as session, pytest.raises(ControlPlaneError) as caught:
        read(case, session)
    assert caught.value.code == (
        "CONTROL_SIMILARITY_AUTHORITY_DENIED"
        if code == "SOURCE_REVOKED"
        else "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
        if code == "AUTHORITY_UNAVAILABLE"
        else "CONTROL_SIMILARITY_CONTEXT_INVALID"
    )
    assert case["material"].call_count == int(late)


@pytest.mark.parametrize("fault", ("bytes", "revision", "job", "root", "late_revision"))
def test_actual_file_producer_and_lifecycle_are_not_bypassed(reading, tmp_path, fault):
    case = reading
    pin = case["receipt"].delivery.context_member
    options = {}
    with case["publisher"].sessions.begin() as session:
        if fault == "bytes":
            next(case["publisher"].settings.nas_artifact_root.rglob("context.json")).write_bytes(
                b"{}"
            )
        elif fault == "revision":
            session.get(ArtifactRevisionRecord, pin.artifact_revision_id).approved = False
        elif fault == "job":
            session.get(JobRecord, case["receipt"].owner_job_id).status = "FAILED"
        elif fault == "root":
            options["canonical_artifact_root"] = tmp_path
        else:

            def revoke(*arguments):
                if case["current"].call_count == 2:
                    session.get(ArtifactRevisionRecord, pin.artifact_revision_id).approved = False
                    session.flush()
                return case["context"]

            case["current"].side_effect = revoke
        session.flush()
        with pytest.raises(ControlPlaneError):
            read(case, session, **options)


def test_direct_current_operator_revocation_is_not_a_generic_or_cached_success(reading):
    case = reading
    case["current"].side_effect = [
        case["context"],
        OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"),
    ]
    with case["publisher"].sessions.begin() as session, pytest.raises(ControlPlaneError) as caught:
        read(case, session)
    assert caught.value.code == "CONTROL_SIMILARITY_AUTHORITY_DENIED"
