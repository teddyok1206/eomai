"""Publish validated public science-assessment PDFs through Content Intake."""

from __future__ import annotations

import json
import shutil
import stat
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from eom_catalog_contracts import (
    ScienceAssessmentAcquisitionFailureObservation,
    ScienceAssessmentAcquisitionSuccess,
    ScienceAssessmentCorpusAcquisitionFailure,
    ScienceAssessmentCorpusDocument,
    ScienceAssessmentCorpusIntakeShard,
    ScienceAssessmentCorpusOrigin,
    ScienceAssessmentCorpusSourcePointer,
    ScienceAssessmentCorpusSummary,
    ScienceAssessmentWebAcquisition,
    ScienceAssessmentWebCorpusManifest,
    ScienceAssessmentWebCorpusPlan,
    validate_contract,
    validate_science_acquisition_against_plan,
    validate_science_corpus_manifest_against_acquisition,
    validate_science_corpus_manifest_against_plan,
)
from eom_catalog_contracts.science_assessment_corpus import IssuerType, SubjectFamily
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.intake_evidence import IntakeEvidenceResolver
from eom_catalog_service.intake_files import discover_source_files, source_fingerprint
from eom_catalog_service.intake_service import IntakeService, IntakeSourceDeclaration
from eom_catalog_service.knowledge_analysis_sources import CONTENT_INTAKE_ELIGIBLE_STATES
from eom_catalog_service.models import ContentIntakeBatchRecord, ContentIntakeSourceFileRecord
from eom_catalog_service.science_assessment_web_acquisition import (
    AcquiredScienceAssessmentPdf,
    ScienceAssessmentDiscovery,
)
from eom_catalog_service.science_assessment_web_acquisition import (
    ScienceAssessmentAcquisitionFailure as DownloadFailure,
)
from eom_catalog_service.settings import CatalogSettings

MAX_INTAKE_FILES = 499
MAX_INTAKE_BYTES = 2 * 1024 * 1024 * 1024
SOURCE_MEMBER_SCHEMA_REF = "eom://schemas/content-intake/source-file/1.0"
CORPUS_MANIFEST_SCHEMA_REF = (
    "eom://schemas/legacy-assessment/science-assessment-web-corpus-manifest/1.0"
)


class ScienceAssessmentCorpusPublicationError(RuntimeError):
    """Stable, content-free corpus publication error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ScienceAssessmentCorpusPublication:
    manifest: ScienceAssessmentWebCorpusManifest
    artifact_id: str
    artifact_revision_id: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class _AggregatedPdf:
    source: Path
    sha256: str
    bytes: int
    page_count: int
    original_filename: str
    subject_family: SubjectFamily
    subject_label: str
    issuer_type: IssuerType
    administration_year: int
    grade: int
    session_label: str
    origins: tuple[ScienceAssessmentCorpusOrigin, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedSource:
    pointer: ScienceAssessmentCorpusSourcePointer
    disposition: Literal["NEW_INTAKE", "REUSED_EXISTING"]


class ScienceAssessmentWebCorpusService:
    """Own exact deduplication, Content Intake sharding, and corpus publication."""

    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings | None = None,
        *,
        intake: IntakeService | None = None,
        artifacts: CatalogArtifactService | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.intake = intake or IntakeService(engine, self.settings)
        self.artifacts = artifacts or CatalogArtifactService(engine, self.settings)
        self.evidence = IntakeEvidenceResolver()

    def publish(
        self,
        *,
        plan: ScienceAssessmentWebCorpusPlan,
        acquisition: ScienceAssessmentWebAcquisition,
        discovery: ScienceAssessmentDiscovery,
        acquired: tuple[AcquiredScienceAssessmentPdf, ...],
        failures: tuple[DownloadFailure, ...],
        received_by: str,
    ) -> ScienceAssessmentCorpusPublication:
        if not acquired:
            raise ScienceAssessmentCorpusPublicationError("SCIENCE_CORPUS_NO_VALID_PDFS")
        validate_science_acquisition_against_plan(acquisition, plan)
        _require_acquisition_projection(acquisition, discovery, acquired, failures)
        aggregate = _aggregate_acquired(acquired)
        resolved = self._resolve_existing_sources(aggregate)
        new_hashes = tuple(value for value in aggregate if value not in resolved)
        new_shards = self._publish_new_sources(
            plan=plan,
            aggregate=aggregate,
            hashes=new_hashes,
            received_by=received_by,
            resolved=resolved,
        )
        manifest = _build_manifest(
            plan=plan,
            acquisition=acquisition,
            discovery=discovery,
            aggregate=aggregate,
            failures=failures,
            resolved=resolved,
            new_shards=new_shards,
        )
        validate_science_corpus_manifest_against_acquisition(manifest, acquisition)
        return self._commit_manifest(manifest, plan)

    def _resolve_existing_sources(
        self,
        aggregate: dict[str, _AggregatedPdf],
    ) -> dict[str, _ResolvedSource]:
        hashes = tuple(sorted(aggregate))
        with self.sessions() as session:
            rows = tuple(
                session.scalars(
                    select(ContentIntakeSourceFileRecord)
                    .where(ContentIntakeSourceFileRecord.sha256.in_(hashes))
                    .order_by(
                        ContentIntakeSourceFileRecord.sha256,
                        ContentIntakeSourceFileRecord.created_at,
                        ContentIntakeSourceFileRecord.source_file_id,
                    )
                )
            )
            by_hash: dict[str, list[ContentIntakeSourceFileRecord]] = {}
            for row in rows:
                by_hash.setdefault(row.sha256, []).append(row)
            selected: dict[str, ContentIntakeSourceFileRecord] = {}
            for content_hash, candidates in by_hash.items():
                expected = aggregate[content_hash]
                for source in candidates:
                    batch = session.get(ContentIntakeBatchRecord, source.intake_batch_id)
                    if (
                        batch is None
                        or batch.state not in CONTENT_INTAKE_ELIGIBLE_STATES
                        or source.media_type != "application/pdf"
                        or source.size_bytes != expected.bytes
                    ):
                        continue
                    try:
                        self.evidence.verify_source_manifest(session, batch)
                        self.artifacts.verify_member(
                            artifact_id=source.artifact_id,
                            revision_id=source.artifact_revision_id,
                            member_path=source.relative_path,
                            sha256=source.sha256,
                            media_type=source.media_type,
                            schema_ref=SOURCE_MEMBER_SCHEMA_REF,
                            max_bytes=expected.bytes,
                        )
                    except (OSError, ValueError):
                        continue
                    selected[content_hash] = source
                    break
        return {
            content_hash: _ResolvedSource(
                pointer=_source_pointer(source),
                disposition="REUSED_EXISTING",
            )
            for content_hash, source in selected.items()
        }

    def _publish_new_sources(
        self,
        *,
        plan: ScienceAssessmentWebCorpusPlan,
        aggregate: dict[str, _AggregatedPdf],
        hashes: tuple[str, ...],
        received_by: str,
        resolved: dict[str, _ResolvedSource],
    ) -> tuple[ScienceAssessmentCorpusIntakeShard, ...]:
        shards: list[ScienceAssessmentCorpusIntakeShard] = []
        for ordinal, shard_hashes in enumerate(_bounded_shards(hashes, aggregate), start=1):
            directory = _stage_intake_shard(
                staging_root=self.settings.staging_root,
                plan=plan,
                hashes=shard_hashes,
                aggregate=aggregate,
            )
            declarations: list[IntakeSourceDeclaration] = []
            for content_hash in shard_hashes:
                document = aggregate[content_hash]
                filename = content_hash.removeprefix("sha256:") + ".pdf"
                declarations.append(
                    IntakeSourceDeclaration(
                        normalized_relative_path=filename,
                        original_filename=document.original_filename,
                        media_type="application/pdf",
                        declared_role="REFERENCE",
                        declared_description=(
                            "Public science-assessment problem PDF; "
                            f"issuer={document.issuer_type}; year={document.administration_year}; "
                            f"grade={document.grade}; subject={document.subject_family}; "
                            f"session={document.session_label}; discovery=legendstudy.com"
                        ),
                    )
                )
            discovered = discover_source_files(directory)
            fingerprint = source_fingerprint(discovered)
            with self.sessions() as session:
                existed = session.scalar(
                    select(ContentIntakeBatchRecord).where(
                        ContentIntakeBatchRecord.source_fingerprint == fingerprint
                    )
                )
            batch = self.intake.create(
                directory,
                batch_name=f"science-assessment-{plan.plan_id[-12:]}-{ordinal:03d}",
                received_by=received_by,
                purpose=(
                    "Immutable KICE and education-authority science-assessment problem PDF corpus; "
                    f"plan={plan.plan_id}; shard={ordinal}"
                ),
                source_owner_type="other",
                source_owner_reference="public-exam-authorities-via-legendstudy",
                source_declarations=tuple(declarations),
            )
            if batch.state not in CONTENT_INTAKE_ELIGIBLE_STATES:
                raise ScienceAssessmentCorpusPublicationError(
                    "SCIENCE_CORPUS_INTAKE_SOURCE_INELIGIBLE"
                )
            with self.sessions() as session:
                sources = tuple(
                    session.scalars(
                        select(ContentIntakeSourceFileRecord)
                        .where(
                            ContentIntakeSourceFileRecord.intake_batch_id == batch.intake_batch_id
                        )
                        .order_by(ContentIntakeSourceFileRecord.sha256)
                    )
                )
            by_hash = {value.sha256: value for value in sources}
            if set(by_hash) != set(shard_hashes):
                raise ScienceAssessmentCorpusPublicationError(
                    "SCIENCE_CORPUS_INTAKE_SOURCE_MISMATCH"
                )
            disposition: Literal["NEW_INTAKE", "REUSED_EXISTING"] = (
                "REUSED_EXISTING" if existed is not None else "NEW_INTAKE"
            )
            for content_hash in shard_hashes:
                source = by_hash[content_hash]
                self.artifacts.verify_member(
                    artifact_id=source.artifact_id,
                    revision_id=source.artifact_revision_id,
                    member_path=source.relative_path,
                    sha256=source.sha256,
                    media_type=source.media_type,
                    schema_ref=SOURCE_MEMBER_SCHEMA_REF,
                    max_bytes=source.size_bytes,
                )
                resolved[content_hash] = _ResolvedSource(
                    pointer=_source_pointer(source),
                    disposition=disposition,
                )
            if existed is None:
                if (
                    batch.source_manifest_artifact_id is None
                    or batch.source_manifest_artifact_revision_id is None
                ):
                    raise ScienceAssessmentCorpusPublicationError(
                        "SCIENCE_CORPUS_INTAKE_POINTER_INCOMPLETE"
                    )
                shards.append(
                    ScienceAssessmentCorpusIntakeShard(
                        ordinal=len(shards) + 1,
                        intake_batch_id=batch.intake_batch_id,
                        artifact_id=batch.source_manifest_artifact_id,
                        artifact_revision_id=batch.source_manifest_artifact_revision_id,
                        source_fingerprint=batch.source_fingerprint,
                        document_count=len(shard_hashes),
                    )
                )
        return tuple(shards)

    def _commit_manifest(
        self,
        manifest: ScienceAssessmentWebCorpusManifest,
        plan: ScienceAssessmentWebCorpusPlan,
    ) -> ScienceAssessmentCorpusPublication:
        validate_science_corpus_manifest_against_plan(manifest, plan)
        value = manifest.model_dump(mode="json")
        validate_contract("science-assessment-web-corpus-manifest", value)
        control = self.settings.staging_root / "science-assessment-web-corpus" / manifest.corpus_id
        control.mkdir(mode=0o750, parents=True, exist_ok=True)
        path = control / f"{manifest.manifest_sha256.removeprefix('sha256:')}.json"
        if path.exists():
            if path.is_symlink() or sha256_file(path) != manifest.manifest_sha256:
                raise ScienceAssessmentCorpusPublicationError(
                    "SCIENCE_CORPUS_LOCAL_MANIFEST_CONFLICT"
                )
        else:
            temporary = control / ".corpus-manifest.json.tmp"
            temporary.write_bytes(canonical_json_bytes(value))
            temporary.chmod(0o600)
            temporary.replace(path)
        committed = self.artifacts.commit_file_set(
            files={"corpus-manifest.json": path},
            primary_file="corpus-manifest.json",
            artifact_type="science-assessment-web-corpus",
            idempotency_key=f"science-assessment-web-corpus:{manifest.corpus_id}",
            request={
                "corpus_id": manifest.corpus_id,
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
            },
            result={"corpus_id": manifest.corpus_id, "summary": value["summary"]},
            file_metadata={
                "corpus-manifest.json": {
                    "media_type": "application/json",
                    "schema_ref": CORPUS_MANIFEST_SCHEMA_REF,
                }
            },
            expected_file_sha256={"corpus-manifest.json": manifest.manifest_sha256},
        )
        raw = self.artifacts.read_member(
            artifact_id=committed.artifact_id,
            revision_id=committed.revision_id,
            member_path="corpus-manifest.json",
            sha256=committed.content_hash,
            media_type="application/json",
            schema_ref=CORPUS_MANIFEST_SCHEMA_REF,
            max_bytes=32 * 1024 * 1024,
        )
        stored_value: object = json.loads(raw)
        if not isinstance(stored_value, dict):
            raise ScienceAssessmentCorpusPublicationError("SCIENCE_CORPUS_MANIFEST_INVALID")
        validate_contract("science-assessment-web-corpus-manifest", stored_value)
        stored = ScienceAssessmentWebCorpusManifest.model_validate(stored_value)
        validate_science_corpus_manifest_against_plan(stored, plan)
        return ScienceAssessmentCorpusPublication(
            manifest=stored,
            artifact_id=committed.artifact_id,
            artifact_revision_id=committed.revision_id,
            manifest_sha256=stored.manifest_sha256,
        )


def _aggregate_acquired(
    acquired: tuple[AcquiredScienceAssessmentPdf, ...],
) -> dict[str, _AggregatedPdf]:
    grouped: dict[str, list[AcquiredScienceAssessmentPdf]] = {}
    for value in acquired:
        grouped.setdefault(value.sha256, []).append(value)
    result: dict[str, _AggregatedPdf] = {}
    for content_hash, observations in sorted(grouped.items()):
        first = observations[0]
        identities = {
            (
                value.bytes,
                value.page_count,
                value.candidate.subject_family,
                value.candidate.issuer_type,
                value.candidate.administration_year,
                value.candidate.grade,
                value.candidate.session_label,
            )
            for value in observations
        }
        if len(identities) != 1:
            raise ScienceAssessmentCorpusPublicationError("SCIENCE_CORPUS_METADATA_CONFLICT")
        origins = tuple(
            sorted(
                {
                    ScienceAssessmentCorpusOrigin(
                        post_url=value.candidate.post_url,
                        download_url=value.candidate.download_url,
                        resolved_url=value.resolved_url,
                        link_text=value.candidate.link_text,
                    )
                    for value in observations
                },
                key=lambda value: (
                    value.post_url,
                    value.download_url,
                    value.resolved_url,
                    value.link_text,
                ),
            )
        )
        result[content_hash] = _AggregatedPdf(
            source=first.source,
            sha256=content_hash,
            bytes=first.bytes,
            page_count=first.page_count,
            original_filename=min(value.candidate.original_filename for value in observations),
            subject_family=first.candidate.subject_family,
            subject_label=min(value.candidate.subject_label for value in observations),
            issuer_type=first.candidate.issuer_type,
            administration_year=first.candidate.administration_year,
            grade=first.candidate.grade,
            session_label=first.candidate.session_label,
            origins=origins,
        )
    return result


def _bounded_shards(
    hashes: Iterable[str],
    aggregate: dict[str, _AggregatedPdf],
) -> tuple[tuple[str, ...], ...]:
    shards: list[tuple[str, ...]] = []
    current: list[str] = []
    current_bytes = 0
    for content_hash in hashes:
        size = aggregate[content_hash].bytes
        if current and (
            len(current) >= MAX_INTAKE_FILES or current_bytes + size > MAX_INTAKE_BYTES
        ):
            shards.append(tuple(current))
            current = []
            current_bytes = 0
        current.append(content_hash)
        current_bytes += size
    if current:
        shards.append(tuple(current))
    return tuple(shards)


def _build_manifest(
    *,
    plan: ScienceAssessmentWebCorpusPlan,
    acquisition: ScienceAssessmentWebAcquisition,
    discovery: ScienceAssessmentDiscovery,
    aggregate: dict[str, _AggregatedPdf],
    failures: tuple[DownloadFailure, ...],
    resolved: dict[str, _ResolvedSource],
    new_shards: tuple[ScienceAssessmentCorpusIntakeShard, ...],
) -> ScienceAssessmentWebCorpusManifest:
    documents = tuple(
        ScienceAssessmentCorpusDocument(
            document_id="sciencedoc_" + content_hash.removeprefix("sha256:")[:32],
            sha256=content_hash,
            bytes=document.bytes,
            page_count=document.page_count,
            original_filename=document.original_filename,
            media_type="application/pdf",
            document_role="PROBLEM_DOCUMENT",
            subject_family=document.subject_family,
            subject_label=document.subject_label,
            issuer_type=document.issuer_type,
            administration_year=document.administration_year,
            grade=document.grade,
            session_label=document.session_label,
            publication_disposition=resolved[content_hash].disposition,
            origins=document.origins,
            source=resolved[content_hash].pointer,
        )
        for content_hash, document in sorted(aggregate.items())
    )
    failure_models = tuple(
        sorted(
            {
                ScienceAssessmentCorpusAcquisitionFailure(
                    post_url=value.candidate.post_url,
                    download_url=value.candidate.download_url,
                    error_code=value.error_code,
                )
                for value in failures
            },
            key=lambda value: (value.post_url, value.download_url, value.error_code),
        )
    )
    origin_count = sum(len(value.origins) for value in documents)
    reused = sum(value.publication_disposition == "REUSED_EXISTING" for value in documents)
    identity = content_sha256(
        {
            "schema_version": "science-assessment-web-corpus-manifest/1.0",
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "acquisition_sha256": acquisition.acquisition_sha256,
        }
    )
    summary = ScienceAssessmentCorpusSummary(
        unique_document_count=len(documents),
        scanned_post_count=discovery.post_count,
        candidate_count=len(discovery.candidates),
        acquisition_failure_count=len(failure_models),
        duplicate_observation_count=origin_count - len(documents),
        reused_existing_count=reused,
        new_intake_count=len(documents) - reused,
        total_bytes=sum(value.bytes for value in documents),
    )
    value: dict[str, object] = {
        "schema_version": "science-assessment-web-corpus-manifest/1.0",
        "corpus_id": "sciencecorpus_" + identity.removeprefix("sha256:")[:32],
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "acquisition_sha256": acquisition.acquisition_sha256,
        "observed_at": acquisition.observed_at.isoformat().replace("+00:00", "Z"),
        "pdf_validator": acquisition.pdf_validator.model_dump(mode="json"),
        "documents": [item.model_dump(mode="json") for item in documents],
        "failures": [item.model_dump(mode="json") for item in failure_models],
        "intake_shards": [item.model_dump(mode="json") for item in new_shards],
        "summary": summary.model_dump(mode="json"),
        "manifest_sha256": "sha256:" + "0" * 64,
    }
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    return ScienceAssessmentWebCorpusManifest.model_validate(value)


def _require_acquisition_projection(
    acquisition: ScienceAssessmentWebAcquisition,
    discovery: ScienceAssessmentDiscovery,
    acquired: tuple[AcquiredScienceAssessmentPdf, ...],
    failures: tuple[DownloadFailure, ...],
) -> None:
    successful = tuple(
        sorted(
            (
                ScienceAssessmentAcquisitionSuccess(
                    post_url=value.candidate.post_url,
                    download_url=value.candidate.download_url,
                    link_text=value.candidate.link_text,
                    original_filename=value.candidate.original_filename,
                    subject_family=value.candidate.subject_family,
                    subject_label=value.candidate.subject_label,
                    issuer_type=value.candidate.issuer_type,
                    administration_year=value.candidate.administration_year,
                    grade=value.candidate.grade,
                    session_label=value.candidate.session_label,
                    resolved_url=value.resolved_url,
                    member_path=f"documents/{value.sha256.removeprefix('sha256:')}.pdf",
                    sha256=value.sha256,
                    bytes=value.bytes,
                    page_count=value.page_count,
                )
                for value in acquired
            ),
            key=lambda value: (
                value.post_url,
                value.download_url,
                value.link_text,
                value.sha256,
            ),
        )
    )
    failed = tuple(
        sorted(
            (
                ScienceAssessmentAcquisitionFailureObservation(
                    post_url=value.candidate.post_url,
                    download_url=value.candidate.download_url,
                    link_text=value.candidate.link_text,
                    original_filename=value.candidate.original_filename,
                    subject_family=value.candidate.subject_family,
                    subject_label=value.candidate.subject_label,
                    issuer_type=value.candidate.issuer_type,
                    administration_year=value.candidate.administration_year,
                    grade=value.candidate.grade,
                    session_label=value.candidate.session_label,
                    error_code=value.error_code,
                )
                for value in failures
            ),
            key=lambda value: (
                value.post_url,
                value.download_url,
                value.link_text,
                value.error_code,
            ),
        )
    )
    if (
        successful != acquisition.successful_observations
        or failed != acquisition.failed_observations
        or discovery.post_count != acquisition.summary.scanned_post_count
        or discovery.rejected_link_count != acquisition.summary.rejected_link_count
        or len(discovery.candidates) != acquisition.summary.candidate_count
    ):
        raise ScienceAssessmentCorpusPublicationError(
            "SCIENCE_CORPUS_ACQUISITION_PROJECTION_MISMATCH"
        )


def _source_pointer(source: ContentIntakeSourceFileRecord) -> ScienceAssessmentCorpusSourcePointer:
    return ScienceAssessmentCorpusSourcePointer(
        intake_batch_id=source.intake_batch_id,
        source_file_id=source.source_file_id,
        artifact_id=source.artifact_id,
        artifact_revision_id=source.artifact_revision_id,
        member_path=source.relative_path,
        sha256=source.sha256,
    )


def _copy_exact(source: Path, target: Path, expected_hash: str, expected_bytes: int) -> None:
    source_metadata = source.lstat()
    if (
        source.is_symlink()
        or not stat.S_ISREG(source_metadata.st_mode)
        or source_metadata.st_nlink != 1
        or source_metadata.st_size != expected_bytes
        or target.exists()
    ):
        raise ScienceAssessmentCorpusPublicationError("SCIENCE_CORPUS_SOURCE_INVALID")
    shutil.copyfile(source, target)
    target.chmod(0o600)
    target_metadata = target.lstat()
    if (
        target.is_symlink()
        or not stat.S_ISREG(target_metadata.st_mode)
        or target_metadata.st_nlink != 1
        or target_metadata.st_size != expected_bytes
        or sha256_file(target) != expected_hash
    ):
        raise ScienceAssessmentCorpusPublicationError("SCIENCE_CORPUS_SOURCE_COPY_INVALID")


def _stage_intake_shard(
    *,
    staging_root: Path,
    plan: ScienceAssessmentWebCorpusPlan,
    hashes: tuple[str, ...],
    aggregate: dict[str, _AggregatedPdf],
) -> Path:
    identity = content_sha256(
        {
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "source_sha256s": list(hashes),
        }
    ).removeprefix("sha256:")
    parent = staging_root / "science-assessment-web-corpus" / "intake-shards"
    parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    directory = parent / identity
    if directory.exists():
        _require_exact_staged_shard(directory, hashes, aggregate)
        return directory

    temporary = Path(tempfile.mkdtemp(prefix=f".{identity}.", dir=parent))
    temporary.chmod(0o700)
    try:
        for content_hash in hashes:
            document = aggregate[content_hash]
            target = temporary / f"{content_hash.removeprefix('sha256:')}.pdf"
            _copy_exact(document.source, target, content_hash, document.bytes)
        _require_exact_staged_shard(temporary, hashes, aggregate)
        try:
            temporary.rename(directory)
        except FileExistsError:
            _require_exact_staged_shard(directory, hashes, aggregate)
        else:
            temporary = directory
        return directory
    finally:
        if temporary != directory and temporary.exists():
            shutil.rmtree(temporary)


def _require_exact_staged_shard(
    directory: Path,
    hashes: tuple[str, ...],
    aggregate: dict[str, _AggregatedPdf],
) -> None:
    metadata = directory.lstat()
    if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise ScienceAssessmentCorpusPublicationError("SCIENCE_CORPUS_STAGING_INVALID")
    expected_names = {f"{value.removeprefix('sha256:')}.pdf" for value in hashes}
    if {value.name for value in directory.iterdir()} != expected_names:
        raise ScienceAssessmentCorpusPublicationError("SCIENCE_CORPUS_STAGING_INVALID")
    for content_hash in hashes:
        source = directory / f"{content_hash.removeprefix('sha256:')}.pdf"
        source_metadata = source.lstat()
        expected = aggregate[content_hash]
        if (
            source.is_symlink()
            or not stat.S_ISREG(source_metadata.st_mode)
            or source_metadata.st_nlink != 1
            or source_metadata.st_size != expected.bytes
            or sha256_file(source) != content_hash
        ):
            raise ScienceAssessmentCorpusPublicationError("SCIENCE_CORPUS_STAGING_INVALID")
