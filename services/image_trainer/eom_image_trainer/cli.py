"""CLI boundary for one isolated local-image training job."""

from __future__ import annotations

import argparse
import fcntl
import os
import signal
import stat
from pathlib import Path

from eom_image_provider.provider import verify_model_revision

from eom_image_trainer.crop_locator_runner import (
    CropLocatorRunnerError,
    load_crop_locator_command,
    run_crop_locator_command,
)
from eom_image_trainer.diffusers_backend import Ssd1bLoraBackend
from eom_image_trainer.micro_evaluation_runner import (
    MicroEvaluationRunnerError,
    Ssd1bMicroEvaluationBackend,
    load_micro_evaluation_command,
    run_micro_evaluation_command,
)
from eom_image_trainer.micro_probe_runner import (
    MicroProbeRunnerError,
    load_micro_probe_command,
    run_micro_probe_command,
)
from eom_image_trainer.runner import (
    TrainingRunnerError,
    load_training_command,
    run_training_command,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="operation", required=True)
    train = subcommands.add_parser("train")
    train.add_argument("--command", required=True, type=Path)
    train.add_argument("--model-store-root", required=True, type=Path)
    train.add_argument("--workspace", required=True, type=Path)
    train.add_argument("--gpu-lock", required=True, type=Path)
    micro = subcommands.add_parser("micro-probe")
    micro.add_argument("--command", required=True, type=Path)
    micro.add_argument("--model-store-root", required=True, type=Path)
    micro.add_argument("--workspace", required=True, type=Path)
    micro.add_argument("--gpu-lock", required=True, type=Path)
    evaluate = subcommands.add_parser("evaluate-micro-probe")
    evaluate.add_argument("--command", required=True, type=Path)
    evaluate.add_argument("--model-store-root", required=True, type=Path)
    evaluate.add_argument("--workspace", required=True, type=Path)
    evaluate.add_argument("--gpu-lock", required=True, type=Path)
    locate = subcommands.add_parser("locate-crops")
    locate.add_argument("--command", required=True, type=Path)
    locate.add_argument("--workspace", required=True, type=Path)
    return parser


def _lock_gpu(path: Path) -> int:
    if not path.is_absolute():
        raise TrainingRunnerError("IMAGE_TRAINING_GPU_LOCK_INVALID")
    try:
        parent_metadata = path.parent.lstat()
    except OSError as exc:
        raise TrainingRunnerError("IMAGE_TRAINING_GPU_LOCK_INVALID") from exc
    if (
        path.parent.is_symlink()
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
    ):
        raise TrainingRunnerError("IMAGE_TRAINING_GPU_LOCK_INVALID")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o660,
        )
        metadata = os.fstat(descriptor)
        os.fchmod(descriptor, 0o600)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600
        ):
            raise TrainingRunnerError("IMAGE_TRAINING_GPU_LOCK_INVALID")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor
    except BlockingIOError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise TrainingRunnerError("IMAGE_TRAINING_GPU_BUSY") from exc
    except TrainingRunnerError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise TrainingRunnerError("IMAGE_TRAINING_GPU_LOCK_INVALID") from exc


def main() -> None:
    args = _parser().parse_args()
    if args.operation == "locate-crops":
        try:
            locator_command = load_crop_locator_command(args.command)
            if args.workspace.name != locator_command.locator_run_id:
                raise CropLocatorRunnerError("IMAGE_TRAINING_WORKSPACE_ID_MISMATCH")
            locator_result = run_crop_locator_command(
                workspace=args.workspace,
                command=locator_command,
            )
        except CropLocatorRunnerError as exc:
            raise SystemExit(exc.code) from exc
        if locator_result.status != "SUCCEEDED":
            raise SystemExit(locator_result.error_code or "IMAGE_TRAINING_CROP_LOCATOR_FAILED")
        return
    if args.operation == "evaluate-micro-probe":
        evaluation_command = load_micro_evaluation_command(args.command)
        if args.workspace.name != evaluation_command.evaluation_run_id:
            raise SystemExit("IMAGE_EVALUATION_WORKSPACE_ID_MISMATCH")
        lock_descriptor = _lock_gpu(args.gpu_lock)
        try:
            evaluation_result = run_micro_evaluation_command(
                workspace=args.workspace,
                model_store_root=args.model_store_root,
                command=evaluation_command,
                backend=Ssd1bMicroEvaluationBackend(),
                model_resolver=verify_model_revision,
            )
        except (TrainingRunnerError, MicroEvaluationRunnerError) as exc:
            raise SystemExit(exc.code) from exc
        finally:
            os.close(lock_descriptor)
        if evaluation_result.status != "SUCCEEDED":
            raise SystemExit(evaluation_result.error_code or "IMAGE_EVALUATION_EXEC_FAILED")
        return
    if args.operation == "micro-probe":
        micro_command = load_micro_probe_command(args.command)
        if args.workspace.name != micro_command.training_run_id:
            raise SystemExit("IMAGE_TRAINING_WORKSPACE_ID_MISMATCH")
        lock_descriptor = _lock_gpu(args.gpu_lock)
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def _cancel_micro(_signum: int, _frame: object) -> None:
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, _cancel_micro)
        try:
            micro_result = run_micro_probe_command(
                workspace=args.workspace,
                model_store_root=args.model_store_root,
                command=micro_command,
                backend=Ssd1bLoraBackend(),
                model_resolver=verify_model_revision,
            )
        except (TrainingRunnerError, MicroProbeRunnerError) as exc:
            raise SystemExit(exc.code) from exc
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
            os.close(lock_descriptor)
        if micro_result.status != "SUCCEEDED":
            raise SystemExit(micro_result.error_code or "IMAGE_TRAINING_EXEC_FAILED")
        return
    training_command = load_training_command(args.command)
    if args.workspace.name != training_command.training_run_id:
        raise SystemExit("IMAGE_TRAINING_WORKSPACE_ID_MISMATCH")
    lock_descriptor = _lock_gpu(args.gpu_lock)
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def _cancel(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _cancel)
    try:
        training_result = run_training_command(
            workspace=args.workspace,
            model_store_root=args.model_store_root,
            command=training_command,
            backend=Ssd1bLoraBackend(),
            model_resolver=verify_model_revision,
        )
    except TrainingRunnerError as exc:
        raise SystemExit(exc.code) from exc
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        os.close(lock_descriptor)
    if training_result.status != "SUCCEEDED":
        raise SystemExit(training_result.error_code or "IMAGE_TRAINING_EXEC_FAILED")


if __name__ == "__main__":
    main()
