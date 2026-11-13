"""Fixed systemd workspace wrapper; only the installed native CPU parser handles untrusted bytes."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from eom_hwpx_contracts.native_exam_preparation import (
    NATIVE_EXAM_REQUEST_LIMIT,
    NATIVE_EXAM_SOURCE_LIMIT,
    NATIVE_EXAM_ZIP_LIMIT,
    NativeExamFilePreparationRequest,
)
from eom_hwpx_contracts.validation import parse_json_object
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.native_exam_preparation import require_native_exam_runtime_python

from eom_catalog_service.native_exam_preparer import (
    NATIVE_EXAM_WORKER_ROOT,
    native_exam_workspace_principals,
    read_native_exam_workspace_file,
    require_native_exam_workspace,
)


def prepare_workspace(
    instance: str,
    *,
    root: Path = NATIVE_EXAM_WORKER_ROOT,
    python: Path,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> Path:
    principals = native_exam_workspace_principals()
    if os.geteuid() != principals.worker_uid or os.getegid() != principals.group_gid:
        raise ValueError("NATIVE_EXAM_PREPARER_IDENTITY_INVALID")
    workspace = require_native_exam_workspace(
        root,
        instance,
        root_owner_uid=principals.worker_uid,
        workspace_owner_uid=principals.manager_uid,
        group_gid=principals.group_gid,
    )
    executable = require_native_exam_runtime_python(python)

    def read_input(name: str, maximum: int) -> bytes:
        return read_native_exam_workspace_file(
            workspace / name,
            maximum=maximum,
            owner_uid=principals.manager_uid,
            group_gid=principals.group_gid,
        )

    raw = read_input("request.json", NATIVE_EXAM_REQUEST_LIMIT)
    request = NativeExamFilePreparationRequest.model_validate(parse_json_object(raw))
    if canonical_json_bytes(request.model_dump(mode="json")) != raw:
        raise ValueError("NATIVE_EXAM_PREPARER_REQUEST_NONCANONICAL")
    source = read_input("input.native", NATIVE_EXAM_SOURCE_LIMIT)
    if sha256_bytes(source) != request.expected_source_sha256:
        raise ValueError("NATIVE_EXAM_PREPARATION_SOURCE_CHANGED")
    temporary = workspace / "result.partial"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    os.fchmod(descriptor, 0o640)
    with (
        os.fdopen(descriptor, "wb") as output,
        tempfile.TemporaryDirectory(prefix="native-exam-home-") as home,
    ):
        completed = run(
            [
                str(executable),
                "-I",
                "-B",
                "-m",
                "eom_hwpx_builder.native_exam_tool",
                "--request-json",
                raw.decode("utf-8"),
            ],
            input=source,
            stdout=output,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=105.0,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "TZ": "UTC",
                "HOME": home,
                "CUDA_VISIBLE_DEVICES": "",
            },
        )
    if completed.returncode:
        raise ValueError("NATIVE_EXAM_PREPARER_TOOL_FAILED")
    if not 0 < temporary.stat().st_size <= NATIVE_EXAM_ZIP_LIMIT:
        raise ValueError("NATIVE_EXAM_PREPARER_RESULT_SIZE_INVALID")
    if (
        read_input("request.json", NATIVE_EXAM_REQUEST_LIMIT) != raw
        or read_input("input.native", NATIVE_EXAM_SOURCE_LIMIT) != source
    ):
        raise ValueError("NATIVE_EXAM_PREPARER_INPUT_CHANGED")
    result = workspace / "result.zip"
    os.link(temporary, result, follow_symlinks=False)
    temporary.unlink()
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if len(arguments) != 1:
            raise ValueError("NATIVE_EXAM_PREPARER_INSTANCE_INVALID")
        tool = os.environ.get("EOM_NATIVE_EXAM_TOOL_PYTHON", "")
        if not tool:
            raise ValueError("NATIVE_EXAM_PREPARER_RUNTIME_MISSING")
        os.umask(0o077)
        prepare_workspace(arguments[0], python=Path(tool))
        return 0
    except Exception:
        # Original content, converter diagnostics and credentials never enter journald.
        print("native_exam_preparer=FAILED code=NATIVE_EXAM_PREPARER_FAILED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
