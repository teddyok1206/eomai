from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts import (
    ScienceAssessmentWebCorpusManifest,
    ScienceAssessmentWebCorpusPlan,
    validate_contract,
    validate_science_corpus_manifest_against_plan,
)
from eom_identifiers import content_sha256
from pydantic import ValidationError


def _plan() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "science-assessment-web-corpus-plan/1.0",
        "plan_id": "sciencecorpusplan_" + "0" * 32,
        "source_site": "https://legendstudy.com",
        "sitemap_url": "https://legendstudy.com/sitemap.xml",
        "category_urls": [
            "https://legendstudy.com/category/high-1-science",
            "https://legendstudy.com/category/high-3-science",
        ],
        "allowed_download_hosts": ["blog.kakaocdn.net", "t1.daumcdn.net"],
        "scope": "KICE_AND_EDUCATION_AUTHORITY_SCIENCE_ASSESSMENTS",
        "issuer_types": ["EDUCATION_AUTHORITY", "KICE"],
        "subject_families": [
            "CHEMISTRY",
            "EARTH_SCIENCE",
            "GENERAL_SCIENCE",
            "INTEGRATED_SCIENCE",
            "LIFE_SCIENCE",
            "PHYSICS",
        ],
        "document_roles": ["PROBLEM_DOCUMENT"],
        "crawl_delay_ms": 1000,
        "max_post_pages": 5000,
        "max_pdf_bytes": 104857600,
        "created_at": "2026-09-25T15:00:00Z",
        "plan_sha256": "sha256:" + "0" * 64,
    }
    identity = content_sha256(
        {
            key: item
            for key, item in value.items()
            if key not in {"plan_id", "created_at", "plan_sha256"}
        }
    )
    value["plan_id"] = "sciencecorpusplan_" + identity.removeprefix("sha256:")[:32]
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    return value


def _document(
    character: str,
    *,
    disposition: str,
    batch_character: str,
) -> dict[str, object]:
    digest = "sha256:" + character * 64
    return {
        "document_id": "sciencedoc_" + character * 32,
        "sha256": digest,
        "bytes": 4096,
        "page_count": 4,
        "original_filename": f"physics-{character}.pdf",
        "media_type": "application/pdf",
        "document_role": "PROBLEM_DOCUMENT",
        "subject_family": "PHYSICS",
        "subject_label": "물리학1",
        "issuer_type": "KICE",
        "administration_year": 2025,
        "grade": 3,
        "session_label": "6월 모의평가",
        "publication_disposition": disposition,
        "origins": [
            {
                "post_url": "https://legendstudy.com/1665",
                "download_url": f"https://blog.kakaocdn.net/file/{character}",
                "resolved_url": f"https://blog.kakaocdn.net/file/{character}",
                "link_text": f"2026학년도 6월 모의평가 물리학1 문제 {character}",
            }
        ],
        "source": {
            "intake_batch_id": "intake_" + batch_character * 32,
            "source_file_id": "source_" + character * 32,
            "artifact_id": "artifact_" + batch_character * 32,
            "artifact_revision_id": "rev_" + batch_character * 32,
            "member_path": f"source/{character * 64}.pdf",
            "sha256": digest,
        },
    }


def _manifest(plan: dict[str, object]) -> dict[str, object]:
    documents = [
        _document("1", disposition="NEW_INTAKE", batch_character="a"),
        _document("2", disposition="REUSED_EXISTING", batch_character="b"),
    ]
    identity = content_sha256(
        {
            "schema_version": "science-assessment-web-corpus-manifest/1.0",
            "plan_id": plan["plan_id"],
            "plan_sha256": plan["plan_sha256"],
            "document_sha256s": [document["sha256"] for document in documents],
        }
    )
    value: dict[str, object] = {
        "schema_version": "science-assessment-web-corpus-manifest/1.0",
        "corpus_id": "sciencecorpus_" + identity.removeprefix("sha256:")[:32],
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "observed_at": "2026-09-25T15:30:00Z",
        "pdf_validator": {
            "qpdf_path": "/usr/bin/qpdf",
            "qpdf_sha256": "sha256:" + "c" * 64,
            "pdfinfo_path": "/usr/bin/pdfinfo",
            "pdfinfo_sha256": "sha256:" + "d" * 64,
        },
        "documents": documents,
        "intake_shards": [
            {
                "ordinal": 1,
                "intake_batch_id": "intake_" + "a" * 32,
                "artifact_id": "artifact_" + "a" * 32,
                "artifact_revision_id": "rev_" + "a" * 32,
                "source_fingerprint": "sha256:" + "e" * 64,
                "document_count": 1,
            }
        ],
        "summary": {
            "unique_document_count": 2,
            "duplicate_observation_count": 0,
            "reused_existing_count": 1,
            "new_intake_count": 1,
            "total_bytes": 8192,
        },
        "manifest_sha256": "sha256:" + "0" * 64,
    }
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    return value


def test_science_corpus_contracts_match_json_schema_and_models() -> None:
    plan_value = _plan()
    manifest_value = _manifest(plan_value)

    validate_contract("science-assessment-web-corpus-plan", plan_value)
    validate_contract("science-assessment-web-corpus-manifest", manifest_value)
    plan = ScienceAssessmentWebCorpusPlan.model_validate(plan_value)
    manifest = ScienceAssessmentWebCorpusManifest.model_validate(manifest_value)
    validate_science_corpus_manifest_against_plan(manifest, plan)


def test_science_corpus_rejects_hash_drift_and_unlisted_host() -> None:
    plan = ScienceAssessmentWebCorpusPlan.model_validate(_plan())
    manifest_value = _manifest(plan.model_dump(mode="json"))
    manifest_value["manifest_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError, match="manifest hash"):
        ScienceAssessmentWebCorpusManifest.model_validate(manifest_value)

    manifest_value = _manifest(plan.model_dump(mode="json"))
    documents = deepcopy(manifest_value["documents"])
    assert isinstance(documents, list)
    assert isinstance(documents[0], dict)
    origins = documents[0]["origins"]
    assert isinstance(origins, list)
    assert isinstance(origins[0], dict)
    origins[0]["resolved_url"] = "https://unlisted.example/file.pdf"
    manifest_value["documents"] = documents
    manifest_value["manifest_sha256"] = content_sha256(
        {key: item for key, item in manifest_value.items() if key != "manifest_sha256"}
    )
    manifest = ScienceAssessmentWebCorpusManifest.model_validate(manifest_value)
    with pytest.raises(ValueError, match="allowlist"):
        validate_science_corpus_manifest_against_plan(manifest, plan)
