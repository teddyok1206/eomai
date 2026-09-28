"""Command-line boundary for one isolated candidate probe."""

from __future__ import annotations

import argparse
import fcntl
import os
import stat
from pathlib import Path

from eom_image_candidate_runner.backend import Flux2KleinBackend
from eom_image_candidate_runner.runner import CandidateRunnerError, load_probe_command, run_probe


def _lock_gpu(path: Path) -> int:
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise CandidateRunnerError("FLUX2_PROBE_GPU_UNAVAILABLE") from exc
    if (
        not path.is_absolute()
        or path.parent.is_symlink()
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise CandidateRunnerError("FLUX2_PROBE_GPU_UNAVAILABLE")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
        ):
            raise CandidateRunnerError("FLUX2_PROBE_GPU_UNAVAILABLE")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor
    except (BlockingIOError, OSError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise CandidateRunnerError("FLUX2_PROBE_GPU_UNAVAILABLE") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--gpu-lock", required=True, type=Path)
    args = parser.parse_args()
    descriptor: int | None = None
    try:
        command = load_probe_command(args.command)
        descriptor = _lock_gpu(args.gpu_lock)
        result = run_probe(workspace=args.workspace, command=command, backend=Flux2KleinBackend())
    except CandidateRunnerError as exc:
        raise SystemExit(exc.code) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if result.status != "SUCCEEDED":
        raise SystemExit(result.error_code or "FLUX2_PROBE_EXEC_FAILED")


if __name__ == "__main__":
    main()
