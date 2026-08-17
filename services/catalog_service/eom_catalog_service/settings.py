"""Catalog settings without credential material."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CatalogSettings:
    staging_root: Path = Path("/srv/eom/staging/catalog")
    nas_artifact_root: Path = Path("/mnt/nas/eom/artifacts")
    intake_root: Path = Path("/mnt/nas/eom/content-intake")

    @classmethod
    def from_environment(cls) -> CatalogSettings:
        return cls(
            staging_root=Path(os.environ.get("EOM_CATALOG_STAGING_ROOT", cls.staging_root)),
            nas_artifact_root=Path(os.environ.get("EOM_NAS_ARTIFACT_ROOT", cls.nas_artifact_root)),
            intake_root=Path(os.environ.get("EOM_CONTENT_INTAKE_ROOT", cls.intake_root)),
        )
