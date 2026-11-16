"""Bounded local render handoff; no authority, publication or browser session input."""

import argparse
import json
import sys
from pathlib import Path

from eom_kakao_archive_contracts import RenderCommand, canonical_bytes
from eom_kakao_archive_contracts.validation import validate_contract

from .question_pdf import render_questions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--renderer-release-sha256", required=True)
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(32769)
    try:
        if len(raw) > 32768:
            raise ValueError("command too large")
        decoded = json.loads(raw)
        validate_contract("command", decoded)
        command = RenderCommand.model_validate(decoded)
        result = render_questions(
            command,
            input_root=args.input_root,
            output_root=args.output_root,
            renderer_release_sha256=args.renderer_release_sha256,
        )
    except Exception:
        # Pydantic/decoder errors can contain source text; return only a stable code.
        sys.stderr.write("KAKAO_RENDER_COMMAND_INVALID\n")
        return 2
    sys.stdout.buffer.write(canonical_bytes(result.model_dump(mode="json")) + b"\n")
    return 0 if result.status == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
