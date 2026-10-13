"""Closed owner leaf; real tool/loader composition is deliberately unavailable.

The stdlib Conda byte audit is callable by an independently admitted owner context.
This standalone CLI cannot manufacture that context from root-owned JSON or an ID.
No installed-prefix imports, filesystem mutations or successor instructions occur.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    flags = {"--profile", "--owner-input", "--owner-input-sha256"}
    if len(arguments) != 7 or arguments[0] != "conda31-bytes" or set(arguments[1::2]) != flags:
        print("EMBEDDING_CONDA_ARGUMENTS_INVALID", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("conda31-bytes",))
    parser.add_argument("--profile", choices=("CPU_INDEX_FP32", "CUDA_INDEX_FP32"), required=True)
    parser.add_argument("--owner-input", required=True)
    parser.add_argument("--owner-input-sha256", required=True)
    try:
        args = parser.parse_args(arguments)
    except SystemExit:
        print("EMBEDDING_CONDA_ARGUMENTS_INVALID", file=sys.stderr)
        return 1
    if (
        re.fullmatch(
            r"/opt/eom/\.embedding-index-install-[A-Za-z0-9]{8}/conda31-audit-input\.json",
            args.owner_input,
        )
        is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", args.owner_input_sha256) is None
    ):
        print("EMBEDDING_CONDA_ARGUMENTS_INVALID", file=sys.stderr)
        return 1
    if (
        os.geteuid() != 0
        or Path(sys.prefix) != Path("/opt/eom/conda/envs/eom-embedding-experiment")
        or sys.version_info[:3] != (3, 12, 13)
        or not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode)
    ):
        print("EMBEDDING_CONDA_OWNER_UNAVAILABLE", file=sys.stderr)
        return 1
    # No source/input import or tool subprocess before a genuinely captured handle.
    # The later reviewed OS closure owner must wire that mandatory port explicitly.
    print("INSTALLED_RUNTIME_CONDA_TOOL_UNAVAILABLE", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
