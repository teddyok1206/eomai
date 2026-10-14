"""Optional completed-read composition in the existing Catalog, never native execution."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.similarity_reader_configuration import (
    MAX_SIMILARITY_READER_CONFIGURATION_BYTES,
    parse_similarity_reader_configuration,
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
from eom_workflow_runner.reference_query_source_read import (
    CatalogReferenceQueryReadOwner,
    ReferenceQueryOwnerConfiguration,
)
from pydantic import TypeAdapter
from sqlalchemy import Engine, text

from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_read_service import CatalogSimilarityContextReadService

SIMILARITY_READER_CONFIGURATION_PATH = Path("/etc/eom/catalog-similarity-read.json")


class SimilarityReaderRuntimeError(ValueError):
    def __init__(self) -> None:
        super().__init__("CATALOG_SIMILARITY_READ_UNAVAILABLE")


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
    TypeAdapter(Sha256).validate_python(expected_raw_sha256)
    path = SIMILARITY_READER_CONFIGURATION_PATH
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


def build_catalog_similarity_context_reads(
    engine: Engine,
    *,
    mode: str,
    configuration_raw_sha256: str | None = None,
    settings: CatalogSettings | None = None,
) -> CatalogSimilarityContextReadService | None:
    if mode == "DISABLED":
        return None
    if mode != "ENABLED" or configuration_raw_sha256 is None:
        raise SimilarityReaderRuntimeError()
    try:
        selection = parse_similarity_reader_configuration(
            read_similarity_reader_configuration(configuration_raw_sha256)
        )
        pin = OperatorAuthorizationFenceOwnerPin(
            selection.database_owner.role_name, selection.database_owner.role_oid
        )
        # This independently verifies installation; it does not install, grant,
        # authorize an operator, open an old capture or inspect a current index.
        with engine.connect() as connection:
            if connection.dialect.name != "postgresql" or (
                connection.scalar(text("SELECT CURRENT_USER"))
                != OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE
            ):
                raise SimilarityReaderRuntimeError()
            require_operator_authorization_fence_installation(connection, pin)
        owner = CatalogReferenceQueryReadOwner(
            engine,
            ReferenceQueryOwnerConfiguration(
                EmbeddingRegistryOwnerConfiguration(
                    selection.corpus_id,
                    selection.namespace,
                    selection.document_space,
                    selection.recipe,
                    selection.source_classes,
                ),
                selection.native_execution_policy,
                selection.native_execution_policy_sha256,
                selection.runtime_bundle,
            ),
            identity_fence=PostgresOperatorAuthorizationFence(pin),
            settings=settings,
        )
        return CatalogSimilarityContextReadService(owner)
    except Exception:
        raise SimilarityReaderRuntimeError() from None
