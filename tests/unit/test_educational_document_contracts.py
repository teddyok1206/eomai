from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    EducationalDocumentRegistrationRequest,
    EducationalDocumentRevisionManifest,
    EducationalDocumentRightsAttestation,
    TextbookAnalysisBundleManifest,
    validate_contract,
)
from eom_catalog_service.educational_document_service import (
    EducationalDocumentError,
    load_educational_document_registration_request,
    prepare_textbook_registration_request,
    write_educational_document_registration_request,
)
from eom_identifiers import (
    canonical_json_bytes,
    content_sha256,
    educational_document_id,
    educational_document_registration_id,
    educational_document_revision_id,
    sha256_bytes,
)
from pydantic import ValidationError


def _write_textbook_fixture(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nlicensed textbook fixture\n")
    source.chmod(0o400)
    index_payload = b"# textbook index\n"
    page_payload = "# page 1\n\n시간과 공간\n".encode()
    bundle_root = tmp_path / "bundle"
    pages_root = bundle_root / "pages"
    pages_root.mkdir(parents=True)
    index_path = bundle_root / "index.md"
    page_path = pages_root / "page-000001.md"
    index_path.write_bytes(index_payload)
    page_path.write_bytes(page_payload)
    index_path.chmod(0o400)
    page_path.chmod(0o400)
    page_text = "시간과 공간\n"
    value: dict[str, object] = {
        "schema_version": "textbook-analysis-bundle-manifest/1.0",
        "bundle_id": "textbookbundle_" + "1" * 32,
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
            "implementation": "fixture",
            "version": "1.0.0",
            "implementation_sha256": "sha256:" + "2" * 64,
            "options_sha256": "sha256:" + "3" * 64,
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
                "anchor_id": "textbookanchor_" + "4" * 32,
                "member_path": "pages/page-000001.md",
                "media_type": "text/markdown; charset=utf-8",
                "extraction_state": "TEXT",
                "character_count": len(page_text),
                "replacement_character_count": 0,
                "text_sha256": sha256_bytes(page_text.encode()),
                "member_sha256": sha256_bytes(page_payload),
            }
        ],
        "curriculum_mappings": [
            {
                "mapping_id": "textbookmapping_" + "5" * 32,
                "eom_unit_key": "1-(1)",
                "eom_unit_label": "시간과 공간",
                "first_physical_page": 1,
                "last_physical_page": 1,
                "evidence_anchor_ids": ["textbookanchor_" + "4" * 32],
                "mapping_kind": "PRIMARY",
                "confidence_milli": 1000,
                "review_state": "PROPOSED",
            }
        ],
        "generated_at": "2026-08-25T00:00:00Z",
        "generated_by": "codex-data-analysis-pilot",
    }
    value["manifest_sha256"] = content_sha256(value)
    manifest = TextbookAnalysisBundleManifest.model_validate(value)
    validate_contract("textbook-analysis-bundle-manifest", manifest.model_dump(mode="json"))
    manifest_path = bundle_root / "manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    manifest_path.chmod(0o400)
    pages_root.chmod(0o500)
    bundle_root.chmod(0o500)
    return source, bundle_root


def _prepare(tmp_path: Path) -> EducationalDocumentRegistrationRequest:
    source, bundle = _write_textbook_fixture(tmp_path)
    return prepare_textbook_registration_request(
        source_path=source,
        analysis_bundle_root=bundle,
        document_key="textbook-miraen-integrated-science-i",
        edition_label="purchased-2026",
        registered_by="operator_test",
        registration_key="educational-document:test:miraen:i:0001",
        confirmation_reference="operator-confirmation:2026-08-25:purchased-and-negotiated",
        registered_at=datetime(2026, 8, 25, tzinfo=UTC),
    )


def test_registration_request_is_schema_and_type_valid_and_source_bound(tmp_path: Path) -> None:
    request = _prepare(tmp_path)
    validate_contract(
        "educational-document-rights-attestation", request.rights.model_dump(mode="json")
    )
    validate_contract("educational-document-registration-request", request.model_dump(mode="json"))
    assert request.rights.rights_state == "CLEARED_LICENSED"
    assert request.rights.source_sha256 == request.expected_source_sha256
    assert request.rights.answer_bearing
    assert request.rights.attribution_required
    assert request.request_sha256 == content_sha256(
        request.model_dump(mode="json", exclude={"request_sha256"})
    )


def test_protected_request_round_trip_never_persists_source_path(tmp_path: Path) -> None:
    request = _prepare(tmp_path)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    output = state / "registration.json"
    write_educational_document_registration_request(output, request)
    loaded = load_educational_document_registration_request(output)
    assert loaded == request
    assert (output.stat().st_mode & 0o7777) == 0o600
    serialized = output.read_text()
    assert str(tmp_path) not in serialized
    with pytest.raises(EducationalDocumentError, match="REQUEST_OUTPUT_INVALID"):
        write_educational_document_registration_request(output, request)


def test_source_and_bundle_symlinks_and_hardlinks_fail_closed(tmp_path: Path) -> None:
    source, bundle = _write_textbook_fixture(tmp_path)
    link = tmp_path / "source-link.pdf"
    link.symlink_to(source)
    with pytest.raises(EducationalDocumentError, match="REQUEST_PREPARATION_FAILED"):
        prepare_textbook_registration_request(
            source_path=link,
            analysis_bundle_root=bundle,
            document_key="textbook-miraen-integrated-science-i",
            edition_label="purchased-2026",
            registered_by="operator_test",
            registration_key="educational-document:test:miraen:i:0002",
            confirmation_reference="operator-confirmation:licensed",
        )
    source.chmod(0o600)
    hardlink = tmp_path / "source-hardlink.pdf"
    os.link(source, hardlink)
    source.chmod(0o400)
    hardlink.chmod(0o400)
    with pytest.raises(EducationalDocumentError, match="REQUEST_PREPARATION_FAILED"):
        prepare_textbook_registration_request(
            source_path=source,
            analysis_bundle_root=bundle,
            document_key="textbook-miraen-integrated-science-i",
            edition_label="purchased-2026",
            registered_by="operator_test",
            registration_key="educational-document:test:miraen:i:0003",
            confirmation_reference="operator-confirmation:licensed",
        )


def test_rights_and_revision_cross_contracts_fail_closed(tmp_path: Path) -> None:
    request = _prepare(tmp_path)
    rights_value = request.rights.model_dump(mode="json")
    rights_value["permitted_uses"] = list(reversed(rights_value["permitted_uses"]))
    rights_value["rights_attestation_sha256"] = content_sha256(
        {key: value for key, value in rights_value.items() if key != "rights_attestation_sha256"}
    )
    with pytest.raises(ValidationError, match="sorted and unique"):
        EducationalDocumentRightsAttestation.model_validate(rights_value)

    pointer = {
        "pointer_type": "ARTIFACT_MEMBER",
        "artifact_id": "artifact_" + "6" * 32,
        "artifact_revision_id": "rev_" + "7" * 32,
        "member_path": "source/original.pdf",
        "schema_ref": "eom://schemas/educational-document/pdf-source/1.0",
        "media_type": "application/pdf",
        "sha256": request.expected_source_sha256,
    }
    revision_value = {
        "schema_version": "educational-document-revision-manifest/1.0",
        "document_id": "edudoc_" + "8" * 32,
        "document_revision_id": "edudocrev_" + "9" * 32,
        "revision_number": 2,
        "previous_revision_id": None,
        "identity": request.identity.model_dump(mode="json"),
        "source": pointer,
        "source_size_bytes": request.expected_source_size_bytes,
        "source_page_count": request.expected_source_page_count,
        "analysis_bundle_manifest": {
            **pointer,
            "member_path": "analysis/manifest.json",
            "schema_ref": "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0",
            "media_type": "application/json",
        },
        "analysis_bundle_root": "analysis",
        "rights_attestation": {
            **pointer,
            "member_path": "rights/attestation.json",
            "schema_ref": "eom://schemas/educational-document/rights-attestation/1.0",
            "media_type": "application/json",
        },
        "registered_at": request.model_dump(mode="json")["registered_at"],
        "registered_by": request.registered_by,
        "registration_request_sha256": request.request_sha256,
    }
    revision_value["document_revision_sha256"] = content_sha256(revision_value)
    with pytest.raises(ValidationError, match="requires a predecessor"):
        EducationalDocumentRevisionManifest.model_validate(revision_value)

    revision_value["revision_number"] = 1
    revision_value["document_revision_sha256"] = content_sha256(
        {key: value for key, value in revision_value.items() if key != "document_revision_sha256"}
    )
    assert EducationalDocumentRevisionManifest.model_validate(revision_value).revision_number == 1


def test_educational_document_ids_are_stable_and_separate() -> None:
    request_sha = "sha256:" + "a" * 64
    assert educational_document_id("textbook-miraen-integrated-science-i") == (
        educational_document_id("textbook-miraen-integrated-science-i")
    )
    revision_id = educational_document_revision_id(request_sha)
    registration_id = educational_document_registration_id(request_sha)
    assert revision_id.startswith("edudocrev_")
    assert registration_id.startswith("edudocreg_")
    assert revision_id.removeprefix("edudocrev_") != registration_id.removeprefix("edudocreg_")
