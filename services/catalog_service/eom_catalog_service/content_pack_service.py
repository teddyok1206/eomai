"""Content Pack import, immutable release, activation, and profile resolution use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eom_content_pack import (
    ContentPackError,
    ContentPackErrorCode,
    ContentPackState,
    new_activation_id,
    new_content_pack_file_id,
    new_content_pack_id,
    new_content_pack_profile_id,
    new_content_pack_release_id,
)
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRevisionRecord
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.content_pack_files import (
    BuiltPack,
    build_pack,
    compile_pack,
    materialize_pack_source,
)
from eom_catalog_service.content_pack_repository import append_pack_event, transition_pack
from eom_catalog_service.models import (
    ContentIntakeAnalysisRecord,
    ContentIntakeBatchRecord,
    ContentPackActivationRecord,
    ContentPackFileRecord,
    ContentPackProfileRecord,
    ContentPackRecord,
    ContentPackReleaseRecord,
)
from eom_catalog_service.settings import CatalogSettings


class ContentPackService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)

    def generate_source(
        self,
        batch_id: str,
        *,
        pack_key: str,
        version: str,
        output: Path,
    ) -> dict[str, Any]:
        with self.sessions() as session:
            batch = session.get(ContentIntakeBatchRecord, batch_id)
            analysis = session.scalar(
                select(ContentIntakeAnalysisRecord).where(
                    ContentIntakeAnalysisRecord.intake_batch_id == batch_id
                )
            )
            if batch is None or batch.state != "ACCEPTED" or analysis is None:
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_INVALID,
                    "pack source requires accepted immutable intake evidence",
                )
            proposal_key = analysis.proposal_key
        compiled = materialize_pack_source(
            self.settings.placeholder_pack_source,
            output,
            batch_id=batch_id,
            proposal_key=proposal_key,
            pack_key=pack_key,
            version=version,
        )
        return {
            "pack_key": compiled.manifest.pack.key,
            "version": compiled.manifest.pack.version,
            "source_tree_sha256": compiled.source_tree_sha256,
            "output": str(output),
        }

    def import_source(self, source_root: Path) -> ContentPackReleaseRecord:
        compiled = compile_pack(source_root)
        identity = compiled.manifest.pack
        self._validate_intake_provenance(
            compiled.manifest.provenance.intake_batch_ids,
            compiled.manifest.provenance.mapping_proposal_ids,
        )
        with self.sessions() as session:
            pack = session.scalar(
                select(ContentPackRecord).where(ContentPackRecord.pack_key == identity.key)
            )
            if pack is not None:
                existing = session.scalar(
                    select(ContentPackReleaseRecord).where(
                        ContentPackReleaseRecord.content_pack_id == pack.content_pack_id,
                        ContentPackReleaseRecord.version == identity.version,
                    )
                )
                if existing is not None:
                    if existing.source_tree_sha256 != compiled.source_tree_sha256:
                        raise ContentPackError(
                            ContentPackErrorCode.CONTENT_PACK_HASH_CONFLICT,
                            "pack key and version already exist with different content",
                        )
                    session.expunge(existing)
                    return existing

        output = self.settings.staging_root / "content-packs" / compiled.source_tree_sha256[7:]
        built = build_pack(source_root, output)
        artifact = self.artifacts.commit_file_set(
            files={
                built.bundle_path.name: built.bundle_path,
                "content-pack-manifest.json": built.manifest_path,
            },
            primary_file=built.bundle_path.name,
            artifact_type="content-pack-bundle",
            idempotency_key=f"content-pack:{identity.key}:{identity.version}:{built.bundle_sha256}",
            request={
                "pack_key": identity.key,
                "version": identity.version,
                "source_tree_sha256": built.compiled.source_tree_sha256,
            },
            result={"pack_key": identity.key, "version": identity.version},
        )
        with transaction(self.sessions) as session:
            pack = session.scalar(
                select(ContentPackRecord).where(ContentPackRecord.pack_key == identity.key)
            )
            if pack is None:
                pack = ContentPackRecord(
                    content_pack_id=new_content_pack_id(),
                    pack_key=identity.key,
                    display_name=identity.name,
                    description=identity.description,
                    locale=identity.locale,
                    domain_key=identity.domain_key,
                )
                session.add(pack)
                session.flush()
            release = ContentPackReleaseRecord(
                content_pack_release_id=new_content_pack_release_id(),
                content_pack_id=pack.content_pack_id,
                version=identity.version,
                schema_version=built.compiled.manifest.schema_version,
                state=ContentPackState.DRAFT.value,
                source_tree_sha256=built.compiled.source_tree_sha256,
                bundle_sha256=built.bundle_sha256,
                manifest_sha256=built.manifest_sha256,
                bundle_artifact_id=artifact.artifact_id,
                bundle_artifact_revision_id=artifact.revision_id,
                canonical_manifest_json=built.compiled.canonical_manifest,
                compatibility_json=built.compiled.manifest.compatibility.model_dump(mode="json"),
                lock_version=1,
            )
            session.add(release)
            session.flush()
            append_pack_event(
                session,
                release,
                event_type="CONTENT_PACK_DRAFT_CREATED",
                prior_state=None,
                new_state=ContentPackState.DRAFT.value,
                actor_id="catalog_service",
            )
            self._add_files_and_profiles(session, release, built)
            transition_pack(
                session,
                release,
                ContentPackState.VALIDATED,
                event_type="CONTENT_PACK_VALIDATED",
                actor_id="catalog_service",
            )
            session.flush()
            session.expunge(release)
            return release

    def release(self, release_id: str, *, actor_id: str) -> ContentPackReleaseRecord:
        with transaction(self.sessions) as session:
            release = session.execute(
                select(ContentPackReleaseRecord)
                .where(ContentPackReleaseRecord.content_pack_release_id == release_id)
                .with_for_update()
            ).scalar_one_or_none()
            if release is None:
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_INVALID, "content pack release not found"
                )
            if release.state == ContentPackState.RELEASED.value:
                session.expunge(release)
                return release
            self._verify_bundle_pointer(session, release)
            transition_pack(
                session,
                release,
                ContentPackState.RELEASED,
                event_type="CONTENT_PACK_RELEASED",
                actor_id=actor_id,
            )
            session.flush()
            session.expunge(release)
            return release

    def activate(
        self, release_id: str, *, environment: str, actor_id: str
    ) -> ContentPackActivationRecord:
        if environment not in {"development", "test"}:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_ACTIVATION_CONFLICT,
                "unsupported activation environment",
            )
        with transaction(self.sessions) as session:
            release = session.execute(
                select(ContentPackReleaseRecord)
                .where(ContentPackReleaseRecord.content_pack_release_id == release_id)
                .with_for_update()
            ).scalar_one_or_none()
            if release is None or release.state != ContentPackState.RELEASED.value:
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_NOT_RELEASED,
                    "only a released content pack can be activated",
                )
            pack = session.get(ContentPackRecord, release.content_pack_id)
            assert pack is not None
            current = session.scalar(
                select(ContentPackActivationRecord)
                .where(
                    ContentPackActivationRecord.environment == environment,
                    ContentPackActivationRecord.pack_key == pack.pack_key,
                    ContentPackActivationRecord.active.is_(True),
                )
                .with_for_update()
            )
            if current is not None and current.content_pack_release_id == release_id:
                session.expunge(current)
                return current
            if current is not None:
                current.active = False
                current.deactivated_at = datetime.now(UTC)
                current.lock_version += 1
            activation = ContentPackActivationRecord(
                activation_id=new_activation_id(),
                environment=environment,
                pack_key=pack.pack_key,
                content_pack_release_id=release_id,
                active=True,
                activated_by=actor_id,
                lock_version=1,
            )
            session.add(activation)
            append_pack_event(
                session,
                release,
                event_type="CONTENT_PACK_ACTIVATED",
                prior_state=release.state,
                new_state=release.state,
                actor_id=actor_id,
                payload={"environment": environment},
            )
            session.flush()
            session.expunge(activation)
            return activation

    def resolve(self, *, pack_key: str, environment: str) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.execute(
                select(ContentPackActivationRecord, ContentPackReleaseRecord)
                .join(
                    ContentPackReleaseRecord,
                    ContentPackReleaseRecord.content_pack_release_id
                    == ContentPackActivationRecord.content_pack_release_id,
                )
                .where(
                    ContentPackActivationRecord.pack_key == pack_key,
                    ContentPackActivationRecord.environment == environment,
                    ContentPackActivationRecord.active.is_(True),
                )
            ).one_or_none()
            if row is None or row.ContentPackReleaseRecord.state != ContentPackState.RELEASED.value:
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_NOT_RELEASED,
                    "active released content pack not found",
                )
            return self.release_dict(row.ContentPackReleaseRecord) | {
                "environment": environment,
                "activation_id": row.ContentPackActivationRecord.activation_id,
            }

    def list_releases(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.execute(
                select(ContentPackReleaseRecord, ContentPackRecord)
                .join(ContentPackRecord)
                .order_by(ContentPackRecord.pack_key, ContentPackReleaseRecord.version)
            ).all()
            return [
                self.release_dict(release) | {"pack_key": pack.pack_key} for release, pack in rows
            ]

    def inspect(self, release_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            release = session.get(ContentPackReleaseRecord, release_id)
            if release is None:
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_INVALID, "content pack release not found"
                )
            pack = session.get(ContentPackRecord, release.content_pack_id)
            files = list(
                session.scalars(
                    select(ContentPackFileRecord)
                    .where(ContentPackFileRecord.content_pack_release_id == release_id)
                    .order_by(ContentPackFileRecord.relative_path)
                )
            )
            profiles = list(
                session.scalars(
                    select(ContentPackProfileRecord)
                    .where(ContentPackProfileRecord.content_pack_release_id == release_id)
                    .order_by(
                        ContentPackProfileRecord.profile_type,
                        ContentPackProfileRecord.profile_key,
                    )
                )
            )
            return self.release_dict(release) | {
                "pack_key": pack.pack_key if pack else None,
                "files": [
                    {
                        "relative_path": item.relative_path,
                        "sha256": item.sha256,
                        "logical_role": item.logical_role,
                    }
                    for item in files
                ],
                "profiles": [
                    {
                        "profile_type": item.profile_type,
                        "profile_key": item.profile_key,
                        "profile_version": item.profile_version,
                        "profile_sha256": item.profile_sha256,
                    }
                    for item in profiles
                ],
            }

    def _validate_intake_provenance(
        self, batch_ids: tuple[str, ...], proposal_keys: tuple[str, ...]
    ) -> None:
        with self.sessions() as session:
            batches = list(
                session.scalars(
                    select(ContentIntakeBatchRecord).where(
                        ContentIntakeBatchRecord.intake_batch_id.in_(batch_ids)
                    )
                )
            )
            if len(batches) != len(set(batch_ids)) or any(
                batch.state not in {"ACCEPTED", "IMPORTED"} for batch in batches
            ):
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_INVALID,
                    "content pack provenance requires accepted intake batches",
                )
            keys = set(
                session.scalars(
                    select(ContentIntakeAnalysisRecord.proposal_key).where(
                        ContentIntakeAnalysisRecord.intake_batch_id.in_(batch_ids)
                    )
                )
            )
            if not set(proposal_keys).issubset(keys):
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_INVALID,
                    "content pack proposal provenance does not resolve",
                )

    @staticmethod
    def _verify_bundle_pointer(
        session: Session, release: ContentPackReleaseRecord
    ) -> ArtifactRevisionRecord:
        revision = session.get(ArtifactRevisionRecord, release.bundle_artifact_revision_id)
        if (
            revision is None
            or revision.logical_artifact_id != release.bundle_artifact_id
            or revision.content_hash != release.bundle_sha256
            or not revision.approved
            or revision.manifest.get("artifact_type") != "content-pack-bundle"
            or revision.manifest.get("manifest_version") != "catalog-file-set/1.0"
        ):
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_INVALID,
                "content pack bundle pointer does not resolve",
            )
        return revision

    @staticmethod
    def _add_files_and_profiles(
        session: Session, release: ContentPackReleaseRecord, built: BuiltPack
    ) -> None:
        by_path = {item.relative_path: item for item in built.compiled.files}
        for item in built.compiled.files:
            session.add(
                ContentPackFileRecord(
                    content_pack_file_id=new_content_pack_file_id(),
                    content_pack_release_id=release.content_pack_release_id,
                    relative_path=item.relative_path,
                    media_type=item.media_type,
                    size_bytes=item.size_bytes,
                    sha256=item.sha256,
                    logical_role=item.logical_role,
                    schema_ref=None,
                )
            )
        for profile in built.compiled.profiles:
            source_path = built.compiled.manifest.profiles[profile.profile.type][
                profile.profile.key
            ]
            session.add(
                ContentPackProfileRecord(
                    content_pack_profile_id=new_content_pack_profile_id(),
                    content_pack_release_id=release.content_pack_release_id,
                    profile_type=profile.profile.type,
                    profile_key=profile.profile.key,
                    profile_version=profile.profile.version,
                    profile_sha256=by_path[source_path].sha256,
                    template_relative_path=profile.template,
                    input_schema_ref=profile.input_schema_ref,
                    output_schema_ref=profile.output_schema_ref,
                    compiled_profile_json=profile.model_dump(mode="json"),
                )
            )

    @staticmethod
    def release_dict(release: ContentPackReleaseRecord) -> dict[str, Any]:
        return {
            "content_pack_release_id": release.content_pack_release_id,
            "content_pack_id": release.content_pack_id,
            "version": release.version,
            "state": release.state,
            "source_tree_sha256": release.source_tree_sha256,
            "bundle_sha256": release.bundle_sha256,
            "manifest_sha256": release.manifest_sha256,
            "bundle_artifact_id": release.bundle_artifact_id,
            "bundle_artifact_revision_id": release.bundle_artifact_revision_id,
            "created_at": release.created_at,
            "validated_at": release.validated_at,
            "released_at": release.released_at,
            "released_by": release.released_by,
            "lock_version": release.lock_version,
        }
