"""Pinned media provisioning and resolution for knowledge-backed template workflows."""

from __future__ import annotations

import stat
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from eom_identifiers import sha256_file
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import Engine, select

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.settings import CatalogSettings

KNOWLEDGE_STIMULUS_ASSET_KEY = "eom-question-template-reference-v1"
KNOWLEDGE_STIMULUS_IDEMPOTENCY_KEY = "knowledge-stimulus:eom-question-template-reference-v1"
KNOWLEDGE_STIMULUS_MEMBER = "eom-question-template-reference-v1.png"
MAX_STIMULUS_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class KnowledgeStimulusPointer:
    asset_key: str
    artifact_id: str
    artifact_revision_id: str
    artifact_member: str
    sha256: str
    media_type: str
    width_px: int
    height_px: int

    def as_dict(self) -> dict[str, str | int]:
        return {
            "asset_key": self.asset_key,
            "artifact_id": self.artifact_id,
            "artifact_revision_id": self.artifact_revision_id,
            "artifact_member": self.artifact_member,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "width_px": self.width_px,
            "height_px": self.height_px,
        }


class KnowledgeStimulusService:
    """Own the one fixed media pointer; workers receive bytes neither from DB nor NAS."""

    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)

    def provision(self, source: Path | None = None) -> KnowledgeStimulusPointer:
        selected = source or self.settings.knowledge_stimulus_source
        self._validate_png(selected)
        self.artifacts.commit_file_set(
            files={KNOWLEDGE_STIMULUS_MEMBER: selected},
            primary_file=KNOWLEDGE_STIMULUS_MEMBER,
            artifact_type="knowledge-workflow-stimulus",
            idempotency_key=KNOWLEDGE_STIMULUS_IDEMPOTENCY_KEY,
            request={"asset_key": KNOWLEDGE_STIMULUS_ASSET_KEY},
            result={"asset_key": KNOWLEDGE_STIMULUS_ASSET_KEY, "width_px": 800, "height_px": 500},
        )
        return self.resolve(KNOWLEDGE_STIMULUS_ASSET_KEY)

    def resolve(self, asset_key: str) -> KnowledgeStimulusPointer:
        if asset_key != KNOWLEDGE_STIMULUS_ASSET_KEY:
            raise ValueError("unknown knowledge stimulus asset key")
        with self.sessions() as session:
            job = session.scalar(
                select(JobRecord).where(
                    JobRecord.idempotency_key == KNOWLEDGE_STIMULUS_IDEMPOTENCY_KEY
                )
            )
            revision = (
                session.scalar(
                    select(ArtifactRevisionRecord).where(
                        ArtifactRevisionRecord.job_id == job.job_id
                    )
                )
                if job is not None
                else None
            )
            if (
                job is None
                or job.status != "SUCCEEDED"
                or revision is None
                or not revision.approved
                or revision.logical_artifact_id != job.logical_artifact_id
                or revision.revision_id != job.revision_id
                or revision.manifest.get("primary_file") != KNOWLEDGE_STIMULUS_MEMBER
            ):
                raise ValueError("knowledge stimulus artifact is not provisioned")
            root = self.settings.nas_artifact_root.resolve(strict=True)
            artifact_root = Path(revision.nas_path).resolve(strict=True)
            if not artifact_root.is_relative_to(root):
                raise ValueError("knowledge stimulus artifact escapes storage root")
            file_path = artifact_root / KNOWLEDGE_STIMULUS_MEMBER
            width, height = self._validate_png(file_path)
            digest = sha256_file(file_path)
            if digest != revision.content_hash:
                raise ValueError("knowledge stimulus artifact hash mismatch")
            return KnowledgeStimulusPointer(
                asset_key=asset_key,
                artifact_id=revision.logical_artifact_id,
                artifact_revision_id=revision.revision_id,
                artifact_member=KNOWLEDGE_STIMULUS_MEMBER,
                sha256=digest,
                media_type="image/png",
                width_px=width,
                height_px=height,
            )

    @staticmethod
    def _validate_png(path: Path) -> tuple[int, int]:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("knowledge stimulus is not a regular file")
        if metadata.st_size < 24 or metadata.st_size > MAX_STIMULUS_BYTES:
            raise ValueError("knowledge stimulus size is invalid")
        data = path.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("knowledge stimulus PNG header is invalid")
        offset = 8
        dimensions: tuple[int, int] | None = None
        saw_image_data = False
        saw_end = False
        while offset < len(data):
            if len(data) - offset < 12:
                raise ValueError("knowledge stimulus PNG structure is invalid")
            length = struct.unpack(">I", data[offset : offset + 4])[0]
            chunk_type = data[offset + 4 : offset + 8]
            chunk_end = offset + 12 + length
            if chunk_end > len(data):
                raise ValueError("knowledge stimulus PNG structure is invalid")
            payload = data[offset + 8 : offset + 8 + length]
            expected_crc = struct.unpack(">I", data[offset + 8 + length : chunk_end])[0]
            if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
                raise ValueError("knowledge stimulus PNG checksum is invalid")
            if chunk_type == b"IHDR":
                if offset != 8 or length != 13 or dimensions is not None:
                    raise ValueError("knowledge stimulus PNG header is invalid")
                dimensions = struct.unpack(">II", payload[:8])
            elif chunk_type == b"IDAT":
                saw_image_data = True
            elif chunk_type == b"IEND":
                if length != 0 or chunk_end != len(data):
                    raise ValueError("knowledge stimulus PNG structure is invalid")
                saw_end = True
            offset = chunk_end
        if dimensions is None or not saw_image_data or not saw_end:
            raise ValueError("knowledge stimulus PNG structure is invalid")
        width, height = dimensions
        if (width, height) != (800, 500):
            raise ValueError("knowledge stimulus dimensions are incompatible")
        return width, height
