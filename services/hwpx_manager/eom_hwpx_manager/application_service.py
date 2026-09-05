"""Item Revision HWPX request queue, manager runner, and secure artifact resolution."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from eom_hwpx_contracts import (
    ContentTeamHandoffSnapshot,
    ContentTeamImageSource,
    ContentTeamItemSource,
    KordocExpectedStructure,
    KordocRenderOptions,
    KordocSourcePointer,
)
from eom_identifiers import content_sha256, new_hwpx_build_id
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from pydantic import ValidationError
from sqlalchemy import Engine, select

from eom_hwpx_manager.application_adapter import FixedKordocBuilderAdapter
from eom_hwpx_manager.application_state import (
    ApplicationBuildState,
    require_application_transition,
)
from eom_hwpx_manager.content_team_service import (
    CONTENT_TEAM_RENDERER,
    CONTENT_TEAM_RENDERER_VERSION,
    ContentTeamBuildReceipt,
    ContentTeamHwpxService,
)
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.kordoc_service import KordocBuildReceipt, KordocHwpxService
from eom_hwpx_manager.markdown_structure import inspect_markdown_structure
from eom_hwpx_manager.models import HwpxApplicationBuildRecord
from eom_hwpx_manager.question_template_service import (
    QUESTION_TEMPLATE_RENDERER,
    QUESTION_TEMPLATE_RENDERER_VERSION,
    ItemContentSourcePointer,
    QuestionTemplateBuildReceipt,
    QuestionTemplateHwpxService,
    QuestionTemplateSnapshot,
)
from eom_hwpx_manager.settings import HwpxSettings

MARKDOWN_MEDIA_TYPES = frozenset({"text/markdown", "text/markdown; charset=utf-8"})
MARKDOWN_SCHEMA_REFS = frozenset({"eom.hwpx.markdown-document", "eom.hwpx.markdown-document/1.0"})
ITEM_CONTENT_MEDIA_TYPE = "application/json"
ITEM_CONTENT_SCHEMA_REFS = frozenset(
    {
        "eom.assessment.item-content/1.0",
        "eom://schemas/item-registry/assessment-item-content-v1",
    }
)
CONTENT_TEAM_ITEM_CONTENT_SCHEMA_REFS = frozenset(
    {
        "eom.assessment.item-content/2.0",
        "eom://schemas/item-registry/assessment-item-content-v2",
    }
)
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
AUTOMATIC_RENDERER = "auto"
AUTOMATIC_DOCUMENT_PROFILE = "item-revision-auto"


class ItemRevisionResolver(Protocol):
    """Read-only application boundary needed to resolve a pinned Item Revision."""

    def inspect_revision(self, item_revision_id: str) -> dict[str, Any]: ...

    def inspect_item(self, item_id: str) -> dict[str, Any]: ...


class HwpxRenderer(Protocol):
    """Closed renderer port implemented by the isolated Kordoc adapter."""

    def build(
        self,
        source_path: Path,
        source: KordocSourcePointer,
        expected_structure: KordocExpectedStructure,
        *,
        idempotency_key: str,
        options: KordocRenderOptions | None = None,
        build_id: str | None = None,
    ) -> KordocBuildReceipt: ...


class QuestionTemplateRenderer(Protocol):
    def snapshot(self) -> QuestionTemplateSnapshot: ...

    def build(
        self,
        source_path: Path,
        source: ItemContentSourcePointer,
        *,
        item_revision_id: str,
        item_number: int,
        idempotency_key: str,
        build_id: str,
        template_snapshot: QuestionTemplateSnapshot,
    ) -> QuestionTemplateBuildReceipt: ...


class ContentTeamRenderer(Protocol):
    def snapshot(self) -> ContentTeamHandoffSnapshot: ...

    def build(
        self,
        source_path: Path,
        source: ContentTeamItemSource,
        *,
        item_revision_id: str,
        image_sources: tuple[ContentTeamImageSource, ...],
        idempotency_key: str,
        build_id: str,
        handoff_snapshot: ContentTeamHandoffSnapshot,
    ) -> ContentTeamBuildReceipt: ...


@dataclass(frozen=True)
class SecureHwpxDownload:
    fd: int
    filename: str
    content_length: int
    sha256: str

    def iter_chunks(self, chunk_size: int = 1024 * 1024) -> Generator[bytes, None, None]:
        try:
            while chunk := os.read(self.fd, chunk_size):
                yield chunk
        finally:
            os.close(self.fd)


class HwpxApplicationService:
    """Application service; only the runner method executes a renderer adapter."""

    def __init__(
        self,
        engine: Engine,
        *,
        registry: ItemRevisionResolver,
        renderer: HwpxRenderer | None = None,
        template_renderer: QuestionTemplateRenderer | None = None,
        content_team_renderer: ContentTeamRenderer | None = None,
    ) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.registry = registry
        self.renderer = renderer or KordocHwpxService(
            engine,
            adapter=FixedKordocBuilderAdapter(HwpxSettings.from_environment()),
        )
        self.template_renderer = template_renderer or QuestionTemplateHwpxService(engine)
        self.content_team_renderer = content_team_renderer or ContentTeamHwpxService(engine)

    def request_build(
        self,
        item_revision_id: str,
        *,
        renderer: str = "kordoc",
        options: dict[str, Any],
        operator_id: str,
        idempotency_key: str,
    ) -> tuple[HwpxApplicationBuildRecord, bool]:
        revision = self._eligible_revision(item_revision_id)
        requested_renderer = renderer
        renderer, component = self._resolve_build_source(revision, renderer)
        if renderer == "kordoc":
            normalized_options = dict(options)
            renderer_version = "4.9.0"
        elif renderer == QUESTION_TEMPLATE_RENDERER:
            template_snapshot = self.template_renderer.snapshot()
            normalized_options = dict(options) | template_snapshot.request_identity()
            renderer_version = QUESTION_TEMPLATE_RENDERER_VERSION
        elif renderer == CONTENT_TEAM_RENDERER:
            metadata = component.get("metadata")
            if not isinstance(metadata, dict):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                    "content-team ITEM_CONTENT metadata is missing",
                )
            markdown_member = metadata.get("editorial_markdown_member")
            markdown_sha256 = metadata.get("editorial_markdown_sha256")
            if markdown_member != "content-team-item.md" or not isinstance(markdown_sha256, str):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                    "content-team Markdown member pointer is incomplete",
                )
            handoff_snapshot = self.content_team_renderer.snapshot()
            normalized_options = dict(options) | {
                "document_profile": "content-team-hwp-question-editor-v2",
                "editorial_markdown_member": markdown_member,
                "editorial_markdown_sha256": markdown_sha256,
                "handoff": handoff_snapshot.model_dump(mode="json"),
                "content_team_images": self._content_team_image_sources(revision),
            }
            renderer_version = CONTENT_TEAM_RENDERER_VERSION
        else:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                "unsupported HWPX renderer profile",
            )
        if requested_renderer == AUTOMATIC_RENDERER:
            normalized_options["delivery_profile_selection"] = AUTOMATIC_DOCUMENT_PROFILE
        request_identity = {
            "item_revision_id": item_revision_id,
            "renderer": renderer,
            "options": normalized_options,
            "source_artifact_id": component["artifact_id"],
            "source_artifact_revision_id": component["artifact_revision_id"],
            "source_sha256": component["sha256"],
        }
        request_sha256 = content_sha256(request_identity)
        with transaction(self.sessions) as session:
            artifact = session.get(ArtifactRecord, component["artifact_id"])
            artifact_revision = session.get(
                ArtifactRevisionRecord, component["artifact_revision_id"]
            )
            if (
                artifact is None
                or artifact_revision is None
                or not artifact.approved
                or not artifact_revision.approved
                or artifact_revision.logical_artifact_id != component["artifact_id"]
                or artifact_revision.content_hash != component["sha256"]
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                    "Item Revision source artifact pointer is stale or invalid",
                )
            existing = session.scalar(
                select(HwpxApplicationBuildRecord).where(
                    HwpxApplicationBuildRecord.created_by_operator_id == operator_id,
                    HwpxApplicationBuildRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_sha256 != request_sha256:
                    raise HwpxManagerError(
                        HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                        "HWPX application build idempotency conflict",
                    )
                session.expunge(existing)
                return existing, False
            record = HwpxApplicationBuildRecord(
                build_id=new_hwpx_build_id(),
                item_id=revision["item_id"],
                item_revision_id=item_revision_id,
                source_artifact_id=component["artifact_id"],
                source_artifact_revision_id=component["artifact_revision_id"],
                source_sha256=component["sha256"],
                source_schema_ref=component["schema_ref"],
                source_media_type=component["media_type"],
                renderer=renderer,
                renderer_version=renderer_version,
                options=normalized_options,
                request_sha256=request_sha256,
                idempotency_key=idempotency_key,
                created_by_operator_id=operator_id,
                state=ApplicationBuildState.REQUESTED.value,
                validation_state="PENDING",
                resource_version=1,
            )
            session.add(record)
            session.flush()
            session.expunge(record)
            return record, True

    def get_build(self, build_id: str) -> HwpxApplicationBuildRecord:
        with self.sessions() as session:
            record = session.get(HwpxApplicationBuildRecord, build_id)
            if record is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_APPLICATION_BUILD_NOT_FOUND,
                    "HWPX application build does not exist",
                )
            session.expunge(record)
            return record

    def process_next(self) -> HwpxApplicationBuildRecord | None:
        """Claim and process one FIFO request; never retries a terminal build."""
        with transaction(self.sessions) as session:
            record = session.scalar(
                select(HwpxApplicationBuildRecord)
                .where(HwpxApplicationBuildRecord.state == ApplicationBuildState.REQUESTED.value)
                .order_by(
                    HwpxApplicationBuildRecord.created_at,
                    HwpxApplicationBuildRecord.build_id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            self._transition(record, ApplicationBuildState.RUNNING)
            record.started_at = datetime.now(UTC)
            record.resource_version += 1
            session.flush()
            session.expunge(record)
        try:
            source_path = self._source_path(record)
            receipt: KordocBuildReceipt | QuestionTemplateBuildReceipt | ContentTeamBuildReceipt
            if record.renderer == "kordoc":
                structure = inspect_markdown_structure(source_path.read_bytes())
                if record.options.get("require_native_equations") and not (
                    structure.native_equation_count > 0
                ):
                    raise HwpxManagerError(
                        HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                        "required native equation is absent from Markdown",
                    )
                if record.options.get("require_native_tables") and not (
                    structure.native_table_count > 0
                ):
                    raise HwpxManagerError(
                        HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                        "required native table is absent from Markdown",
                    )
                receipt = self.renderer.build(
                    source_path,
                    KordocSourcePointer(
                        artifact_id=record.source_artifact_id,
                        artifact_revision_id=record.source_artifact_revision_id,
                        sha256=record.source_sha256,
                    ),
                    KordocExpectedStructure(
                        display_equation_count=structure.native_equation_count,
                        table_count=structure.native_table_count,
                    ),
                    idempotency_key=record.idempotency_key,
                    options=KordocRenderOptions(gongmun_preset="report"),
                    build_id=record.build_id,
                )
            elif record.renderer == QUESTION_TEMPLATE_RENDERER:
                receipt = self.template_renderer.build(
                    source_path,
                    ItemContentSourcePointer(
                        artifact_id=record.source_artifact_id,
                        artifact_revision_id=record.source_artifact_revision_id,
                        sha256=record.source_sha256,
                    ),
                    item_revision_id=record.item_revision_id,
                    item_number=int(record.options["item_number"]),
                    idempotency_key=record.idempotency_key,
                    build_id=record.build_id,
                    template_snapshot=QuestionTemplateSnapshot.from_request_options(record.options),
                )
            elif record.renderer == CONTENT_TEAM_RENDERER:
                handoff_raw = record.options.get("handoff")
                if not isinstance(handoff_raw, dict):
                    raise HwpxManagerError(
                        HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                        "stored content-team handoff snapshot is incomplete",
                    )
                receipt = self.content_team_renderer.build(
                    source_path,
                    ContentTeamItemSource(
                        artifact_id=record.source_artifact_id,
                        artifact_revision_id=record.source_artifact_revision_id,
                        json_sha256=record.source_sha256,
                        markdown_sha256=str(record.options["editorial_markdown_sha256"]),
                    ),
                    item_revision_id=record.item_revision_id,
                    image_sources=tuple(
                        ContentTeamImageSource.model_validate(value)
                        for value in record.options.get("content_team_images", [])
                    ),
                    idempotency_key=record.idempotency_key,
                    build_id=record.build_id,
                    handoff_snapshot=ContentTeamHandoffSnapshot.model_validate(handoff_raw),
                )
            else:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                    "stored HWPX renderer profile is unsupported",
                )
            with transaction(self.sessions) as session:
                current = session.get(HwpxApplicationBuildRecord, record.build_id)
                if current is None:
                    raise RuntimeError("claimed HWPX application build disappeared")
                self._transition(current, ApplicationBuildState.VALIDATING)
                current.platform_job_id = receipt.job_id
                current.native_equation_count = receipt.native_equation_count
                current.native_table_count = receipt.native_table_count
                current.output_artifact_id = receipt.artifact_id
                current.output_artifact_revision_id = receipt.artifact_revision_id
                current.output_sha256 = receipt.output_sha256
                current.output_filename = f"eom-{current.item_id}-{current.item_revision_id}.hwpx"
                current.validation_state = "PASS"
                self._transition(current, ApplicationBuildState.SUCCEEDED)
                current.completed_at = datetime.now(UTC)
                current.resource_version += 1
                session.flush()
                session.expunge(current)
                return current
        except Exception as exc:
            self._fail_build(record.build_id, exc)
            raise

    def secure_download(self, build_id: str) -> SecureHwpxDownload:
        record = self.get_build(build_id)
        if (
            record.state != ApplicationBuildState.SUCCEEDED.value
            or record.validation_state != "PASS"
            or not record.output_artifact_id
            or not record.output_artifact_revision_id
            or not record.output_sha256
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_DOWNLOAD_UNAVAILABLE,
                "validated HWPX output is unavailable",
            )
        with self.sessions() as session:
            revision = session.get(ArtifactRevisionRecord, record.output_artifact_revision_id)
            if (
                revision is None
                or not revision.approved
                or revision.logical_artifact_id != record.output_artifact_id
                or revision.content_hash != record.output_sha256
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_RESULT_INVALID,
                    "HWPX output Artifact Revision pointer is stale",
                )
            path = self._primary_file(revision)
        fd = self._verified_fd(path, record.output_sha256)
        size = os.fstat(fd).st_size
        filename = record.output_filename or f"eom-{record.build_id}.hwpx"
        return SecureHwpxDownload(fd, self._safe_filename(filename), size, record.output_sha256)

    def _eligible_revision(self, revision_id: str) -> dict[str, Any]:
        try:
            revision = self.registry.inspect_revision(revision_id)
            item = self.registry.inspect_item(str(revision["item_id"]))
        except Exception as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_REVISION_INELIGIBLE,
                "Item Revision does not exist",
            ) from exc
        if (
            revision.get("revision_state") != "APPROVED"
            or item.get("current_revision_id") != revision_id
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_REVISION_INELIGIBLE,
                "Item Revision is not the current approved revision",
            )
        return revision

    @staticmethod
    def _markdown_component(revision: dict[str, Any]) -> dict[str, Any]:
        components = revision.get("components", [])
        eligible = [
            component
            for component in components
            if isinstance(component, dict)
            and component.get("media_type") in MARKDOWN_MEDIA_TYPES
            and component.get("schema_ref") in MARKDOWN_SCHEMA_REFS
        ]
        if len(eligible) != 1:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                "Item Revision must have exactly one HWPX Markdown source component",
            )
        return eligible[0]

    @staticmethod
    def _item_content_component(revision: dict[str, Any]) -> dict[str, Any]:
        components = revision.get("components", [])
        eligible = [
            component
            for component in components
            if isinstance(component, dict)
            and component.get("component_type") == "ITEM_CONTENT"
            and component.get("ordinal") == 0
            and component.get("media_type") == ITEM_CONTENT_MEDIA_TYPE
            and component.get("schema_ref") in ITEM_CONTENT_SCHEMA_REFS
        ]
        if len(eligible) != 1:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                "Item Revision must have exactly one canonical ITEM_CONTENT component",
            )
        return eligible[0]

    @staticmethod
    def _content_team_item_component(revision: dict[str, Any]) -> dict[str, Any]:
        components = revision.get("components", [])
        eligible = [
            component
            for component in components
            if isinstance(component, dict)
            and component.get("component_type") == "ITEM_CONTENT"
            and component.get("ordinal") == 0
            and component.get("media_type") == ITEM_CONTENT_MEDIA_TYPE
            and component.get("schema_ref") in CONTENT_TEAM_ITEM_CONTENT_SCHEMA_REFS
        ]
        if len(eligible) != 1:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                "Item Revision must have exactly one V2 content-team ITEM_CONTENT component",
            )
        return eligible[0]

    @staticmethod
    def _content_team_image_sources(revision: dict[str, Any]) -> list[dict[str, Any]]:
        components = revision.get("components", [])
        candidates = tuple(
            component
            for component in components
            if isinstance(component, dict) and component.get("component_type") == "IMAGE"
        )
        if any(
            not isinstance(component.get("ordinal"), int)
            or isinstance(component.get("ordinal"), bool)
            for component in candidates
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                "content-team image component ordinal is invalid",
            )
        images = sorted(candidates, key=lambda component: component["ordinal"])
        ordinals = tuple(component["ordinal"] for component in images)
        if len(images) > 2 or ordinals != tuple(sorted(set(ordinals))):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                "content-team image component ordinals are ambiguous",
            )
        sources: list[dict[str, Any]] = []
        for component in images:
            metadata = component.get("metadata")
            if not isinstance(metadata, dict):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                    "content-team image metadata is missing",
                )
            ordinal = component.get("ordinal")
            try:
                source = ContentTeamImageSource.model_validate(
                    {
                        "visual_ordinal": ordinal,
                        "label": metadata.get("label"),
                        "artifact_id": component.get("artifact_id"),
                        "artifact_revision_id": component.get("artifact_revision_id"),
                        "artifact_member": metadata.get("artifact_member"),
                        "sha256": component.get("sha256"),
                        "schema_ref": component.get("schema_ref"),
                        "media_type": component.get("media_type"),
                        "width_px": metadata.get("width_px"),
                        "height_px": metadata.get("height_px"),
                        "alt_text": metadata.get("alt_text"),
                        "file_name": f"input/visual-{ordinal}.png",
                    }
                )
            except ValidationError as exc:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                    "content-team image component is malformed",
                ) from exc
            sources.append(source.model_dump(mode="json"))
        return sources

    @classmethod
    def _resolve_build_source(
        cls, revision: dict[str, Any], renderer: str
    ) -> tuple[str, dict[str, Any]]:
        """Resolve an explicit or revision-derived renderer to one immutable source pointer."""

        if renderer == "kordoc":
            return renderer, cls._markdown_component(revision)
        if renderer == QUESTION_TEMPLATE_RENDERER:
            return renderer, cls._item_content_component(revision)
        if renderer == CONTENT_TEAM_RENDERER:
            return renderer, cls._content_team_item_component(revision)
        if renderer != AUTOMATIC_RENDERER:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                "unsupported HWPX renderer profile",
            )

        components = revision.get("components", [])
        match: tuple[str, dict[str, Any]] | None = None
        for component in components if isinstance(components, list) else []:
            if (
                not isinstance(component, dict)
                or component.get("component_type") != "ITEM_CONTENT"
                or component.get("ordinal") != 0
                or component.get("media_type") != ITEM_CONTENT_MEDIA_TYPE
            ):
                continue
            schema_ref = component.get("schema_ref")
            if schema_ref in ITEM_CONTENT_SCHEMA_REFS:
                candidate = (QUESTION_TEMPLATE_RENDERER, component)
            elif schema_ref in CONTENT_TEAM_ITEM_CONTENT_SCHEMA_REFS:
                candidate = (CONTENT_TEAM_RENDERER, component)
            else:
                continue
            if match is not None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                    "Item Revision must resolve to exactly one automatic HWPX delivery profile",
                )
            match = candidate
        if match is None:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_SOURCE_AMBIGUOUS,
                "Item Revision must resolve to exactly one automatic HWPX delivery profile",
            )
        return match

    def _source_path(self, record: HwpxApplicationBuildRecord) -> Path:
        with self.sessions() as session:
            revision = session.get(ArtifactRevisionRecord, record.source_artifact_revision_id)
            if (
                revision is None
                or not revision.approved
                or revision.logical_artifact_id != record.source_artifact_id
                or revision.content_hash != record.source_sha256
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                    "pinned Item source Artifact Revision is stale",
                )
            return self._primary_file(revision)

    @staticmethod
    def _primary_file(revision: ArtifactRevisionRecord) -> Path:
        primary = revision.manifest.get("primary_file")
        if not isinstance(primary, str):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "artifact manifest has no primary file",
            )
        relative = Path(primary)
        root = Path(revision.nas_path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in primary:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "artifact primary file is unsafe",
            )
        try:
            root_metadata = root.lstat()
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "artifact materialization is missing",
            ) from exc
        if not stat.S_ISDIR(root_metadata.st_mode) or root.is_symlink():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "artifact root is unsafe",
            )
        candidate = root / relative
        current = root
        for part in relative.parts:
            current = current / part
            try:
                metadata = current.lstat()
            except OSError as exc:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                    "artifact primary file is missing",
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                    "artifact path contains a symbolic link",
                )
        return candidate

    @staticmethod
    def _verified_fd(path: Path, expected_sha256: str) -> int:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_DOWNLOAD_UNAVAILABLE,
                "HWPX output could not be opened safely",
            ) from exc
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_DOWNLOAD_BYTES:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_RESULT_INVALID,
                    "HWPX output type or size is invalid",
                )
            digest = hashlib.sha256()
            while chunk := os.read(fd, 1024 * 1024):
                digest.update(chunk)
            actual = "sha256:" + digest.hexdigest()
            if actual != expected_sha256:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_KORDOC_RESULT_INVALID,
                    "HWPX output hash does not match its Artifact Revision",
                )
            os.lseek(fd, 0, os.SEEK_SET)
            return fd
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _safe_filename(value: str) -> str:
        safe = "".join(
            character
            if character.isascii() and (character.isalnum() or character in "-_.")
            else "-"
            for character in value
        )
        safe = safe.strip(".-")[:150]
        return safe if safe.endswith(".hwpx") and len(safe) > 5 else "eom-item.hwpx"

    @staticmethod
    def _transition(record: HwpxApplicationBuildRecord, target: ApplicationBuildState) -> None:
        require_application_transition(ApplicationBuildState(record.state), target)
        record.state = target.value

    def _fail_build(self, build_id: str, error: Exception) -> None:
        with transaction(self.sessions) as session:
            record = session.get(HwpxApplicationBuildRecord, build_id)
            if record is None or record.state in {"SUCCEEDED", "FAILED"}:
                return
            self._transition(record, ApplicationBuildState.FAILED)
            record.validation_state = "FAIL"
            record.failure_code = (
                error.code.value
                if isinstance(error, HwpxManagerError)
                else HwpxManagerErrorCode.HWPX_BUILDER_FAILED.value
            )
            record.failure_detail_sanitized = "HWPX build failed at a validated manager boundary"
            record.completed_at = datetime.now(UTC)
            record.resource_version += 1
