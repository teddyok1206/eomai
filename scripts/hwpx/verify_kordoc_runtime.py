#!/srv/eom/conda/envs/eom-hwpx/bin/python
"""Run one disposable, offline Kordoc conversion without creating an application build."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from eom_hwpx_builder.kordoc_markdown import inspect_kordoc_markdown
from eom_hwpx_builder.kordoc_runtime import KordocRuntime
from eom_hwpx_builder.validation import (
    classify_kordoc_native_structure,
    validate_kordoc_structure,
)

FIXTURE = Path("/home/eom/EOM/tests/fixtures/hwpx/kordoc-runtime-smoke.md")
EXPECTED_RESULT = {
    "content_tables": 1,
    "equations": 1,
    "kordoc_version": "4.9.0",
    "layout_tables": 1,
    "status": "PASS",
    "total_tables": 2,
}


def main() -> None:
    source = FIXTURE.read_bytes()
    profile = inspect_kordoc_markdown(source)
    previous_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix="eom-kordoc-runtime-smoke-", dir="/tmp") as root:
            workspace = Path(root)
            input_directory = workspace / "input"
            input_directory.mkdir(mode=0o700)
            (input_directory / "document.md").write_bytes(source)
            report = KordocRuntime().render(workspace, "report")
            output = workspace / ".kordoc-generated.hwpx"
            counts = classify_kordoc_native_structure(
                output,
                kordoc_version=report.kordoc_version,
                gongmun_preset="report",
            )
            validation = validate_kordoc_structure(
                output,
                expected_equation_count=profile.display_equation_count,
                expected_table_count=profile.table_count,
                kordoc_version=report.kordoc_version,
                gongmun_preset="report",
            )
            if validation.status != "PASS":
                raise SystemExit("KORDOC_RUNTIME_SMOKE_VALIDATION_FAILED")
            result = {
                "content_tables": counts.content_native_table_count,
                "equations": counts.native_equation_count,
                "kordoc_version": report.kordoc_version,
                "layout_tables": counts.layout_native_table_count,
                "status": "PASS",
                "total_tables": counts.total_native_table_count,
            }
            if result != EXPECTED_RESULT:
                raise SystemExit("KORDOC_RUNTIME_SMOKE_CONTRACT_MISMATCH")
            print(json.dumps(result, sort_keys=True))
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    main()
