"""Official read composition with explicitly synthetic source/vector/SQL leaves."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.public_solution_similarity import (
    PublicSolutionSimilarityIndexPin,
    PublicSolutionSimilarityView,
)
from eom_catalog_contracts.similarity_context import SimilarityIndexPin, SimilarityViewSelection
from eom_catalog_service import embedding_device_index_read as application
from eom_catalog_service.embedding_device_index_pair import EmbeddingDeviceIndexPairError
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    EmbeddingRegistryOwnerConfiguration,
    EmbeddingRegistryRead,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes

from tests.unit.inference_transfer_embedding_fixtures import embedding_space, index_pointer
from tests.unit.test_embedding_device_index_pair import _index, public_index


@pytest.fixture(params=("legacy", "public"))
def case(tmp_path, monkeypatch, request):
    engine = object()
    settings = CatalogSettings(nas_artifact_root=tmp_path)
    root = SimpleNamespace(is_active=True)
    session = Mock()
    session.get_transaction.return_value = root
    session.get_nested_transaction.return_value = None
    session.get_bind.return_value = engine
    session.new, session.dirty, session.deleted = [], [], []
    caller = EmbeddingRegistryCaller("operator_" + "a" * 32)
    public = request.param == "public"
    indexes = (
        (public_index("CPU")[1], public_index("CUDA")[1])
        if public
        else (_index("CPU", "a", "b"), _index("CUDA", "a", "b"))
    )
    owners, intents, readings, payloads = [], [], [], {}
    for device, seed, index in zip(("CPU", "CUDA"), ("4", "5"), indexes, strict=True):
        binding = index.bindings[0]
        namespace_type = PublicSolutionIndexNamespace if public else EmbeddingIndexNamespace
        namespace = namespace_type(
            storage_partition=index.storage_partition,
            space_sha256=index.space.space_sha256,
            recipe_sha256=index.recipe.recipe_sha256,
            view=index.view,
            population_scope="ALL_ADMITTED_GRAPH_ITEMS",
        )
        scope = EmbeddingRegistryLookup(
            "corpus_" + "b" * 32,
            namespace,
            binding.graph_snapshot,
            binding.policy_revision_id,
            binding.policy_sha256,
        )
        pointer = public_index(device)[0] if public else index_pointer(index, seed)
        view_type = PublicSolutionSimilarityView if public else SimilarityViewSelection
        pin_type = PublicSolutionSimilarityIndexPin if public else SimilarityIndexPin
        selection = view_type(
            view=index.view,
            recipe=index.recipe,
            index=pin_type(
                index_id=index.index_id,
                index_revision_id=index.index_revision_id,
                index_manifest=pointer,
                index_sha256=index.index_sha256,
                storage_partition=index.storage_partition,
                spaces=ReferenceQuerySpaces(
                    query=embedding_space(device=device, purpose="QUERY"), document=index.space
                ),
            ),
        )
        intent = EmbeddingRegistryRead(scope, selection)
        owner = CatalogEmbeddingRegistryVerifier(
            engine,
            EmbeddingRegistryOwnerConfiguration(
                scope.corpus_id,
                namespace,
                index.space,
                index.recipe,
                ("APPROVED_ITEM", "PAST_EXAM") if public else ("PAST_EXAM",),
            ),
            identity_fence=Mock(),
            settings=settings,
        )
        owner.authorize_scope = Mock()
        owners.append(owner)
        intents.append(intent)
        readings.append(
            ResolvedPinnedEmbeddingIndex(
                intent,
                tuple(b.source for b in index.bindings),
                tuple(
                    AuthorizedEmbeddingReadProfile(b.source.item_revision_id, b.profile)
                    for b in index.bindings
                ),
                index.bindings,
                (),
            )
        )
        payloads[pointer.sha256] = canonical_json_bytes(index.model_dump(mode="json"))
    reader = Mock(spec=PinnedArtifactReadContext)
    reader.settings = settings
    reader.read_pinned.side_effect = lambda **kw: SimpleNamespace(payload=payloads[kw["sha256"]])
    official = Mock(side_effect=readings)
    monkeypatch.setattr(application, "read_pinned_embedding_index", official)
    arguments = dict(
        cpu_owner=owners[0],
        cpu_intent=intents[0],
        cuda_owner=owners[1],
        cuda_intent=intents[1],
        artifact_reader=reader,
    )
    return SimpleNamespace(
        session=session,
        root=root,
        caller=caller,
        indexes=indexes,
        owners=owners,
        intents=intents,
        readings=readings,
        reader=reader,
        official=official,
        arguments=arguments,
    )


def run(case, **overrides):
    return application.resolve_embedding_device_index_pair(
        case.session, case.caller, **(case.arguments | overrides)
    )


def test_two_exact_official_reads_return_only_small_pair(case):
    pair = run(case)
    assert pair.target_count == 2 and pair.cpu.space != pair.cuda.space
    assert pair.cpu.manifest == case.intents[0].selection.index.index_manifest
    assert pair.cuda.manifest == case.intents[1].selection.index.index_manifest
    assert not hasattr(pair, "bindings") and not hasattr(pair, "vectors")
    assert case.official.call_count == case.reader.read_pinned.call_count == 2
    for position, owner in enumerate(case.owners):
        assert case.official.call_args_list[position].args == (
            case.session,
            case.caller,
            case.intents[position],
            owner,
        )
        owner.authorize_scope.assert_called_once_with(
            case.session, case.caller, case.intents[position].scope
        )
    case.reader.require_session.assert_called_once_with(case.session)
    case.reader.revalidate_provenance.assert_called_once()


def test_public_partial_selection_keeps_both_current_authority_reads(case):
    if not isinstance(case.intents[0].selection, PublicSolutionSimilarityView):
        with pytest.raises(EmbeddingDeviceIndexPairError, match="NAMESPACE_MISMATCH"):
            application.resolve_public_solution_device_indexes(
                case.session, case.caller, **case.arguments
            )
        return
    selected = application.resolve_public_solution_device_indexes(
        case.session, case.caller, **case.arguments
    )
    assert selected.cpu_target_count == selected.cuda_target_count == 2
    assert case.official.call_count == 2
    case.reader.revalidate_provenance.assert_called_once()
    for position, owner in enumerate(case.owners):
        owner.authorize_scope.assert_called_once_with(
            case.session, case.caller, case.intents[position].scope
        )


@pytest.mark.parametrize("fault", ("corpus", "policy", "graph", "bound", "namespace", "class"))
def test_scope_mismatch_is_not_smaller_device_fallback(case, fault):
    intent = case.intents[1]
    if fault == "class":
        case.owners[1].configuration = replace(
            case.owners[1].configuration,
            source_classes=("PAST_EXAM",)
            if len(case.owners[0].configuration.source_classes) == 2
            else ("APPROVED_ITEM", "PAST_EXAM"),
        )
    else:
        changes = {
            "corpus": {"corpus_id": "corpus_" + "c" * 32},
            "policy": {"policy_sha256": "sha256:" + "c" * 64},
            "graph": {
                "graph_snapshot": intent.scope.graph_snapshot.model_copy(
                    update={"graph_id": "graph_" + "c" * 32}
                )
            },
            "bound": {"maximum_sources": 1},
            "namespace": {
                "namespace": intent.scope.namespace.model_copy(update={"view": "CONTENT_ONLY"})
            },
        }[fault]
        intent = replace(intent, scope=replace(intent.scope, **changes))
    with pytest.raises(EmbeddingDeviceIndexPairError, match="NAMESPACE_MISMATCH"):
        run(case, cuda_intent=intent)
    case.official.assert_not_called()


@pytest.mark.parametrize("fault", ("sources", "profiles", "bindings"))
def test_current_revocation_or_partial_disclosure_cannot_hide_manifest_members(case, fault):
    changed = replace(case.readings[1], **{fault: getattr(case.readings[1], fault)[:-1]})
    case.official.side_effect = (case.readings[0], changed)
    with pytest.raises(EmbeddingDeviceIndexPairError, match="CURRENT_TARGET_SET_MISMATCH"):
        run(case)
    case.reader.revalidate_provenance.assert_not_called()


@pytest.mark.parametrize("position", (0, 1))
def test_permission_source_or_hash_error_from_owner_is_preserved(case, position):
    failure = EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
    case.official.side_effect = [failure] if position == 0 else [case.readings[0], failure]
    with pytest.raises(EmbeddingRegistryError) as error:
        run(case)
    assert error.value is failure and case.official.call_count == position + 1
    case.reader.read_pinned.assert_not_called()


@pytest.mark.parametrize(
    "fault", ("root", "nested", "pending_write", "identity", "reader", "engine")
)
def test_noncurrent_or_unrelated_read_root_rejected_before_resolution(case, fault):
    if fault == "root":
        case.root.is_active = False
    elif fault == "nested":
        case.session.get_nested_transaction.return_value = object()
    elif fault == "pending_write":
        case.session.dirty = [object()]
    elif fault == "identity":
        case.owners[1].identity_fence = None
    elif fault == "reader":
        case.reader.settings = CatalogSettings(nas_artifact_root="/tmp/unrelated-catalog")
    else:
        case.session.get_bind.return_value = object()
    with pytest.raises(EmbeddingDeviceIndexPairError, match="AUTHORITY_UNAVAILABLE"):
        run(case)
    case.official.assert_not_called()


def test_root_change_or_final_authority_denial_cannot_return_a_pair(case):
    case.reader.read_pinned.side_effect = [
        SimpleNamespace(payload=canonical_json_bytes(i.model_dump(mode="json")))
        for i in case.indexes
    ]
    case.owners[1].authorize_scope.side_effect = EmbeddingRegistryError(
        "EMBEDDING_REGISTRY_FORBIDDEN"
    )
    with pytest.raises(EmbeddingRegistryError):
        run(case)
    case.reader.revalidate_provenance.assert_not_called()


def test_artifact_provenance_recheck_cannot_be_replaced_by_a_good_pair(case):
    case.reader.revalidate_provenance.side_effect = ValueError(
        "synthetic immutable provenance changed"
    )
    with pytest.raises(ValueError, match="provenance changed"):
        run(case)


def test_each_call_resolves_its_exact_pins_again(case):
    case.official.side_effect = list(case.readings) * 2
    assert run(case) == run(case)
    assert case.official.call_count == case.reader.read_pinned.call_count == 4
    assert case.reader.revalidate_provenance.call_count == 2


def test_original_transaction_cannot_change_while_reading_pinned_members(case):
    payloads = [canonical_json_bytes(index.model_dump(mode="json")) for index in case.indexes]

    def read(**_kwargs):
        case.session.get_transaction.return_value = SimpleNamespace(is_active=True)
        return SimpleNamespace(payload=payloads.pop(0))

    case.reader.read_pinned.side_effect = read
    with pytest.raises(EmbeddingDeviceIndexPairError, match="AUTHORITY_UNAVAILABLE"):
        run(case)
    for owner in case.owners:
        owner.authorize_scope.assert_not_called()


def test_manifest_hash_or_storage_error_is_not_an_allocation_failure(case):
    failure = ValueError("synthetic canonical member hash failure")
    case.reader.read_pinned.side_effect = failure
    with pytest.raises(ValueError) as error:
        run(case)
    assert error.value is failure
    for owner in case.owners:
        owner.authorize_scope.assert_not_called()


def test_no_source_or_service_identity_can_replace_the_actual_operator(case):
    with pytest.raises(EmbeddingDeviceIndexPairError, match="AUTHORITY_UNAVAILABLE"):
        application.resolve_embedding_device_index_pair(
            case.session, SimpleNamespace(operator_id=case.caller.operator_id), **case.arguments
        )
    case.official.assert_not_called()
