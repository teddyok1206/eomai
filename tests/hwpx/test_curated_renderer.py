from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from eom_hwpx_builder.curated_renderer import render_curated_workspace
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file
from eom_hwpx_contracts.curated_document import CuratedHwpxRenderResult
from eom_hwpx_contracts.validation import validate_contract
from pydantic import ValidationError

from tests.hwpx.test_curated_native_merge import request_value, source


def workspace(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "workspace"
    root.mkdir(mode=0o700)
    inputs = root / "inputs"
    inputs.mkdir(mode=0o700)
    document = source(inputs, "001.hwpx")
    value = request_value()
    value["segments"][0].update(sha256=sha256_file(document), size_bytes=document.stat().st_size)
    return root, value


def submit(root: Path, value: dict) -> CuratedHwpxRenderResult:
    request = root / "request.json"
    request.write_bytes(canonical_json_bytes(value))
    return render_curated_workspace(request, root / "result.json")


def test_renderer_writes_validated_private_result_and_editable_output(tmp_path: Path) -> None:
    root, value = workspace(tmp_path)
    result = submit(root, value)
    assert result.status == "SUCCEEDED"
    assert result.request_sha256 == sha256_bytes(canonical_json_bytes(value))
    assert result.source_sha256 == (value["segments"][0]["sha256"],)
    output = root / "output/assembled.hwpx"
    assert result.output_sha256 == sha256_file(output)
    assert result.output_size_bytes == output.stat().st_size
    observed = json.loads((root / "result.json").read_bytes())
    validate_contract("curated-render-result", observed)
    assert CuratedHwpxRenderResult.model_validate(observed) == result
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    assert stat.S_IMODE((root / "result.json").stat().st_mode) == 0o640
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o750


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("sha256", "sha256:" + "0" * 64, "HWPX_CURATED_INPUT_CHANGED"),
        ("size_bytes", 12, "HWPX_CURATED_INPUT_INVALID"),
    ],
)
def test_pinned_source_mismatch_produces_failure_without_deliverable(
    tmp_path, field, value, code
) -> None:
    root, request = workspace(tmp_path)
    request["segments"][0][field] = value
    result = submit(root, request)
    assert result.status == "FAILED" and result.failure_code == code
    assert not (root / "output/assembled.hwpx").exists()
    assert result.output_sha256 is None and result.source_sha256 == ()
    validate_contract("curated-render-result", result.model_dump(mode="json"))


def test_native_hwp_is_not_published_using_lossy_or_raster_fallback(tmp_path: Path) -> None:
    root, value = workspace(tmp_path)
    (root / "inputs/001.hwpx").rename(root / "inputs/001.hwp")
    value["segments"][0].update(source_format="HWP", local_file="inputs/001.hwp")
    result = submit(root, value)
    assert result.failure_code == "HWPX_CURATED_FORMAT_UNSUPPORTED"
    assert not (root / "output/assembled.hwpx").exists()


@pytest.mark.parametrize("member", ["inputs", "source", "request", "result"])
def test_symlink_boundaries_and_existing_result_are_not_followed(
    tmp_path: Path, member: str
) -> None:
    root, value = workspace(tmp_path)
    request, result = root / "request.json", root / "result.json"
    request.write_bytes(canonical_json_bytes(value))
    external = tmp_path / "external"
    external.mkdir()
    if member == "inputs":
        (root / "inputs").rename(external / "inputs")
        (root / "inputs").symlink_to(external / "inputs", target_is_directory=True)
    elif member == "source":
        path = root / "inputs/001.hwpx"
        path.rename(external / "source.hwpx")
        path.symlink_to(external / "source.hwpx")
    else:
        target = external / member
        target.write_bytes(b"unaltered outside file")
        if member == "request":
            request.unlink()
            request.symlink_to(target)
        else:
            result.symlink_to(target)
    if member == "source":
        assert render_curated_workspace(request, result).status == "FAILED"
    else:
        with pytest.raises((HwpxError, OSError)):
            render_curated_workspace(request, result)
    if member in {"request", "result"}:
        assert (external / member).read_bytes() == b"unaltered outside file"


def test_repeated_invocation_does_not_overwrite_published_output_or_receipt(tmp_path: Path) -> None:
    root, value = workspace(tmp_path)
    submit(root, value)
    output, receipt = root / "output/assembled.hwpx", root / "result.json"
    before = output.read_bytes(), receipt.read_bytes()
    with pytest.raises(HwpxError):
        render_curated_workspace(root / "request.json", receipt)
    assert before == (output.read_bytes(), receipt.read_bytes())


def test_result_rejects_success_with_missing_source_and_reordered_sections(tmp_path: Path) -> None:
    root, request = workspace(tmp_path)
    value = submit(root, request).model_dump(mode="json")
    value["source_sha256"] *= 2
    value["section_source_positions"] = [2, 1]
    with pytest.raises(ValidationError):
        CuratedHwpxRenderResult.model_validate(value)
    value["source_sha256"] = []
    value["section_source_positions"] = []
    with pytest.raises(ValidationError):
        CuratedHwpxRenderResult.model_validate(value)


def test_result_schema_bytes_are_mirrored() -> None:
    root = Path(__file__).resolve().parents[2]
    filename = "hwpx-curated-render-result-v1.schema.json"
    assert (root / "schemas/hwpx" / filename).read_bytes() == (
        root / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / filename
    ).read_bytes()
