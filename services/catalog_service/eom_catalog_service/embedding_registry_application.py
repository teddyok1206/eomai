"""Catalog registration/replay/CAS and exact bounded missing-binding use cases.

No runtime composition is provided. A trusted official-source/Artifact verifier
is mandatory; neither contract possession nor database FK existence is authority.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, NoReturn

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexNamespace,
    EmbeddingIndexRegistrationResult,
    RegisterEmbeddingIndexCommand,
    parse_embedding_registration_command,
    validate_embedding_registration_result,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_ROWS,
    EmbeddingSourceBinding,
    parse_embedding_binding,
    parse_embedding_index,
    validate_embedding_index_references,
    validate_embedding_source_bindings,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    StagedExperimentEntry,
    population_sha256,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import TypeAdapter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_incremental_plan import plan_embedding_delta
from eom_catalog_service.embedding_registry_models import (
    EmbeddingIndexRecord,
    EmbeddingIndexRevisionRecord,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingBindingLookupKey,
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    EmbeddingRegistryVerificationPort,
    MissingEmbeddingBindings,
    ResolvedEmbeddingRegistration,
)
from eom_catalog_service.embedding_registry_repository import (
    EmbeddingRegistryRepository,
    artifact_member,
    binding_origin,
    registered_row,
)


def _fail(code: str) -> NoReturn:
    raise EmbeddingRegistryError(code)


def _pointer_columns(prefix: str, pointer: ArtifactMemberPointer) -> dict[str, str]:
    return {prefix + name: value for name, value in pointer.model_dump(mode="python").items()}


def _key(binding: EmbeddingSourceBinding) -> EmbeddingBindingLookupKey:
    return EmbeddingBindingLookupKey(
        binding.source.item_revision_id,
        binding.graph_snapshot.graph_snapshot_revision_id,
        binding.policy_revision_id,
        binding.recipe.recipe_sha256,
        binding.view,
        binding.projection_version,
        binding.solution_evidence.base_analysis_run_id,
        binding.profile.profile_revision_id,
        binding.solution_evidence.solution_analysis_run_id,
        binding.encoding.encoding_sha256,
    )


def _binding_columns(binding: EmbeddingSourceBinding) -> dict[str, Any]:
    return {
        "binding_sha256": binding.binding_sha256,
        "encoding_sha256": binding.encoding.encoding_sha256,
        "item_id": binding.source.item_id,
        "item_revision_id": binding.source.item_revision_id,
        "source_class": binding.source.source_class,
        "source_sha256": binding.source.artifact_member.sha256,
        "base_analysis_run_id": binding.solution_evidence.base_analysis_run_id,
        "solution_analysis_run_id": binding.solution_evidence.solution_analysis_run_id,
        "solution_pointer_sha256": binding.solution_evidence.pointer_sha256,
        "profile_id": binding.profile.profile_id,
        "profile_revision_id": binding.profile.profile_revision_id,
        "profile_sha256": binding.profile.profile_sha256,
        "graph_snapshot_revision_id": binding.graph_snapshot.graph_snapshot_revision_id,
        "policy_revision_id": binding.policy_revision_id,
        "policy_sha256": binding.policy_sha256,
        "view": binding.view,
        "recipe_sha256": binding.recipe.recipe_sha256,
        "projection_version": binding.projection_version,
    }


def validate_resolved_embedding_registration(
    command: RegisterEmbeddingIndexCommand,
    resolved: ResolvedEmbeddingRegistration,
) -> ResolvedEmbeddingRegistration:
    """Pure closure validation after the trusted owner resolves and reauthorizes bytes."""
    try:
        command = parse_embedding_registration_command(command.model_dump(mode="json"))
        index = parse_embedding_index(resolved.index.model_dump(mode="json"))
        if (
            resolved.truncated
            or not 1 <= len(resolved.sources) <= MAX_EMBEDDING_ROWS
            or len(resolved.entries) > MAX_EMBEDDING_ROWS
        ):
            _fail("EMBEDDING_REGISTRY_SCOPE_LIMIT")
        sources = {
            source.item_revision_id: type(source).model_validate(source.model_dump(mode="json"))
            for source in resolved.sources
        }
        entries = {}
        for original in resolved.entries:
            entry = StagedExperimentEntry.model_validate(original.model_dump(mode="json"))
            entries[entry.profile.source_basis.source.item_revision_id] = entry
        if (
            len(sources) != len(resolved.sources)
            or len(entries) != len(resolved.entries)
            or not set(entries).issubset(sources)
        ):
            _fail("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        namespace = command.namespace
        if (
            resolved.corpus_id != command.corpus_id
            or index.index_id != command.index_id
            or index.index_revision_id != command.index_revision_id
            or command.index_manifest.sha256 != content_sha256(index.model_dump(mode="json"))
            or index.index_sha256 != command.index_sha256
            or index.storage_partition != namespace.storage_partition
            or index.space.space_sha256 != namespace.space_sha256
            or index.view != namespace.view
            or index.recipe.recipe_sha256 != namespace.recipe_sha256
            or command.source_set_sha256 != population_sha256(resolved.sources)
            or command.binding_set_sha256
            != content_sha256([value.binding_sha256 for value in index.bindings])
            or command.eligible_source_count != len(sources)
            or command.binding_count != len(index.bindings)
        ):
            _fail("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        validate_embedding_index_references(index, resolved.shards, resolved.previous)
        if (resolved.previous is None) != (command.expected_current_index_revision_id is None) or (
            resolved.previous is not None
            and resolved.previous[1].index_revision_id != command.expected_current_index_revision_id
        ):
            _fail("EMBEDDING_INDEX_STALE_CURRENT")
        for binding in index.bindings:
            selected_entry = entries.get(binding.source.item_revision_id)
            if (
                selected_entry is None
                or sources.get(binding.source.item_revision_id) != binding.source
                or binding.graph_snapshot != command.graph_snapshot
                or binding.policy_revision_id != command.policy_revision_id
                or binding.policy_sha256 != command.policy_sha256
                or binding.projection_version != namespace.projection_version
            ):
                _fail("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        validate_embedding_source_bindings(index.bindings, resolved.entries, resolved.shards)
        return resolved
    except EmbeddingRegistryError:
        raise
    except (JsonSchemaError, ValueError, TypeError, KeyError):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID") from None


def _context(
    session: Session,
    caller: EmbeddingRegistryCaller,
    verification: EmbeddingRegistryVerificationPort | None,
) -> EmbeddingRegistryVerificationPort:
    if verification is None:
        _fail("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
    if type(caller.operator_id) is not str or not re.fullmatch(
        r"operator_[0-9a-f]{32}", caller.operator_id
    ):
        _fail("EMBEDDING_REGISTRY_CALLER_INVALID")
    if not session.in_transaction():
        _fail("EMBEDDING_REGISTRY_TRANSACTION_REQUIRED")
    assert verification is not None
    return verification


def _matches(row: object, expected: dict[str, Any]) -> bool:
    return all(getattr(row, name) == value for name, value in expected.items())


def _components(
    session: Session,
    caller: EmbeddingRegistryCaller,
    command: RegisterEmbeddingIndexCommand,
    resolved: ResolvedEmbeddingRegistration,
    repository: EmbeddingRegistryRepository,
    verification: EmbeddingRegistryVerificationPort,
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_encoding = {binding.encoding.encoding_sha256: binding for binding in resolved.index.bindings}
    encodings = repository.encodings(tuple(sorted(by_encoding)))
    bindings = repository.bindings(tuple(_key(binding) for binding in resolved.index.bindings))
    for key, encoding_record in encodings.items():
        binding = by_encoding[key]
        stored_row = registered_row(encoding_record)
        if stored_row.encoding != binding.encoding or stored_row.row_ref != binding.row_ref:
            _fail("EMBEDDING_REGISTRATION_CONFLICT")
    expected_bindings = {binding.binding_sha256: binding for binding in resolved.index.bindings}
    for digest, binding_record in bindings.items():
        expected_binding = expected_bindings.get(digest)
        if expected_binding is None or not _matches(
            binding_record, _binding_columns(expected_binding)
        ):
            _fail("EMBEDDING_REGISTRATION_CONFLICT")
    origins = tuple(binding_origin(bindings[key]) for key in sorted(bindings))
    verified = verification.verify_registered_references(
        session,
        caller,
        command,
        tuple(registered_row(encodings[key]) for key in sorted(encodings)),
        origins,
    )
    if len(verified.origins) != len(origins) or {value.origin for value in verified.origins} != set(
        origins
    ):
        _fail("EMBEDDING_REGISTRY_POINTER_INVALID")
    validate_embedding_source_bindings(
        tuple(value.binding for value in verified.origins), resolved.entries, verified.shards
    )
    for value in verified.origins:
        binding = parse_embedding_binding(value.binding.model_dump(mode="json"))
        if binding != expected_bindings.get(value.origin.binding_sha256):
            _fail("EMBEDDING_REGISTRY_POINTER_INVALID")
    return encodings, bindings


def _receipt(
    command: RegisterEmbeddingIndexCommand,
    row: EmbeddingIndexRevisionRecord,
    head: EmbeddingIndexRecord,
    *,
    replayed: bool,
) -> EmbeddingIndexRegistrationResult:
    if head.current_index_revision_id is None:
        _fail("EMBEDDING_REGISTRY_POINTER_INVALID")
    body = EmbeddingIndexRegistrationResult.model_construct(
        operation_key=row.operation_key,
        request_sha256=row.registration_request_sha256,
        index_id=row.index_id,
        index_revision_id=row.index_revision_id,
        previous_index_revision_id=row.previous_index_revision_id,
        index_manifest=artifact_member(row, "manifest_"),
        index_sha256=row.index_sha256,
        registered_lock_version=row.revision_number + 1,
        current_index_revision_id=head.current_index_revision_id,
        current_lock_version=head.lock_version,
        replayed=replayed,
        is_current=head.current_index_revision_id == row.index_revision_id,
        registered_at=row.created_at,
    ).model_dump(mode="json", exclude={"result_sha256"})
    result = EmbeddingIndexRegistrationResult.model_validate(
        body | {"result_sha256": content_sha256(body)}
    )
    return validate_embedding_registration_result(command, result)


def _registration(
    session: Session,
    caller: EmbeddingRegistryCaller,
    command: RegisterEmbeddingIndexCommand,
    verification: EmbeddingRegistryVerificationPort,
    now: datetime,
) -> EmbeddingIndexRegistrationResult:
    repository = EmbeddingRegistryRepository(session)
    operation = repository.operation(command.operation_key)
    if operation is not None and operation.registration_request_sha256 != command.request_sha256:
        _fail("EMBEDDING_REGISTRATION_CONFLICT")
    resolved = validate_resolved_embedding_registration(
        command, verification.resolve_registration(session, caller, command)
    )
    head = repository.head(command.index_id)
    if operation is not None and head is None:
        _fail("EMBEDDING_REGISTRY_POINTER_INVALID")
    if head is None:
        if command.expected_current_index_revision_id is not None:
            _fail("EMBEDDING_INDEX_STALE_CURRENT")
        try:
            with session.begin_nested():
                head = repository.create_head(command, now)
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) != "23505":
                raise
            head = repository.head(command.index_id)
            if head is None:
                _fail("EMBEDDING_REGISTRATION_CONFLICT")
    assert head is not None
    if not _matches(
        head, {"corpus_id": command.corpus_id, **command.namespace.model_dump(mode="python")}
    ):
        _fail("EMBEDDING_REGISTRATION_CONFLICT")
    # The head lock serializes contenders; recheck operation after waiting for its owner.
    operation = repository.operation(command.operation_key) or operation
    if operation is not None:
        if not _matches(
            operation,
            {
                "index_id": command.index_id,
                "index_revision_id": command.index_revision_id,
                "registration_request_sha256": command.request_sha256,
                "index_sha256": command.index_sha256,
                **_pointer_columns("manifest_", command.index_manifest),
            },
        ):
            _fail("EMBEDDING_REGISTRATION_CONFLICT")
        replay_encodings, replay_bindings = _components(
            session, caller, command, resolved, repository, verification
        )
        if len(replay_bindings) != command.binding_count or len(replay_encodings) != len(
            {value.encoding.encoding_sha256 for value in resolved.index.bindings}
        ):
            _fail("EMBEDDING_REGISTRY_POINTER_INVALID")
        return _receipt(command, operation, head, replayed=True)
    if (
        head.lock_version != command.expected_lock_version
        or head.current_index_revision_id != command.expected_current_index_revision_id
    ):
        _fail("EMBEDDING_INDEX_STALE_CURRENT")
    predecessor = (
        None
        if head.current_index_revision_id is None
        else repository.revision(head.current_index_revision_id)
    )
    if head.current_index_revision_id is not None and (
        predecessor is None
        or resolved.previous is None
        or artifact_member(predecessor, "manifest_") != resolved.previous[0]
        or predecessor.index_sha256 != resolved.previous[1].index_sha256
        or predecessor.revision_number + 1 != command.expected_lock_version
    ):
        _fail("EMBEDDING_INDEX_STALE_CURRENT")
    _components(session, caller, command, resolved, repository, verification)
    encodings = []
    bindings = []
    seen: set[str] = set()
    for binding in resolved.index.bindings:
        if binding.encoding.encoding_sha256 not in seen:
            seen.add(binding.encoding.encoding_sha256)
            encodings.append(
                {
                    **binding.encoding.model_dump(mode="python"),
                    **_pointer_columns("shard_", binding.row_ref.shard_manifest),
                    "row_index": binding.row_ref.row_index,
                    "registered_at": now,
                }
            )
        bindings.append(
            {
                **_binding_columns(binding),
                **_pointer_columns("binding_manifest_", command.index_manifest),
                "registered_at": now,
            }
        )
    repository.insert_components(encodings, bindings)
    stored_encodings, stored_bindings = _components(
        session, caller, command, resolved, repository, verification
    )
    if len(stored_bindings) != command.binding_count or len(stored_encodings) != len(seen):
        _fail("EMBEDDING_REGISTRY_POINTER_INVALID")
    row = EmbeddingIndexRevisionRecord(
        index_revision_id=command.index_revision_id,
        index_id=command.index_id,
        revision_number=command.expected_lock_version,
        previous_index_revision_id=command.expected_current_index_revision_id,
        graph_snapshot_revision_id=command.graph_snapshot.graph_snapshot_revision_id,
        policy_revision_id=command.policy_revision_id,
        policy_sha256=command.policy_sha256,
        **_pointer_columns("manifest_", command.index_manifest),
        index_sha256=command.index_sha256,
        source_set_sha256=command.source_set_sha256,
        binding_set_sha256=command.binding_set_sha256,
        eligible_source_count=command.eligible_source_count,
        binding_count=command.binding_count,
        operation_key=command.operation_key,
        registration_request_sha256=command.request_sha256,
        created_at=now,
    )
    repository.add_revision(row)
    if not repository.advance(command, now):
        _fail("EMBEDDING_INDEX_STALE_CURRENT")
    session.refresh(head)
    return _receipt(command, row, head, replayed=False)


def register_embedding_index(
    session: Session,
    caller: EmbeddingRegistryCaller,
    command: RegisterEmbeddingIndexCommand,
    verification: EmbeddingRegistryVerificationPort | None,
    *,
    now: datetime | None = None,
) -> EmbeddingIndexRegistrationResult:
    """Register metadata only; caller retains transaction commit/rollback ownership."""
    try:
        command = parse_embedding_registration_command(command.model_dump(mode="json"))
    except (JsonSchemaError, ValueError, TypeError):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID") from None
    owner = _context(session, caller, verification)
    try:
        timestamp = TypeAdapter(UtcDatetime).validate_python(now or datetime.now(UTC))
    except (ValueError, TypeError):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID") from None
    for attempt in range(2):
        try:
            # Acquire authority's retained row fence in the root transaction.
            # A uniqueness savepoint rollback must not release that fence.
            owner.authorize_scope(session, caller, command)
            with session.begin_nested():
                return _registration(session, caller, command, owner, timestamp)
        except IntegrityError as error:
            # One bounded same-operation uniqueness replay; no identity/CAS fallback.
            if (
                attempt == 0
                and getattr(error.orig, "sqlstate", None) == "23505"
                and EmbeddingRegistryRepository(session).operation(command.operation_key)
                is not None
            ):
                continue
            raise EmbeddingRegistryError("EMBEDDING_REGISTRATION_CONFLICT") from None
        except EmbeddingRegistryError:
            raise
        except (JsonSchemaError, ValueError, TypeError, KeyError):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID") from None
    raise AssertionError("bounded registration attempts must return or fail")


def _lookup_missing_embedding_bindings(
    session: Session,
    caller: EmbeddingRegistryCaller,
    query: EmbeddingRegistryLookup,
    verification: EmbeddingRegistryVerificationPort | None,
) -> MissingEmbeddingBindings:
    """Exact bounded lookup after official owner admission; never corpus discovery."""
    owner = _context(session, caller, verification)
    try:
        EmbeddingIndexNamespace.model_validate(query.namespace.model_dump(mode="json"))
        KnowledgeGraphSnapshotPointer.model_validate(query.graph_snapshot.model_dump(mode="json"))
        TypeAdapter(Sha256).validate_python(query.policy_sha256)
        if (
            type(query.maximum_sources) is not int
            or not 1 <= query.maximum_sources <= MAX_EMBEDDING_ROWS
        ):
            _fail("EMBEDDING_REGISTRY_REQUEST_INVALID")
        if not re.fullmatch(r"corpus_[0-9a-f]{32}", query.corpus_id) or not re.fullmatch(
            r"accessrev_[0-9a-f]{32}", query.policy_revision_id
        ):
            _fail("EMBEDDING_REGISTRY_REQUEST_INVALID")
    except (JsonSchemaError, ValueError, TypeError):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID") from None
    owner.authorize_scope(session, caller, query)
    resolved = owner.resolve_lookup(session, caller, query)
    if (
        resolved.truncated
        or resolved.corpus_id != query.corpus_id
        or not 0 <= len(resolved.sources) <= query.maximum_sources
        or len(resolved.entries) > query.maximum_sources
        or resolved.space.space_sha256 != query.namespace.space_sha256
        or resolved.recipe.recipe_sha256 != query.namespace.recipe_sha256
    ):
        _fail("EMBEDDING_REGISTRY_SCOPE_LIMIT")
    sources = {
        value.item_revision_id: type(value).model_validate(value.model_dump(mode="json"))
        for value in resolved.sources
    }
    checked_entries = tuple(
        StagedExperimentEntry.model_validate(value.model_dump(mode="json"))
        for value in resolved.entries
    )
    entries = {
        value.profile.source_basis.source.item_revision_id: value for value in checked_entries
    }
    if (
        len(sources) != len(resolved.sources)
        or len(entries) != len(resolved.entries)
        or not set(entries).issubset(sources)
    ):
        _fail("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    if any(
        entry.profile.extraction.method != "DETERMINISTIC_REPORT_PROJECTION"
        or entry.profile.extraction.extractor_version != query.namespace.projection_version
        for entry in resolved.entries
    ):
        _fail("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    plan = plan_embedding_delta(
        resolved.entries,
        space=resolved.space,
        storage_partition=query.namespace.storage_partition,
        views=(query.namespace.view,),
    )
    keys = []
    for demand in plan.demands:
        basis = entries[demand.source_revision_id].profile.source_basis
        if basis.graph_snapshot != query.graph_snapshot:
            _fail("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        keys.append(
            EmbeddingBindingLookupKey(
                demand.source_revision_id,
                query.graph_snapshot.graph_snapshot_revision_id,
                query.policy_revision_id,
                query.namespace.recipe_sha256,
                query.namespace.view,
                query.namespace.projection_version,
                basis.solution_evidence.base_analysis_run_id,
                demand.profile.profile_revision_id,
                basis.solution_evidence.solution_analysis_run_id,
                demand.encoding.encoding_sha256,
            )
        )
    selected = tuple(keys)
    repository = EmbeddingRegistryRepository(session)
    encodings = repository.encodings(tuple(sorted({key.encoding_sha256 for key in selected})))
    bindings = repository.bindings(selected)
    origins = tuple(binding_origin(bindings[key]) for key in sorted(bindings))
    rows = tuple(registered_row(encodings[key]) for key in sorted(encodings))
    expected_encodings = {
        demand.encoding.encoding_sha256: demand.encoding for demand in plan.demands
    }
    if any(row.encoding != expected_encodings.get(row.encoding.encoding_sha256) for row in rows):
        _fail("EMBEDDING_REGISTRY_POINTER_INVALID")
    verified = owner.verify_registered_references(session, caller, query, rows, origins)
    if len(verified.origins) != len(origins) or {value.origin for value in verified.origins} != set(
        origins
    ):
        _fail("EMBEDDING_REGISTRY_POINTER_INVALID")
    validate_embedding_source_bindings(
        tuple(value.binding for value in verified.origins), checked_entries, verified.shards
    )
    selected_set = set(selected)
    for value in verified.origins:
        binding = parse_embedding_binding(value.binding.model_dump(mode="json"))
        record = bindings.get(binding.binding_sha256)
        if (
            record is None
            or not _matches(record, _binding_columns(binding))
            or _key(binding) not in selected_set
        ):
            _fail("EMBEDDING_REGISTRY_POINTER_INVALID")
        row = encodings[binding.encoding.encoding_sha256]
        if (
            registered_row(row).row_ref != binding.row_ref
            or binding.graph_snapshot != query.graph_snapshot
        ):
            _fail("EMBEDDING_REGISTRY_POINTER_INVALID")
        if (
            binding.policy_sha256 != query.policy_sha256
            or binding.recipe != resolved.recipe
            or sources.get(binding.source.item_revision_id) != binding.source
        ):
            _fail("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    missing = repository.missing_bindings(selected)
    return MissingEmbeddingBindings(missing, rows, len(sources), len(selected))


def lookup_missing_embedding_bindings(
    session: Session,
    caller: EmbeddingRegistryCaller,
    query: EmbeddingRegistryLookup,
    verification: EmbeddingRegistryVerificationPort | None,
) -> MissingEmbeddingBindings:
    """Redacted application boundary; caller owns this read/authorization transaction."""
    try:
        return _lookup_missing_embedding_bindings(session, caller, query, verification)
    except EmbeddingRegistryError:
        raise
    except (JsonSchemaError, ValueError, TypeError, KeyError):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID") from None
