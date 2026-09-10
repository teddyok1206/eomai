from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import eom_api.build_info as build_info_module
import pytest
from eom_api.build_info import BuildInfoError, get_build_info
from eom_api_contracts import ApiReleaseBuildInfo
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_SCHEMA = ROOT / "schemas/api/v1/api-release-build-info-v1.schema.json"
PACKAGED_SCHEMA = (
    ROOT / "packages/api_contracts/eom_api_contracts/schemas/api-release-build-info-v1.schema.json"
)


def _document() -> dict[str, Any]:
    return {
        "build_timestamp_utc": "2026-09-09T14:00:00Z",
        "package_version": "0.1.0",
        "schema_version": "api-release-build-info/1.0",
        "source_archive_sha256": "sha256:" + "3" * 64,
        "source_commit": "1" * 40,
        "source_tree": "2" * 40,
    }


def _canonical_bytes(document: object) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("ascii")


def _install_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    payload: bytes | None,
    schema_payload: bytes | None = None,
) -> None:
    api_root = tmp_path / "eom_api"
    schema_root = tmp_path / "eom_api_contracts" / "schemas"
    api_root.mkdir(parents=True)
    schema_root.mkdir(parents=True)
    if payload is not None:
        (api_root / "build-info.json").write_bytes(payload)
    (schema_root / "api-release-build-info-v1.schema.json").write_bytes(
        PACKAGED_SCHEMA.read_bytes() if schema_payload is None else schema_payload
    )
    monkeypatch.setattr(build_info_module, "files", lambda package: tmp_path / package)


def test_release_build_info_schema_is_mirrored_and_matches_the_typed_contract() -> None:
    assert CANONICAL_SCHEMA.read_bytes() == PACKAGED_SCHEMA.read_bytes()
    schema = json.loads(CANONICAL_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    model = ApiReleaseBuildInfo.model_validate(_document())
    value = model.model_dump(mode="json")
    assert (
        tuple(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)) == ()
    )
    assert model.build_timestamp_utc == datetime(2026, 9, 9, 14, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "api-release-build-info/2.0"),
        ("package_version", ""),
        ("source_commit", "A" * 40),
        ("source_tree", "2" * 39),
        ("source_archive_sha256", "3" * 64),
        ("build_timestamp_utc", "2026-09-09T23:00:00+09:00"),
        ("build_timestamp_utc", "2026-09-09T14:00:00-00:00"),
        ("build_timestamp_utc", 1),
    ),
)
def test_release_build_info_rejects_noncanonical_identity_values(field: str, value: object) -> None:
    document = _document()
    document[field] = value
    schema = json.loads(CANONICAL_SCHEMA.read_text(encoding="utf-8"))
    assert tuple(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document))
    with pytest.raises(ValidationError):
        ApiReleaseBuildInfo.model_validate(document)


def test_packaged_build_info_loader_returns_only_the_validated_typed_resource(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_resources(monkeypatch, tmp_path, payload=_canonical_bytes(_document()))

    loaded = get_build_info()

    assert isinstance(loaded, ApiReleaseBuildInfo)
    assert loaded.source_commit == "1" * 40
    assert loaded.source_tree == "2" * 40
    assert loaded.source_archive_sha256 == "sha256:" + "3" * 64


@pytest.mark.parametrize(
    "payload",
    (
        b'{"source_commit":"1111111111111111111111111111111111111111",'
        b'"source_commit":"1111111111111111111111111111111111111111"}\n',
        json.dumps(_document(), indent=2).encode("ascii") + b"\n",
        _canonical_bytes([_document()]),
        _canonical_bytes({**_document(), "unexpected": True}),
        b"x" * 4097,
    ),
)
def test_packaged_build_info_loader_fails_closed_on_ambiguous_or_invalid_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: bytes
) -> None:
    _install_resources(monkeypatch, tmp_path, payload=payload)

    with pytest.raises(BuildInfoError, match="unavailable or invalid"):
        get_build_info()


def test_packaged_build_info_loader_fails_closed_when_resource_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_resources(monkeypatch, tmp_path, payload=None)

    with pytest.raises(BuildInfoError, match="unavailable or invalid"):
        get_build_info()


def test_packaged_build_info_loader_requires_the_explicit_schema_discriminator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    document = _document()
    del document["schema_version"]
    _install_resources(monkeypatch, tmp_path, payload=_canonical_bytes(document))

    with pytest.raises(BuildInfoError, match="unavailable or invalid"):
        get_build_info()


def test_packaged_build_info_loader_fails_closed_on_invalid_packaged_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_resources(
        monkeypatch,
        tmp_path,
        payload=_canonical_bytes(_document()),
        schema_payload=b'{"$schema":"https://json-schema.org/draft/2020-12/schema","type":42}\n',
    )

    with pytest.raises(BuildInfoError, match="unavailable or invalid"):
        get_build_info()


def test_release_builder_derives_and_verifies_source_identity_without_runtime_git_lookup() -> None:
    deploy = (ROOT / "scripts/api/deploy_release.sh").read_text(encoding="utf-8")
    loader = (ROOT / "apps/application_api/eom_api/build_info.py").read_text(encoding="utf-8")
    application_project = (ROOT / "apps/application_api/pyproject.toml").read_text(encoding="utf-8")

    assert 'GIT="/usr/bin/git"' in deploy
    assert 'rev-parse "${COMMIT}^{tree}"' in deploy
    assert 'ls-tree -r "${COMMIT}"' in deploy
    assert "release source cannot contain symlinks or unmaterialized Git submodules" in deploy
    assert '"${GIT}" -C "${REPOSITORY_ROOT}" archive \\' in deploy
    assert '--format=tar --output="${SOURCE_ARCHIVE_PATH}" "${COMMIT}"' in deploy
    assert '"${SHA256SUM}" "${SOURCE_ARCHIVE_PATH}"' in deploy
    assert '/usr/bin/chmod 0600 "${SOURCE_ARCHIVE_PATH}"' in deploy
    assert '"${TAR}" --extract --file="${SOURCE_ARCHIVE_PATH}"' in deploy
    assert '"${SOURCE_ROOT}" >/dev/null' in deploy
    assert '"source_tree": os.environ["SOURCE_TREE"]' in deploy
    assert '"source_archive_sha256": os.environ["SOURCE_ARCHIVE_SHA256"]' in deploy
    assert "Application API wheel source archive bytes mismatch" in deploy
    assert "Application API release source archive changed during inspection" in deploy
    assert "installed-wheel API release source identity mismatch" in deploy
    assert deploy.count("\n  verify_release_wheel_records") == 1
    assert 'scripts/api/verify_release_wheel_records.py"' in deploy
    install_start = deploy.index("install_wheels() {")
    pip_install = deploy.index("install --no-deps --force-reinstall", install_start)
    preinstall_identity = deploy.index(
        'verify_captured_release_wheel_inspection_identity "${wheels[@]}"', install_start
    )
    postinstall_identity = deploy.index(
        'verify_captured_release_wheel_inspection_identity "${wheels[@]}"',
        preinstall_identity + 1,
    )
    assert preinstall_identity < pip_install < postinstall_identity
    assert deploy.find("capture_release_wheel_inspection_identity", install_start) == -1
    build_start = deploy.index("build_release() {")
    inspect = deploy.index("\n  inspect_release", build_start)
    capture = deploy.index("\n  capture_release_wheel_inspection_identity", inspect)
    assert inspect < capture < install_start
    assert "release wheel bytes changed after inspection" in deploy
    assert "from eom_api.build_info import get_build_info" in deploy
    assert "installed API release source identity mismatch" in deploy
    assert "verify_install_mode exact-source" in deploy
    assert "verify_install_mode validated-resource-only" in deploy
    assert 'os.environ["SOURCE_IDENTITY_MODE"] == "exact-source"' in deploy
    assert "expected exactly 29 packaged API schemas" in deploy
    assert "subprocess" not in loader
    assert "os.environ" not in loader
    assert ".git" not in loader
    assert '"jsonschema==4.26.0"' in application_project
