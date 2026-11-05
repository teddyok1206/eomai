"""BFF preserves explicit consent, operator boundary and typed immutable receipts."""

from eom_identifiers import sha256_bytes
from eom_web_gui.material_learning_contracts import (
    MaterialLearningRuns,
    MaterialLearningSourceReceipt,
)

from tests.unit.test_material_learning_intake import source_receipt
from tests.web_gui.helpers import FakeGateway, login, make_client


class LearningGateway(FakeGateway):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.learning_calls = []

    async def material_learning_runs(self, session):
        self.learning_calls.append("list")
        return MaterialLearningRuns(schema_version="material-learning-run-list/1.0", runs=())

    async def material_learning_source(self, session, **kwargs):
        data = b"".join([chunk async for chunk in kwargs.pop("content")])
        self.learning_calls.append((kwargs, data))
        receipt = source_receipt()
        receipt["original_filename"] = kwargs["original_filename"]
        receipt["original"]["bytes"] = len(data)
        receipt["original"]["sha256"] = sha256_bytes(data)
        return MaterialLearningSourceReceipt.model_validate(receipt)


def test_new_learning_list_preserves_admin_only_boundary():
    gateway = LearningGateway(roles=["VIEWER"])
    client, _ = make_client(gateway=gateway)
    with client:
        login(client)
        assert client.get("/studio/api/v1/material-learning").status_code == 403
        assert not gateway.learning_calls


def test_learning_list_has_typed_empty_projection():
    gateway = LearningGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        login(client)
        response = client.get("/studio/api/v1/material-learning")
        assert response.status_code == 200, response.text
        assert response.json()["runs"] == []
        assert gateway.learning_calls == ["list"]


def test_material_upload_without_csrf_is_denied_before_reading_source():
    gateway = LearningGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        login(client)
        response = client.put(
            "/studio/api/v1/material-learning/sources?original_filename=test.pdf",
            content=b"%PDF-1.7\ntest",
            headers={
                "Content-Type": "application/octet-stream",
                "Idempotency-Key": "material-upload-test-1234",
                "X-EOM-Rights-Confirmed": "true",
            },
        )
        assert response.status_code == 403
        assert not gateway.learning_calls


def test_material_upload_stream_uses_binary_limit_and_exact_consent():
    gateway = LearningGateway()
    client, _ = make_client(gateway=gateway)
    body = b"%PDF-1.7\n" + b"x" * 300_000
    with client:
        session = login(client)
        response = client.put(
            "/studio/api/v1/material-learning/sources?original_filename=test.pdf",
            content=body,
            headers={
                "Content-Type": "application/octet-stream",
                "Idempotency-Key": "material-upload-test-1234",
                "X-EOM-Rights-Confirmed": "true",
                "X-CSRF-Token": session["csrf_token"],
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["original"]["sha256"] == sha256_bytes(body)
        assert gateway.learning_calls[0][1] == body
        assert gateway.learning_calls[0][0]["content_length"] == len(body)


def test_material_learning_browser_replay_and_owner_reset():
    import os
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Opt-in check requires an existing local Playwright environment")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual material upload browser check")
    script = Path(__file__).with_name("material_learning_browser_checks.mjs")
    result = subprocess.run(
        [node, str(script)], capture_output=True, text=True, timeout=90, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "MATERIAL_LEARNING_BROWSER=PASS" in result.stdout
