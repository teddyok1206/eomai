from __future__ import annotations

import json
from types import SimpleNamespace

from eom_identifiers import sha256_bytes
from eom_image_contracts import content_json_bytes

from scripts.image_trainer import publish_science_subject_benchmark_review as publication
from tests.unit.test_science_visual_subject_benchmark_contracts import (
    _command,
    _inventory,
    _plan,
    _result,
    _review,
)


class _Engine:
    disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _inputs():  # type: ignore[no-untyped-def]
    inventory = _inventory()
    plan = _plan(inventory)
    result = _result(plan, _command(plan))
    review = _review(inventory, plan, result)
    return inventory, plan, result, review


def _patch_resolution(monkeypatch, inventory, plan, result):  # type: ignore[no-untyped-def]
    plan_schema = (
        "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-plan/1.0"
    )
    result_schema = (
        "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-result/1.0"
    )
    payloads = {
        plan.subject_inventory.schema_ref: content_json_bytes(inventory.model_dump(mode="json")),
        plan_schema: content_json_bytes(plan.model_dump(mode="json")),
        result_schema: content_json_bytes(result.model_dump(mode="json")),
    }
    monkeypatch.setattr(
        publication,
        "_resolve",
        lambda _engine, pointer: payloads[pointer.schema_ref],
    )


def test_quality_review_publication_preflight_resolves_exact_pointer_chain(
    tmp_path, monkeypatch, capsys
):  # type: ignore[no-untyped-def]
    inventory, plan, result, review = _inputs()
    review_path = tmp_path / "review.json"
    review_path.write_bytes(content_json_bytes(review.model_dump(mode="json")) + b"\n")
    review_path.chmod(0o600)
    engine = _Engine()
    monkeypatch.setattr(publication, "_require_release", lambda _commit: None)
    monkeypatch.setattr(publication, "build_engine", lambda: engine)
    _patch_resolution(monkeypatch, inventory, plan, result)
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_science_subject_benchmark_review.py",
            "--review",
            str(review_path),
            "--source-commit",
            "a" * 40,
            "--preflight-only",
        ],
    )

    assert publication.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "review_id": review.review_id,
        "review_sha256": review.review_sha256,
        "status": "PREFLIGHT_PASS",
        "subject_count": 2,
    }
    assert engine.disposed


def test_quality_review_publication_commits_only_validated_review_member(
    tmp_path, monkeypatch, capsys
):  # type: ignore[no-untyped-def]
    inventory, plan, result, review = _inputs()
    review_path = tmp_path / "review.json"
    review_payload = content_json_bytes(review.model_dump(mode="json")) + b"\n"
    review_path.write_bytes(review_payload)
    review_path.chmod(0o600)
    engine = _Engine()
    captured = {}

    class _Publisher:
        def __init__(self, actual_engine, _settings):  # type: ignore[no-untyped-def]
            assert actual_engine is engine

        def publish(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            member = kwargs["members"][0]
            assert member.source == review_path
            assert member.sha256 == sha256_bytes(review_payload)
            return SimpleNamespace(
                artifact_id="artifact_" + "1" * 32,
                artifact_revision_id="rev_" + "2" * 32,
                primary_sha256=member.sha256,
                manifest_sha256="sha256:" + "3" * 64,
            )

    receipt = {}
    monkeypatch.setattr(publication, "_require_release", lambda _commit: None)
    monkeypatch.setattr(publication, "build_engine", lambda: engine)
    monkeypatch.setattr(publication, "ControlFileSetPublisher", _Publisher)
    monkeypatch.setattr(publication.Settings, "from_environment", lambda: object())
    monkeypatch.setattr(
        publication,
        "_write_receipt",
        lambda path, payload: receipt.update(path=path, payload=payload),
    )
    _patch_resolution(monkeypatch, inventory, plan, result)
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_science_subject_benchmark_review.py",
            "--review",
            str(review_path),
            "--source-commit",
            "a" * 40,
        ],
    )

    assert publication.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "PUBLISHED"
    assert captured["artifact_type"] == "control_local_image_science_subject_benchmark_review"
    assert captured["idempotency_key"] == (
        f"science-subject-benchmark-review:{review.review_sha256}"
    )
    assert receipt["path"].name == f"science-subject-benchmark-review-{review.review_id}.json"
    assert engine.disposed
