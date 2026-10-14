"""Actual local Artifact reader; current IAM/source/QUERY observations are synthetic fixtures."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.similarity_context import (
    parse_similarity_context,
    parse_similarity_context_request,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.similarity_materialization import (
    SimilarityMaterializationContext,
    resolve_similarity_materials,
)
from eom_workflow.similarity_control import bind_similarity_execution_plan
from eom_workflow_runner.similarity_materialization_adapter import (
    CatalogSimilarityMaterializationReader,
)
from pydantic import TypeAdapter

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.similarity_plan_fixtures import similarity_case
from tests.unit.test_similarity_context_artifact import publish, publisher_for


class CurrentReader:
    def __init__(self, context):
        self.current = context
        self.late = context
        self.calls = []
        self.on_late = None

    def compose(self, caller, request):
        self.calls.append((caller, request))
        if len(self.calls) == 2:
            if self.on_late is not None:
                self.on_late()
            return self.late
        return self.current


def materialization_case(tmp_path, monkeypatch):
    base = tmp_path / "base"
    base.mkdir()
    case = similarity_case(base, monkeypatch)
    publication = tmp_path / "publication"
    publication.mkdir()
    publisher = publisher_for(publication)
    receipt = publish(publisher, case["context"])
    plan = bind_similarity_execution_plan(case["base"], receipt.delivery, case["context"])
    reader = CurrentReader(case["context"])
    caller = EmbeddingRegistryCaller("operator_" + "a" * 32)
    context = SimilarityMaterializationContext(
        workflow_id=plan.workflow_id,
        operator_id=caller.operator_id,
        request=case["context"].request,
        reader=CatalogSimilarityMaterializationReader(caller, reader),
    )
    original = TypeAdapter(PopulationSource).validate_python(case["original_source"])
    return case | {
        "publisher": publisher,
        "receipt": receipt,
        "plan": plan,
        "reader": reader,
        "caller": caller,
        "bound": context,
        "original": original,
    }


def resolve(case, session, **changes):
    arguments = {
        "plan": case["plan"],
        "step_key": "authoring",
        "context": case["bound"],
        "original_source": case["original"],
        "canonical_artifact_root": case["publisher"].settings.nas_artifact_root,
        "authorized_artifact_revision_ids": frozenset(
            (case["receipt"].delivery.context_member.artifact_revision_id,)
        ),
    }
    arguments.update(changes)
    return resolve_similarity_materials(session, **arguments)


def failed_context(context, code):
    raw = context.model_dump(mode="json")
    raw.update(
        status="FAILED",
        population=None,
        query_execution=None,
        graph_evidence=None,
        candidates=[],
        error_code=code,
    )
    return parse_similarity_context(seal(raw, "context_sha256"))


@pytest.mark.parametrize("step_key", ("authoring", "review"))
def test_exact_member_is_read_between_two_current_checks_without_query_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step_key: str
) -> None:
    case = materialization_case(tmp_path, monkeypatch)
    path = next(case["publisher"].settings.nas_artifact_root.rglob("context.json"))
    before = path.stat()
    with case["publisher"].sessions.begin() as session:
        raw = resolve(case, session, step_key=step_key)
    assert raw == canonical_json_bytes(case["context"].model_dump(mode="json"))
    assert case["reader"].calls == [(case["caller"], case["context"].request)] * 2
    assert path.stat() == before


@pytest.mark.parametrize(
    "fault", ("no_context", "other_flow", "other_request", "other_step", "allowlist")
)
def test_missing_or_foreign_expectations_deny_before_common_or_member_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    case = materialization_case(tmp_path, monkeypatch)
    changes = {}
    if fault == "no_context":
        changes["context"] = None
    elif fault == "other_flow":
        changes["context"] = replace(case["bound"], workflow_id="workflow_" + "0" * 32)
    elif fault == "other_request":
        raw = case["context"].request.model_dump(mode="json")
        raw["request_id"] = "similarityrequest_" + "0" * 32
        changes["context"] = replace(
            case["bound"], request=parse_similarity_context_request(seal(raw, "request_sha256"))
        )
    elif fault == "other_step":
        changes["step_key"] = "image"
    else:
        changes["authorized_artifact_revision_ids"] = frozenset()
    with case["publisher"].sessions.begin() as session, pytest.raises(ControlPlaneError):
        resolve(case, session, **changes)
    assert not case["reader"].calls


@pytest.mark.parametrize(
    "code", ("SOURCE_ACCESS_DENIED", "SOURCE_REVOKED", "AUTHORITY_UNAVAILABLE")
)
@pytest.mark.parametrize("late", (False, True))
def test_current_denial_is_not_optional_absence_or_saved_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str, late: bool
) -> None:
    case = materialization_case(tmp_path, monkeypatch)
    setattr(case["reader"], "late" if late else "current", failed_context(case["context"], code))
    expected = "UNAVAILABLE" if code == "AUTHORITY_UNAVAILABLE" else "DENIED"
    with (
        case["publisher"].sessions.begin() as session,
        pytest.raises(ControlPlaneError) as captured,
    ):
        resolve(case, session)
    assert captured.value.code == "CONTROL_SIMILARITY_AUTHORITY_" + expected
    assert len(case["reader"].calls) == (2 if late else 1)


@pytest.mark.parametrize(
    "field", ("item_id", "item_revision_id", "sha256", "member_path", "artifact_revision_id")
)
def test_original_member_identity_is_not_replaced_by_same_source_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    case = materialization_case(tmp_path, monkeypatch)
    original = case["original"].model_dump(mode="json")
    if field in {"item_id", "item_revision_id"}:
        original[field] = ("item_" if field == "item_id" else "itemrev_") + "0" * 32
    else:
        original["artifact_member"][field] = {
            "sha256": "sha256:" + "0" * 64,
            "member_path": "other-content.json",
            "artifact_revision_id": "rev_" + "0" * 32,
        }[field]
    with (
        case["publisher"].sessions.begin() as session,
        pytest.raises(ControlPlaneError) as captured,
    ):
        resolve(
            case,
            session,
            original_source=TypeAdapter(PopulationSource).validate_python(original),
        )
    assert captured.value.code == "CONTROL_SIMILARITY_SOURCE_MISMATCH"
    assert len(case["reader"].calls) == 1


@pytest.mark.parametrize(
    "fault",
    (
        "bytes",
        "missing_bytes",
        "revision_unapproved",
        "logical_unapproved",
        "job_failed",
        "missing_revision",
        "wrong_kind",
        "wrong_root",
    ),
)
def test_pinned_target_integrity_and_lifecycle_are_checked_at_actual_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    case = materialization_case(tmp_path, monkeypatch)
    pin = case["receipt"].delivery.context_member
    path = next(case["publisher"].settings.nas_artifact_root.rglob("context.json"))
    changes = {}
    with case["publisher"].sessions.begin() as session:
        if fault == "bytes":
            path.write_bytes(b"{}")
        elif fault == "missing_bytes":
            path.unlink()
        elif fault == "revision_unapproved":
            session.get(ArtifactRevisionRecord, pin.artifact_revision_id).approved = False
        elif fault == "logical_unapproved":
            session.get(ArtifactRecord, pin.artifact_id).approved = False
        elif fault == "job_failed":
            session.get(JobRecord, case["receipt"].owner_job_id).status = "FAILED"
        elif fault == "missing_revision":
            session.delete(session.get(ArtifactRevisionRecord, pin.artifact_revision_id))
        elif fault == "wrong_kind":
            session.get(ArtifactRecord, pin.artifact_id).artifact_type = "control_other"
        else:
            outside = tmp_path / "different-storage"
            outside.mkdir()
            changes["canonical_artifact_root"] = outside
        session.flush()
        with pytest.raises(ControlPlaneError) as captured:
            resolve(case, session, **changes)
    assert captured.value.code == "CONTROL_SIMILARITY_CONTEXT_INVALID"
    assert len(case["reader"].calls) == 1


@pytest.mark.parametrize("change", ("context", "target_lifecycle"))
def test_late_change_cannot_publish_stale_workspace_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    case = materialization_case(tmp_path, monkeypatch)
    with case["publisher"].sessions.begin() as session:
        if change == "target_lifecycle":
            revision = session.get(
                ArtifactRevisionRecord, case["receipt"].delivery.context_member.artifact_revision_id
            )

            def revoke():
                revision.approved = False
                session.flush()

            case["reader"].on_late = revoke
        else:
            raw = case["context"].model_dump(mode="json")
            raw["candidates"][0]["observations"][0]["graph_relevance_milli"] += 1
            case["reader"].late = parse_similarity_context(seal(raw, "context_sha256"))
        with pytest.raises(ControlPlaneError) as captured:
            resolve(case, session)
    assert captured.value.code == "CONTROL_SIMILARITY_CONTEXT_INVALID"
    assert len(case["reader"].calls) == 2


def test_late_file_change_cannot_replace_already_verified_canonical_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = materialization_case(tmp_path, monkeypatch)
    path = next(case["publisher"].settings.nas_artifact_root.rglob("context.json"))
    case["reader"].on_late = lambda: path.write_bytes(b"{}")
    with case["publisher"].sessions.begin() as session:
        assert resolve(case, session) == canonical_json_bytes(
            case["context"].model_dump(mode="json")
        )
    assert path.read_bytes() == b"{}"
    case["reader"].calls.clear()
    case["reader"].on_late = None
    with (
        case["publisher"].sessions.begin() as session,
        pytest.raises(ControlPlaneError) as captured,
    ):
        resolve(case, session)
    assert captured.value.code == "CONTROL_SIMILARITY_CONTEXT_INVALID"


def test_actual_caller_cannot_be_replaced_by_a_context_operator_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = materialization_case(tmp_path, monkeypatch)
    foreign = replace(case["bound"], operator_id="operator_" + "0" * 32)
    with (
        case["publisher"].sessions.begin() as session,
        pytest.raises(ControlPlaneError) as captured,
    ):
        resolve(case, session, context=foreign)
    assert captured.value.code == "CONTROL_SIMILARITY_AUTHORITY_DENIED"
    assert not case["reader"].calls


@pytest.mark.parametrize("payload", (b"{}", "not-bytes", b"x" * (512 * 1024 + 1)))
def test_port_returned_payload_must_match_the_exact_bounded_member_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload
) -> None:
    case = materialization_case(tmp_path, monkeypatch)

    class WrongPayloadReader:
        def resolve(self, session, **kwargs):
            return payload

    with (
        case["publisher"].sessions.begin() as session,
        pytest.raises(ControlPlaneError) as captured,
    ):
        resolve(case, session, context=replace(case["bound"], reader=WrongPayloadReader()))
    assert captured.value.code == "CONTROL_SIMILARITY_CONTEXT_INVALID"
