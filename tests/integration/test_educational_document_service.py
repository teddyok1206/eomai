from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from eom_catalog_contracts import TextbookAnalysisBundleManifest, validate_contract
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.educational_document_service import (
    EducationalDocumentError,
    EducationalDocumentService,
    prepare_textbook_registration_request,
)
from eom_catalog_service.knowledge_analysis_sources import resolve_educational_document_source
from eom_catalog_service.models import (
    EducationalDocumentRecord,
    EducationalDocumentRegistrationRecord,
    EducationalDocumentRevisionRecord,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import Engine, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nintegration licensed textbook\n")
    source.chmod(0o400)
    bundle = tmp_path / "bundle"
    pages = bundle / "pages"
    pages.mkdir(parents=True)
    index_payload = b"# index\n"
    page_payload = "# page 1\n\n시간과 공간\n".encode()
    (bundle / "index.md").write_bytes(index_payload)
    (pages / "page-000001.md").write_bytes(page_payload)
    (bundle / "index.md").chmod(0o400)
    (pages / "page-000001.md").chmod(0o400)
    text_payload = "시간과 공간\n".encode()
    value: dict[str, object] = {
        "schema_version": "textbook-analysis-bundle-manifest/1.0",
        "bundle_id": "textbookbundle_" + uuid4().hex,
        "bundle_state": "PRE_CANONICAL_REVIEW_ONLY",
        "source": {
            "media_type": "application/pdf",
            "sha256": sha256_bytes(source.read_bytes()),
            "size_bytes": source.stat().st_size,
            "page_count": 1,
        },
        "canonical_source": None,
        "document": {
            "publisher_key": "miraen",
            "publisher_label": "미래엔",
            "title": "통합과학 1",
            "curriculum_volume": "I",
            "language": "ko-KR",
        },
        "scope": {"first_physical_page": 1, "last_physical_page": 1},
        "extractor": {
            "implementation": "integration-fixture",
            "version": "1.0.0",
            "implementation_sha256": "sha256:" + "a" * 64,
            "options_sha256": "sha256:" + "b" * 64,
        },
        "index_member": {
            "member_path": "index.md",
            "media_type": "text/markdown; charset=utf-8",
            "member_sha256": sha256_bytes(index_payload),
        },
        "pages": [
            {
                "physical_page": 1,
                "printed_page": None,
                "anchor_id": "textbookanchor_" + uuid4().hex,
                "member_path": "pages/page-000001.md",
                "media_type": "text/markdown; charset=utf-8",
                "extraction_state": "TEXT",
                "character_count": len(text_payload.decode()),
                "replacement_character_count": 0,
                "text_sha256": sha256_bytes(text_payload),
                "member_sha256": sha256_bytes(page_payload),
            }
        ],
        "curriculum_mappings": [],
        "generated_at": "2026-08-25T00:00:00Z",
        "generated_by": "codex-data-analysis-pilot",
    }
    page = value["pages"][0]  # type: ignore[index]
    assert isinstance(page, dict)
    value["curriculum_mappings"] = [
        {
            "mapping_id": "textbookmapping_" + uuid4().hex,
            "eom_unit_key": "1-(1)",
            "eom_unit_label": "시간과 공간",
            "first_physical_page": 1,
            "last_physical_page": 1,
            "evidence_anchor_ids": [page["anchor_id"]],
            "mapping_kind": "PRIMARY",
            "confidence_milli": 1000,
            "review_state": "PROPOSED",
        }
    ]
    value["manifest_sha256"] = content_sha256(value)
    manifest = TextbookAnalysisBundleManifest.model_validate(value)
    validate_contract("textbook-analysis-bundle-manifest", manifest.model_dump(mode="json"))
    (bundle / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    (bundle / "manifest.json").chmod(0o400)
    pages.chmod(0o500)
    bundle.chmod(0o500)
    return source, bundle


def _settings(tmp_path: Path) -> CatalogSettings:
    staging = tmp_path / "staging"
    nas = tmp_path / "nas"
    intake = tmp_path / "intake"
    staging.mkdir(mode=0o700)
    nas.mkdir(mode=0o700)
    intake.mkdir(mode=0o700)
    return CatalogSettings(
        staging_root=staging,
        nas_artifact_root=nas,
        intake_root=intake,
        placeholder_pack_source=tmp_path / "unused-pack",
        knowledge_stimulus_source=tmp_path / "unused-stimulus.png",
    )


def test_document_registration_is_idempotent_pointer_only_and_immutable(
    integration_engine: Engine,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source, bundle = _fixture(tmp_path)
    settings = _settings(tmp_path)
    unique = uuid4().hex
    request = prepare_textbook_registration_request(
        source_path=source,
        analysis_bundle_root=bundle,
        document_key=f"textbook-miraen-integrated-science-i-{unique}",
        edition_label="purchased-2026",
        registered_by="operator_test",
        registration_key=f"educational-document:integration:{unique}",
        confirmation_reference="operator-confirmation:2026-08-25:purchased-and-negotiated",
        registered_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    service = EducationalDocumentService(integration_engine, settings)
    first = service.register_textbook(request, source_path=source, analysis_bundle_root=bundle)
    second = service.register_textbook(request, source_path=source, analysis_bundle_root=bundle)
    assert first == second == service.inspect(request.identity.document_key)
    assert service.list_current()[-1] == first or first in service.list_current()

    db_session.expire_all()
    document = db_session.get(EducationalDocumentRecord, first.document_id)
    revision = db_session.get(EducationalDocumentRevisionRecord, first.document_revision_id)
    registration = db_session.scalar(
        select(EducationalDocumentRegistrationRecord).where(
            EducationalDocumentRegistrationRecord.registration_request_sha256
            == request.request_sha256
        )
    )
    assert document is not None and document.current_revision_id == first.document_revision_id
    assert revision is not None and revision.revision_state == "APPROVED"
    assert registration is not None and registration.state == "COMMITTED"
    assert revision.source_sha256 == request.expected_source_sha256
    assert revision.rights_attestation_sha256 == first.rights_attestation.sha256
    artifact_revisions = tuple(
        db_session.scalars(
            select(ArtifactRevisionRecord).where(
                ArtifactRevisionRecord.revision_id.in_(
                    (
                        first.source.artifact_revision_id,
                        first.analysis_bundle_manifest.artifact_revision_id,
                        first.rights_attestation.artifact_revision_id,
                        first.revision_manifest.artifact_revision_id,
                    )
                )
            )
        )
    )
    assert len(artifact_revisions) == 4
    artifact_jobs = tuple(
        db_session.scalars(
            select(JobRecord).where(
                JobRecord.job_id.in_(revision.job_id for revision in artifact_revisions)
            )
        )
    )
    assert len(artifact_jobs) == 4
    assert {job.task_type for job in artifact_jobs} == {
        "educational-document-source",
        "educational-document-analysis",
        "educational-document-rights",
        "educational-document-revision-manifest",
    }
    assert all(revision.approved for revision in artifact_revisions)
    assert all(isinstance(revision.result, dict) for revision in artifact_revisions)
    assert all(
        "pdf" not in revision.result and "bytes" not in revision.result
        for revision in artifact_revisions
    )

    resolved = resolve_educational_document_source(
        db_session,
        CatalogArtifactService(integration_engine, settings),
        document_revision_id=first.document_revision_id,
        source_class="TEXTBOOK",
        first_physical_page=1,
        last_physical_page=1,
        curriculum_unit_keys=("1-(1)",),
    )
    assert resolved.document_id == first.document_id
    assert resolved.document_revision_id == first.document_revision_id
    assert resolved.artifact_member.member_path == "source/original.pdf"
    assert tuple(member.member_kind for member in resolved.materialization_members) == (
        "INDEX",
        "PAGE",
    )
    assert resolved.materialization_members[1].materialized_path.endswith("page-000001.md")

    with pytest.raises(DBAPIError, match="immutable"), db_session.begin_nested():
        revision.title = "changed"
        db_session.flush()


def test_registration_key_conflict_fails_before_another_document_revision(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    source, bundle = _fixture(tmp_path)
    settings = _settings(tmp_path)
    unique = uuid4().hex
    first = prepare_textbook_registration_request(
        source_path=source,
        analysis_bundle_root=bundle,
        document_key=f"textbook-miraen-integrated-science-i-conflict-{unique}",
        edition_label="purchased-2026",
        registered_by="operator_test",
        registration_key=f"educational-document:integration:conflict:{unique}",
        confirmation_reference="operator-confirmation:first",
        registered_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    service = EducationalDocumentService(integration_engine, settings)
    service.register_textbook(first, source_path=source, analysis_bundle_root=bundle)
    second = prepare_textbook_registration_request(
        source_path=source,
        analysis_bundle_root=bundle,
        document_key=first.identity.document_key,
        edition_label="purchased-2026-corrected",
        registered_by="operator_test",
        registration_key=first.registration_key,
        confirmation_reference="operator-confirmation:second",
        registered_at=datetime(2026, 8, 25, 0, 0, 1, tzinfo=UTC),
    )
    with pytest.raises(EducationalDocumentError, match="IDEMPOTENCY_CONFLICT"):
        service.register_textbook(second, source_path=source, analysis_bundle_root=bundle)


def test_failed_registration_requires_exact_replay_before_a_new_revision(
    integration_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, bundle = _fixture(tmp_path)
    settings = _settings(tmp_path)
    unique = uuid4().hex
    request = prepare_textbook_registration_request(
        source_path=source,
        analysis_bundle_root=bundle,
        document_key=f"textbook-miraen-integrated-science-i-resume-{unique}",
        edition_label="purchased-2026",
        registered_by="operator_test",
        registration_key=f"educational-document:integration:resume:{unique}",
        confirmation_reference="operator-confirmation:first",
        registered_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    failing_service = EducationalDocumentService(integration_engine, settings)

    def fail_rights(_request: object) -> None:
        raise RuntimeError("synthetic artifact boundary failure")

    monkeypatch.setattr(failing_service, "_publish_rights", fail_rights)
    with pytest.raises(RuntimeError, match="synthetic artifact boundary failure"):
        failing_service.register_textbook(
            request,
            source_path=source,
            analysis_bundle_root=bundle,
        )

    with Session(integration_engine) as session:
        failed = session.scalar(
            select(EducationalDocumentRegistrationRecord).where(
                EducationalDocumentRegistrationRecord.registration_request_sha256
                == request.request_sha256
            )
        )
        assert failed is not None
        assert failed.state == "FAILED"
        assert failed.failure_code == "EDUCATIONAL_DOCUMENT_REGISTRATION_FAILED"

    different = prepare_textbook_registration_request(
        source_path=source,
        analysis_bundle_root=bundle,
        document_key=request.identity.document_key,
        edition_label="purchased-2026-revised",
        registered_by="operator_test",
        registration_key=f"educational-document:integration:blocked:{unique}",
        confirmation_reference="operator-confirmation:second",
        registered_at=datetime(2026, 8, 25, 0, 0, 1, tzinfo=UTC),
    )
    service = EducationalDocumentService(integration_engine, settings)
    with pytest.raises(EducationalDocumentError, match="PREVIOUS_REGISTRATION_INCOMPLETE"):
        service.register_textbook(
            different,
            source_path=source,
            analysis_bundle_root=bundle,
        )

    receipt = service.register_textbook(
        request,
        source_path=source,
        analysis_bundle_root=bundle,
    )
    assert receipt.registration_request_sha256 == request.request_sha256
    with Session(integration_engine) as session:
        resumed = session.scalar(
            select(EducationalDocumentRegistrationRecord).where(
                EducationalDocumentRegistrationRecord.registration_request_sha256
                == request.request_sha256
            )
        )
        assert resumed is not None
        assert resumed.state == "COMMITTED"
        assert resumed.failure_code is None
