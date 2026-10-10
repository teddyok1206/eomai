from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_experiment import InferenceTransferExperimentResult
from eom_identifiers import canonical_json_bytes

from scripts.embedding import run_inference_transfer_experiment as cli
from tests.unit.inference_transfer_experiment_fixtures import experiment_request
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.test_inference_transfer_experiment import FakeMeasuredBackend, run


def staged(tmp_path: Path, *, maximum_input_bytes: int | None = None) -> tuple[Path, str]:
    request = experiment_request(
        **({} if maximum_input_bytes is None else {"maximum_input_bytes": maximum_input_bytes})
    )
    path = tmp_path / "request.json"
    path.write_bytes(canonical_json_bytes(request.model_dump(mode="json")))
    path.chmod(0o600)
    return path, request.request_sha256


def test_cli_reader_and_writer_preserve_exact_request_and_integer_result(tmp_path: Path) -> None:
    _path, expected = staged(tmp_path)
    request = cli.read_request(tmp_path, "request.json", expected)
    result = run(request)
    cli.write_result(tmp_path, "result.json", result)
    committed = InferenceTransferExperimentResult.model_validate_json(
        (tmp_path / "result.json").read_bytes()
    )
    assert committed == result
    assert (tmp_path / "result.json").stat().st_mode & 0o777 == 0o600
    assert (
        json.loads((tmp_path / "result.json").read_bytes())["data_provenance"]
        == "TEST_ONLY_SYNTHETIC"
    )


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    marker = tmp_path / "result.json"
    marker.write_bytes(b"historical immutable output")
    with pytest.raises(FileExistsError):
        cli.write_result(tmp_path, "result.json", run())
    assert marker.read_bytes() == b"historical immutable output"


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../request.json",
        "/tmp/request.json",
        "nested/request.json",
        "nested\\request.json",
    ],
)
def test_member_name_cannot_escape_local_workspace(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="MEMBER_INVALID"):
        cli.read_request(tmp_path, name, sha())


def test_input_symlink_and_hardlink_are_rejected(tmp_path: Path) -> None:
    path, expected = staged(tmp_path)
    linked = tmp_path / "link.json"
    linked.symlink_to(path)
    with pytest.raises(OSError):
        cli.read_request(tmp_path, linked.name, expected)
    linked.unlink()
    os.link(path, linked)
    with pytest.raises(ValueError, match="INPUT_INVALID"):
        cli.read_request(tmp_path, path.name, expected)


def test_workspace_symlink_and_nonsticky_writable_parent_are_rejected(tmp_path: Path) -> None:
    child = tmp_path / "workspace"
    child.mkdir(mode=0o700)
    path, expected = staged(child)
    linked = tmp_path / "linked"
    linked.symlink_to(child, target_is_directory=True)
    with pytest.raises(ValueError, match="WORKSPACE_INVALID"):
        cli.read_request(linked, path.name, expected)
    tmp_path.chmod(0o777)
    try:
        with pytest.raises(ValueError, match="WORKSPACE_INVALID"):
            cli.read_request(child, path.name, expected)
    finally:
        tmp_path.chmod(0o700)


def test_relative_and_nas_workspaces_are_not_worker_output_targets() -> None:
    for path in (Path("workspace"), Path("/mnt/nas/eom/experiment")):
        with pytest.raises(ValueError, match="LOCAL_WORKSPACE_REQUIRED"):
            cli.read_request(path, "request.json", sha())


def test_writable_by_others_input_and_wrong_caller_pin_fail(tmp_path: Path) -> None:
    path, expected = staged(tmp_path)
    with pytest.raises(ValueError, match="INPUT_PIN_OR_BUDGET_MISMATCH"):
        cli.read_request(tmp_path, path.name, sha("f"))
    path.chmod(0o666)
    with pytest.raises(ValueError, match="INPUT_INVALID"):
        cli.read_request(tmp_path, path.name, expected)


def test_declared_input_budget_is_enforced_before_model_loading(tmp_path: Path) -> None:
    path, expected = staged(tmp_path, maximum_input_bytes=1024)
    assert path.stat().st_size > 1024
    with pytest.raises(ValueError, match="INPUT_PIN_OR_BUDGET_MISMATCH"):
        cli.read_request(tmp_path, path.name, expected)


def test_global_input_cap_and_duplicate_json_members_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, expected = staged(tmp_path)
    monkeypatch.setattr(cli, "_MAXIMUM_INPUT_BYTES", 10)
    with pytest.raises(ValueError, match="INPUT_INVALID"):
        cli.read_request(tmp_path, path.name, expected)
    monkeypatch.setattr(cli, "_MAXIMUM_INPUT_BYTES", 64 * 1024**2)
    payload = path.read_text()
    path.write_text('{"schema_version":"forged",' + payload[1:])
    with pytest.raises(ValueError, match="DUPLICATE_JSON_MEMBER"):
        cli.read_request(tmp_path, path.name, expected)


def test_forged_result_hash_does_not_create_output(tmp_path: Path) -> None:
    result = run().model_copy(update={"result_sha256": sha("f")})
    with pytest.raises(ValueError):
        cli.write_result(tmp_path, "result.json", result)
    assert not (tmp_path / "result.json").exists()


def test_cli_smoke_with_explicit_fake_adapter_never_claims_real_model_or_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _path, expected = staged(tmp_path)
    observed: dict[str, Any] = {}

    def fake_backend(*args: Any, **kwargs: Any) -> FakeMeasuredBackend:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return FakeMeasuredBackend()

    monkeypatch.setattr(cli, "OfflineTransformersEmbeddingBackend", fake_backend)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "experiment",
            "--workspace",
            str(tmp_path),
            "--request-sha256",
            expected,
            "--model-store",
            str(tmp_path / "unused-fake-model"),
        ],
    )
    cli.main()
    result = InferenceTransferExperimentResult.model_validate_json(
        (tmp_path / "result.json").read_bytes()
    )
    assert result.backend_kind == "TEST_ONLY" and result.actual_model_manifest_sha256 is None
    assert result.data_provenance == "TEST_ONLY_SYNTHETIC"
    assert result.human_transfer_review == "NOT_EVALUATED"
    assert observed["kwargs"] == {"expected_owner_uid": 0, "batch_size": 4, "threads": 4}
    assert "EXPERIMENT_STATUS=MEASURED" in capsys.readouterr().out
