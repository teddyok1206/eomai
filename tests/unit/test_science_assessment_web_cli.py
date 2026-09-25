from __future__ import annotations

from pathlib import Path

import pytest
from eom_catalog_service.science_assessment_web_cli import _arguments, _write_receipt


def test_science_assessment_cli_rejects_multiple_execution_phases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "eom-science-assessment-corpus",
            "--plan",
            "/tmp/plan.json",
            "--workspace",
            "/tmp/workspace",
            "--received-by",
            "operator_" + "1" * 32,
            "--receipt",
            "/tmp/receipt.json",
            "--acquire-only",
            "--publish-only",
        ],
    )

    with pytest.raises(SystemExit) as caught:
        _arguments()

    assert caught.value.code == 2


def test_science_assessment_cli_receipt_is_canonical_and_exclusive(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    _write_receipt(receipt, {"status": "ACQUIRED", "count": 2})

    assert receipt.read_bytes() == b'{"count":2,"status":"ACQUIRED"}'
    assert receipt.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        _write_receipt(receipt, {"status": "PUBLISHED"})
