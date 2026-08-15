"""HWPX integration paths and resource limits."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HwpxSettings:
    builder_binary: Path = Path("/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx")
    builder_python: Path = Path("/srv/eom/conda/envs/eom-hwpx/bin/python")
    workspace_root: Path = Path("/srv/eom/hwpx-workspaces")
    staging_root: Path = Path("/srv/eom/staging")
    nas_artifact_root: Path = Path("/mnt/nas/eom/artifacts")
    hwpx_root: Path = Path("/mnt/nas/eom/hwpx/poc-v0")
    reference_kit: Path = Path("/mnt/nas/eom/hwpx/poc-v0/reference-kit/v1")
    reference_inbox: Path = Path("/mnt/nas/eom/hwpx/poc-v0/reference/inbox")
    manual_inbox: Path = Path("/mnt/nas/eom/hwpx/poc-v0/manual-validation/inbox")
    builder_user: str = "eom-hwpx"
    timeout_seconds: int = 180
    memory_max: str = "1G"

    @classmethod
    def from_environment(cls) -> HwpxSettings:
        return cls(
            builder_binary=Path(
                os.environ.get("EOM_HWPX_BUILDER", "/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx")
            ),
            builder_python=Path(
                os.environ.get("EOM_HWPX_PYTHON", "/srv/eom/conda/envs/eom-hwpx/bin/python")
            ),
            workspace_root=Path(
                os.environ.get("EOM_HWPX_WORKSPACE_ROOT", "/srv/eom/hwpx-workspaces")
            ),
            staging_root=Path(os.environ.get("EOM_STAGING_ROOT", "/srv/eom/staging")),
            nas_artifact_root=Path(
                os.environ.get("EOM_NAS_ARTIFACT_ROOT", "/mnt/nas/eom/artifacts")
            ),
            hwpx_root=Path(os.environ.get("EOM_HWPX_ROOT", "/mnt/nas/eom/hwpx/poc-v0")),
            builder_user=os.environ.get("EOM_HWPX_BUILDER_USER", "eom-hwpx"),
            timeout_seconds=int(os.environ.get("EOM_HWPX_TIMEOUT_SECONDS", "180")),
        )
