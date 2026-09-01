"""Catalog settings without credential material."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class CatalogStagingArea(StrEnum):
    CONTENT_PACKS = "content-packs"
    REGISTRY = "registry"
    WORKFLOW_PROMPTS = "workflow-prompts"


@dataclass(frozen=True)
class CatalogFixedStagingRoot:
    area: CatalogStagingArea
    check_name: str
    failure_code: str

    def path_beneath(self, staging_root: Path) -> Path:
        return staging_root / self.area.value


CATALOG_FIXED_STAGING_ROOTS = (
    CatalogFixedStagingRoot(
        CatalogStagingArea.CONTENT_PACKS,
        "catalog_content_pack_staging",
        "CATALOG_CONTENT_PACK_STAGING_INVALID",
    ),
    CatalogFixedStagingRoot(
        CatalogStagingArea.REGISTRY,
        "catalog_registry_staging",
        "CATALOG_REGISTRY_STAGING_INVALID",
    ),
    CatalogFixedStagingRoot(
        CatalogStagingArea.WORKFLOW_PROMPTS,
        "catalog_prompt_staging",
        "CATALOG_PROMPT_STAGING_INVALID",
    ),
)


@dataclass(frozen=True)
class CatalogSettings:
    staging_root: Path = Path("/srv/eom/staging/catalog")
    nas_artifact_root: Path = Path("/mnt/nas/eom/artifacts")
    intake_root: Path = Path("/mnt/nas/eom/content-intake")
    placeholder_pack_source: Path = Path("/home/eom/EOM/content/packs/generic-placeholder/0.1.0")
    knowledge_stimulus_source: Path = Path(
        "/mnt/nas/eom/hwpx/poc-v0/reference-kit/v1/eom-placeholder-image-output.png"
    )
    local_image_provider_binding: Path = Path("/etc/eom/local-image-provider.json")
    local_image_workspace_root: Path = Path("/srv/eom/image-workspaces")
    local_image_provider_group: str = "eom-image"

    @property
    def content_pack_staging_root(self) -> Path:
        return self.fixed_staging_root(CatalogStagingArea.CONTENT_PACKS)

    @property
    def registry_staging_root(self) -> Path:
        return self.fixed_staging_root(CatalogStagingArea.REGISTRY)

    @property
    def prompt_staging_root(self) -> Path:
        return self.fixed_staging_root(CatalogStagingArea.WORKFLOW_PROMPTS)

    def fixed_staging_root(self, area: CatalogStagingArea) -> Path:
        return self.staging_root / area.value

    @classmethod
    def from_environment(cls) -> CatalogSettings:
        return cls(
            staging_root=Path(os.environ.get("EOM_CATALOG_STAGING_ROOT", cls.staging_root)),
            nas_artifact_root=Path(os.environ.get("EOM_NAS_ARTIFACT_ROOT", cls.nas_artifact_root)),
            intake_root=Path(os.environ.get("EOM_CONTENT_INTAKE_ROOT", cls.intake_root)),
            placeholder_pack_source=Path(
                os.environ.get("EOM_PLACEHOLDER_PACK_SOURCE", cls.placeholder_pack_source)
            ),
            knowledge_stimulus_source=Path(
                os.environ.get("EOM_KNOWLEDGE_STIMULUS_SOURCE", cls.knowledge_stimulus_source)
            ),
            local_image_provider_binding=Path(
                os.environ.get("EOM_LOCAL_IMAGE_PROVIDER_BINDING", cls.local_image_provider_binding)
            ),
            local_image_workspace_root=Path(
                os.environ.get("EOM_LOCAL_IMAGE_WORKSPACE_ROOT", cls.local_image_workspace_root)
            ),
            local_image_provider_group=os.environ.get(
                "EOM_LOCAL_IMAGE_PROVIDER_GROUP", cls.local_image_provider_group
            ),
        )
