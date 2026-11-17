"""Installed fixed-unit entry point; no caller-controlled argv paths or authority."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path

from eom_kakao_archive_contracts import canonical_bytes
from eom_kakao_archive_contracts.pdf_contracts import parse_pdf_command

from .local_members import directory_descriptor, write_member
from .rendering import render_pdf

RUNTIME_ROOT = Path("/run/eom-kakao-render")


def main() -> int:
    try:
        if len(sys.argv) != 2 or re.fullmatch(r"kakaoattempt_[0-9a-f]{32}", sys.argv[1]) is None:
            raise ValueError("invalid attempt")
        release = os.environ.get("EOM_KAKAO_RENDER_RELEASE_SHA256", "")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", release) is None:
            raise ValueError("missing installed release")
        workspace = RUNTIME_ROOT / sys.argv[1]
        with directory_descriptor(workspace / "input") as directory:
            fd = os.open(
                "request.json",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=directory,
            )
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_mode & 0o022
                or not 0 < info.st_size <= 32768
            ):
                raise ValueError("unsafe request")
            raw = stream.read(32769)
        if len(raw) > 32768:
            raise ValueError("request too large")
        command = parse_pdf_command(json.loads(raw))
        if command.execution.attempt_id != sys.argv[1]:
            raise ValueError("attempt mismatch")
        result = render_pdf(
            command,
            input_root=workspace / "input",
            output_root=workspace / "output",
            renderer_release_sha256=release,
        )
        # A terminal review refusal is a valid execution receipt, not process failure.
        write_member(
            workspace / "output",
            "result.json",
            canonical_bytes(result.model_dump(mode="json")),
            "application/json",
        )
        return 0
    except Exception:
        sys.stderr.write("KAKAO_RENDER_FIXED_EXECUTION_FAILED\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
