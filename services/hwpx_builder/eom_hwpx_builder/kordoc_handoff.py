"""Kordoc-specific facade over the common private Manager handoff contract."""

from __future__ import annotations

from pathlib import Path

from eom_hwpx_builder.handoff import (
    HANDOFF_DIRECTORY_MODE as HANDOFF_DIRECTORY_MODE,
)
from eom_hwpx_builder.handoff import (
    HANDOFF_FILE_MODE as HANDOFF_FILE_MODE,
)
from eom_hwpx_builder.handoff import (
    finalize_failure_result as finalize_failure_result,
)
from eom_hwpx_builder.handoff import (
    finalize_success_handoff as _finalize_success_handoff,
)
from eom_hwpx_builder.handoff import (
    write_private_json as write_private_json,
)

_OUTPUT_FILE_NAMES = (
    "kordoc_document.hwpx",
    "kordoc-validation.json",
    "package-manifest.json",
    "structural-validation.json",
)


def finalize_success_handoff(workspace: Path, result_path: Path) -> None:
    """Expose only validated Kordoc output to the private Manager handoff group."""

    _finalize_success_handoff(
        workspace,
        result_path,
        output_file_names=_OUTPUT_FILE_NAMES,
    )
