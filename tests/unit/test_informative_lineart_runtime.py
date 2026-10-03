"""No-network/no-Torch fixtures test ownership, pinning and safe acquisition boundaries."""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
from datetime import UTC, datetime
from http.client import HTTPException
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest
from eom_image_contracts import (
    InformativeLineartPointer,
    InformativeLineartUpstream,
    LocalImageInformativeLineartManifest,
    ModelFile,
    content_json_bytes,
    validate_contract,
)
from eom_image_provider import informative_lineart_acquisition as acquisition
from eom_image_provider import informative_lineart_download as download
from eom_image_provider import informative_lineart_resolution as resolution
from eom_image_provider.informative_lineart_model import (
    InformativeLineartConversion,
    convert_informative_lineart_weights,
    informative_lineart_config_bytes,
    informative_lineart_license_bytes,
)
from eom_image_provider.provider import ProviderError


def _members() -> dict[str, bytes]:
    return {
        "LICENSE": informative_lineart_license_bytes(),
        "config.json": informative_lineart_config_bytes(),
        "model.safetensors": b"fake unit-test weight; NOT numerically accepted",
        "upstream.json": content_json_bytes(
            InformativeLineartUpstream.pinned().model_dump(mode="json")
        ),
    }


def _manifest(members: dict[str, bytes]) -> LocalImageInformativeLineartManifest:
    return LocalImageInformativeLineartManifest.create(
        files=tuple(
            ModelFile(
                relative_path=name,
                size_bytes=len(payload),
                sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
            )
            for name, payload in sorted(members.items())
        ),
        created_at=datetime(2026, 10, 3, 22, tzinfo=UTC),
        created_by="test.extractor",
    )


def _pointer(manifest: LocalImageInformativeLineartManifest) -> InformativeLineartPointer:
    return InformativeLineartPointer(
        **manifest.model_dump(
            include={
                "extractor_id",
                "extractor_revision_id",
                "manifest_sha256",
                "provider_family",
                "runtime_contract_version",
            }
        )
    )


def _materialize(tmp_path: Path, members: dict[str, bytes] | None = None):
    members = _members() if members is None else members
    manifest = _manifest(members)
    tmp_path.chmod(0o700)
    logical = tmp_path / manifest.extractor_id
    logical.mkdir(mode=0o700)
    root = logical / manifest.extractor_revision_id
    root.mkdir(mode=0o700)
    for name, payload in {
        **members,
        "manifest.json": content_json_bytes(manifest.model_dump(mode="json")),
    }.items():
        (root / name).write_bytes(payload)
        (root / name).chmod(0o600)
    return manifest, _pointer(manifest), root


def test_exact_model_resolution_materializes_each_file_once_without_torch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, pointer, _ = _materialize(tmp_path)
    reader = resolution.read_staged_member
    calls = []

    def read(root, relative, **kwargs):
        calls.append(relative)
        return reader(root, relative, **kwargs)

    monkeypatch.setattr(resolution, "read_staged_member", read)
    resolved = resolution.resolve_informative_lineart_material(
        tmp_path, pointer, expected_owner_uid=os.geteuid()
    )
    assert (
        resolved.manifest == manifest and resolved.weight_bytes == _members()["model.safetensors"]
    )
    assert calls == [
        "manifest.json",
        "LICENSE",
        "config.json",
        "model.safetensors",
        "upstream.json",
    ]
    assert "fake unit-test weight" not in repr(resolved)
    validate_contract("informative-lineart-manifest", manifest.model_dump(mode="json"))


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra",
        "hash",
        "symlink",
        "hardlink",
        "mode",
        "root-mode",
        "logical-mode",
        "revision-mode",
        "owner",
        "stale",
        "pointer",
        "pointer-traversal",
        "schema",
        "noncanonical",
        "duplicate-json",
        "manifest-size",
        "manifest-link",
    ],
)
def test_model_resolution_rejects_unsafe_missing_stale_and_changed_members(
    tmp_path: Path, fault: str
) -> None:
    manifest, pointer, root = _materialize(tmp_path)
    weight = root / "model.safetensors"
    owner = os.geteuid()
    if fault == "missing":
        weight.unlink()
    elif fault == "extra":
        (root / "model.pth").write_bytes(b"untrusted pickle must not be admitted")
    elif fault == "hash":
        weight.write_bytes(b"x" * weight.stat().st_size)
    elif fault in {"symlink", "hardlink"}:
        weight.unlink()
        if fault == "symlink":
            weight.symlink_to(root / "LICENSE")
        else:
            os.link(root / "LICENSE", weight)
    elif fault == "mode":
        weight.chmod(0o660)
    elif fault in {"root-mode", "logical-mode", "revision-mode"}:
        {"root-mode": tmp_path, "logical-mode": root.parent, "revision-mode": root}[fault].chmod(
            0o770
        )
    elif fault == "owner":
        owner += 1
    elif fault == "stale":
        pointer = pointer.model_copy(
            update={"extractor_revision_id": "imgextractorrev_" + "f" * 32}
        )
    elif fault == "pointer":
        pointer = pointer.model_copy(update={"manifest_sha256": "sha256:" + "f" * 64})
    elif fault == "pointer-traversal":
        pointer = pointer.model_copy(update={"extractor_id": "../../elsewhere"})
    elif fault == "schema":
        value = manifest.model_dump(mode="json")
        value["state"] = "APPROVED"
        (root / "manifest.json").write_bytes(content_json_bytes(value))
    elif fault == "noncanonical":
        (root / "manifest.json").write_bytes(
            json.dumps(manifest.model_dump(mode="json"), indent=2).encode()
        )
    elif fault == "duplicate-json":
        value = (root / "manifest.json").read_bytes()
        (root / "manifest.json").write_bytes(b'{"state":"EVALUATION_ONLY",' + value[1:])
    elif fault == "manifest-size":
        (root / "manifest.json").write_bytes(b" " * (64 * 1024 + 1))
    else:
        (root / "manifest.json").unlink()
        (root / "manifest.json").symlink_to(weight)
    with pytest.raises(ProviderError, match="LINEART_EXTRACTOR_"):
        resolution.resolve_informative_lineart_material(tmp_path, pointer, expected_owner_uid=owner)


@pytest.mark.parametrize("member", ["LICENSE", "config.json", "upstream.json"])
def test_resigned_metadata_does_not_bypass_fixed_runtime_meaning(
    tmp_path: Path, member: str
) -> None:
    members = _members()
    members[member] += b" "
    _, pointer, _ = _materialize(tmp_path, members)
    with pytest.raises(ProviderError, match="MODEL_INVALID"):
        resolution.resolve_informative_lineart_material(
            tmp_path, pointer, expected_owner_uid=os.geteuid()
        )


@pytest.mark.parametrize("fault", ["length", "hash", "upstream"])
def test_original_weight_guard_runs_before_torch_import(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name in {"torch", "safetensors.torch"}:
            pytest.fail("unvalidated weight imported a numerical loader")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    upstream = InformativeLineartUpstream.pinned()
    payload = b"x" * upstream.weight_bytes if fault == "hash" else b"bad"
    if fault == "upstream":
        upstream = upstream.model_copy(update={"revision": "main"})
    with pytest.raises((ProviderError, ValueError)):
        convert_informative_lineart_weights(payload, upstream)


def _fake_acquisition(monkeypatch: pytest.MonkeyPatch):
    # Fake ONLY the public source digest in this no-network test. Safe-file and manifest
    # hashes below remain real; these bytes are explicitly not numerical model evidence.
    upstream = InformativeLineartUpstream.pinned()
    sources = {
        "README.md": b"fake-license-record",
        "app.py": b"fake-architecture-record",
        "model.pth": b"x" * upstream.weight_bytes,
    }
    source_sha = {
        sources["README.md"]: upstream.license_record_sha256,
        sources["app.py"]: upstream.architecture_source_sha256,
        sources["model.pth"]: upstream.weight_sha256,
    }
    actual_sha = hashlib.sha256
    monkeypatch.setattr(
        acquisition,
        "hashlib",
        SimpleNamespace(
            sha256=lambda payload: (
                SimpleNamespace(hexdigest=lambda: source_sha[payload][7:])
                if payload in source_sha
                else actual_sha(payload)
            )
        ),
    )
    calls = []

    def fetch(name, maximum):
        calls.append((name, maximum))
        return sources[name]

    def convert(payload, pinned):
        assert pinned == upstream and payload == sources["model.pth"]
        calls.append(("convert", len(payload)))
        return InformativeLineartConversion(b"fake-safetensors", 1, 4)

    return sources, calls, fetch, convert


def test_acquisition_validates_pins_and_writes_only_fresh_safe_runtime_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, calls, fetch, convert = _fake_acquisition(monkeypatch)
    tmp_path.chmod(0o700)
    result = acquisition.acquire_informative_lineart_model(
        tmp_path,
        created_by="test.acquirer",
        fetch=fetch,
        convert=convert,
        created_at=datetime(2026, 10, 3, 22, tzinfo=UTC),
    )
    assert [call[0] for call in calls] == ["README.md", "app.py", "model.pth", "convert"]
    assert set(path.name for path in (tmp_path / "model").iterdir()) == {
        *_members(),
        "manifest.json",
    }
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in (tmp_path / "model").iterdir())
    validate_contract("informative-lineart-manifest", result.manifest.model_dump(mode="json"))
    assert result.manifest.activation_policy == "FORBIDDEN" and result.tensor_count == 1
    calls.clear()
    with pytest.raises(ProviderError, match="STAGING_INVALID"):
        acquisition.acquire_informative_lineart_model(
            tmp_path, created_by="test", fetch=fetch, convert=convert
        )
    assert calls == []


@pytest.mark.parametrize("member", ["README.md", "app.py", "model.pth"])
def test_acquisition_wrong_source_hash_is_write_free_and_never_converts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str
) -> None:
    sources, calls, fetch, _ = _fake_acquisition(monkeypatch)
    sources[member] = b"wrong-source"
    tmp_path.chmod(0o700)
    with pytest.raises(ProviderError, match="HASH_MISMATCH"):
        acquisition.acquire_informative_lineart_model(
            tmp_path,
            created_by="test",
            fetch=fetch,
            convert=lambda *_: pytest.fail("invalid source was deserialized"),
        )
    assert list(tmp_path.iterdir()) == [] and all(call[0] != "convert" for call in calls)


@pytest.mark.parametrize("fault", ["relative", "symlink", "mode", "nonempty"])
def test_acquisition_invalid_staging_is_write_free_before_network(
    tmp_path: Path, fault: str
) -> None:
    tmp_path.chmod(0o700)
    staging = tmp_path
    if fault == "relative":
        staging = Path("relative")
    elif fault == "symlink":
        staging = tmp_path / "link"
        staging.symlink_to(tmp_path, target_is_directory=True)
    elif fault == "mode":
        staging.chmod(0o770)
    else:
        (staging / "already-there").write_bytes(b"retain existing data")
    with pytest.raises(ProviderError, match="STAGING_INVALID"):
        acquisition.acquire_informative_lineart_model(
            staging,
            created_by="test",
            fetch=lambda *_: pytest.fail("unsafe staging reached network"),
        )


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, *, scheme: str = "https", length: str | None = None):
        super().__init__(payload)
        self.scheme = scheme
        self.headers = {} if length is None else {"Content-Length": length}

    def geturl(self):
        return self.scheme + "://cdn.huggingface.co/public-model"


@pytest.mark.parametrize("fault", [None, "downgrade", "declared-size", "read-size", "empty"])
def test_download_is_public_pinned_bounded_and_rejects_downgrade(
    monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    payload = b"x" * (64 * 1024 + 1) if fault == "read-size" else b"public-model"
    if fault == "empty":
        payload = b""

    def fetch(request, *, timeout):
        assert request.full_url == (
            "https://huggingface.co/spaces/carolineec/informativedrawings/resolve/"
            "bd4b4299be505803e036203a39c02024b4cfee11/README.md"
        )
        assert "Authorization" not in request.headers and "Cookie" not in request.headers
        assert timeout == 30
        return _Response(
            payload,
            scheme="http" if fault == "downgrade" else "https",
            length=str(64 * 1024 + 1) if fault == "declared-size" else None,
        )

    monkeypatch.setattr(download, "urlopen", fetch)
    if fault:
        with pytest.raises(ProviderError, match="DOWNLOAD_INVALID"):
            download.fetch_informative_lineart_member("README.md", 64 * 1024)
    else:
        assert download.fetch_informative_lineart_member("README.md", 64 * 1024) == payload


@pytest.mark.parametrize(
    "name,maximum", [("../app.py", 64 * 1024), ("model2.pth", 17173511), ("app.py", 1)]
)
def test_download_rejects_arbitrary_member_and_changed_bounds_before_network(
    monkeypatch: pytest.MonkeyPatch, name: str, maximum: int
) -> None:
    monkeypatch.setattr(
        download, "urlopen", lambda *_a, **_k: pytest.fail("arbitrary input reached network")
    )
    with pytest.raises(ProviderError, match="DOWNLOAD_INVALID"):
        download.fetch_informative_lineart_member(name, maximum)


@pytest.mark.parametrize(
    "failure",
    [
        URLError("unavailable"),
        OSError("timeout"),
        ValueError("bad length"),
        HTTPException("truncated body"),
    ],
)
def test_download_transport_failures_have_one_stable_code(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def unavailable(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(download, "urlopen", unavailable)
    with pytest.raises(ProviderError, match="DOWNLOAD_FAILED"):
        download.fetch_informative_lineart_member("README.md", 64 * 1024)
