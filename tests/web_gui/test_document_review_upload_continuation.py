"""Read the exact existing upload without submitting or replacing its work."""

from datetime import timedelta

import pytest
from eom_web_gui.contracts import DocumentReviewSetView
from eom_web_gui.gateways import GatewayError

from tests.web_gui.helpers import (
    NOW,
    PDF_REVIEW_INTENT_ID,
    FakeGateway,
    login,
    make_client,
)

SET_ID = "docreviewset_" + "8" * 32


class ContinuingReviewGateway(FakeGateway):
    def __init__(self):
        super().__init__()
        self.reads = []
        self.denied = False

    async def pdf_document_review_upload_intent(self, session, upload_intent_id):
        self.reads.append(("single", upload_intent_id, session.operator))
        if self.denied:
            raise GatewayError(status=404, code="PDF_DOCUMENT_REVIEW_UPLOAD_NOT_FOUND")
        assert upload_intent_id == PDF_REVIEW_INTENT_ID
        original = self._pdf_upload_intent(started=False)
        return original.model_copy(
            update={"state": "PROCESSING", "upload_sha256": "sha256:" + "4" * 64}
        )

    async def paired_document_review_set(self, session, review_set_id):
        self.reads.append(("paired", review_set_id, session.operator))
        assert review_set_id == SET_ID
        return DocumentReviewSetView(
            review_set_id=SET_ID,
            state="AWAITING_UPLOADS",
            documents=tuple(
                dict(
                    role=role,
                    state="PROCESSING" if role == "QUESTION" else "AWAITING_UPLOAD",
                    original_filename=f"{role.lower()}.pdf",
                    source_format="PDF",
                    media_type="application/pdf",
                    content_length=12,
                    upload_sha256="sha256:" + "4" * 64 if role == "QUESTION" else None,
                    upload_url=(
                        f"/api/v1/pdf-document-reviews/sets/{SET_ID}/documents/{role}/content"
                    ),
                )
                for role in ("QUESTION", "SOLUTION")
            ),
            preset_key="MOCK_EXAM",
            created_at=NOW,
            updated_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            resource_version=2,
        )


@pytest.mark.parametrize(
    ("path", "kind", "identity"),
    (
        (f"upload-intents/{PDF_REVIEW_INTENT_ID}", "single", PDF_REVIEW_INTENT_ID),
        (f"sets/{SET_ID}", "paired", SET_ID),
    ),
)
def test_authenticated_status_read_preserves_pending_owner_and_never_submits(path, kind, identity):
    gateway = ContinuingReviewGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        assert client.get(f"/studio/api/v1/pdf-document-reviews/{path}").status_code == 401
        assert gateway.reads == []
        login(client)
        for _ in range(2):
            response = client.get(f"/studio/api/v1/pdf-document-reviews/{path}")
            assert response.status_code == 200
            value = response.json()
            if kind == "single":
                assert value["upload_intent_id"] == identity
                assert value["state"] == "PROCESSING"
            else:
                assert value["review_set_id"] == identity
                assert value["documents"][0]["state"] == "PROCESSING"
            assert value["workflow_id"] is None
    assert len(gateway.reads) == 2
    assert all(row[:2] == (kind, identity) for row in gateway.reads)
    assert gateway.pdf_review_create_calls == 0
    assert gateway.pdf_review_uploaded_bytes == b""


def test_status_read_preserves_upstream_ownership_denial():
    gateway = ContinuingReviewGateway()
    gateway.denied = True
    client, _ = make_client(gateway=gateway)
    with client:
        login(client)
        response = client.get(
            f"/studio/api/v1/pdf-document-reviews/upload-intents/{PDF_REVIEW_INTENT_ID}"
        )
    assert response.status_code == 404
    assert response.json()["error_code"] == "PDF_DOCUMENT_REVIEW_UPLOAD_NOT_FOUND"
    assert gateway.pdf_review_create_calls == 0
