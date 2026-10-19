"""Optional completed-read composition in the existing Catalog, never native execution."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.similarity_reader_configuration import (
    MAX_SIMILARITY_READER_CONFIGURATION_BYTES,
    SimilarityReaderConfiguration,
    SupportedSimilarityReaderConfiguration,
    parse_similarity_reader_configuration,
    parse_similarity_reader_configuration_v2,
    require_mixed_similarity_reader_cohost,
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
from eom_workflow_runner.reference_query_source_read import (
    CatalogReferenceQueryReadOwner,
    ReferenceQueryOwnerConfiguration,
)
from pydantic import TypeAdapter
from sqlalchemy import Engine, text

from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.exam_similarity_read_service import CatalogExamSimilarityReadService
from eom_catalog_service.item_similarity_publication_service import (
    CatalogItemSimilarityPublicationService,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_read_service import CatalogSimilarityContextReadService
from eom_catalog_service.workflow_similarity_read_service import (
    CatalogWorkflowSimilarityReadService,
)

SIMILARITY_READER_CONFIGURATION_PATH = Path("/etc/eom/catalog-similarity-read.json")
MIXED_SIMILARITY_READER_CONFIGURATION_PATH = Path("/etc/eom/catalog-mixed-similarity-read.json")
EXAM_SIMILARITY_READER_CONFIGURATION_PATH = Path("/etc/eom/catalog-exam-similarity-read.json")


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
    # Installation/role inspection is independent for each configured reader;
    # no source/operator admission is inferred or cached by this composition.
    with engine.connect() as connection:
        if connection.dialect.name != "postgresql" or (
            connection.scalar(text("SELECT CURRENT_USER"))
            != OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE
        ):
            raise SimilarityReaderRuntimeError()
        require_operator_authorization_fence_installation(connection, pin)
    registry = EmbeddingRegistryOwnerConfiguration(
        selection.corpus_id,
        selection.namespace,
        selection.document_space,
        selection.recipe,
        selection.source_classes,
    )
    return registry, PostgresOperatorAuthorizationFence(pin)


def build_catalog_similarity_context_reads(
    engine: Engine,
    *,
    mode: str,
    configuration_raw_sha256: str | None = None,
    mixed_configuration_raw_sha256: str | None = None,
    settings: CatalogSettings | None = None,
) -> CatalogSimilarityContextReadService | None:
    if mode == "DISABLED":
        return None
    if mode != "ENABLED" or configuration_raw_sha256 is None:
        raise SimilarityReaderRuntimeError()
    try:
        selection, registry, identity = _admitted_reader_inputs(
            engine, read_similarity_reader_configuration(configuration_raw_sha256)
        )
        owner = CatalogReferenceQueryReadOwner(
            engine,
            ReferenceQueryOwnerConfiguration(
                registry,
                selection.native_execution_policy,
                selection.native_execution_policy_sha256,
                selection.runtime_bundle,
            ),
            identity_fence=identity,
            settings=settings,
        )
        mixed_owner = None
        if mixed_configuration_raw_sha256 is not None:
            mixed = parse_similarity_reader_configuration_v2(
                read_mixed_similarity_reader_configuration(mixed_configuration_raw_sha256)
            )
            require_mixed_similarity_reader_cohost(selection, mixed)
            mixed_registry, mixed_identity = _admit_reader_selection(engine, mixed)
            mixed_owner = CatalogReferenceQueryReadOwner(
                engine,
                ReferenceQueryOwnerConfiguration(
                    mixed_registry,
                    mixed.native_execution_policy,
                    mixed.native_execution_policy_sha256,
                    mixed.runtime_bundle,
                ),
                identity_fence=mixed_identity,
                settings=settings,
            )
        return CatalogSimilarityContextReadService(owner, mixed_owner=mixed_owner)
    except Exception:
        raise SimilarityReaderRuntimeError() from None
