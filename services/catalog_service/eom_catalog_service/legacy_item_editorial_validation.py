"""Server-owned deterministic validation for content-team editorial compatibility."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from eom_catalog_contracts import (
    AssessmentItemContent,
    AssessmentItemContentV2,
    EditorialDeterministicCheck,
    HwpQuestionEditorProfilePointer,
    LegacyItemEditorialCompatibilityRequest,
    validate_contract,
)
from eom_hwpx_contracts import (
    ContentTeamEditorialDraft,
    parse_content_team_markdown,
    serialize_content_team_markdown,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRevisionRecord
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.settings import CatalogSettings

V1_SCHEMA_REFS = frozenset(
    {
        "eom.assessment.item-content/1.0",
        "eom://schemas/item-registry/assessment-item-content-v1",
    }
)
V2_SCHEMA_REFS = frozenset(
    {
        "eom.assessment.item-content/2.0",
        "eom://schemas/item-registry/assessment-item-content-v2",
    }
)
MARKDOWN_MEMBER = "content-team-item.md"
MARKDOWN_MEDIA_TYPE = "text/markdown"
MARKDOWN_SCHEMA_REF = "eom://schemas/hwpx/content-team-editorial-markdown/1.0"
MAX_ITEM_BYTES = 16 * 1024 * 1024
MAX_MARKDOWN_BYTES = 1024 * 1024


@dataclass(frozen=True)
class LegacyItemEditorialDeterministicAssessment:
    checks: tuple[EditorialDeterministicCheck, ...]
    lossless_projection: bool


class ContentTeamRenderEvidenceResolver(Protocol):
    """Resolve a completed build for the exact Item and executable handoff revision."""

    def resolve(
        self,
        *,
        item_revision_id: str,
        item_content_sha256: str,
        renderer_profile: HwpQuestionEditorProfilePointer,
    ) -> str | None: ...


class LegacyItemEditorialDeterministicEvaluator:
    """Validate only schema, lossless Markdown, and actual renderer evidence."""

    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings | None = None,
        *,
        artifacts: CatalogArtifactService | None = None,
        render_evidence: ContentTeamRenderEvidenceResolver | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.artifacts = artifacts or CatalogArtifactService(engine, settings)
        self.render_evidence = render_evidence

    def evaluate(
        self,
        request: LegacyItemEditorialCompatibilityRequest,
    ) -> LegacyItemEditorialDeterministicAssessment:
        pointer = request.source.item_content
        item_bytes = self.artifacts.read_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            media_type=pointer.media_type,
            schema_ref=pointer.schema_ref,
            max_bytes=MAX_ITEM_BYTES,
        )
        try:
            value = json.loads(item_bytes)
            if not isinstance(value, dict):
                raise ValueError("item content is not an object")
            if pointer.schema_ref in V1_SCHEMA_REFS:
                validate_contract("assessment-item-content", value)
                AssessmentItemContent.model_validate(value)
                return self._v1_assessment(request, item_bytes)
            if pointer.schema_ref not in V2_SCHEMA_REFS:
                raise ValueError("item content schema is unsupported")
            validate_contract("assessment-item-content-v2", value)
            content = AssessmentItemContentV2.model_validate(value)
        except (UnicodeError, json.JSONDecodeError, PydanticValidationError, ValueError) as exc:
            raise ValueError("legacy editorial Item content is invalid") from exc
        return self._v2_assessment(request, content, item_bytes)

    def _v1_assessment(
        self,
        request: LegacyItemEditorialCompatibilityRequest,
        item_bytes: bytes,
    ) -> LegacyItemEditorialDeterministicAssessment:
        contract_evidence = content_sha256(
            {
                "validator": "catalog.assessment-item-content-v1",
                "item_revision_id": request.source.item_revision_id,
                "item_sha256": sha256_bytes(item_bytes),
                "outcome": "PASS",
            }
        )
        projection_evidence = content_sha256(
            {
                "validator": "content-team.markdown-round-trip",
                "source_schema_ref": request.source.item_content.schema_ref,
                "target_schema_ref": "eom.assessment.item-content/2.0",
                "outcome": "FAIL",
            }
        )
        render_evidence = content_sha256(
            {
                "validator": "content-team.hwp-question-editor-build",
                "renderer_profile": request.renderer_profile.model_dump(mode="json"),
                "outcome": "NOT_APPLICABLE",
                "reason": "LOSSLESS_V2_PROJECTION_ABSENT",
            }
        )
        lossless_evidence = content_sha256(
            {
                "validator": "content-team.lossless-item-projection",
                "source_schema_ref": request.source.item_content.schema_ref,
                "target_schema_ref": "eom.assessment.item-content/2.0",
                "outcome": "FAIL",
            }
        )
        return LegacyItemEditorialDeterministicAssessment(
            checks=(
                self._check("CONTENT_CONTRACT", "PASS", contract_evidence),
                self._check("MARKDOWN_PROJECTION", "FAIL", projection_evidence),
                self._check("HWPX_RENDERABILITY", "NOT_APPLICABLE", render_evidence),
                self._check("LOSSLESSNESS", "FAIL", lossless_evidence),
            ),
            lossless_projection=False,
        )

    def _v2_assessment(
        self,
        request: LegacyItemEditorialCompatibilityRequest,
        content: AssessmentItemContentV2,
        item_bytes: bytes,
    ) -> LegacyItemEditorialDeterministicAssessment:
        draft = ContentTeamEditorialDraft.model_validate(
            content.model_dump(mode="json", exclude={"schema_version"})
        )
        markdown = serialize_content_team_markdown(draft)
        reparsed = parse_content_team_markdown(markdown)
        expected = draft.model_dump(mode="json")
        actual = reparsed.model_dump(mode="json", exclude={"schema_version", "source_sha256"})
        if actual != expected:
            raise ValueError("content-team Markdown round trip is lossy")
        markdown_sha256 = sha256_bytes(markdown)
        stored_markdown_sha256 = self._markdown_member_sha256(
            request.source.item_content.artifact_revision_id
        )
        stored_markdown = self.artifacts.read_member(
            artifact_id=request.source.item_content.artifact_id,
            revision_id=request.source.item_content.artifact_revision_id,
            member_path=MARKDOWN_MEMBER,
            sha256=stored_markdown_sha256,
            media_type=MARKDOWN_MEDIA_TYPE,
            schema_ref=MARKDOWN_SCHEMA_REF,
            max_bytes=MAX_MARKDOWN_BYTES,
        )
        if stored_markdown != markdown or stored_markdown_sha256 != markdown_sha256:
            raise ValueError("stored content-team Markdown is not the canonical projection")
        renderer_evidence = (
            self.render_evidence.resolve(
                item_revision_id=request.source.item_revision_id,
                item_content_sha256=request.source.item_content.sha256,
                renderer_profile=request.renderer_profile,
            )
            if self.render_evidence is not None
            else None
        )
        renderer_outcome = "PASS" if renderer_evidence is not None else "FAIL"
        renderer_evidence = renderer_evidence or content_sha256(
            {
                "validator": "content-team.hwp-question-editor-build",
                "item_revision_id": request.source.item_revision_id,
                "renderer_profile": request.renderer_profile.model_dump(mode="json"),
                "outcome": "FAIL",
                "reason": "EXACT_SUCCESSFUL_BUILD_ABSENT",
            }
        )
        all_lossless = renderer_outcome == "PASS"
        return LegacyItemEditorialDeterministicAssessment(
            checks=(
                self._check(
                    "CONTENT_CONTRACT",
                    "PASS",
                    content_sha256(
                        {
                            "validator": "catalog.assessment-item-content-v2",
                            "item_sha256": sha256_bytes(item_bytes),
                            "outcome": "PASS",
                        }
                    ),
                ),
                self._check(
                    "MARKDOWN_PROJECTION",
                    "PASS",
                    content_sha256(
                        {
                            "validator": "content-team.markdown-round-trip",
                            "markdown_sha256": markdown_sha256,
                            "outcome": "PASS",
                        }
                    ),
                ),
                self._check("HWPX_RENDERABILITY", renderer_outcome, renderer_evidence),
                self._check(
                    "LOSSLESSNESS",
                    "PASS" if all_lossless else "FAIL",
                    content_sha256(
                        {
                            "validator": "content-team.lossless-item-projection",
                            "item_sha256": sha256_bytes(item_bytes),
                            "markdown_sha256": markdown_sha256,
                            "renderer_evidence_sha256": renderer_evidence,
                            "outcome": "PASS" if all_lossless else "FAIL",
                        }
                    ),
                ),
            ),
            lossless_projection=all_lossless,
        )

    def _markdown_member_sha256(self, artifact_revision_id: str) -> str:
        with self.sessions() as session:
            revision = session.get(ArtifactRevisionRecord, artifact_revision_id)
            files = revision.manifest.get("files") if revision is not None else None
            entries = (
                [
                    item
                    for item in files
                    if isinstance(item, dict)
                    and item.get("file_name") == MARKDOWN_MEMBER
                    and item.get("media_type") == MARKDOWN_MEDIA_TYPE
                    and item.get("schema_ref") == MARKDOWN_SCHEMA_REF
                ]
                if isinstance(files, list)
                else []
            )
        if len(entries) != 1 or not isinstance(entries[0].get("sha256"), str):
            raise ValueError("content-team Markdown member is absent or ambiguous")
        return str(entries[0]["sha256"])

    @staticmethod
    def _check(
        kind: str,
        outcome: str,
        evidence_sha256: str,
    ) -> EditorialDeterministicCheck:
        return EditorialDeterministicCheck.model_validate(
            {
                "check_kind": kind,
                "outcome": outcome,
                "validator_key": {
                    "CONTENT_CONTRACT": "catalog.assessment-item-content",
                    "MARKDOWN_PROJECTION": "content-team.markdown-round-trip",
                    "HWPX_RENDERABILITY": "content-team.hwp-question-editor-build",
                    "LOSSLESSNESS": "content-team.lossless-item-projection",
                }[kind],
                "validator_revision": "1.0",
                "evidence_sha256": evidence_sha256,
            }
        )
