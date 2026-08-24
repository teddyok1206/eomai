from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_service.knowledge_analysis_sources import (
    KnowledgeAnalysisSourceError,
    resolve_approved_item_source,
    resolve_content_intake_source,
)
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeSourceFileRecord,
    ItemRevisionRecord,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from sqlalchemy.orm import Session

INTAKE_ID = "intake_" + "1" * 32
SOURCE_FILE_ID = "sourcefile_" + "2" * 32
ARTIFACT_ID = "artifact_" + "3" * 32
REVISION_ID = "rev_" + "4" * 32
SOURCE_SHA256 = "sha256:" + "5" * 64
ITEM_ID = "item_" + "6" * 32
ITEM_REVISION_ID = "itemrev_" + "7" * 32


class _FakeSession:
    def __init__(
        self,
        records: dict[tuple[type[Any], str], object],
        *,
        scalar_rows: tuple[object, ...] = (),
    ) -> None:
        self.records = records
        self.scalar_rows = scalar_rows

    def get(self, model: type[Any], identifier: str) -> object | None:
        return self.records.get((model, identifier))

    def scalars(self, _statement: object) -> tuple[object, ...]:
        return self.scalar_rows


def _session(
    *,
    batch_state: str = "HASHED",
    logical_approved: bool = True,
    revision_approved: bool = True,
    source_path: str = "source.txt",
    member_sha256: str = SOURCE_SHA256,
) -> Session:
    size = 21
    batch = SimpleNamespace(
        intake_batch_id=INTAKE_ID,
        state=batch_state,
    )
    source = SimpleNamespace(
        source_file_id=SOURCE_FILE_ID,
        intake_batch_id=INTAKE_ID,
        relative_path=source_path,
        media_type="text/plain",
        size_bytes=size,
        sha256=SOURCE_SHA256,
        artifact_id=ARTIFACT_ID,
        artifact_revision_id=REVISION_ID,
    )
    logical = SimpleNamespace(approved=logical_approved)
    revision = SimpleNamespace(
        approved=revision_approved,
        logical_artifact_id=ARTIFACT_ID,
        manifest={
            "files": [
                {
                    "file_name": source_path,
                    "sha256": member_sha256,
                    "bytes": size,
                    "media_type": "text/plain",
                    "schema_ref": "eom://schemas/knowledge/source-text/1.0",
                }
            ]
        },
    )
    return cast(
        Session,
        _FakeSession(
            {
                (ContentIntakeBatchRecord, INTAKE_ID): batch,
                (ContentIntakeSourceFileRecord, SOURCE_FILE_ID): source,
                (ArtifactRecord, ARTIFACT_ID): logical,
                (ArtifactRevisionRecord, REVISION_ID): revision,
            }
        ),
    )


def test_content_intake_source_resolves_exact_member_pointer() -> None:
    source = resolve_content_intake_source(
        _session(),
        intake_batch_id=INTAKE_ID,
        source_file_id=SOURCE_FILE_ID,
        source_class="TEXTBOOK",
    )

    assert source.source_file_id == SOURCE_FILE_ID
    assert source.artifact_member.artifact_revision_id == REVISION_ID
    assert source.artifact_member.sha256 == SOURCE_SHA256
    assert source.artifact_member.materialized_path.startswith("source/source-")
    assert source.artifact_member.schema_ref == "eom://schemas/knowledge/source-text/1.0"


@pytest.mark.parametrize(
    "session",
    (
        _session(logical_approved=False),
        _session(revision_approved=False),
    ),
)
def test_content_intake_source_rejects_unapproved_artifact(session: Session) -> None:
    with pytest.raises(KnowledgeAnalysisSourceError) as raised:
        resolve_content_intake_source(
            session,
            intake_batch_id=INTAKE_ID,
            source_file_id=SOURCE_FILE_ID,
            source_class="TEXTBOOK",
        )
    assert raised.value.code == "KNOWLEDGE_ANALYSIS_SOURCE_STALE"


def test_content_intake_source_rejects_hash_mismatch() -> None:
    with pytest.raises(KnowledgeAnalysisSourceError) as raised:
        resolve_content_intake_source(
            _session(member_sha256="sha256:" + "6" * 64),
            intake_batch_id=INTAKE_ID,
            source_file_id=SOURCE_FILE_ID,
            source_class="TEXTBOOK",
        )
    assert raised.value.code == "KNOWLEDGE_ANALYSIS_SOURCE_HASH_MISMATCH"


def test_content_intake_source_rejects_path_escape() -> None:
    with pytest.raises(KnowledgeAnalysisSourceError) as raised:
        resolve_content_intake_source(
            _session(source_path="../source.txt"),
            intake_batch_id=INTAKE_ID,
            source_file_id=SOURCE_FILE_ID,
            source_class="TEXTBOOK",
        )
    assert raised.value.code == "KNOWLEDGE_ANALYSIS_POINTER_INVALID"


def test_approved_historical_item_revision_resolves_without_implicit_latest_lookup() -> None:
    content_bytes = 512
    component = SimpleNamespace(
        required=True,
        media_type="application/json",
        schema_ref="eom.assessment.item-content/1.0",
        artifact_id=ARTIFACT_ID,
        artifact_revision_id=REVISION_ID,
        logical_name="assessment-item-content.json",
        sha256=SOURCE_SHA256,
    )
    session = cast(
        Session,
        _FakeSession(
            {
                (ItemRevisionRecord, ITEM_REVISION_ID): SimpleNamespace(
                    revision_state="APPROVED",
                    item_id=ITEM_ID,
                ),
                (ArtifactRecord, ARTIFACT_ID): SimpleNamespace(approved=True),
                (ArtifactRevisionRecord, REVISION_ID): SimpleNamespace(
                    approved=True,
                    logical_artifact_id=ARTIFACT_ID,
                    content_bytes=content_bytes,
                    manifest={
                        "files": [
                            {
                                "file_name": component.logical_name,
                                "sha256": SOURCE_SHA256,
                                "bytes": content_bytes,
                                "media_type": component.media_type,
                                "schema_ref": component.schema_ref,
                            }
                        ]
                    },
                ),
            },
            scalar_rows=(component,),
        ),
    )

    source = resolve_approved_item_source(
        session,
        item_revision_id=ITEM_REVISION_ID,
        source_class="APPROVED_ITEM",
    )

    assert source.item_id == ITEM_ID
    assert source.item_revision_id == ITEM_REVISION_ID
    assert source.artifact_member.artifact_revision_id == REVISION_ID
    assert source.artifact_member.materialized_path == "source/item-content.json"
