"""Optional completed-read composition in the existing Catalog, never native execution."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import replace
from pathlib import Path

from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.similarity_reader_configuration import (
    MAX_SIMILARITY_READER_CONFIGURATION_BYTES,
    SimilarityReaderConfiguration,
    SimilarityReaderConfigurationV2,
    SupportedSimilarityReaderConfiguration,
    parse_similarity_reader_configuration,
    require_mixed_similarity_reader_cohost,
)
from eom_catalog_contracts.similarity_reader_routed_configuration import (
    RoutedSimilarityReaderConfiguration,
    parse_similarity_reader_installed_selection,
    require_same_routed_reader_controls,
)
from eom_identifiers import sha256_bytes
from eom_identity_service import (
    OperatorAuthorizationFenceOwnerPin,
    PostgresOperatorAuthorizationFence,
    require_operator_authorization_fence_installation,
)
from eom_identity_service.operator_authorization_fence_sql import (
    OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.settings import Settings
from eom_workflow.reference_query_owner_configuration import (
    ReferenceQueryPublicServiceConfiguration,
)
from eom_workflow.reference_query_routed_owner_configuration import (
    PublicRoutedReferenceQueryOwnerConfiguration,
    parse_reference_query_installed_owner_selection,
    require_supported_routed_reference_query_policy,
)
from eom_workflow_runner.embedding_batch_plan_admission import (
    resolve_embedding_device_routing_policy,
)
from eom_workflow_runner.reference_query_source_read import (
    CatalogReferenceQueryReadOwner,
    ReferenceQueryOwnerConfiguration,
    read_pinned_reference_query_controls,
    read_selected_reference_query_controls,
)
from pydantic import TypeAdapter
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.exam_similarity_read_service import CatalogExamSimilarityReadService
from eom_catalog_service.item_similarity_publication_service import (
    CatalogItemSimilarityPublicationService,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_read_service import CatalogSimilarityContextReadService
from eom_catalog_service.workflow_similarity_read_service import (
    CatalogWorkflowSimilarityReadService,
)

SIMILARITY_READER_CONFIGURATION_PATH = Path("/etc/eom/catalog-similarity-read.json")
MIXED_SIMILARITY_READER_CONFIGURATION_PATH = Path("/etc/eom/catalog-mixed-similarity-read.json")
EXAM_SIMILARITY_READER_CONFIGURATION_PATH = Path("/etc/eom/catalog-exam-similarity-read.json")
PUBLIC_SIMILARITY_READER_CONFIGURATION_PATH = Path("/etc/eom/public-reference-query-owner.json")


class SimilarityReaderRuntimeError(ValueError):
    def __init__(self) -> None:
        super().__init__("CATALOG_SIMILARITY_READ_UNAVAILABLE")


def build_catalog_exam_similarity_reads(
    engine: Engine,
    *,
    mode: str,
    configuration_raw_sha256: str | None = None,
    settings: CatalogSettings | None = None,
) -> CatalogExamSimilarityReadService | None:
    """Independent configured DOCUMENT scope; reference enable never grants exam access."""
    if mode == "DISABLED":
        return None
    if mode != "ENABLED" or configuration_raw_sha256 is None:
        raise SimilarityReaderRuntimeError()
    try:
        _selection, registry, identity = _admitted_reader_inputs(
            engine, read_exam_similarity_reader_configuration(configuration_raw_sha256)
        )
        catalog = CatalogEmbeddingRegistryVerifier(
            engine, registry, identity_fence=identity, settings=settings
        )
        return CatalogExamSimilarityReadService(catalog, identity)
    except Exception:
        raise SimilarityReaderRuntimeError() from None


def build_catalog_item_similarity_publications(
    *,
    mode: str,
    context_reads: CatalogSimilarityContextReadService | None,
    source_commit: str | None,
) -> CatalogItemSimilarityPublicationService | None:
    """Explicit publication enable; old read/runner flags alone grant no writes."""
    if mode == "DISABLED":
        return None
    if (
        mode != "ENABLED"
        or not isinstance(context_reads, CatalogSimilarityContextReadService)
        or source_commit is None
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
    ):
        raise SimilarityReaderRuntimeError()
    owner = context_reads.owner
    settings = owner.settings
    try:
        parent = settings.staging_root.lstat()
        if (
            not settings.staging_root.is_absolute()
            or settings.staging_root.resolve(strict=True) != settings.staging_root
            or settings.staging_root.is_symlink()
            or not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.geteuid()
            or parent.st_mode & 0o022
        ):
            raise SimilarityReaderRuntimeError()
        root = settings.staging_root / "item-similarity-publication"
        for path in (root, root / "workspaces", root / "staging"):
            path.mkdir(mode=0o700, exist_ok=True)
            metadata = path.lstat()
            if (
                path.is_symlink()
                or not stat.S_ISDIR(metadata.st_mode)
                or (metadata.st_uid, metadata.st_gid) != (os.geteuid(), os.getegid())
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise SimilarityReaderRuntimeError()
        publisher = ControlFileSetPublisher(
            owner.catalog.engine,
            Settings(
                staging_root=root / "staging",
                workspace_root=root / "workspaces",
                nas_artifact_root=settings.nas_artifact_root,
                runtime_source_commit=source_commit,
            ),
        )
        return CatalogItemSimilarityPublicationService(
            owner, publisher, source_commit=source_commit
        )
    except OSError:
        raise SimilarityReaderRuntimeError() from None


def build_catalog_workflow_similarity_reads(
    *, mode: str, context_reads: CatalogSimilarityContextReadService | None
) -> CatalogWorkflowSimilarityReadService | None:
    """Separately enable the runner operation; the existing API flag grants no new peer."""
    if mode == "DISABLED":
        return None
    if mode != "ENABLED" or not isinstance(context_reads, CatalogSimilarityContextReadService):
        raise SimilarityReaderRuntimeError()
    return CatalogWorkflowSimilarityReadService(context_reads.owner)


def _directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        *_directory_identity(value),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_similarity_reader_configuration(expected_raw_sha256: str) -> bytes:
    """One fixed root-protected non-secret file; no user/model supplied path."""
    return _read_reader_configuration(SIMILARITY_READER_CONFIGURATION_PATH, expected_raw_sha256)


def read_exam_similarity_reader_configuration(expected_raw_sha256: str) -> bytes:
    """C5's independent fixed selection; never fall back to reference configuration."""
    return _read_reader_configuration(
        EXAM_SIMILARITY_READER_CONFIGURATION_PATH, expected_raw_sha256
    )


def read_mixed_similarity_reader_configuration(expected_raw_sha256: str) -> bytes:
    """Separate protected opt-in; neither primary nor exam selection is a fallback."""
    return _read_reader_configuration(
        MIXED_SIMILARITY_READER_CONFIGURATION_PATH, expected_raw_sha256
    )


def read_public_similarity_reader_configuration(expected_raw_sha256: str) -> bytes:
    """Reuse the installed public controls, not QUERY process privileges or capture."""
    return _read_reader_configuration(
        PUBLIC_SIMILARITY_READER_CONFIGURATION_PATH, expected_raw_sha256
    )


def _read_reader_configuration(path: Path, expected_raw_sha256: str) -> bytes:
    TypeAdapter(Sha256).validate_python(expected_raw_sha256)
    directories: list[tuple[int, int | None, str, tuple[int, ...]]] = []
    descriptor = -1
    try:
        for component in path.parent.parts:
            parent = directories[-1][0] if directories else None
            fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            metadata = os.fstat(fd)
            directories.append((fd, parent, component, _directory_identity(metadata)))
            if metadata.st_uid != 0 or metadata.st_mode & 0o022:
                raise SimilarityReaderRuntimeError()
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directories[-1][0],
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) not in {0o640, 0o644}
            or not 0 < before.st_size <= MAX_SIMILARITY_READER_CONFIGURATION_BYTES
        ):
            raise SimilarityReaderRuntimeError()
        raw = os.pread(descriptor, MAX_SIMILARITY_READER_CONFIGURATION_BYTES + 1, 0)
        if (
            len(raw) != before.st_size
            or sha256_bytes(raw) != expected_raw_sha256
            or _file_identity(os.fstat(descriptor)) != _file_identity(before)
            or _file_identity(os.stat(path.name, dir_fd=directories[-1][0], follow_symlinks=False))
            != _file_identity(before)
        ):
            raise SimilarityReaderRuntimeError()
        for fd, parent, name, identity in directories:
            if (
                _directory_identity(os.fstat(fd)) != identity
                or _directory_identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
                != identity
            ):
                raise SimilarityReaderRuntimeError()
        return raw
    except OSError:
        raise SimilarityReaderRuntimeError() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        for fd, *_rest in reversed(directories):
            os.close(fd)


def _admitted_reader_inputs(
    engine: Engine, raw: bytes
) -> tuple[
    SimilarityReaderConfiguration,
    EmbeddingRegistryOwnerConfiguration,
    PostgresOperatorAuthorizationFence,
]:
    selection = parse_similarity_reader_configuration(raw)
    registry, identity = _admit_reader_selection(engine, selection)
    return selection, registry, identity


def _admit_reader_selection(
    engine: Engine, selection: SupportedSimilarityReaderConfiguration
) -> tuple[EmbeddingRegistryOwnerConfiguration, PostgresOperatorAuthorizationFence]:
    pin = OperatorAuthorizationFenceOwnerPin(
        selection.database_owner.role_name, selection.database_owner.role_oid
    )
    identity = _admit_reader_database_owner(engine, pin)
    registry = EmbeddingRegistryOwnerConfiguration(
        selection.corpus_id,
        selection.namespace,
        selection.document_space,
        selection.recipe,
        selection.source_classes,
    )
    return registry, identity


def _admit_reader_database_owner(
    engine: Engine, pin: OperatorAuthorizationFenceOwnerPin
) -> PostgresOperatorAuthorizationFence:
    # Installation/role inspection is independent for each configured reader;
    # no source/operator admission is inferred or cached by this composition.
    with engine.connect() as connection:
        if connection.dialect.name != "postgresql" or (
            connection.scalar(text("SELECT CURRENT_USER"))
            != OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE
        ):
            raise SimilarityReaderRuntimeError()
        require_operator_authorization_fence_installation(connection, pin)
    return PostgresOperatorAuthorizationFence(pin)


def build_catalog_similarity_context_reads(
    engine: Engine,
    *,
    mode: str,
    configuration_raw_sha256: str | None = None,
    mixed_configuration_raw_sha256: str | None = None,
    public_configuration_raw_sha256: str | None = None,
    settings: CatalogSettings | None = None,
) -> CatalogSimilarityContextReadService | None:
    if mode == "DISABLED":
        return None
    if mode != "ENABLED" or configuration_raw_sha256 is None:
        raise SimilarityReaderRuntimeError()
    try:
        selection, routed, owner = _configured_reference_read_owner(
            engine,
            read_similarity_reader_configuration(configuration_raw_sha256),
            settings=settings,
        )
        if type(selection) is not SimilarityReaderConfiguration:
            raise SimilarityReaderRuntimeError()
        mixed_owner = None
        if mixed_configuration_raw_sha256 is not None:
            mixed, mixed_routed, mixed_owner = _configured_reference_read_owner(
                engine,
                read_mixed_similarity_reader_configuration(mixed_configuration_raw_sha256),
                settings=settings,
            )
            if type(mixed) is not SimilarityReaderConfigurationV2:
                raise SimilarityReaderRuntimeError()
            require_mixed_similarity_reader_cohost(selection, mixed)
            require_same_routed_reader_controls(routed, mixed_routed)
        public_owner = None
        if public_configuration_raw_sha256 is not None:
            public_owner = _configured_public_reference_read_owner(
                engine,
                read_public_similarity_reader_configuration(public_configuration_raw_sha256),
                settings=settings,
            )
            if (
                public_owner.configuration.registry.corpus_id
                != owner.configuration.registry.corpus_id
            ):
                raise SimilarityReaderRuntimeError()
        return CatalogSimilarityContextReadService(
            owner, mixed_owner=mixed_owner, public_owner=public_owner
        )
    except Exception:
        raise SimilarityReaderRuntimeError() from None


def _configured_reference_read_owner(
    engine: Engine, raw: bytes, *, settings: CatalogSettings | None
) -> tuple[
    SupportedSimilarityReaderConfiguration,
    RoutedSimilarityReaderConfiguration | None,
    CatalogReferenceQueryReadOwner,
]:
    selection, routed = parse_similarity_reader_installed_selection(raw)
    registry, identity = _admit_reader_selection(engine, selection)
    cpu_configuration = ReferenceQueryOwnerConfiguration(
        registry,
        selection.native_execution_policy,
        selection.native_execution_policy_sha256,
        selection.runtime_bundle,
    )
    cuda_owner = None
    if routed is not None:
        namespace = type(registry.namespace).model_validate(
            registry.namespace.model_dump(mode="json")
            | {"space_sha256": routed.cuda_document_space.space_sha256}
        )
        cuda_configuration = ReferenceQueryOwnerConfiguration(
            replace(registry, namespace=namespace, space=routed.cuda_document_space),
            routed.cuda_native_execution_policy,
            routed.cuda_native_execution_policy_sha256,
            routed.cuda_runtime_bundle,
        )
        with Session(engine) as session, session.begin():
            session.execute(text("SET TRANSACTION READ ONLY"))
            reader = PinnedArtifactReadContext.for_session(
                session, settings or CatalogSettings.from_environment()
            )
            for configuration in (cpu_configuration, cuda_configuration):
                policy, _bundle = read_pinned_reference_query_controls(reader, configuration)
                if policy.spaces.document != configuration.registry.space:
                    raise SimilarityReaderRuntimeError()
            reader.revalidate_provenance()
        cuda_owner = CatalogReferenceQueryReadOwner(
            engine, cuda_configuration, identity_fence=identity, settings=settings
        )
    owner = CatalogReferenceQueryReadOwner(
        engine, cpu_configuration, identity_fence=identity, settings=settings, cuda_owner=cuda_owner
    )
    return selection, routed, owner


def _configured_public_reference_read_owner(
    engine: Engine, raw: bytes, *, settings: CatalogSettings | None
) -> CatalogReferenceQueryReadOwner:
    """Derive read-only CPU/CUDA owners from exact public controls, never a launcher."""
    selected, routed = parse_reference_query_installed_owner_selection(raw)
    if not isinstance(selected, ReferenceQueryPublicServiceConfiguration) or not isinstance(
        routed, PublicRoutedReferenceQueryOwnerConfiguration
    ):
        raise SimilarityReaderRuntimeError()
    identity = _admit_reader_database_owner(
        engine,
        OperatorAuthorizationFenceOwnerPin(
            selected.database_owner.role_name, selected.database_owner.role_oid
        ),
    )
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION READ ONLY"))
        reader = PinnedArtifactReadContext.for_session(
            session, settings or CatalogSettings.from_environment()
        )
        cpu, _ = read_selected_reference_query_controls(
            reader,
            policy_member=selected.native_execution_policy,
            policy_sha256=selected.native_execution_policy_sha256,
            runtime_bundle=selected.runtime_bundle,
        )
        routing = resolve_embedding_device_routing_policy(reader, routed.routing_policy)
        cuda, _ = read_selected_reference_query_controls(
            reader,
            policy_member=routed.cuda_native_execution_policy,
            policy_sha256=routed.cuda_native_execution_policy_sha256,
            runtime_bundle=routing.cuda.profile.runtime_bundle,
        )
        require_supported_routed_reference_query_policy(routed, routing, cpu, cuda)
        reader.revalidate_provenance()
    cpu_registry = EmbeddingRegistryOwnerConfiguration(
        selected.corpus_id,
        selected.namespace,
        cpu.spaces.document,
        selected.recipe,
        selected.source_classes,
    )
    cuda_namespace = type(selected.namespace).model_validate(
        selected.namespace.model_dump(mode="json")
        | {"space_sha256": cuda.spaces.document.space_sha256}
    )
    cuda_owner = CatalogReferenceQueryReadOwner(
        engine,
        ReferenceQueryOwnerConfiguration(
            replace(cpu_registry, namespace=cuda_namespace, space=cuda.spaces.document),
            routed.cuda_native_execution_policy,
            routed.cuda_native_execution_policy_sha256,
            routing.cuda.profile.runtime_bundle,
        ),
        identity_fence=identity,
        settings=settings,
    )
    return CatalogReferenceQueryReadOwner(
        engine,
        ReferenceQueryOwnerConfiguration(
            cpu_registry,
            selected.native_execution_policy,
            selected.native_execution_policy_sha256,
            selected.runtime_bundle,
        ),
        identity_fence=identity,
        settings=settings,
        cuda_owner=cuda_owner,
    )
