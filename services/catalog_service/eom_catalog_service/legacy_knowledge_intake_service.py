"""Catalog application boundary for legacy inventory dry runs and manifest commit."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from eom_catalog_contracts import (
    LegacyRootAlias,
    LegacySourceInventoryPolicy,
    LegacySourceInventoryV2,
    validate_contract,
)
from eom_identifiers import content_sha256
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.legacy_source_inventory import (
    LegacySourceInventoryScanner,
    LegacySourceRootConfiguration,
)
from eom_catalog_service.settings import CatalogSettings

LEGACY_INVENTORY_PROTOCOL_VERSION = "legacy-source-inventory/1.0"
LEGACY_INVENTORY_PROTOCOL_SCHEMA_HASH = content_sha256(
    {
        "protocol": LEGACY_INVENTORY_PROTOCOL_VERSION,
        "contracts": {
            "legacy-source-inventory-policy/1.0": (
                "sha256:a48a917eeeb5460404c58f8ca12bdf6bcf0b70a15cbec88fa7398442bd79c742"
            ),
            "legacy-source-inventory/2.0": (
                "sha256:ecb02a261d523e640cda1d11118b988c1d5038e020429e959856eb08c65979e7"
            ),
        },
    }
)


@dataclass(frozen=True)
class LegacyInventoryCommitResult:
    inventory_id: str
    source_set_sha256: str
    inventory_sha256: str
    artifact_id: str
    artifact_revision_id: str
    artifact_content_sha256: str
    artifact_manifest_sha256: str


class LegacyKnowledgeIntakeService:
    """Orchestrate one inventory without making legacy files canonical."""

    def __init__(
        self,
        engine: Engine | None = None,
        *,
        settings: CatalogSettings | None = None,
        scanner: LegacySourceInventoryScanner | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.scanner = scanner or LegacySourceInventoryScanner()
        self.artifacts = (
            CatalogArtifactService(engine, self.settings) if engine is not None else None
        )

    def dry_run(
        self,
        *,
        policy: LegacySourceInventoryPolicy,
        roots: LegacySourceRootConfiguration,
        root_alias: LegacyRootAlias,
        observed_at: datetime | None = None,
    ) -> LegacySourceInventoryV2:
        return self.scanner.scan(
            policy=policy,
            roots=roots,
            root_alias=root_alias,
            observed_at=observed_at,
        )

    def commit_inventory(self, inventory: LegacySourceInventoryV2) -> LegacyInventoryCommitResult:
        """Commit only the manifest; source bytes remain outside EOM and untouched."""

        if self.artifacts is None:
            raise RuntimeError("legacy inventory Artifact service is not configured")
        value = inventory.model_dump(mode="json")
        validate_contract("legacy-source-inventory-v2", value)
        payload = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            + b"\n"
        )
        with tempfile.TemporaryDirectory(
            prefix="legacy-source-inventory-", dir=self.settings.staging_root
        ) as directory:
            staging_directory = Path(directory)
            os.chmod(staging_directory, 0o700)
            manifest_path = staging_directory / "legacy-source-inventory.json"
            descriptor = os.open(
                manifest_path,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                os.fchmod(descriptor, 0o600)
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("short legacy inventory staging write")
                    view = view[written:]
                os.fsync(descriptor)
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
                    raise OSError("legacy inventory staging metadata mismatch")
            finally:
                os.close(descriptor)
            artifact = self.artifacts.commit_file_set(
                files={"legacy-source-inventory.json": manifest_path},
                primary_file="legacy-source-inventory.json",
                artifact_type="legacy-source-inventory",
                idempotency_key=f"legacy-source-inventory:{inventory.source_set_sha256}",
                request={
                    "schema_version": "legacy-source-inventory-commit-request/1.0",
                    "inventory_id": inventory.inventory_id,
                    "source_set_sha256": inventory.source_set_sha256,
                    "inventory_sha256": inventory.inventory_sha256,
                    "root_alias": inventory.root_alias,
                    "scanner_policy_revision_id": inventory.scanner_policy_revision_id,
                    "scanner_policy_sha256": inventory.scanner_policy_sha256,
                },
                result={
                    "schema_version": "legacy-source-inventory-commit-result/1.0",
                    "inventory_id": inventory.inventory_id,
                    "source_set_sha256": inventory.source_set_sha256,
                    "inventory_sha256": inventory.inventory_sha256,
                    "summary": inventory.summary.model_dump(mode="json"),
                },
                file_metadata={
                    "legacy-source-inventory.json": {
                        "media_type": "application/json",
                        "schema_ref": (
                            "eom://schemas/legacy-knowledge/legacy-source-inventory/2.0"
                        ),
                    }
                },
                manifest_version="legacy-source-inventory-artifact/1.0",
                protocol_version=LEGACY_INVENTORY_PROTOCOL_VERSION,
                protocol_schema_hash=LEGACY_INVENTORY_PROTOCOL_SCHEMA_HASH,
            )
        return LegacyInventoryCommitResult(
            inventory_id=inventory.inventory_id,
            source_set_sha256=inventory.source_set_sha256,
            inventory_sha256=inventory.inventory_sha256,
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            artifact_content_sha256=artifact.content_hash,
            artifact_manifest_sha256=artifact.manifest_hash,
        )
