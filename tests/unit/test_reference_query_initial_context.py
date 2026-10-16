"""Real temporary index bytes; explicit synthetic source/IAM/metadata, no model or live grant."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingIndexManifest
from eom_catalog_contracts.inference_transfer_experiment import VIEWS
from eom_catalog_contracts.similarity_context import parse_similarity_context_request
from eom_catalog_service import embedding_registry_catalog_adapter as module
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    ReferenceQueryContextPreparation,
    RegisteredEmbeddingIndexRead,
    SelectedEmbeddingSources,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    InferenceTransferSessionCapturePhase,
)
from eom_catalog_service.reference_query_context_preparation import (
    validate_reference_query_context_preparation,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service import OperatorAuthorizationFenceError

from tests.unit.embedding_registry_application_fixtures import capture_pair
from tests.unit.inference_transfer_embedding_fixtures import (
    index_manifest,
    index_pointer,
    seal,
    source_binding,
)
from tests.unit.test_embedding_registry_catalog_adapter import _file_set
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_pinned_artifact_read_context import MetadataSession


@pytest.fixture
def initial(owner, monkeypatch):
    verifier, session, command, index, binding, _scope, root = owner
    session.get_bind = lambda: verifier.engine
    query_space = type(index.space).model_validate(
        seal(index.space.model_dump(mode="json") | {"purpose": "QUERY"}, "space_sha256")
    )
    scope = EmbeddingRegistryLookup(
        command.corpus_id,
        command.namespace,
        command.graph_snapshot,
        command.policy_revision_id,
        command.policy_sha256,
    )
    request = ReferenceQueryContextPreparation(
        "similarityrequest_" + "a" * 32,
        SelectedEmbeddingSources(scope, (binding.source.item_revision_id,)),
        ReferenceQuerySpaces(query=query_space, document=index.space),
        VIEWS,
        "OPTIONAL",
        8,
    )
    registered = RegisteredEmbeddingIndexRead(
        command.corpus_id,
        command.namespace,
        index.index_id,
        index.index_revision_id,
        command.index_manifest,
        index.index_sha256,
        command.graph_snapshot.graph_snapshot_revision_id,
        command.policy_revision_id,
        command.policy_sha256,
        len(index.bindings),
        command.binding_set_sha256,
    )
    value = SimpleNamespace(
        verifier=verifier,
        session=session,
        command=command,
        index=index,
        binding=binding,
        root=root,
        request=request,
        registered=registered,
        heads={command.namespace.view: registered},
        reads=[],
        captures=[],
        denied_at=None,
        missing_report=False,
        late_remove=False,
        advance_head=False,
    )

    class Repository:
        def __init__(self, current):
            assert current is session

        def current_namespace_revision(self, corpus_id, namespace):
            assert corpus_id == command.corpus_id
            value.reads.append(namespace)
            found = value.heads.get(namespace.view)
            return None if found is None else (found, 2)

    monkeypatch.setattr(module, "EmbeddingRegistryRepository", Repository)
    original = verifier.sources.capture_in_session.side_effect

    def capture(*args, **options):
        assert options["phase"] is InferenceTransferSessionCapturePhase.CAPTURE_POPULATION
        assert args[1].source_revision_ids == (binding.source.item_revision_id,)
        value.captures.append(args[1])
        if value.denied_at == len(value.captures):
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")
        resolved = original(*args, **options)
        if value.missing_report:
            resolved = replace(resolved, entries=())
        if len(value.captures) == 2:
            if value.late_remove:
                resolved = replace(resolved, corpus=replace(resolved.corpus, sources=()))
            if value.advance_head:
                value.heads[command.namespace.view] = replace(
                    registered,
                    index_revision_id="embeddingindexrev_" + "f" * 32,
                )
        return resolved

    verifier.sources.capture_in_session.side_effect = capture
    monkeypatch.setattr(
        verifier,
        "_iter_numerical_shards",
        Mock(side_effect=AssertionError("numeric materialization")),
    )
    return value


def prepare(value, *, caller=None, request=None):
    return value.verifier.prepare_reference_query_context_in_session(
        value.session,
        caller or EmbeddingRegistryCaller("operator_" + "1" * 32),
        request or value.request,
    )


def test_initial_scope_pins_exact_source_report_and_available_index_without_full_population(
    initial,
):
    value = initial
    result = prepare(value)
    assert result == parse_similarity_context_request(result.model_dump(mode="json"))
    assert result.anchor.source == value.binding.source
    assert result.anchor.profile == value.binding.profile
    assert result.anchor.solution_evidence == value.binding.solution_evidence
    assert result.graph_snapshot == value.command.graph_snapshot
    assert result.policy_sha256 == value.command.policy_sha256
    assert result.consumer_purpose == "PAST_EXAM_VARIATION"
    assert tuple(row.view for row in result.views) == VIEWS
    available = tuple(row.index for row in result.views if row.index is not None)
    assert len(available) == 1
    assert available[0].index_revision_id == value.index.index_revision_id
    assert available[0].index_manifest == value.command.index_manifest
    assert available[0].index_sha256 == value.index.index_sha256
    assert len(value.captures) == 2 and len(value.reads) == 3
    assert len(value.session.statements) == 3  # one present index's bounded metadata prefetch


@pytest.mark.parametrize("purpose", ("ITEM_AUTHORING", "ITEM_REVIEW"))
def test_initial_authoring_reference_preserves_purpose_and_exact_current_sources(initial, purpose):
    value = initial
    selected = replace(value.request, consumer_purpose=purpose)
    result = prepare(value, request=selected)
    assert result.consumer_purpose == purpose
    assert result.anchor.basis == "APPROVED_REFERENCE_ITEM"
    assert result.anchor.source == value.binding.source
    assert result.anchor.profile == value.binding.profile
    assert result.anchor.solution_evidence == value.binding.solution_evidence
    assert result.graph_snapshot == value.command.graph_snapshot
    assert result.policy_sha256 == value.command.policy_sha256
    assert len(value.captures) == 2 and len(value.reads) == 3
    validate_reference_query_context_preparation(selected, value.verifier.configuration, result)
    with pytest.raises(EmbeddingRegistryError, match="SOURCE_PIN_MISMATCH"):
        validate_reference_query_context_preparation(
            value.request, value.verifier.configuration, result
        )


@pytest.mark.parametrize(
    "purpose", ("GENERAL_CHAT_READ", "MOCK_EXAM_OBSERVATION", "PRIVATE_CHAT_QUERY", True, [], None)
)
def test_preparation_rejects_unoffered_or_untyped_purpose_before_source_io(initial, purpose):
    value = initial
    with pytest.raises(EmbeddingRegistryError, match="REQUEST_INVALID"):
        replace(value.request, consumer_purpose=purpose)
    assert not value.captures and not value.reads and not value.session.statements


@pytest.mark.parametrize("required", (False, True))
def test_absent_views_and_report_remain_explicit_not_synthetic_vectors(initial, required):
    value = initial
    value.heads.clear()
    value.missing_report = True
    value.request = replace(value.request, vector_mode="REQUIRED" if required else "OPTIONAL")
    result = prepare(value)
    assert result.anchor.profile is None and result.anchor.solution_evidence is None
    assert all(row.index is None for row in result.views)
    assert result.vector_mode == value.request.vector_mode
    assert len(value.captures) == 2 and value.session.statements == []


def test_late_head_advance_does_not_substitute_latest(initial):
    value = initial
    value.advance_head = True
    result = prepare(value)
    selected = next(row.index for row in result.views if row.index is not None)
    assert selected.index_revision_id == value.index.index_revision_id
    assert value.heads[value.command.namespace.view].index_revision_id != selected.index_revision_id
    assert len(value.reads) == 3


@pytest.mark.parametrize("when", (1, 2))
def test_current_denial_is_not_optional_unavailability_or_metadata_disclosure(initial, when):
    value = initial
    value.denied_at = when
    with pytest.raises(EmbeddingRegistryError) as raised:
        prepare(value)
    assert raised.value.code == "EMBEDDING_REGISTRY_FORBIDDEN"
    assert len(value.captures) == when
    if when == 1:
        assert value.reads == [] and value.session.statements == []


def test_revoked_exact_anchor_after_member_reads_is_rejected_not_reselected(initial):
    value = initial
    value.late_remove = True
    with pytest.raises(EmbeddingRegistryError, match="SOURCE_PIN_MISMATCH"):
        prepare(value)
    assert len(value.captures) == 2 and len(value.reads) == 3


@pytest.mark.parametrize(
    "field",
    (
        "corpus_id",
        "graph_snapshot_revision_id",
        "policy_revision_id",
        "policy_sha256",
        "index_revision_id",
        "binding_count",
        "binding_set_sha256",
        "namespace",
    ),
)
def test_wrong_present_index_cannot_fall_back_to_absent_or_another_head(initial, field):
    value = initial
    old = getattr(value.registered, field)
    bad = (
        old + 1
        if field == "binding_count"
        else EmbeddingIndexNamespace.model_validate(
            old.model_dump(mode="json") | {"space_sha256": "sha256:" + "0" * 64}
        )
        if field == "namespace"
        else "wrong"
    )
    value.heads[value.command.namespace.view] = replace(value.registered, **{field: bad})
    with pytest.raises(EmbeddingRegistryError):
        prepare(value)
    assert len(value.captures) == 1
    assert len(value.reads) <= 3


def test_real_corrupt_index_member_is_rejected_without_repair(initial):
    value = initial
    pointer = value.command.index_manifest
    path = value.root / pointer.artifact_id / pointer.artifact_revision_id / pointer.member_path
    damaged = path.read_bytes() + b"corrupt"
    path.write_bytes(damaged)
    with pytest.raises(EmbeddingRegistryError):
        prepare(value)
    assert path.read_bytes() == damaged and len(value.captures) == 1


@pytest.mark.parametrize(
    "fault", ("foreign_engine", "nested", "inactive", "wrong_actor", "wrong_value")
)
def test_root_or_authority_projection_cannot_disclose_metadata(initial, fault):
    value = initial
    caller = request = None
    if fault == "foreign_engine":
        value.session.get_bind = lambda: object()
    elif fault == "nested":
        value.session.in_nested_transaction = lambda: True
    elif fault == "inactive":
        value.session.root.is_active = False
    elif fault == "wrong_actor":
        caller = SimpleNamespace(operator_id="operator_" + "1" * 32)
    else:
        request = object()
    with pytest.raises((EmbeddingRegistryError, SimilarityContextReadError)):
        prepare(value, caller=caller, request=request)
    assert value.captures == [] and value.reads == [] and value.session.statements == []


def test_three_real_view_manifests_have_independent_pins_and_bounded_reads(initial):
    value = initial
    _, resolved = capture_pair()
    value.heads.clear()
    for view, seed in zip(VIEWS, ("4", "5", "6"), strict=True):
        binding = source_binding(resolved.entries[0], view=view)
        index = index_manifest(binding, view=view, revision_seed=seed)
        index = EmbeddingIndexManifest.model_validate(
            seal(
                index.model_dump(mode="json") | {"index_id": "embeddingindex_" + seed * 32},
                "index_sha256",
            )
        )
        pointer = index_pointer(index, seed)
        records = _file_set(
            value.root,
            pointer.artifact_id,
            pointer.artifact_revision_id,
            "control_embedding_index",
            "index.json",
            {
                "index.json": (
                    canonical_json_bytes(index.model_dump(mode="json")),
                    pointer.schema_ref,
                    "application/json",
                )
            },
            seed,
        )
        value.session.records.update(MetadataSession(*records).records)
        namespace = EmbeddingIndexNamespace.model_validate(
            value.command.namespace.model_dump(mode="json") | {"view": view}
        )
        value.heads[view] = replace(
            value.registered,
            namespace=namespace,
            index_id=index.index_id,
            index_revision_id=index.index_revision_id,
            index_manifest=pointer,
            index_sha256=index.index_sha256,
            binding_set_sha256=content_sha256([binding.binding_sha256]),
        )
    result = prepare(value)
    assert all(row.index is not None for row in result.views)
    assert len({row.index.index_id for row in result.views}) == 3
    assert len(value.captures) == 2 and len(value.reads) == 3
    assert len(value.session.statements) == 9
