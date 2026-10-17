"""Actual pinned index/shard/binary bytes; registered lookup/source/IAM seams are synthetic."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_catalog_service import embedding_registry_catalog_adapter as module
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryError,
    EmbeddingRegistryServiceCaller,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.private_chat_similarity_ports import PreparedPrivateChatDocumentScope
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_private_chat_query import private_context_request
from tests.unit.test_embedding_registry_catalog_adapter import _read_selection
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_similarity_context_service import CALLER

pytestmark = pytest.mark.parametrize("owner", ["CONTENT_ONLY"], indirect=True)


@pytest.fixture
def private(owner, monkeypatch):
    verifier, session, command, index, binding, _scope, root = owner
    intent, registered = _read_selection(command, index)
    request = PrivateChatSimilarityRequest.model_validate(
        seal(
            private_context_request(intent.selection).model_dump(mode="json")
            | {
                "graph_snapshot": command.graph_snapshot.model_dump(mode="json"),
                "policy_revision_id": command.policy_revision_id,
                "policy_sha256": command.policy_sha256,
                "source_classes": ["PAST_EXAM"],
            },
            "request_sha256",
        )
    )
    original = verifier.sources.capture_in_session.side_effect
    phases, windows, commands, files = [], [], [], []
    fault = SimpleNamespace(value=None)
    reader = PinnedArtifactReadContext.read_pinned

    def counted(actual_reader, **arguments):
        files.append(arguments["member_path"])
        return reader(actual_reader, **arguments)

    def capture(actual_session, source_command, recipe, **options):
        assert actual_session is session and source_command.actor_id == CALLER.operator_id
        assert source_command.top_k == request.top_k
        assert source_command.source_revision_ids == ()
        assert not hasattr(source_command, "anchor") and not hasattr(source_command, "query_basis")
        commands.append(source_command)
        phase = options["phase"].value
        phases.append(phase)
        if fault.value == "denied" or (
            fault.value == "late_denied" and phases.count("CAPTURE_POPULATION") >= 2
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
        value = original(actual_session, source_command, recipe, **options)
        if phase == "CAPTURE_POPULATION" and phases.count(phase) >= 2:
            if fault.value == "revoked_source":
                return replace(
                    value,
                    corpus=replace(
                        value.corpus, profiles=(), sources=(), missing_solution_reports=0
                    ),
                    entries=(),
                )
            if fault.value == "revoked_report":
                return replace(
                    value,
                    corpus=replace(value.corpus, profiles=(), missing_solution_reports=1),
                    entries=(),
                )
        return value

    def read(actual_session, caller, query, read_owner):
        assert actual_session is session and caller == CALLER
        windows.append(read_owner._similarity_read_window)
        # Exercise the actual source/member/numeric read. Only the registered
        # metadata lookup is synthetic here; real DB lookup is a separate gate.
        value = read_owner.resolve_pinned_read(actual_session, caller, query, registered)
        if fault.value == "root":
            monkeypatch.setattr(session, "get_transaction", lambda: SimpleNamespace(is_active=True))
        if fault.value == "pending_write":
            session.new.append(object())
        return value

    monkeypatch.setattr(verifier.sources, "capture_in_session", capture)
    monkeypatch.setattr(module, "read_pinned_embedding_index", read)
    monkeypatch.setattr(PinnedArtifactReadContext, "read_pinned", counted)
    monkeypatch.setattr(
        verifier, "sessions", Mock(side_effect=AssertionError("must retain caller root"))
    )
    return SimpleNamespace(
        verifier=verifier,
        session=session,
        request=request,
        phases=phases,
        windows=windows,
        commands=commands,
        files=files,
        fault=fault,
        binding=binding,
        root=root,
    )


def prepare(value, request=None):
    return value.verifier.prepare_private_chat_document_scope_in_session(
        value.session, CALLER, value.request if request is None else request
    )


def read(value, prepared, request=None):
    return value.verifier.read_private_chat_document_index_in_session(
        value.session, CALLER, value.request if request is None else request, prepared
    )


@pytest.mark.parametrize("has_index", [True, False])
def test_private_scope_no_fake_anchor_and_same_official_document_read(private, has_index):
    value, request = private, private.request
    if not has_index:
        body = request.model_dump(mode="json")
        body["views"][0]["index"] = None
        request = PrivateChatSimilarityRequest.model_validate(seal(body, "request_sha256"))
    prepared = prepare(value, request)
    assert type(prepared) is PreparedPrivateChatDocumentScope
    assert prepared.request_sha256 == request.request_sha256
    assert len(prepared.sources) == 1 and prepared.sources[0].source == value.binding.source
    assert not hasattr(prepared, "query_text") and not hasattr(prepared, "query_basis")
    assert b'"text"' not in canonical_json_bytes([p.source for p in prepared.sources])
    assert value.files == []
    value.phases.clear()
    values = read(value, prepared, request)
    assert len(values) == (1 if has_index else 0)
    if has_index:
        assert values[0].bindings == (value.binding,)
        assert values[0].numerical_rows[0].values[0] == 1.0
        assert sorted(value.files) == ["index.json", "result.json", "shard.json", "vectors.f32"]
        assert len(value.windows) == 1 and value.windows[0].session is value.session
    else:
        assert not value.files and not value.windows
    assert value.phases.count("CAPTURE_POPULATION") == 2
    value.verifier.sessions.assert_not_called()


@pytest.mark.parametrize(
    "fault", ["revoked_source", "revoked_report", "late_denied", "root", "pending_write"]
)
def test_private_document_late_revocation_and_root_changes_prevent_delivery(private, fault):
    prepared = prepare(private)
    private.phases.clear()
    private.fault.value = fault
    with pytest.raises(SimilarityContextReadError) as error:
        read(private, prepared)
    assert (
        error.value.code
        == {
            "revoked_source": "SOURCE_REVOKED",
            "revoked_report": "SOURCE_REVOKED",
            "late_denied": "SOURCE_ACCESS_DENIED",
            "root": "AUTHORITY_UNAVAILABLE",
            "pending_write": "AUTHORITY_UNAVAILABLE",
        }[fault]
    )
    private.verifier.sessions.assert_not_called()


@pytest.mark.parametrize("fault", ["missing", "ended", "nested", "new", "dirty", "deleted"])
def test_private_scope_requires_clean_original_root_before_source_or_member_io(
    private, monkeypatch, fault
):
    value = private
    if fault == "missing":
        monkeypatch.setattr(value.session, "get_transaction", lambda: None)
    elif fault == "ended":
        value.session.root.is_active = False
    elif fault == "nested":
        monkeypatch.setattr(value.session, "in_nested_transaction", lambda: True)
    else:
        getattr(value.session, fault).append(object())
    with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
        prepare(value)
    assert value.phases == value.files == []


@pytest.mark.parametrize(
    "fault", ["identity", "service_caller", "source_class", "query_model", "purpose"]
)
def test_private_public_reads_never_borrow_other_authority(private, monkeypatch, fault):
    value = private
    request, caller = value.request, CALLER
    if fault == "identity":
        value.verifier.identity_fence = None
    elif fault == "service_caller":
        caller = EmbeddingRegistryServiceCaller("not a consumer identity")
    elif fault == "source_class":
        value.verifier.configuration = replace(
            value.verifier.configuration, source_classes=("APPROVED_ITEM",)
        )
    elif fault == "query_model":
        request = request.model_copy(update={"consumer_purpose": "ITEM_AUTHORING"})
    else:
        request = request.model_copy(update={"authority": "ADMIN"})
    with pytest.raises(ValueError):
        value.verifier.prepare_private_chat_document_scope_in_session(
            value.session, caller, request
        )
    assert value.phases == value.files == []


@pytest.mark.parametrize("fault", ["request", "bool", "duplicate", "profile"])
def test_private_prepared_scope_is_not_a_replay_or_current_authority_token(private, fault):
    prepared = prepare(private)
    private.phases.clear()
    if fault == "request":
        prepared = replace(prepared, request_sha256="sha256:" + "f" * 64)
    elif fault == "duplicate":
        prepared = replace(prepared, sources=prepared.sources * 2)
    elif fault == "profile":
        source = replace(prepared.sources[0], profile=None, solution_evidence=None)
        prepared = replace(prepared, sources=(source,))
    else:
        object.__setattr__(prepared, "truncated", 0)
    with pytest.raises(ValueError):
        read(private, prepared)
    assert not private.files


@pytest.mark.parametrize("member", ["index.json", "result.json", "shard.json", "vectors.f32"])
def test_private_read_checks_real_file_hashes_before_delivery(private, member):
    prepared = prepare(private)
    private.phases.clear()
    path = next(path for path in private.root.rglob(member) if path.is_file())
    original = path.read_bytes()
    path.write_bytes(original + b"broken")
    with pytest.raises(SimilarityContextReadError, match="INDEX_POINTER_INVALID"):
        read(private, prepared)
    assert path.read_bytes() == original + b"broken"  # no repair/latest fallback
