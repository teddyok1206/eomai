"""Synthetic original Evidence/source/IAM seams; no live authorization or model work."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from eom_catalog_contracts import (
    EducationRetrievalRequestV2,
    EvidenceBundleManifestV5,
    EvidenceBundlePublicationResultV5,
)
from eom_catalog_contracts.authoring_reference import (
    AuthoringReferenceReply,
    AuthoringReferenceRequest,
    validate_authoring_reference_reply,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_service import authoring_reference_selection as module
from eom_catalog_service.authoring_reference_selection import (
    CatalogAuthoringReferenceSelection,
    authoring_reference_ids,
    select_authoring_reference,
)
from eom_catalog_service.embedding_registry_ports import ResolvedEmbeddingLookup
from eom_catalog_service.knowledge_graph_models import (
    EducationRetrievalRequestRecord,
    EvidenceBundleRecord,
    EvidenceBundleRevisionRecord,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_entry,
    embedding_space,
    seal,
    view_recipe,
)
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_embedding_registry_contracts import registration_command
from tests.unit.test_knowledge_retrieval_service import _request


def case():
    entries = (embedding_entry("b"), embedding_entry("a"))
    request = _request().model_dump(mode="json") | {
        "graph_snapshot": entries[0].profile.source_basis.graph_snapshot.model_dump(mode="json"),
        "source_classes": ["PAST_EXAM"],
    }
    original = EducationRetrievalRequestV2.model_validate(seal(request, "request_sha256"))
    context = {
        "artifact_id": "artifact_" + "8" * 32,
        "artifact_revision_id": "rev_" + "8" * 32,
        "sha256": sha256_bytes(b"synthetic context"),
        "schema_ref": "eom://schemas/knowledge/evidence-bundle-context/1.0",
        "media_type": "text/markdown",
        "logical_name": "context.md",
        "member_path": "evidence/context.md",
    }
    body = {
        "schema_version": "evidence-bundle-manifest/5.0",
        "evidence_bundle_id": "evidence_" + "1" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "2" * 32,
        "revision_number": 1,
        "retrieval_request_id": original.retrieval_request_id,
        "retrieval_request_sha256": original.request_sha256,
        "graph_snapshot": original.graph_snapshot.model_dump(mode="json"),
        "access_policy_revision_id": original.access_policy_revision_id,
        "access_policy_sha256": original.access_policy_sha256,
        "requester_permissions_sha256": original.requester_permissions_sha256,
        "materials": {"context_markdown": context},
        "entries": [
            {
                "evidence_id": "evidenceitem_" + seed * 32,
                "evidence_kind": "ITEM_REVISION",
                "use": "REFERENCE_PATTERN",
                "source": entry.profile.source_basis.source.model_dump(mode="json"),
                "graph_node_ids": ["knode_" + seed * 32],
                "anchor_ids": ["anchor_" + seed * 32],
                "relevance_milli": 950 - index * 50,
                "answer_bearing": False,
                "solution_evidence": entry.profile.source_basis.solution_evidence.model_dump(
                    mode="json"
                ),
            }
            for index, (entry, seed) in enumerate(zip(entries, ("b", "a"), strict=True))
        ],
        "budget": {
            "document_count": 0,
            "item_revision_count": 2,
            "graph_node_count": 2,
            "claim_count": 0,
            "estimated_context_tokens": 10,
        },
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    manifest = EvidenceBundleManifestV5.model_validate(seal(body, "manifest_sha256"))
    raw = canonical_json_bytes(manifest)
    publication_body = {
        name: manifest.model_dump(mode="json")[name]
        for name in (
            "evidence_bundle_id",
            "evidence_bundle_revision_id",
            "revision_number",
            "retrieval_request_id",
            "retrieval_request_sha256",
            "graph_snapshot",
            "access_policy_revision_id",
            "access_policy_sha256",
            "requester_permissions_sha256",
            "budget",
            "manifest_sha256",
        )
    }
    publication_body |= {
        "schema_version": "evidence-bundle-publication-result/5.0",
        "state": "PUBLISHED",
        "context_artifact": context,
        "manifest_artifact": context
        | {
            "artifact_id": "artifact_" + "9" * 32,
            "artifact_revision_id": "rev_" + "9" * 32,
            "sha256": sha256_bytes(raw),
            "member_path": "evidence/manifest.json",
            "logical_name": "manifest.json",
            "media_type": "application/json",
            "schema_ref": "eom://schemas/knowledge/evidence-bundle-manifest/5.0",
        },
        "published_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    publication = EvidenceBundlePublicationResultV5.model_validate(
        seal(publication_body, "result_sha256")
    )
    return SimpleNamespace(
        original=original,
        manifest=manifest,
        publication=publication,
        raw=raw,
        resolved=ResolvedEmbeddingLookup(
            "corpus_" + "a" * 32,
            embedding_space(),
            view_recipe(),
            tuple(entry.profile.source_basis.source for entry in entries),
            entries,
        ),
        request=AuthoringReferenceRequest(
            schema_version="system-rag-authoring-reference-request/1.0",
            operation="SELECT_ITEM_AUTHORING_REFERENCE",
            actor_id=original.requester_operator_id,
            evidence=publication,
        ),
    )


def test_schema_and_packaged_bytes_are_closed_and_independently_pinned():
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-authoring-reference"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    Draft202012Validator.check_schema(load_schema("system-rag-authoring-reference"))


def test_selection_keeps_official_relevance_order_not_sorted_revision_order():
    value = case()
    assert authoring_reference_ids(value.manifest)[0] == "itemrev_" + "a" * 32
    selected = select_authoring_reference(value.manifest, value.resolved)
    assert selected.source_item_revision_id == "itemrev_" + "b" * 32
    assert selected.evidence_id == value.manifest.entries[0].evidence_id
    assert selected.source_sha256 == value.manifest.entries[0].source.artifact_member.sha256


@pytest.mark.parametrize(
    "change", ("missing", "extra", "duplicate", "report", "source", "truncated")
)
def test_foreign_missing_duplicate_or_changed_current_sources_cannot_be_selected(change):
    value = case()
    resolved = value.resolved
    if change == "missing":
        resolved = replace(resolved, entries=resolved.entries[:1])
    elif change == "extra":
        resolved = replace(
            resolved, sources=(*resolved.sources, embedding_entry("c").profile.source_basis.source)
        )
    elif change == "duplicate":
        resolved = replace(resolved, entries=(*resolved.entries, resolved.entries[0]))
    elif change == "truncated":
        resolved = replace(resolved, truncated=True)
    else:
        entry = resolved.entries[0]
        raw = entry.profile.model_dump(mode="json")
        if change == "report":
            pointer = raw["source_basis"]["solution_evidence"]
            pointer["solution_report"]["sha256"] = "sha256:" + "f" * 64
            raw["source_basis"]["solution_evidence"] = seal(pointer, "pointer_sha256")
        else:
            raw["source_basis"]["source"]["artifact_member"]["sha256"] = "sha256:" + "f" * 64
        staged = entry.model_dump(mode="json")
        staged["profile"] = seal(raw, "profile_sha256")
        if change == "report":
            for field in staged["metadata"]:
                field["source_sha256"] = raw["source_basis"]["solution_evidence"][
                    "solution_report"
                ]["sha256"]
        else:
            staged["content"]["original_source"] = raw["source_basis"]["source"]["artifact_member"]
        changed = entry.model_validate(staged)
        resolved = replace(resolved, entries=(changed, resolved.entries[1]))
    with pytest.raises(SimilarityContextReadError):
        select_authoring_reference(value.manifest, resolved)


@pytest.mark.parametrize("fault", ("answer", "grounding", "no_report", "non_item", "generated"))
def test_nonreference_answer_bearing_or_reportless_entries_are_not_offered(fault):
    value = case()
    raw = value.manifest.model_dump(mode="json")
    for entry in raw["entries"]:
        if fault == "answer":
            entry |= {"answer_bearing": True, "use": "AVOID_COPY"}
        elif fault == "grounding":
            entry["use"] = "GROUNDING"
        elif fault == "no_report":
            entry["solution_evidence"] = None
        elif fault == "non_item":
            entry["evidence_kind"] = "TABLE"
        else:
            entry["source"]["source_class"] = "APPROVED_ITEM"
    manifest = EvidenceBundleManifestV5.model_validate(seal(raw, "manifest_sha256"))
    assert authoring_reference_ids(manifest) == ()
    assert (
        select_authoring_reference(manifest, replace(value.resolved, sources=(), entries=()))
        is None
    )


@pytest.mark.parametrize("status", ("SELECTED", "UNAVAILABLE", "FAILED"))
def test_reply_exact_request_and_actor_binding(status):
    value = case()
    reply = AuthoringReferenceReply(
        schema_version="system-rag-authoring-reference-reply/1.0",
        operation="SELECT_ITEM_AUTHORING_REFERENCE",
        status=status,
        actor_id=value.request.actor_id,
        request_sha256=content_sha256(value.request),
        selection=select_authoring_reference(value.manifest, value.resolved)
        if status == "SELECTED"
        else None,
        error_code=None
        if status == "SELECTED"
        else "REFERENCE_NOT_OFFERED"
        if status == "UNAVAILABLE"
        else "SOURCE_REVOKED",
    )
    validate_authoring_reference_reply(value.request, reply)
    with pytest.raises(ValueError, match="BINDING_INVALID"):
        validate_authoring_reference_reply(
            value.request, reply.model_copy(update={"actor_id": "operator_" + "f" * 32})
        )
    with pytest.raises((ValueError, SchemaError)):
        AuthoringReferenceRequest.model_validate(
            value.request.model_dump(mode="json") | {"role": "ADMIN"}
        )


def read_case(monkeypatch):
    value = case()
    request, evidence = value.original, value.publication
    rows = {
        EvidenceBundleRecord: SimpleNamespace(
            retrieval_request_id=request.retrieval_request_id,
            evidence_bundle_id=evidence.evidence_bundle_id,
            created_by_operator_id=value.request.actor_id,
        ),
        EvidenceBundleRevisionRecord: SimpleNamespace(
            evidence_bundle_id=evidence.evidence_bundle_id,
            retrieval_request_id=request.retrieval_request_id,
            state="PUBLISHED",
            graph_snapshot_revision_id=request.graph_snapshot.graph_snapshot_revision_id,
            access_policy_revision_id=request.access_policy_revision_id,
            requester_permissions_sha256=request.requester_permissions_sha256,
        ),
        EducationRetrievalRequestRecord: SimpleNamespace(
            retrieval_request_id=request.retrieval_request_id,
            requester_operator_id=value.request.actor_id,
            state="PUBLISHED",
            request_sha256=request.request_sha256,
            canonical_request=request.model_dump(mode="json"),
            query_kind=request.query_kind,
            requester_role=request.requester_role,
            graph_snapshot_revision_id=request.graph_snapshot.graph_snapshot_revision_id,
            access_policy_revision_id=request.access_policy_revision_id,
            requester_permissions_sha256=request.requester_permissions_sha256,
        ),
    }
    session = Mock()
    session.get.side_effect = lambda model, identity: rows[model]
    session.get_nested_transaction.return_value = None
    reader = Mock()
    reader.read_pinned.side_effect = [
        SimpleNamespace(payload=value.raw),
        SimpleNamespace(payload=b"synthetic context"),
    ]
    service = object.__new__(KnowledgeRetrievalApplicationService)
    monkeypatch.setattr(service, "_result_v2", Mock(return_value=evidence))
    return value, rows, session, reader, service


def read(value, session, reader, service):
    return service.read_published_item_evidence_in_session(
        session, value.publication, requested_by=value.request.actor_id, artifact_reader=reader
    )


def test_original_evidence_read_closes_all_pins_and_one_manifest_context_materialization(
    monkeypatch,
):
    value, _rows, session, reader, service = read_case(monkeypatch)
    assert read(value, session, reader, service) == value.manifest
    reader.require_session.assert_called_once_with(session)
    assert reader.read_pinned.call_count == reader.require_file_set.call_count == 2
    service._result_v2.assert_called_once()


@pytest.mark.parametrize(
    "fault",
    (
        "missing",
        "foreign_actor",
        "revision_graph",
        "target",
        "canonical_request",
        "manifest",
        "context",
    ),
)
def test_original_evidence_read_never_substitutes_latest_or_foreign_content(monkeypatch, fault):
    value, rows, session, reader, service = read_case(monkeypatch)
    if fault == "missing":
        rows[EvidenceBundleRecord] = None
    elif fault == "foreign_actor":
        rows[EducationRetrievalRequestRecord].requester_operator_id = "operator_" + "f" * 32
    elif fault == "revision_graph":
        rows[EvidenceBundleRevisionRecord].graph_snapshot_revision_id = "graphrev_" + "f" * 32
    elif fault in {"target", "canonical_request"}:
        raw = rows[EducationRetrievalRequestRecord].canonical_request
        raw["target_item_revision_id" if fault == "target" else "requester_operator_id"] = (
            "itemrev_" + "f" * 32 if fault == "target" else "operator_" + "f" * 32
        )
        rows[EducationRetrievalRequestRecord].canonical_request = seal(raw, "request_sha256")
    else:
        raw = value.manifest.model_dump(mode="json")
        if fault == "manifest":
            raw["evidence_bundle_revision_id"] = "evidencerev_" + "f" * 32
        else:
            raw["materials"]["context_markdown"]["sha256"] = "sha256:" + "f" * 64
        reader.read_pinned.side_effect = [
            SimpleNamespace(payload=canonical_json_bytes(seal(raw, "manifest_sha256"))),
            SimpleNamespace(payload=b"synthetic context"),
        ]
    with pytest.raises(KnowledgeRetrievalServiceError):
        read(value, session, reader, service)


def test_current_identity_denial_precedes_any_evidence_io(monkeypatch):
    value = case()
    owner = Mock()
    owner.catalog.engine = Mock()
    owner.identity.fence_current_operator.side_effect = SimilarityContextReadError(
        "AUTHORITY_UNAVAILABLE"
    )
    sessions = MagicMock()
    sessions.begin.return_value.__enter__.return_value = Mock()
    monkeypatch.setattr(module, "build_session_factory", Mock(return_value=sessions))
    monkeypatch.setattr(module, "KnowledgeRetrievalApplicationService", Mock())
    service = CatalogAuthoringReferenceSelection(owner)
    with pytest.raises(SimilarityContextReadError):
        service.select(value.request)
    service.retrieval.read_published_item_evidence_in_session.assert_not_called()
    owner.catalog.resolve_selected_sources.assert_not_called()


@pytest.mark.parametrize("fault", ("none", "empty", "late_denial"))
def test_owner_keeps_same_root_batch_resolution_and_final_authority_even_for_absence(fault):
    value = case()
    owner = Mock()
    owner.configuration.registry.corpus_id = value.resolved.corpus_id
    owner.configuration.registry.namespace = registration_command().namespace
    owner.catalog.resolve_selected_sources.return_value = value.resolved
    service = object.__new__(CatalogAuthoringReferenceSelection)
    service.owner, service.sessions, service.retrieval = owner, MagicMock(), Mock()
    session = service.sessions.begin.return_value.__enter__.return_value
    manifest = value.manifest
    if fault == "empty":
        raw = manifest.model_dump(mode="json")
        for entry in raw["entries"]:
            entry["use"] = "GROUNDING"
        manifest = EvidenceBundleManifestV5.model_validate(seal(raw, "manifest_sha256"))
    service.retrieval.read_published_item_evidence_in_session.return_value = manifest
    if fault == "late_denial":
        owner.catalog.authorize_scope.side_effect = [
            None,
            SimilarityContextReadError("SOURCE_REVOKED"),
        ]
        with pytest.raises(SimilarityContextReadError):
            service.select(value.request)
    else:
        selected = service.select(value.request)
        assert (selected is None) == (fault == "empty")
    owner.identity.fence_current_operator.assert_called_once_with(session, value.request.actor_id)
    assert owner.catalog.authorize_scope.call_count == 2
    assert all(call.args[0] is session for call in owner.catalog.authorize_scope.call_args_list)
    if fault == "empty":
        owner.catalog.resolve_selected_sources.assert_not_called()
    else:
        owner.catalog.resolve_selected_sources.assert_called_once()
        args = owner.catalog.resolve_selected_sources.call_args.args
        assert args[0] is session and args[1].operator_id == value.request.actor_id
        assert args[2].source_revision_ids == authoring_reference_ids(manifest)
    service.sessions.commit.assert_not_called()


def test_hidden_raw_publication_fields_are_rejected_before_metadata_or_member_io(monkeypatch):
    value, _rows, session, reader, service = read_case(monkeypatch)
    value.publication = value.publication.model_copy(update={"authority": "ADMIN"})
    with pytest.raises((ValueError, SchemaError)):
        read(value, session, reader, service)
    session.get.assert_not_called()
    reader.read_pinned.assert_not_called()
