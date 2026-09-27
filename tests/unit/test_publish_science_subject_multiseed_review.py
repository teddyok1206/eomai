from __future__ import annotations

import json

from eom_image_contracts import content_json_bytes

from scripts.image_trainer import publish_science_subject_multiseed_review as publication
from tests.unit.test_science_visual_subject_benchmark_contracts import (
    _command,
    _multiseed_command,
    _multiseed_initials,
    _multiseed_plan,
    _multiseed_result,
    _multiseed_review,
    _result,
)


class _Engine:
    disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _key(pointer):  # type: ignore[no-untyped-def]
    return (pointer.artifact_id, pointer.artifact_revision_id, pointer.member_path)


def test_multiseed_review_preflight_resolves_exact_predecessor_chain(
    tmp_path,
    monkeypatch,
    capsys,
):  # type: ignore[no-untyped-def]
    inventory, initial_plan, initial_review = _multiseed_initials()
    initial_result = _result(initial_plan, _command(initial_plan))
    plan = _multiseed_plan(inventory, initial_plan, initial_review)
    result = _multiseed_result(plan, _multiseed_command(plan))
    review = _multiseed_review(initial_plan, initial_review, plan, result)
    review_path = tmp_path / "review.json"
    review_path.write_bytes(content_json_bytes(review.model_dump(mode="json")) + b"\n")
    review_path.chmod(0o600)
    payloads = {
        _key(review.multiseed_plan): content_json_bytes(plan.model_dump(mode="json")),
        _key(review.multiseed_result): content_json_bytes(result.model_dump(mode="json")),
        _key(review.initial_quality_review): content_json_bytes(
            initial_review.model_dump(mode="json")
        ),
        _key(initial_review.benchmark_plan): content_json_bytes(
            initial_plan.model_dump(mode="json")
        ),
        _key(initial_review.benchmark_result): content_json_bytes(
            initial_result.model_dump(mode="json")
        ),
        _key(initial_review.subject_inventory): content_json_bytes(
            inventory.model_dump(mode="json")
        ),
    }
    engine = _Engine()
    monkeypatch.setattr(publication, "_require_release", lambda _commit: None)
    monkeypatch.setattr(publication, "build_engine", lambda: engine)
    monkeypatch.setattr(
        publication,
        "_resolve",
        lambda _engine, pointer: payloads[_key(pointer)],
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_science_subject_multiseed_review.py",
            "--review",
            str(review_path),
            "--source-commit",
            "a" * 40,
            "--preflight-only",
        ],
    )

    assert publication.main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "review_id": review.review_id,
        "review_sha256": review.review_sha256,
        "status": "PREFLIGHT_PASS",
        "subject_count": 1,
    }
    assert engine.disposed
