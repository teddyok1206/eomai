"""New release closure checks without invoking any deployment operation."""

from __future__ import annotations

import ast
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts/api/deploy_release.sh"


def _source_inspector() -> Callable[[Path, Path], None]:
    source = DEPLOY.read_text()
    start = source.index("<<'PY'\n", source.index("inspect_release() {")) + len("<<'PY'\n")
    end = source.index("\nPY\n", start)
    function = next(
        node
        for node in ast.parse(source[start:end]).body
        if isinstance(node, ast.FunctionDef) and node.name == "inspect_kakao_contract_source"
    )
    namespace: dict[str, object] = {"Path": Path, "zipfile": zipfile}
    # Only this build-time source inventory reader runs; no shell/deploy path executes.
    exec(compile(ast.Module(body=[function], type_ignores=[]), "Kakao wheel", "exec"), namespace)
    return cast(Callable[[Path, Path], None], namespace[function.name])


def _fixture(tmp_path: Path, *, mutation: str = "") -> tuple[Path, Path]:
    package = "eom_kakao_archive_contracts"
    repository = tmp_path / "source"
    root = repository / "packages/kakao_archive_contracts"
    (root / package / "schemas").mkdir(parents=True)
    canonical = repository / "schemas/kakao-archive"
    canonical.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname="eom-kakao-archive-contracts"\nversion="0.1.0"\n'
        'requires-python=">=3.12,<3.13"\n'
        'dependencies=["jsonschema>=4.25.1,<4.27", "pydantic==2.13.4"]\n'
    )
    source = {
        f"{package}/__init__.py": b'"""Pure package fixture."""\n',
        f"{package}/py.typed": b"",
        f"{package}/schemas/example.schema.json": b'{"type":"object"}\n',
    }
    for name, value in source.items():
        (root / name).write_bytes(value)
    (canonical / "example.schema.json").write_bytes(
        source[f"{package}/schemas/example.schema.json"]
    )
    metadata = (
        "Metadata-Version: 2.4\nName: eom-kakao-archive-contracts\nVersion: 0.1.0\n"
        "Requires-Python: <3.13,>=3.12\nRequires-Dist: jsonschema<4.27,>=4.25.1\n"
        "Requires-Dist: pydantic==2.13.4\n"
    )
    match mutation:
        case "stale_member":
            source[f"{package}/__init__.py"] = b"STALE=True\n"
        case "missing_member":
            del source[f"{package}/py.typed"]
        case "extra_member":
            source[f"{package}/obsolete.py"] = b""
        case "foreign_package":
            source["foreign/__init__.py"] = b""
        case "canonical_mismatch":
            (canonical / "example.schema.json").write_bytes(b"{}")
        case "source_symlink":
            actual = root / package / "__init__.py"
            actual.rename(root / "elsewhere")
            actual.symlink_to(root / "elsewhere")
        case "wrong_version":
            metadata = metadata.replace("Version: 0.1.0", "Version: 0.9.0")
        case "wrong_dependency":
            metadata = metadata.replace("pydantic==2.13.4", "pydantic==2.0.0")
        case "missing_metadata":
            metadata = ""
    wheel = tmp_path / "eom_kakao_archive_contracts-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, value in source.items():
            archive.writestr(name, value)
        if metadata:
            archive.writestr("eom_kakao_archive_contracts-0.1.0.dist-info/METADATA", metadata)
    return wheel, repository


def test_kakao_contract_wheel_matches_exact_archive_payload_and_canonical_schemas(
    tmp_path: Path,
) -> None:
    _source_inspector()(*_fixture(tmp_path))


@pytest.mark.parametrize(
    "mutation",
    [
        "stale_member",
        "missing_member",
        "extra_member",
        "foreign_package",
        "canonical_mismatch",
        "source_symlink",
        "wrong_version",
        "wrong_dependency",
        "missing_metadata",
    ],
)
def test_kakao_source_inspection_rejects_an_independently_changed_dependency(
    tmp_path: Path, mutation: str
) -> None:
    with pytest.raises(SystemExit, match="Kakao contracts"):
        _source_inspector()(*_fixture(tmp_path, mutation=mutation))


def test_new_release_pins_all_four_wheels_through_build_inspection_install_and_record() -> None:
    source = DEPLOY.read_text()
    build = source.split("build_release() {", 1)[1].split("inspect_release() {", 1)[0]
    assert '"${SOURCE_ROOT}/packages/kakao_archive_contracts" >/dev/null' in build
    assert source.count("--kakao-release") == 3
    assert 'MIGRATION_VERIFY_0084 "${COMMIT}"' in source
    assert 'MIGRATION_VERIFY_0079 "${COMMIT}"' not in source
    assert 'str(by_prefix["eom_kakao_archive_contracts"])' in source
    assert '"eom_kakao_archive_contracts.kakao_remote"' in source
    assert '"eom_catalog_service.kakao_manual_service"' in source
    install = source.split("install_wheels() {", 1)[1].split("\n}\n", 1)[0]
    assert "((${#wheels[@]} == 4))" in install
    assert install.count('verify_captured_release_wheel_inspection_identity "${wheels[@]}"') == 2
    assert 'install --no-deps --force-reinstall "${wheels[@]}"' in install
    installed_verifier = source.split("verify_install_mode() {", 1)[1]
    assert '"eom_kakao_archive_contracts",' in installed_verifier
    assert '"eom-kakao-archive-contracts"' in installed_verifier
    assert 'for path in sorted(dist.glob("*.whl")):' in installed_verifier
    assert "pinned pure Kakao contracts wheel" in installed_verifier


def test_every_embedded_release_python_program_compiles() -> None:
    source = DEPLOY.read_text()
    # Validate every static Python heredoc without shell interpolation or side effects.
    chunks = source.split("<<'PY'\n")[1:]
    assert chunks
    for index, chunk in enumerate(chunks):
        compile(chunk.split("\nPY\n", 1)[0], f"release-heredoc-{index}", "exec")
