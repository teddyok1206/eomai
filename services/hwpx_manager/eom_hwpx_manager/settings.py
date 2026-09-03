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
    question_template_id: str = "hwpxtpl_4f0243bf966c4b9e81f987e448f68e24"
    question_template_revision_id: str = "hwpxrev_b6e818d569de4684a7a48d825b163b8e"
    question_template_artifact_id: str = "artifact_26dfd0347df0442982f539f98498b416"
    question_template_artifact_revision_id: str = "rev_aa42b43580d44652818b1a78469fe109"
    question_template_source_sha256: str = (
        "sha256:4287cfe4db91f497368c3e0c32b7efadab05e2137512c1341cc3b220cda8cefc"
    )
    question_template_binding_manifest_sha256: str = (
        "sha256:770f07c9f710870c45b4e4bad8cbe49781ec8e3eff9ea6229ddd1b6145c8598c"
    )
    content_team_handoff_artifact_id: str = "artifact_73e80b48f1054d8f8bb733dc1d13ae6f"
    content_team_handoff_artifact_revision_id: str = "rev_2801db879a4c4aaaa589f0cf2991b8c3"
    content_team_handoff_archive_sha256: str = (
        "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91"
    )
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
            question_template_id=os.environ.get(
                "EOM_HWPX_QUESTION_TEMPLATE_ID",
                "hwpxtpl_4f0243bf966c4b9e81f987e448f68e24",
            ),
            question_template_revision_id=os.environ.get(
                "EOM_HWPX_QUESTION_TEMPLATE_REVISION_ID",
                "hwpxrev_b6e818d569de4684a7a48d825b163b8e",
            ),
            question_template_artifact_id=os.environ.get(
                "EOM_HWPX_QUESTION_TEMPLATE_ARTIFACT_ID",
                "artifact_26dfd0347df0442982f539f98498b416",
            ),
            question_template_artifact_revision_id=os.environ.get(
                "EOM_HWPX_QUESTION_TEMPLATE_ARTIFACT_REVISION_ID",
                "rev_aa42b43580d44652818b1a78469fe109",
            ),
            question_template_source_sha256=os.environ.get(
                "EOM_HWPX_QUESTION_TEMPLATE_SOURCE_SHA256",
                "sha256:4287cfe4db91f497368c3e0c32b7efadab05e2137512c1341cc3b220cda8cefc",
            ),
            question_template_binding_manifest_sha256=os.environ.get(
                "EOM_HWPX_QUESTION_TEMPLATE_BINDING_MANIFEST_SHA256",
                "sha256:770f07c9f710870c45b4e4bad8cbe49781ec8e3eff9ea6229ddd1b6145c8598c",
            ),
            content_team_handoff_artifact_id=os.environ.get(
                "EOM_HWPX_CONTENT_TEAM_HANDOFF_ARTIFACT_ID",
                "artifact_73e80b48f1054d8f8bb733dc1d13ae6f",
            ),
            content_team_handoff_artifact_revision_id=os.environ.get(
                "EOM_HWPX_CONTENT_TEAM_HANDOFF_ARTIFACT_REVISION_ID",
                "rev_2801db879a4c4aaaa589f0cf2991b8c3",
            ),
            content_team_handoff_archive_sha256=os.environ.get(
                "EOM_HWPX_CONTENT_TEAM_HANDOFF_ARCHIVE_SHA256",
                "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91",
            ),
            timeout_seconds=int(os.environ.get("EOM_HWPX_TIMEOUT_SECONDS", "180")),
        )
