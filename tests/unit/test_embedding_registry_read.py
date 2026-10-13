"""Exact read orchestration and indexed SQL shape; synthetic metadata, no DB or grants."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexNamespace,
    RegisterEmbeddingIndexCommand,
)
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSourceBinding
from eom_catalog_contracts.inference_transfer_experiment import VIEWS
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.similarity_context import SimilarityIndexPin, SimilarityViewSelection
from eom_catalog_service import embedding_registry_application as application
from eom_catalog_service.embedding_registry_models import EmbeddingSourceBindingRecord
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    EmbeddingRegistryRead,
    EmbeddingRegistryVerificationPort,
    MaterializedEmbeddingReadRow,
    RegisteredEmbeddingIndexRead,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.embedding_registry_repository import (
    EmbeddingRegistryRepository,
    artifact_member,
)
from eom_identifiers import content_sha256
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Session

from tests.unit.embedding_registry_application_fixtures import (
    MemoryRepository,
    MemorySession,
    SyntheticVerifier,
    capture_pair,
)
from tests.unit.inference_transfer_embedding_fixtures import embedding_space, seal

CALLER = EmbeddingRegistryCaller("operator_" + "1" * 32)


def read_intent(command: RegisterEmbeddingIndexCommand) -> EmbeddingRegistryRead:
    _, capture = capture_pair()
    return EmbeddingRegistryRead(
        EmbeddingRegistryLookup(
            command.corpus_id,
            command.namespace,
            command.graph_snapshot,
            command.policy_revision_id,
            command.policy_sha256,
        ),
        SimilarityViewSelection(
            view=command.namespace.view,
            recipe=capture.index.recipe,
            index=SimilarityIndexPin(
                index_id=command.index_id,
                index_revision_id=command.index_revision_id,
                index_manifest=command.index_manifest,
                index_sha256=command.index_sha256,
                storage_partition=command.namespace.storage_partition,
                spaces=ReferenceQuerySpaces(
                    query=embedding_space(purpose="QUERY"), document=capture.index.space
                ),
            ),
        ),
    )


class ReadSession(MemorySession):
    no_autoflush = nullcontext()

    def __init__(self) -> None:
        super().__init__()
        self.read_calls: list[str] = []

    def in_nested_transaction(self) -> bool:
        return False


class ReadRepository(MemoryRepository):
    def read_pinned_revision(
        self, index_id: str, revision_id: str
    ) -> RegisteredEmbeddingIndexRead | None:
        cast(ReadSession, self.session).read_calls.append("revision")
        revision = self.revision(revision_id)
        head = self.session.state["heads"].get(index_id)
        if revision is None or head is None or revision.index_id != index_id:
            return None
        return RegisteredEmbeddingIndexRead(
            head.corpus_id,
            EmbeddingIndexNamespace.model_validate(
                {name: getattr(head, name) for name in EmbeddingIndexNamespace.model_fields}
            ),
            revision.index_id,
            revision.index_revision_id,
            artifact_member(revision, "manifest_"),
            revision.index_sha256,
            revision.graph_snapshot_revision_id,
            revision.policy_revision_id,
            revision.policy_sha256,
            revision.binding_count,
            revision.binding_set_sha256,
        )

    def bindings(self, keys: Any) -> Any:
        cast(ReadSession, self.session).read_calls.append("bindings")
        return super().bindings(keys)

    def encodings(self, keys: Any) -> Any:
        cast(ReadSession, self.session).read_calls.append("encodings")
        return super().encodings(keys)

    def head(self, _index_id: str) -> Any:
        raise AssertionError("read must never resolve or lock current head")


class ReadOwner(SyntheticVerifier):
    def __init__(self, intent: EmbeddingRegistryRead) -> None:
        _, capture = capture_pair()
        super().__init__(capture)
        self.intent = intent
        binding = capture.index.bindings[0]
        entry = capture.entries[0]
        self.result = ResolvedPinnedEmbeddingIndex(
            intent,
            capture.sources,
            (
                AuthorizedEmbeddingReadProfile(
                    binding.source.item_revision_id,
                    InferenceTransferProfilePointer.from_profile(entry.profile),
                ),
            ),
            (binding,),
            (
                MaterializedEmbeddingReadRow(
                    registered_row_from_binding(binding),
                    (1.0,) + (0.0,) * (capture.index.space.model_spec.dimension - 1),
                ),
            ),
        )
        self.deny_first = False
        self.deny_late = False

    def authorize_scope(
        self, session: Session, caller: EmbeddingRegistryCaller, intent: Any
    ) -> None:
        super().authorize_scope(session, caller, intent)
        if self.deny_first or (self.deny_late and self.calls.count("authorize") == 2):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")

    def resolve_pinned_read(
        self,
        _session: Session,
        _caller: EmbeddingRegistryCaller,
        _intent: EmbeddingRegistryRead,
        _registered: RegisteredEmbeddingIndexRead,
    ) -> ResolvedPinnedEmbeddingIndex:
        self.calls.append("read")
        return self.result


def registered_row_from_binding(binding: Any) -> Any:
    from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow

    return RegisteredEmbeddingRow(binding.encoding, binding.row_ref)


@pytest.fixture
def read_case(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ReadSession, ReadOwner, EmbeddingRegistryRead]:
    command, capture = capture_pair()
    session = ReadSession()
    monkeypatch.setattr(application, "EmbeddingRegistryRepository", MemoryRepository)
    application.register_embedding_index(
        cast(Session, session),
        CALLER,
        command,
        cast(EmbeddingRegistryVerificationPort, SyntheticVerifier(capture)),
    )
    intent = read_intent(command)
    owner = ReadOwner(intent)
    monkeypatch.setattr(application, "EmbeddingRegistryRepository", ReadRepository)
    return session, owner, intent


def invoke(
    case: tuple[ReadSession, ReadOwner, EmbeddingRegistryRead],
) -> ResolvedPinnedEmbeddingIndex:
    session, owner, intent = case
    return application.read_pinned_embedding_index(
        cast(Session, session), CALLER, intent, cast(EmbeddingRegistryVerificationPort, owner)
    )


def test_exact_historical_read_ignores_current_head_and_batches_selected_relations(
    read_case: tuple[Any, ...],
) -> None:
    session, owner, intent = read_case
    session.state["heads"][intent.selection.index.index_id].current_index_revision_id = (
        "embeddingindexrev_" + "f" * 32
    )
    result = invoke(read_case)
    assert result is owner.result
    assert (
        result.authorized_source_count
        == result.accepted_profile_count
        == result.available_binding_count
        == 1
    )
    assert result.missing_report_count == 0
    assert session.read_calls == ["revision", "bindings", "encodings"]
    assert owner.calls == ["authorize", "read", "authorize"]
    assert not hasattr(result, "index") and not hasattr(result, "entries")


@pytest.mark.parametrize(
    "denial",
    ["missing_owner", "old_owner", "first_permission", "late_permission", "nested", "transaction"],
)
def test_authority_is_required_before_lookup_and_rechecked_before_disclosure(
    read_case: tuple[Any, ...],
    denial: str,
) -> None:
    session, owner, intent = read_case
    verification: Any = owner
    if denial == "missing_owner":
        verification = None
    elif denial == "old_owner":
        verification = SyntheticVerifier(owner.capture)
    elif denial == "first_permission":
        owner.deny_first = True
    elif denial == "late_permission":
        owner.deny_late = True
    elif denial == "nested":
        session.in_nested_transaction = lambda: True
    else:
        session.transaction_active = False
    with pytest.raises(EmbeddingRegistryError):
        application.read_pinned_embedding_index(
            cast(Session, session), CALLER, intent, verification
        )
    if denial != "late_permission":
        assert not session.read_calls


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "namespace",
        "hash",
        "row",
        "source",
        "duplicate",
        "unranked_source",
        "wrong_recipe",
        "wrong_view",
    ],
)
def test_missing_stale_or_forged_registered_closure_is_never_repaired(
    read_case: tuple[Any, ...],
    change: str,
) -> None:
    session, owner, intent = read_case
    pin = intent.selection.index
    assert pin is not None
    if change == "missing":
        session.state["revisions"].clear()
    elif change == "namespace":
        session.state["heads"][pin.index_id].storage_partition = "other"
    elif change == "hash":
        session.state["revisions"][pin.index_revision_id].index_sha256 = "sha256:" + "f" * 64
    elif change == "row":
        next(iter(session.state["encodings"].values())).row_index = 99
    elif change == "source":
        next(iter(session.state["bindings"].values())).source_sha256 = "sha256:" + "f" * 64
    elif change == "duplicate":
        owner.result = replace(owner.result, sources=owner.result.sources * 2)
    elif change == "unranked_source":
        owner.result = replace(
            owner.result,
            sources=(owner.result.sources[0].model_copy(update={"lifecycle_state": "PENDING"}),),
        )
    elif change == "wrong_recipe":
        intent = replace(
            intent,
            selection=intent.selection.model_copy(
                update={
                    "recipe": intent.selection.recipe.model_copy(update={"ranking": "ROUNDED_TIES"})
                }
            ),
        )
    else:
        intent = replace(intent, selection=intent.selection.model_copy(update={"view": VIEWS[0]}))
    with pytest.raises(EmbeddingRegistryError):
        invoke((session, owner, intent))


def test_zero_selected_bindings_is_authorized_partial_coverage_not_missing_source(
    read_case: tuple[Any, ...],
) -> None:
    session, owner, intent = read_case
    owner.result = replace(owner.result, profiles=(), bindings=(), numerical_rows=())
    result = invoke((session, owner, intent))
    assert result.authorized_source_count == result.missing_report_count == 1
    assert result.accepted_profile_count == result.available_binding_count == 0


def test_repository_read_is_exact_pk_namespace_join_without_mutable_head_or_lock() -> None:
    session = Mock(spec=Session)
    session.execute.return_value.one_or_none.return_value = None
    assert (
        EmbeddingRegistryRepository(session).read_pinned_revision(
            "embeddingindex_" + "1" * 32, "embeddingindexrev_" + "2" * 32
        )
        is None
    )
    statement = session.execute.call_args.args[0]
    dialect = cast(type[Dialect], PGDialect)()
    sql = str(statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    assert (
        "JOIN embedding_indexes" in sql and "embedding_index_revisions.index_revision_id =" in sql
    )
    assert "FOR UPDATE" not in sql and "current_index_revision_id" not in sql
    assert "lock_version" not in sql and "eligible_source_count" not in sql
    assert session.execute.call_count == 1


def test_bounded_1024_binding_read_keeps_constant_batch_query_count_and_one_shared_vector(
    read_case: tuple[Any, ...],
) -> None:
    """Synthetic pointer/lookup complexity evidence, not DB EXPLAIN or encoder throughput."""
    session, owner, intent = read_case
    original = owner.result.bindings[0]
    template = next(iter(session.state["bindings"].values()))
    sources = []
    profiles = []
    bindings = []
    records = {}
    for ordinal in range(1024):
        seed = f"{ordinal:032x}"
        source_body = original.source.model_dump(mode="json")
        source_body.update(item_id="item_" + seed, item_revision_id="itemrev_" + seed)
        source = type(original.source).model_validate(source_body)
        profile = InferenceTransferProfilePointer(
            profile_id="inferenceprofile_" + seed,
            profile_revision_id="inferenceprofilerev_" + seed,
            profile_sha256=content_sha256({"synthetic_source_revision": source.item_revision_id}),
        )
        body = original.model_dump(mode="json")
        body.update(source=source.model_dump(mode="json"), profile=profile.model_dump(mode="json"))
        binding = EmbeddingSourceBinding.model_validate(seal(body, "binding_sha256"))
        record_body = {
            column.name: getattr(template, column.name)
            for column in EmbeddingSourceBindingRecord.__table__.columns
        }
        record_body.update(
            binding_sha256=binding.binding_sha256,
            item_id=source.item_id,
            item_revision_id=source.item_revision_id,
            profile_id=profile.profile_id,
            profile_revision_id=profile.profile_revision_id,
            profile_sha256=profile.profile_sha256,
        )
        records[binding.binding_sha256] = EmbeddingSourceBindingRecord(**record_body)
        sources.append(source)
        profiles.append(AuthorizedEmbeddingReadProfile(source.item_revision_id, profile))
        bindings.append(binding)
    owner.result = replace(
        owner.result, sources=tuple(sources), profiles=tuple(profiles), bindings=tuple(bindings)
    )
    session.state["bindings"] = records
    assert intent.selection.index is not None
    session.state["revisions"][intent.selection.index.index_revision_id].binding_count = 1024
    result = invoke((session, owner, intent))
    assert result.authorized_source_count == result.available_binding_count == 1024
    assert len(result.numerical_rows) == 1
    assert session.read_calls == ["revision", "bindings", "encodings"]


def test_raw_copied_model_boolean_cannot_be_repaired_before_read_authorization(
    read_case: tuple[Any, ...],
) -> None:
    session, owner, intent = read_case
    assert intent.selection.index is not None
    pin = intent.selection.index
    space = pin.spaces.document
    model = space.model_spec
    copied_model = model.model_copy(
        update={
            "files": (
                model.files[0].model_copy(update={"size_bytes": True}),
                *model.files[1:],
            )
        }
    )
    copied_space = space.model_copy(update={"model_spec": copied_model})
    copied_pin = pin.model_copy(
        update={"spaces": pin.spaces.model_copy(update={"document": copied_space})}
    )
    intent = replace(intent, selection=intent.selection.model_copy(update={"index": copied_pin}))
    with pytest.raises(EmbeddingRegistryError):
        invoke((session, owner, intent))
    assert not owner.calls and not session.read_calls


@pytest.mark.parametrize("malformed", ["profile", "row", "encoding", "row_ref"])
def test_malformed_owner_nested_values_fail_with_stable_pointer_error_not_attribute_error(
    read_case: tuple[Any, ...],
    malformed: str,
) -> None:
    session, owner, intent = read_case
    if malformed == "profile":
        original = owner.result.profiles[0]
        owner.result = replace(owner.result, profiles=(replace(original, profile="bad"),))
    else:
        original_row = owner.result.numerical_rows[0]
        if malformed == "row":
            changed = replace(original_row, row="bad")
        elif malformed == "encoding":
            changed = replace(original_row, row=replace(original_row.row, encoding="bad"))
        else:
            changed = replace(original_row, row=replace(original_row.row, row_ref="bad"))
        owner.result = replace(owner.result, numerical_rows=(changed,))
    with pytest.raises(EmbeddingRegistryError) as error:
        invoke((session, owner, intent))
    assert error.value.code == "EMBEDDING_REGISTRY_POINTER_INVALID"
