from __future__ import annotations

import ast
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from eom_hwpx_builder.archive import canonicalize_package
from eom_hwpx_builder.bindings import TEXT_MARKERS
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.kordoc_markdown import inspect_kordoc_markdown
from eom_hwpx_builder.kordoc_renderer import render_kordoc_workspace
from eom_hwpx_builder.kordoc_runtime import (
    KORDOC_PACKAGE_LOCK_SHA256,
    KordocBridgeReport,
    KordocRuntime,
    KordocRuntimeSettings,
)
from eom_hwpx_builder.util import sha256_bytes, sha256_file
from eom_hwpx_builder.validation import validate_kordoc_structure, validate_structure
from eom_hwpx_contracts import (
    KordocBuildResult,
    KordocRendererDependency,
    KordocRenderRequest,
    validate_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError

from tests.hwpx.helpers import synthetic_parts

MARKDOWN = """# 통합과학 문항

$$E = mc^2$$

| 조건 | 측정값 | 단위 |
| --- | ---: | :---: |
| 질량 | 2.50 | kg |
"""


def request_value(source: bytes) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "renderer_profile": "kordoc-markdown-v1",
        "build_id": "hwpxbuild_" + "a" * 32,
        "source": {
            "artifact_id": "artifact_" + "b" * 32,
            "artifact_revision_id": "rev_" + "c" * 32,
            "schema_id": "eom.hwpx.markdown-document",
            "schema_version": "1.0",
            "media_type": "text/markdown; charset=utf-8",
            "sha256": sha256_bytes(source),
            "file": "input/document.md",
        },
        "renderer_dependency": {
            "package": "kordoc",
            "version": "4.9.0",
            "npm_integrity": KordocRendererDependency().npm_integrity,
        },
        "options": {"offline": True, "gongmun_preset": "report"},
        "expected_structure": {"display_equation_count": 1, "table_count": 1},
        "output_directory": "output",
    }


def kordoc_like_parts() -> list[tuple[str, bytes, int]]:
    parts: list[tuple[str, bytes, int]] = []
    for name, data, compression in synthetic_parts(split_marker=False):
        for marker in (*TEXT_MARKERS.values(), "EOM_EQ_PLACEHOLDER"):
            data = data.replace(marker.encode(), b"KORDOC_VALUE")
        parts.append((name, data, compression))
    return parts


class FakeKordocRuntime:
    def __init__(self, *, timestamp: tuple[int, int, int, int, int, int]) -> None:
        self.timestamp = timestamp
        self.calls = 0

    def render(self, workspace: Path, preset: str) -> KordocBridgeReport:
        assert preset == "report"
        self.calls += 1
        output = workspace / ".kordoc-generated.hwpx"
        with zipfile.ZipFile(output, "w") as archive:
            for name, data, compression in kordoc_like_parts():
                info = zipfile.ZipInfo(name, self.timestamp)
                info.compress_type = compression
                archive.writestr(info, data)
        (workspace / ".kordoc-report.json").write_text("{}\n", encoding="utf-8")
        source = workspace / "input/document.md"
        return KordocBridgeReport(
            schema_version="1.0",
            kordoc_version="4.9.0",
            source_sha256=sha256_file(source),
            output_sha256=sha256_file(output),
            validation_ok=True,
            validation_issue_count=0,
            parse_success=True,
            parsed_markdown_sha256="sha256:" + "d" * 64,
            parse_warning_count=0,
            parsed_table_count=1,
        )


def prepare_workspace(root: Path) -> Path:
    source = MARKDOWN.encode()
    (root / "input").mkdir(parents=True)
    (root / "input/document.md").write_bytes(source)
    request = root / "request.json"
    request.write_text(json.dumps(request_value(source), ensure_ascii=False), encoding="utf-8")
    return request


def test_kordoc_contract_is_json_schema_2020_12_and_closed() -> None:
    value = request_value(MARKDOWN.encode())
    validate_contract("kordoc-render-request", value)
    assert KordocRenderRequest.model_validate(value).renderer_profile == "kordoc-markdown-v1"
    value["source"]["file"] = "../document.md"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("kordoc-render-request", value)
    value = request_value(MARKDOWN.encode())
    value["renderer_dependency"]["version"] = "latest"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("kordoc-render-request", value)


def test_kordoc_result_contract_couples_status_to_materialization() -> None:
    failed = {
        "schema_version": "1.0",
        "renderer_profile": "kordoc-markdown-v1",
        "build_id": "hwpxbuild_" + "a" * 32,
        "source_artifact_id": "artifact_" + "b" * 32,
        "source_artifact_revision_id": "rev_" + "c" * 32,
        "source_sha256": "sha256:" + "d" * 64,
        "renderer_version": "0.1.0",
        "kordoc_version": "4.9.0",
        "status": "FAILED",
        "output_file": None,
        "output_sha256": None,
        "package_manifest_file": None,
        "validation_report_file": None,
        "renderer_report_file": None,
        "native_equation_count": 0,
        "native_table_count": 0,
        "warnings": [],
        "errors": ["HWPX_KORDOC_RENDER_FAILED"],
        "started_at": "2026-08-21T00:00:00Z",
        "completed_at": "2026-08-21T00:00:01Z",
    }
    validate_contract("kordoc-build-result", failed)
    KordocBuildResult.model_validate(failed)
    failed["output_file"] = "output/kordoc_document.hwpx"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("kordoc-build-result", failed)
    with pytest.raises(ValueError):
        KordocBuildResult.model_validate(failed)


@pytest.mark.parametrize(
    "markdown",
    [
        "<script>bad</script>",
        "![image](https://example.invalid/a.png)",
        "[link](https://example.invalid)",
        "$$\\input{secret}$$",
        "$$\\begin{document}x\\end{document}$$",
        "$$\\begin{pmatrix}a & b\\end{bmatrix}$$",
        "$$\nE=mc^2\n$$",
        "| A | B |\n| --- | --- |\n",
        "bad\x01text",
    ],
)
def test_kordoc_markdown_rejects_unsafe_or_out_of_profile_input(markdown: str) -> None:
    with pytest.raises(HwpxError) as caught:
        inspect_kordoc_markdown(markdown.encode())
    assert caught.value.code == HwpxErrorCode.HWPX_KORDOC_MARKDOWN_UNSAFE


def test_kordoc_markdown_accepts_documented_science_equation_subset() -> None:
    value = (
        "$$\\left(\\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}\\right)$$\n\n"
        "$$\\begin{bmatrix}\\alpha & \\Delta \\\\ \\int_0^T F(t)\\,dt & \\infty"
        "\\end{bmatrix}$$\n"
    )
    profile = inspect_kordoc_markdown(value.encode())
    assert profile.display_equation_count == 2
    assert profile.table_count == 0


def test_kordoc_renderer_preserves_template_validator_and_is_deterministic(tmp_path: Path) -> None:
    first_request = prepare_workspace(tmp_path / "first")
    second_request = prepare_workspace(tmp_path / "second")
    first_runtime = FakeKordocRuntime(timestamp=(2026, 8, 21, 1, 2, 4))
    second_runtime = FakeKordocRuntime(timestamp=(2026, 8, 21, 1, 4, 6))

    first = render_kordoc_workspace(
        first_request, first_request.parent / "result.json", runtime=first_runtime
    )
    second = render_kordoc_workspace(
        second_request,
        second_request.parent / "result.json",
        runtime=second_runtime,
    )
    first_output = first_request.parent / str(first.output_file)
    second_output = second_request.parent / str(second.output_file)

    assert first.status == "PENDING_MANUAL_HANCOM_VALIDATION"
    assert first.native_equation_count == 1
    assert first.native_table_count == 1
    assert first.output_sha256 == second.output_sha256
    assert first_output.read_bytes() == second_output.read_bytes()
    assert (
        validate_kordoc_structure(
            first_output, expected_equation_count=1, expected_table_count=1
        ).status
        == "PASS"
    )
    assert validate_structure(first_output).status == "FAIL"
    assert first_runtime.calls == second_runtime.calls == 1


def test_kordoc_renderer_fails_before_runtime_on_declared_count_mismatch(tmp_path: Path) -> None:
    request = prepare_workspace(tmp_path / "workspace")
    value = json.loads(request.read_text())
    value["expected_structure"]["display_equation_count"] = 2
    request.write_text(json.dumps(value), encoding="utf-8")
    runtime = FakeKordocRuntime(timestamp=(2026, 8, 21, 1, 2, 4))
    with pytest.raises(HwpxError) as caught:
        render_kordoc_workspace(request, request.parent / "result.json", runtime=runtime)
    assert caught.value.code == HwpxErrorCode.HWPX_KORDOC_MARKDOWN_UNSAFE
    assert runtime.calls == 0


def test_canonicalizer_removes_zip_timestamp_variance(tmp_path: Path) -> None:
    sources = []
    for index, timestamp in enumerate(((2026, 8, 21, 1, 2, 4), (2026, 8, 21, 1, 4, 6))):
        source = tmp_path / f"source-{index}.hwpx"
        with zipfile.ZipFile(source, "w") as archive:
            for name, data, compression in kordoc_like_parts():
                info = zipfile.ZipInfo(name, timestamp)
                info.compress_type = compression
                archive.writestr(info, data)
        sources.append(source)
    first = tmp_path / "first.hwpx"
    second = tmp_path / "second.hwpx"
    canonicalize_package(sources[0], first)
    canonicalize_package(sources[1], second)
    assert first.read_bytes() == second.read_bytes()


def test_runtime_uses_fixed_node_bridge_and_sanitized_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = tmp_path / "node"
    node.write_text("fixed", encoding="utf-8")
    node.chmod(0o700)
    runtime_root = tmp_path / "runtime"
    (runtime_root / "node_modules/kordoc").mkdir(parents=True)
    (runtime_root / "package.json").write_text("{}", encoding="utf-8")
    lock_source = (
        Path(__file__).resolve().parents[2]
        / "services/hwpx_builder/kordoc_runtime/package-lock.json"
    )
    (runtime_root / "package-lock.json").write_bytes(lock_source.read_bytes())
    (runtime_root / "node_modules/kordoc/package.json").write_text(
        '{"name":"kordoc","version":"4.9.0"}\n', encoding="utf-8"
    )
    observed: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        observed.update({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=b'{"status":"READY","node_major":20,"kordoc_version":"4.9.0","offline_required":true}\n',
            stderr=b"",
        )

    monkeypatch.setattr("eom_hwpx_builder.kordoc_runtime.subprocess.run", fake_run)
    capability = KordocRuntime(
        KordocRuntimeSettings(node_binary=node, runtime_root=runtime_root, home=tmp_path)
    ).capabilities()
    assert capability.status == "READY"
    assert observed["argv"][0] == str(node.resolve())
    assert observed["argv"][-1] == "--capabilities"
    assert observed["env"] == {
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin",
        "KORDOC_OFFLINE": "1",
        "EOM_KORDOC_RUNTIME": str(runtime_root.resolve()),
    }
    assert "shell" not in observed


def test_runtime_fails_closed_without_node_and_does_not_expose_details(tmp_path: Path) -> None:
    runtime = KordocRuntime(
        KordocRuntimeSettings(
            node_binary=tmp_path / "missing-node",
            runtime_root=tmp_path / "missing-runtime",
            home=tmp_path,
        )
    )
    with pytest.raises(HwpxError) as caught:
        runtime.capabilities()
    assert caught.value.code == HwpxErrorCode.HWPX_KORDOC_RUNTIME_UNAVAILABLE
    assert "missing-node" not in str(caught.value)


def test_runtime_fails_closed_when_pinned_lock_integrity_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = tmp_path / "node"
    node.write_text("fixed", encoding="utf-8")
    node.chmod(0o700)
    runtime_root = tmp_path / "runtime"
    (runtime_root / "node_modules/kordoc").mkdir(parents=True)
    (runtime_root / "package.json").write_text("{}", encoding="utf-8")
    (runtime_root / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (runtime_root / "node_modules/kordoc/package.json").write_text(
        '{"name":"kordoc","version":"4.9.0"}\n', encoding="utf-8"
    )
    called = False

    def unexpected_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        nonlocal called
        called = True
        raise AssertionError("Node must not run after an integrity mismatch")

    monkeypatch.setattr("eom_hwpx_builder.kordoc_runtime.subprocess.run", unexpected_run)
    runtime = KordocRuntime(
        KordocRuntimeSettings(node_binary=node, runtime_root=runtime_root, home=tmp_path)
    )
    with pytest.raises(HwpxError) as caught:
        runtime.capabilities()
    assert caught.value.code == HwpxErrorCode.HWPX_KORDOC_DEPENDENCY_MISMATCH
    assert not called


def test_release_wiring_pins_node_kordoc_and_fixed_offline_bridge() -> None:
    root = Path(__file__).resolve().parents[2]
    lock = json.loads((root / "services/hwpx_builder/kordoc_runtime/package-lock.json").read_text())
    package = lock["packages"]["node_modules/kordoc"]
    assert sha256_file(root / "services/hwpx_builder/kordoc_runtime/package-lock.json") == (
        "sha256:" + KORDOC_PACKAGE_LOCK_SHA256
    )
    assert package["version"] == "4.9.0"
    assert package["integrity"] == KordocRendererDependency().npm_integrity
    environment = (root / "infra/conda/eom-hwpx.environment.yml").read_text()
    deployment = (root / "scripts/hwpx/deploy_builder.sh").read_text()
    layout_helper = (root / "scripts/hwpx/python_runtime_layout.py").read_text()
    layout_tree = ast.parse(layout_helper)
    bridge = (root / "services/hwpx_builder/eom_hwpx_builder/kordoc_bridge.mjs").read_text()
    package_config = (root / "services/hwpx_builder/pyproject.toml").read_text()
    assert "nodejs=20" in environment
    assert "ci --omit=optional --ignore-scripts" in deployment
    assert '"$NODE" "$NPM" ci' in deployment
    assert '\n"$NPM" ci' not in deployment
    assert "KORDOC_RUNTIME_LAYOUT=PASS" in deployment
    assert "contains an unexpected symbolic link" in deployment
    assert "KORDOC_FAILED" in deployment
    assert "normalize_python_layout" in deployment
    assert "--normalize-python-layout" in deployment
    assert "normalize_node_layout" in deployment
    assert "--normalize-node-layout" in deployment
    assert "normalize_node_libraries" in deployment
    assert "--normalize-node-libraries" in deployment
    assert (
        'PYTHON_LAYOUT_HELPER="$REPOSITORY_ROOT/scripts/hwpx/python_runtime_layout.py"'
        in deployment
    )
    assert '"$PYTHON" "$PYTHON_LAYOUT_HELPER" verify' in deployment
    assert '"$PYTHON" "$PYTHON_LAYOUT_HELPER" normalize' in deployment
    assert '"$PYTHON" "$PYTHON_LAYOUT_HELPER" normalize-node' in deployment
    assert '"$PYTHON" "$PYTHON_LAYOUT_HELPER" normalize-node-libraries' in deployment
    assert (
        "pip install"
        not in deployment.split('if [[ "$MODE" = "normalize-python-layout" ]]', 1)[1].split(
            "exit 0", 1
        )[0]
    )
    assignments = {
        target.id: node.value
        for node in layout_tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance((target := node.targets[0]), ast.Name)
    }
    expected_prefix = assignments["EXPECTED_PREFIX"]
    assert isinstance(expected_prefix, ast.Call)
    assert isinstance(expected_prefix.func, ast.Name)
    assert expected_prefix.func.id == "Path"
    assert len(expected_prefix.args) == 1
    assert isinstance(expected_prefix.args[0], ast.Constant)
    assert expected_prefix.args[0].value == "/srv/eom/conda/envs/eom-hwpx"
    assert any(
        isinstance(node, ast.Constant) and node.value == "bin/eom-hwpx"
        for node in ast.walk(layout_tree)
    )
    assert any(
        isinstance(node, ast.Constant) and node.value == "bin/node"
        for node in ast.walk(layout_tree)
    )
    parser_arguments = [
        node
        for node in ast.walk(layout_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
    ]
    assert len(parser_arguments) == 1
    assert len(parser_arguments[0].args) == 1
    assert isinstance(parser_arguments[0].args[0], ast.Constant)
    assert parser_arguments[0].args[0].value == "action"
    choices = next(
        keyword.value for keyword in parser_arguments[0].keywords if keyword.arg == "choices"
    )
    assert isinstance(choices, ast.Tuple)
    assert [element.value for element in choices.elts if isinstance(element, ast.Constant)] == [
        "verify",
        "normalize",
        "verify-node",
        "normalize-node",
        "verify-node-libraries",
        "normalize-node-libraries",
    ]
    assert "st_nlink" in layout_helper
    assert "os.replace" in layout_helper
    assert "NODE_RUNTIME_LIBRARY_NAMES" in layout_helper
    assert '"libnode.so.115"' in layout_helper
    assert '"libuv.so.1"' in layout_helper
    assert "eom_hwpx_builder/kordoc_bridge.mjs" in deployment
    assert 'KORDOC_OFFLINE !== "1"' in bridge
    assert "process.argv.length === 2" in bridge
    assert "child_process" not in bridge
    assert "eval(" not in bridge
    assert "*.mjs" in package_config
