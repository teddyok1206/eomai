"""Current-operator Catalog composition; no transport, IAM grant or background admission."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexNamespace,
    RegisterEmbeddingIndexCommand,
)
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
    MAX_EMBEDDING_INPUT_BYTES,
    RESULT_SCHEMA_REF,
    SHARD_SCHEMA_REF,
    EmbeddingEncodingIdentity,
    EmbeddingIndexManifest,
    EmbeddingSpace,
    EmbeddingVectorRowRef,
    EmbeddingVectorShardManifest,
    parse_embedding_index,
    parse_embedding_shard,
    parse_incremental_embedding_result,
    validate_embedding_source_bindings,
)
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_identifiers import canonical_json_bytes
from eom_identity_service import OperatorAuthorizationFenceError
from eom_identity_service.operator_authorization_fence import OperatorAuthorizationFence
from eom_operator_identity.errors import IdentityError
from eom_orchestrator.embedding_artifact_store import (
    EMBEDDING_INDEX_ARTIFACT_TYPE,
    EMBEDDING_INDEX_MANIFEST_VERSION,
    EMBEDDING_INDEX_MEMBER_NAMES,
    EMBEDDING_INDEX_PRIMARY_MEMBER,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as JsonSchemaError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_incremental_plan import (
    RegisteredEmbeddingRow,
    plan_embedding_delta,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingBindingOrigin,
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    ResolvedEmbeddingBindingOrigin,
    ResolvedEmbeddingLookup,
    ResolvedEmbeddingReferences,
    ResolvedEmbeddingRegistration,
)
from eom_catalog_service.inference_transfer_catalog_adapter import (
    InferenceTransferCorpusReadCommand,
)
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
    InferenceTransferSessionCapture,
    InferenceTransferSessionCapturePhase,
)
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeGraphPublicationRecord,
    KnowledgeGraphSnapshotRecord,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalServiceError
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_catalog_service.settings import CatalogSettings


@dataclass(frozen=True, slots=True)
class EmbeddingRegistryOwnerConfiguration:
    """Owner numerical/isolation configuration, never a source permission grant."""

    corpus_id: str
    namespace: EmbeddingIndexNamespace
    space: EmbeddingSpace
    recipe: ExperimentViewRecipe
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise ValueError("duplicate immutable JSON key")
        value[name] = item
    return value


def _reject_constant(_value: str) -> Any:
    raise ValueError("nonstandard immutable JSON constant")


def _document(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        raise ValueError("immutable member is not exact canonical JSON")
    return value


class CatalogEmbeddingRegistryVerifier:
    """Concrete official source/member composition; IAM fence is mandatory and not supplied.

    Construct in the trusted owner, not from a DTO. No controller/runtime wiring
    is activated here. A required Identity fence implementation remains a separate
    official Identity security gate, and absent composition fails before writes.
    """

    def __init__(
        self,
        engine: Engine,
        configuration: EmbeddingRegistryOwnerConfiguration,
        *,
        identity_fence: OperatorAuthorizationFence | None,
        settings: CatalogSettings | None = None,
    ) -> None:
        self.configuration = EmbeddingRegistryOwnerConfiguration(
            configuration.corpus_id,
            EmbeddingIndexNamespace.model_validate(configuration.namespace.model_dump(mode="json")),
            EmbeddingSpace.model_validate(configuration.space.model_dump(mode="json")),
            ExperimentViewRecipe.model_validate(configuration.recipe.model_dump(mode="json")),
            configuration.source_classes,
        )
        config = self.configuration
        if (
            config.namespace.space_sha256 != config.space.space_sha256
            or config.namespace.recipe_sha256 != config.recipe.recipe_sha256
            or config.space.purpose != "DOCUMENT"
            or not config.source_classes
            or config.source_classes != tuple(sorted(set(config.source_classes)))
            or not set(config.source_classes).issubset({"APPROVED_ITEM", "PAST_EXAM"})
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_CONFIGURATION_INVALID")
        self.settings = settings or CatalogSettings.from_environment()
        self.identity_fence = identity_fence
        self.sources = CatalogInferenceTransferSnapshotSourceAdapter(engine, self.settings)

    def _capture(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
        phase: InferenceTransferSessionCapturePhase,
    ) -> tuple[PinnedArtifactReadContext, InferenceTransferSessionCapture]:
        if self.identity_fence is None:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
        if (
            intent.corpus_id != self.configuration.corpus_id
            or intent.namespace != self.configuration.namespace
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        reader = PinnedArtifactReadContext(session, self.settings)
        command = InferenceTransferCorpusReadCommand(
            actor_id=caller.operator_id,
            graph_snapshot=intent.graph_snapshot,
            access_policy_revision_id=intent.policy_revision_id,
            access_policy_sha256=intent.policy_sha256,
            source_classes=self.configuration.source_classes,
            maximum_candidates=1024
            if isinstance(intent, RegisterEmbeddingIndexCommand)
            else intent.maximum_sources,
            population_scope=InferenceTransferPopulationScope(intent.namespace.population_scope),
        )
        capture = self.sources.capture_in_session(
            session,
            command,
            self.configuration.recipe,
            identity_fence=self.identity_fence,
            artifact_reader=reader,
            phase=phase,
        )
        if (
            isinstance(intent, RegisterEmbeddingIndexCommand)
            and "knowledge_graph:publish" not in capture.scope.requester_permission_keys
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
        corpus = session.scalar(
            select(KnowledgeCorpusRecord)
            .where(KnowledgeCorpusRecord.corpus_id == intent.corpus_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        graph = session.get(
            KnowledgeGraphSnapshotRecord, intent.graph_snapshot.graph_snapshot_revision_id
        )
        publication = session.scalar(
            select(KnowledgeGraphPublicationRecord).where(
                KnowledgeGraphPublicationRecord.graph_snapshot_revision_id
                == intent.graph_snapshot.graph_snapshot_revision_id,
                KnowledgeGraphPublicationRecord.corpus_id == intent.corpus_id,
            )
        )
        if (
            corpus is None
            or graph is None
            or publication is None
            or corpus.lifecycle_state != "ACTIVE"
            or graph.graph_id != corpus.graph_id
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        return reader, capture

    def _read_index(
        self, reader: PinnedArtifactReadContext, pointer: ArtifactMemberPointer
    ) -> EmbeddingIndexManifest:
        pointer = ArtifactMemberPointer.model_validate(pointer.model_dump(mode="json"))
        if (
            pointer.schema_ref != INDEX_SCHEMA_REF
            or pointer.member_path != EMBEDDING_INDEX_PRIMARY_MEMBER
            or pointer.media_type != "application/json"
        ):
            raise ValueError("foreign index pointer")
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        raw = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(EMBEDDING_INDEX_ARTIFACT_TYPE,),
            expected_primary_file=EMBEDDING_INDEX_PRIMARY_MEMBER,
            max_bytes=MAX_EMBEDDING_INPUT_BYTES,
        )
        reader.require_file_set(
            pointer.artifact_id,
            pointer.artifact_revision_id,
            EMBEDDING_INDEX_MEMBER_NAMES,
            manifest_version=EMBEDDING_INDEX_MANIFEST_VERSION,
        )
        return parse_embedding_index(_document(raw.payload))

    def _read_shards(
        self,
        reader: PinnedArtifactReadContext,
        pointers: tuple[ArtifactMemberPointer, ...],
    ) -> tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]:
        reader.prefetch(tuple(sorted({(p.artifact_id, p.artifact_revision_id) for p in pointers})))
        shards = []
        for pointer in pointers:
            if (
                pointer.schema_ref != SHARD_SCHEMA_REF
                or pointer.member_path != "shard.json"
                or pointer.media_type != "application/json"
            ):
                raise ValueError("foreign shard pointer")
            shard = parse_embedding_shard(
                _document(
                    reader.read_pinned(
                        **pointer.model_dump(mode="python"),
                        expected_artifact_types=("control_incremental_embedding",),
                        expected_primary_file="result.json",
                        max_bytes=MAX_EMBEDDING_INPUT_BYTES,
                    ).payload
                )
            )
            reader.require_file_set(
                pointer.artifact_id,
                pointer.artifact_revision_id,
                ("result.json", "shard.json", "vectors.f32"),
                manifest_version="control-file-set/1.0",
            )
            # The primary SHA is owner metadata, never guessed from the shard SHA.
            result_pointer = reader.member_pointer(
                pointer.artifact_id,
                pointer.artifact_revision_id,
                "result.json",
                schema_ref=RESULT_SCHEMA_REF,
                media_type="application/json",
            )
            result = parse_incremental_embedding_result(
                _document(
                    reader.read_pinned(
                        **result_pointer.model_dump(mode="python"),
                        expected_artifact_types=("control_incremental_embedding",),
                        expected_primary_file="result.json",
                        max_bytes=MAX_EMBEDDING_INPUT_BYTES,
                    ).payload
                )
            )
            if result.shard != shard or shard.space != self.configuration.space:
                raise ValueError("native result and exact configured shard differ")
            binary = ArtifactMemberPointer(
                artifact_id=pointer.artifact_id,
                artifact_revision_id=pointer.artifact_revision_id,
                member_path=shard.binary.member_path,
                schema_ref=shard.binary.schema_ref,
                media_type=shard.binary.media_type,
                sha256=shard.binary.sha256,
            )
            read_unit_vectors(
                reader.read_pinned(
                    **binary.model_dump(mode="python"),
                    expected_artifact_types=("control_incremental_embedding",),
                    expected_primary_file="result.json",
                    max_bytes=shard.binary.byte_count,
                ).payload,
                dimension=shard.dimension,
                row_count=shard.row_count,
                expected_sha256=shard.binary.sha256,
            )
            shards.append((pointer, shard))
        return tuple(shards)

    def authorize_scope(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
    ) -> None:
        self._guard(
            lambda: self._capture(
                session, caller, intent, InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE
            )
        )

    @staticmethod
    def _guard[T](operation: Callable[[], T]) -> T:
        try:
            return operation()
        except EmbeddingRegistryError:
            raise
        except OperatorAuthorizationFenceError as error:
            code = (
                "EMBEDDING_REGISTRY_FORBIDDEN"
                if error.code
                in {
                    "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN",
                    "OPERATOR_AUTHORIZATION_FENCE_OPERATOR_INVALID",
                }
                else "EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE"
            )
            raise EmbeddingRegistryError(code) from None
        except IdentityError:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN") from None
        except InferenceTransferServiceError as error:
            code = (
                "EMBEDDING_REGISTRY_FORBIDDEN"
                if error.code == "INFERENCE_TRANSFER_FORBIDDEN"
                else "EMBEDDING_REGISTRY_POINTER_INVALID"
            )
            raise EmbeddingRegistryError(code) from None
        except KnowledgeRetrievalServiceError as error:
            code = (
                "EMBEDDING_REGISTRY_FORBIDDEN"
                if error.code
                in {"KNOWLEDGE_RETRIEVAL_UNAUTHORIZED", "KNOWLEDGE_RETRIEVAL_REQUESTER_INVALID"}
                else "EMBEDDING_REGISTRY_POINTER_INVALID"
            )
            raise EmbeddingRegistryError(code) from None
        except (PinnedArtifactResolutionError, JsonSchemaError, ValueError, TypeError, KeyError):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID") from None

    def resolve_registration(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        command: RegisterEmbeddingIndexCommand,
    ) -> ResolvedEmbeddingRegistration:
        def resolve() -> ResolvedEmbeddingRegistration:
            reader, _ = self._capture(
                session, caller, command, InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE
            )
            index = self._read_index(reader, command.index_manifest)
            if index.space != self.configuration.space or index.recipe != self.configuration.recipe:
                raise ValueError("index numerical configuration differs")
            shards = self._read_shards(reader, index.shards)
            previous = (
                None
                if index.previous_manifest is None
                else (index.previous_manifest, self._read_index(reader, index.previous_manifest))
            )
            # Source/lifecycle eligibility stays with the same official owner and root Session.
            capture = self.sources.capture_in_session(
                session,
                InferenceTransferCorpusReadCommand(
                    caller.operator_id,
                    command.graph_snapshot,
                    command.policy_revision_id,
                    command.policy_sha256,
                    self.configuration.source_classes,
                    1024,
                    InferenceTransferPopulationScope(command.namespace.population_scope),
                ),
                self.configuration.recipe,
                identity_fence=self.identity_fence,
                artifact_reader=reader,
            )
            assert capture.corpus is not None
            sources = tuple(
                sorted(
                    (value.source for value in capture.corpus.sources),
                    key=lambda value: value.item_revision_id,
                )
            )
            return ResolvedEmbeddingRegistration(
                command.corpus_id, index, shards, previous, sources, capture.entries
            )

        return self._guard(resolve)

    def resolve_lookup(
        self, session: Session, caller: EmbeddingRegistryCaller, query: EmbeddingRegistryLookup
    ) -> ResolvedEmbeddingLookup:
        def resolve() -> ResolvedEmbeddingLookup:
            _reader, capture = self._capture(
                session, caller, query, InferenceTransferSessionCapturePhase.CAPTURE_POPULATION
            )
            assert capture.corpus is not None
            return ResolvedEmbeddingLookup(
                query.corpus_id,
                self.configuration.space,
                self.configuration.recipe,
                tuple(value.source for value in capture.corpus.sources),
                capture.entries,
            )

        return self._guard(resolve)

    def verify_registered_references(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
        rows: tuple[RegisteredEmbeddingRow, ...],
        origins: tuple[EmbeddingBindingOrigin, ...],
    ) -> ResolvedEmbeddingReferences:
        def resolve() -> ResolvedEmbeddingReferences:
            if len(rows) > 1024 or len(origins) > 1024:
                raise ValueError("registered reference budget exceeded")
            reader, capture = self._capture(
                session, caller, intent, InferenceTransferSessionCapturePhase.CAPTURE_POPULATION
            )
            plan = plan_embedding_delta(
                capture.entries,
                space=self.configuration.space,
                storage_partition=intent.namespace.storage_partition,
                views=(intent.namespace.view,),
            )
            expected = {d.encoding.encoding_sha256: d.encoding for d in plan.demands}
            checked_rows = tuple(
                RegisteredEmbeddingRow(
                    EmbeddingEncodingIdentity.model_validate(row.encoding.model_dump(mode="json")),
                    EmbeddingVectorRowRef.model_validate(row.row_ref.model_dump(mode="json")),
                )
                for row in rows
            )
            if len({row.encoding.encoding_sha256 for row in checked_rows}) != len(rows) or len(
                set(origins)
            ) != len(origins):
                raise ValueError("duplicate registered references")
            pointers = {row.row_ref.shard_manifest for row in checked_rows}
            index_pointers = tuple(
                sorted(
                    {origin.manifest for origin in origins},
                    key=lambda p: (p.artifact_id, p.artifact_revision_id, p.member_path, p.sha256),
                )
            )
            reader.prefetch(tuple((p.artifact_id, p.artifact_revision_id) for p in index_pointers))
            indices = {pointer: self._read_index(reader, pointer) for pointer in index_pointers}
            bindings = {
                pointer: {value.binding_sha256: value for value in index.bindings}
                for pointer, index in indices.items()
            }
            resolved = tuple(
                ResolvedEmbeddingBindingOrigin(
                    origin, bindings[origin.manifest][origin.binding_sha256]
                )
                for origin in origins
            )
            pointers.update(value.binding.row_ref.shard_manifest for value in resolved)
            shards = self._read_shards(
                reader,
                tuple(
                    sorted(
                        pointers,
                        key=lambda p: (
                            p.artifact_id,
                            p.artifact_revision_id,
                            p.member_path,
                            p.sha256,
                        ),
                    )
                ),
            )
            by_pointer = dict(shards)
            for row in checked_rows:
                shard = by_pointer[row.row_ref.shard_manifest]
                if (
                    row.encoding != expected.get(row.encoding.encoding_sha256)
                    or row.row_ref.encoding_sha256 != row.encoding.encoding_sha256
                    or row.row_ref.row_index >= len(shard.rows)
                    or shard.rows[row.row_ref.row_index] != row.encoding
                ):
                    raise ValueError("registered encoding differs from current source or exact row")
            selected = {value.binding.row_ref.shard_manifest for value in resolved}
            assert capture.corpus is not None
            admitted_sources = {
                value.source.item_revision_id: value.source for value in capture.corpus.sources
            }
            if any(
                value.binding.source != admitted_sources.get(value.binding.source.item_revision_id)
                or value.binding.graph_snapshot != intent.graph_snapshot
                or value.binding.policy_revision_id != intent.policy_revision_id
                or value.binding.policy_sha256 != intent.policy_sha256
                or value.binding.view != intent.namespace.view
                or value.binding.recipe != self.configuration.recipe
                or value.binding.projection_version != intent.namespace.projection_version
                for value in resolved
            ):
                raise ValueError("registered binding differs from exact current admitted scope")
            binding_shards = tuple(
                (pointer, shard) for pointer, shard in shards if pointer in selected
            )
            validate_embedding_source_bindings(
                tuple(value.binding for value in resolved), capture.entries, binding_shards
            )
            return ResolvedEmbeddingReferences(resolved, binding_shards)

        return self._guard(resolve)
