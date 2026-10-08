"""The real Catalog chat boundary reuses exact accepted additive report evidence."""

import json
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service import chat_knowledge_resolution as resolution
from eom_identity_service.models import OperatorRecord
from eom_operator_identity import PermissionKey
from eom_protocol.general_chat_grounding import ChatKnowledgeCatalogRequest

from tests.unit.test_assessment_item_content import item_content
from tests.unit.test_knowledge_retrieval_service import _solution_evidence


def resolve(monkeypatch, *, mutate=None, reports=True, approved=True):
    evidence = _solution_evidence()
    if mutate:
        evidence = mutate(evidence)
    reference = {
        "item_id": "item_" + "b" * 32,
        "item_revision_id": "itemrev_" + "c" * 32,
        "manifest_sha256": "sha256:" + "a" * 64,
    }
    source = _solution_evidence().source.artifact_member
    base_pointer = _solution_evidence().base_accepted_result
    base_id = "analysisrun_" + "3" * 32
    association = SimpleNamespace(
        analysis_run_id=base_id,
        source_revision_id=reference["item_revision_id"],
        source_artifact_id=source.artifact_id,
        source_artifact_revision_id=source.artifact_revision_id,
        source_sha256=source.sha256,
        accepted_result_artifact_id=base_pointer.artifact_id,
        accepted_result_artifact_revision_id=base_pointer.artifact_revision_id,
        accepted_result_sha256=base_pointer.sha256,
    )
    component = SimpleNamespace(
        artifact_id=source.artifact_id,
        artifact_revision_id=source.artifact_revision_id,
        sha256=source.sha256,
        schema_ref=source.schema_ref,
        media_type=source.media_type,
    )
    revision = SimpleNamespace(
        item_revision_id=reference["item_revision_id"],
        revision_state="APPROVED" if approved else "IN_REVIEW",
        approved_at="recorded" if approved else None,
        manifest_artifact_id="artifact_" + "a" * 32,
        manifest_artifact_revision_id="rev_" + "a" * 32,
        manifest_sha256=reference["manifest_sha256"],
        metadata_json={"title": "기출"},
        item_type_key="integrated-science",
    )
    rows = [
        (
            SimpleNamespace(item_id=reference["item_id"], lifecycle_state="ACTIVE"),
            revision,
            component,
            SimpleNamespace(
                logical_artifact_id=component.artifact_id,
                content_hash=component.sha256,
                approved=True,
                manifest={"primary_file": source.member_path},
            ),
        )
    ]
    manifests = [
        (
            SimpleNamespace(approved=True, artifact_type="item-revision-manifest"),
            SimpleNamespace(
                revision_id=revision.manifest_artifact_revision_id,
                logical_artifact_id=revision.manifest_artifact_id,
                content_hash=revision.manifest_sha256,
                approved=True,
            ),
        )
    ]
    snapshot = SimpleNamespace(
        graph_snapshot_revision_id="graphrev_" + "d" * 32,
        snapshot_sha256="sha256:" + "d" * 64,
    )
    lookups = []

    class Session:
        def __init__(self):
            self.results = iter((rows, manifests))
            self.counts = iter((1, None))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def begin(self):
            return nullcontext()

        def connection(self, **kwargs):
            pass

        def get(self, model, key):
            if model is OperatorRecord:
                return SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False)
            assert key == snapshot.graph_snapshot_revision_id
            return snapshot

        def scalar(self, statement):
            return next(self.counts)

        def execute(self, statement):
            if str(statement).startswith("SET "):
                return None
            values = next(self.results)
            return SimpleNamespace(tuples=lambda: values)

        def scalars(self, statement):
            parameters = statement.compile().params.values()
            assert snapshot.graph_snapshot_revision_id in parameters
            assert [reference["item_revision_id"]] in parameters
            # The Graph contains only the accepted V9 base, not its V10 report.
            return (association,)

    service = object.__new__(resolution.ChatKnowledgeResolutionService)
    service.sessions = Session
    service.engine = object()
    service.artifacts = object()
    service.retrieval = SimpleNamespace(
        resolve_snapshot_pointer=lambda session, value: lookups.append(value)
    )
    monkeypatch.setattr(
        resolution,
        "effective_permissions",
        lambda *args: frozenset(
            {
                PermissionKey.GENERAL_CHAT_READ,
                PermissionKey.ITEM_READ,
            }
        ),
    )
    monkeypatch.setattr(
        resolution,
        "resolve_control_artifact_members",
        lambda *args: (json.dumps(item_content()).encode(),),
    )

    def solutions(session, artifacts, *, base_analysis_run_ids):
        assert base_analysis_run_ids == (base_id,)
        return {base_id: evidence} if reports else {}

    monkeypatch.setattr(resolution, "resolve_solution_evidence_by_base_run", solutions)
    request = ChatKnowledgeCatalogRequest.model_validate(
        {
            "actor_id": "operator_" + "1" * 32,
            "purpose": "MATERIALIZE",
            "selection": {
                "references": [reference],
                "snapshot": {
                    "graph_snapshot_revision_id": snapshot.graph_snapshot_revision_id,
                    "sha256": snapshot.snapshot_sha256,
                },
            },
        }
    )
    reply = service.resolve(request)
    assert lookups == [snapshot.graph_snapshot_revision_id]
    return reply


def test_accepted_additive_report_does_not_require_graph_republication(monkeypatch):
    reply = resolve(monkeypatch)
    assert [source.kind for source in reply.context.sources] == [
        "REGISTRY_DIRECT",
        "SOLUTION_REPORT",
    ]
    report = reply.context.sources[1]
    assert (
        report.pointer.artifact_revision_id
        == _solution_evidence().pointer.solution_report.artifact_revision_id
    )
    assert "FINAL_ANSWER_MUST_NOT_LEAK" in report.text  # authorized explanation projection


@pytest.mark.parametrize("reports,approved", [(False, True), (True, False)])
def test_missing_or_unapproved_report_stays_an_explicit_limitation(monkeypatch, reports, approved):
    reply = resolve(monkeypatch, reports=reports, approved=approved)
    assert [source.kind for source in reply.context.sources] == ["REGISTRY_DIRECT"]
    assert any("풀이보고서" in limitation for limitation in reply.context.limitations)


@pytest.mark.parametrize(
    "field",
    [
        "item_id",
        "item_revision_id",
        "artifact_id",
        "artifact_revision_id",
        "sha256",
        "base_artifact_id",
        "base_revision_id",
        "base_sha256",
        "base_analysis_run_id",
    ],
)
def test_wrong_source_or_base_binding_is_rejected(monkeypatch, field):
    def mutate(evidence):
        if field.startswith("base_") and field != "base_analysis_run_id":
            key = field.removeprefix("base_")
            key = "artifact_revision_id" if key == "revision_id" else key
            value = {
                "artifact_id": "artifact_",
                "artifact_revision_id": "rev_",
                "sha256": "sha256:",
            }[key]
            value += "f" * (64 if key == "sha256" else 32)
            return replace(
                evidence,
                base_accepted_result=evidence.base_accepted_result.model_copy(update={key: value}),
            )
        if field == "base_analysis_run_id":
            return replace(
                evidence,
                pointer=evidence.pointer.model_copy(update={field: "analysisrun_" + "f" * 32}),
            )
        if field.startswith("item_"):
            value = ("item_" if field == "item_id" else "itemrev_") + "f" * 32
            return replace(evidence, source=evidence.source.model_copy(update={field: value}))
        value = {"artifact_id": "artifact_", "artifact_revision_id": "rev_", "sha256": "sha256:"}[
            field
        ]
        value += "f" * (64 if field == "sha256" else 32)
        return replace(
            evidence,
            source=evidence.source.model_copy(
                update={
                    "artifact_member": evidence.source.artifact_member.model_copy(
                        update={field: value}
                    )
                }
            ),
        )

    with pytest.raises(
        resolution.ChatKnowledgeResolutionError, match="CHAT_KNOWLEDGE_HASH_MISMATCH"
    ):
        resolve(monkeypatch, mutate=mutate)
