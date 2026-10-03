from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import LocalImageSdxlLineartStack, validate_contract

from scripts.image_provider import download_sdxl_lineart_stack as acquisition


def _metadata(*, missing: bool = False, excessive: bool = False) -> dict[str, SimpleNamespace]:
    values = {}
    for _, _, repo, revision, _, files in acquisition.COMPONENTS:
        members = [SimpleNamespace(rfilename=name, size=20, lfs=None) for name in files]
        if missing:
            members.pop()
        if excessive:
            for member in members:
                member.size = 8 * 1024**3
        values[repo] = SimpleNamespace(sha=revision, siblings=members)
    return values


@pytest.mark.parametrize("fault", [None, "missing", "excessive", "revision"])
def test_acquisition_preflight_is_pinned_bounded_and_write_free(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fault: str | None
) -> None:
    metadata = _metadata(missing=fault == "missing", excessive=fault == "excessive")
    if fault == "revision":
        next(iter(metadata.values())).sha = "f" * 40
    calls = []

    def info(repo: str, **kwargs: object) -> SimpleNamespace:
        assert kwargs["token"] is False and kwargs["files_metadata"] is True
        calls.append((repo, kwargs["revision"]))
        return metadata[repo]

    monkeypatch.setattr(
        acquisition,
        "_hub_client",
        lambda: (SimpleNamespace(model_info=info), lambda *a, **k: pytest.fail("preflight wrote")),
    )
    with tempfile.TemporaryDirectory(prefix="eom-sdxl-lineart-download.", dir="/tmp") as parent:
        destination = Path(parent) / "stack"
        monkeypatch.setattr(
            "sys.argv", ["acquire", "--destination", str(destination), "--preflight-only"]
        )
        if fault:
            with pytest.raises(SystemExit, match="SDXL_DOWNLOAD_"):
                acquisition.main()
        else:
            acquisition.main()
            assert "PREFLIGHT=READY" in capsys.readouterr().out
            assert calls == [(entry[2], entry[3]) for entry in acquisition.COMPONENTS]
        assert not destination.exists()


def test_download_records_actual_hashes_and_a_valid_evaluation_only_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = _metadata()

    def download(repo: str, name: str, **kwargs: object) -> str:
        assert kwargs["token"] is False
        root = Path(str(kwargs["local_dir"]))
        assert kwargs["revision"] == metadata[repo].sha
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 20)
        return str(target)

    monkeypatch.setattr(
        acquisition,
        "_hub_client",
        lambda: (SimpleNamespace(model_info=lambda repo, **k: metadata[repo]), download),
    )
    prior_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix="eom-sdxl-lineart-download.", dir="/tmp") as parent:
            destination = Path(parent) / "stack"
            monkeypatch.setattr("sys.argv", ["acquire", "--destination", str(destination)])
            acquisition.main()
            value = json.loads((destination / "manifest.json").read_bytes())
            validate_contract("sdxl-lineart-stack", value)
            manifest = LocalImageSdxlLineartStack.model_validate(value)
            assert manifest.state == "EVALUATION_ONLY" and manifest.activation_policy == "FORBIDDEN"
            expected = "sha256:" + hashlib.sha256(b"x" * 20).hexdigest()
            assert all(
                file.sha256 == expected
                for component in manifest.components
                for file in component.files
            )
    finally:
        os.umask(prior_umask)


def test_file_reader_rejects_symbolic_and_hard_links(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"data")
    linked = tmp_path / "linked"
    linked.symlink_to(source)
    with pytest.raises(OSError):
        acquisition._hash(linked)
    linked.unlink()
    os.link(source, linked)
    with pytest.raises(SystemExit, match="FILE_INVALID"):
        acquisition._hash(linked)
