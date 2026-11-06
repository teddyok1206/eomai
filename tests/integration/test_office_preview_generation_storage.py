"""Real preview Artifact/replay/locks in guarded PostgreSQL; synthetic converter port.

This does not claim native Office rendering or source authorization fidelity. Those are
independently tested through fixed units and the existing source-media owner.
"""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier, Lock
from uuid import uuid4

import fitz
import pytest
from eom_catalog_contracts.document_review import OfficeDocumentReviewConversionIdentity
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from eom_catalog_service.artifacts import CatalogArtifactService, VerifiedArtifactMemberStream
from eom_catalog_service.external_item_document_media import ResolvedExternalItemDocumentMedia
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
    _idempotency_key,
)
from eom_catalog_service.office_conversion_profiles import (
    EQUATION_OFFICE_PROFILE,
    LEGACY_OFFICE_PROFILE,
)
from eom_catalog_service.office_document_converter import create_office_conversion_workspace
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import sha256_bytes, sha256_file
from eom_orchestrator.models import JobRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def preview_case(creative_engine, tmp_path: Path):
    source_bytes = b"synthetic already-authorized source port; no native converter claim"
    query = ExternalItemDocumentMediaQuery(
        source_id="extitem_" + uuid4().hex,
        source_revision_id="extitemrev_" + uuid4().hex,
        edition=3,
    )
    settings = CatalogSettings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "nas",
        intake_root=tmp_path / "intake",
    )
    for path in (settings.staging_root, settings.nas_artifact_root, settings.intake_root):
        path.mkdir(mode=0o700)

    class Source:
        def open(self, _query):
            assert _query == query
            return ResolvedExternalItemDocumentMedia(
                member=VerifiedArtifactMemberStream(
                    stream=BytesIO(source_bytes),
                    content_length=len(source_bytes),
                    sha256=sha256_bytes(source_bytes),
                ),
                media_type="application/vnd.hancom.hwpx",
                filename="synthetic_12345.hwpx",
                source_file_id="sourcefile_" + "a" * 32,
                artifact_id="artifact_" + "b" * 32,
                artifact_revision_id="rev_" + "c" * 32,
                member_path="source/synthetic.hwpx",
            )

    class Converter:
        def __init__(self, profile):
            self.profile = profile
            self.count = 0
            self.lock = Lock()

        def create_workspace(self):
            return create_office_conversion_workspace(settings.staging_root)

        def convert(self, path, *, source_format):
            assert source_format == "HWPX"
            assert (path / "original.hwpx").read_bytes() == source_bytes
            with self.lock:
                self.count += 1
            output = path / "converted"
            output.mkdir()
            pdf_path = output / "original.pdf"
            with fitz.open() as document:
                document.new_page().insert_text((40, 40), "A = 3")
                document.save(pdf_path)
            return OfficeDocumentReviewConversionIdentity(
                conversion_kind="LIBREOFFICE_H2ORESTART_PDF",
                review_pdf_sha256=sha256_file(pdf_path),
                libreoffice_version="synthetic fixture",
                libreoffice_sha256="sha256:" + "d" * 64,
                h2orestart_sha256="sha256:" + self.profile.h2orestart_sha256,
            )

    def owner(profile, converter):
        return ExternalItemPreviewProjectionService(
            creative_engine,
            settings=settings,
            source_media=Source(),
            artifacts=CatalogArtifactService(creative_engine, settings),
            converter=converter,
            profile=profile,
        )

    return query, Converter, owner


def test_concurrent_current_generation_renders_once_and_preserves_legacy(
    creative_engine, preview_case
):
    query, converter_type, owner = preview_case
    old_converter = converter_type(LEGACY_OFFICE_PROFILE)
    legacy = owner(LEGACY_OFFICE_PROFILE, old_converter)
    old = legacy.build(query)
    current_converter = converter_type(EQUATION_OFFICE_PROFILE)
    consumers = (
        owner(EQUATION_OFFICE_PROFILE, current_converter),
        owner(EQUATION_OFFICE_PROFILE, current_converter),
    )
    gate = Barrier(2)

    def prepare(consumer):
        gate.wait(timeout=10)
        return consumer.build(query)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(prepare, consumers))
    assert results[0].artifact_id == results[1].artifact_id
    assert results[0].revision_id == results[1].revision_id
    assert current_converter.count == 1
    assert old_converter.count == 1
    assert results[0].artifact_id != old.artifact_id
    assert consumers[0].build(query).revision_id == results[0].revision_id
    assert current_converter.count == 1
    for consumer, expected in ((legacy, old), (consumers[1], results[0])):
        opened = consumer.open(query)
        assert opened.artifact_revision_id == expected.revision_id
        assert opened.member.stream.read(8).startswith(b"%PDF-")
        opened.member.stream.close()
    with Session(creative_engine) as session:
        for profile in (LEGACY_OFFICE_PROFILE, EQUATION_OFFICE_PROFILE):
            from eom_catalog_service.artifacts import normalize_catalog_idempotency_key

            key = normalize_catalog_idempotency_key(_idempotency_key(query, profile))
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(JobRecord)
                    .where(JobRecord.idempotency_key == key)
                )
                == 1
            )


def test_current_generation_rejects_a_legacy_converter_receipt(creative_engine, preview_case):
    query, converter_type, owner = preview_case
    wrong = converter_type(LEGACY_OFFICE_PROFILE)
    service = owner(EQUATION_OFFICE_PROFILE, wrong)
    with pytest.raises(ValueError, match="selected generation"):
        service.build(query)
    assert wrong.count == 1
    with Session(creative_engine) as session:
        from eom_catalog_service.artifacts import normalize_catalog_idempotency_key

        key = normalize_catalog_idempotency_key(_idempotency_key(query, EQUATION_OFFICE_PROFILE))
        assert (
            session.scalar(
                select(func.count()).select_from(JobRecord).where(JobRecord.idempotency_key == key)
            )
            == 0
        )
