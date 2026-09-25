"""Isolated PDF rendering and conservative visual discovery for the science corpus pilot.

The runner reads one schema-validated command and an orchestrator-staged workspace. It performs
one bounded PDF render per source, one OCR/localization pass per rendered page, writes canonical
page/crop members with exclusive creation, and emits one typed result. It never reads PostgreSQL,
NAS, Git, or the network and never decides that a crop is eligible for training.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import warnings
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath

from eom_image_contracts import (
    LocalImageScienceCorpusVisualPilotCommand,
    LocalImageScienceCorpusVisualPilotPlan,
    LocalImageScienceCorpusVisualPilotResult,
    ScienceVisualCandidate,
    ScienceVisualOmission,
    ScienceVisualPageImage,
    ScienceVisualPilotRuntime,
    content_sha256,
    validate_contract,
    validate_science_visual_pilot_command,
    validate_science_visual_pilot_result,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from PIL import Image, ImageDraw, UnidentifiedImageError  # type: ignore[import-not-found]
from pydantic import ValidationError as PydanticValidationError

from eom_image_trainer.crop_locator import (
    CropLocatorError,
    LocatedVisualRegion,
    locate_visual_regions,
    run_tesseract,
)

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_PNG_BYTES = 64 * 1024 * 1024
MAX_PAGE_PIXELS = 100_000_000
PDFTOPPM = Path("/usr/bin/pdftoppm")
TESSERACT = Path("/usr/bin/tesseract")


class ScienceCorpusVisualRunnerError(RuntimeError):
    """Stable fail-closed worker boundary error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_JSON_INVALID")
        value[key] = item
    return value


def _parse_json(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_JSON_INVALID")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_JSON_INVALID")
    return value


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _require_workspace(workspace: Path) -> None:
    if not workspace.is_absolute():
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_WORKSPACE_INVALID")
    try:
        metadata = workspace.lstat()
    except OSError as exc:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_WORKSPACE_INVALID") from exc
    if (
        workspace.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_WORKSPACE_INVALID")


def _member_path(workspace: Path, member: str, *, require_exists: bool = True) -> Path:
    relative = PurePosixPath(member)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_MEMBER_PATH_INVALID")
    current = workspace
    for part in relative.parts:
        current /= part
        if not require_exists and current == workspace / relative:
            break
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_INPUT_MISSING") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_INPUT_INVALID")
    return current


def _read_regular(
    path: Path,
    *,
    maximum_bytes: int,
    expected_sha256: str | None,
    expected_bytes: int | None = None,
) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_INPUT_MISSING") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
            or (expected_bytes is not None and before.st_size != expected_bytes)
        ):
            raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_INPUT_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_INPUT_TRUNCATED")
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_INPUT_CHANGED")
    finally:
        os.close(descriptor)
    body = bytes(payload)
    if expected_sha256 is not None and (
        "sha256:" + hashlib.sha256(body).hexdigest() != expected_sha256
    ):
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_INPUT_HASH_MISMATCH")
    return body


def _write_exclusive(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_OUTPUT_EXISTS") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def _make_output_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
    except OSError as exc:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_OUTPUT_EXISTS") from exc


def _sha256_file(path: Path) -> str:
    payload = _read_regular(path, maximum_bytes=256 * 1024 * 1024, expected_sha256=None)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _tool_version(executable: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            [str(executable), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_TOOL_INVALID") from exc
    if completed.returncode != 0 or len(completed.stdout) > 64 * 1024:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_TOOL_INVALID")
    try:
        first_line = completed.stdout.decode("utf-8", errors="strict").splitlines()[0].strip()
    except (IndexError, UnicodeError) as exc:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_TOOL_INVALID") from exc
    return first_line


def _verify_tools(plan: LocalImageScienceCorpusVisualPilotPlan) -> tuple[str, str]:
    pdftoppm_version = _tool_version(PDFTOPPM, "-v")
    tesseract_version = _tool_version(TESSERACT, "--version")
    if (
        _sha256_file(PDFTOPPM) != plan.tools.pdftoppm.sha256
        or _sha256_file(TESSERACT) != plan.tools.tesseract.sha256
        or pdftoppm_version != plan.tools.pdftoppm.version
        or tesseract_version != plan.tools.tesseract.version
    ):
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_TOOL_DRIFT")
    return pdftoppm_version, tesseract_version


def load_command(path: Path) -> LocalImageScienceCorpusVisualPilotCommand:
    value = _parse_json(_read_regular(path, maximum_bytes=MAX_JSON_BYTES, expected_sha256=None))
    try:
        validate_contract("science-corpus-visual-pilot-command", value)
        return LocalImageScienceCorpusVisualPilotCommand.model_validate(value)
    except (JsonSchemaValidationError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_COMMAND_INVALID") from exc


def _load_plan(
    workspace: Path,
    command: LocalImageScienceCorpusVisualPilotCommand,
) -> LocalImageScienceCorpusVisualPilotPlan:
    value = _parse_json(
        _read_regular(
            _member_path(workspace, command.staged_plan_member),
            maximum_bytes=MAX_JSON_BYTES,
            expected_sha256=command.plan.sha256,
        )
    )
    try:
        validate_contract("science-corpus-visual-pilot-plan", value)
        plan = LocalImageScienceCorpusVisualPilotPlan.model_validate(value)
        validate_science_visual_pilot_command(plan, command)
        return plan
    except (JsonSchemaValidationError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_PLAN_INVALID") from exc


def _decode_png(payload: bytes) -> Image.Image:
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as source:
                if source.format != "PNG" or getattr(source, "n_frames", 1) != 1:
                    raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_PAGE_INVALID")
                source.load()
                return source.convert("RGB")
    except ScienceCorpusVisualRunnerError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_PAGE_TOO_LARGE") from exc
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_PAGE_INVALID") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def _render_pdf(pdf_path: Path, *, expected_pages: int, dpi: int) -> tuple[bytes, ...]:
    temporary = Path(tempfile.mkdtemp(prefix="science-visual-render-"))
    try:
        os.chmod(temporary, 0o700)
        prefix = temporary / "page"
        try:
            completed = subprocess.run(
                [str(PDFTOPPM), "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=max(120, expected_pages * 45),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_PAGE_RENDER_FAILED") from exc
        if completed.returncode != 0:
            raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_PAGE_RENDER_FAILED")
        expected_names = tuple(f"page-{page}.png" for page in range(1, expected_pages + 1))
        actual_names = tuple(sorted(value.name for value in temporary.iterdir()))
        if actual_names != tuple(sorted(expected_names)):
            raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_PAGE_COUNT_MISMATCH")
        return tuple(
            _read_regular(
                temporary / name,
                maximum_bytes=MAX_PNG_BYTES,
                expected_sha256=None,
            )
            for name in expected_names
        )
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _pixel_box(
    region: LocatedVisualRegion,
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    box = region.crop_bounding_box
    return (
        max(0, box.left * width // 10_000),
        max(0, box.top * height // 10_000),
        min(width, (box.right * width + 9_999) // 10_000),
        min(height, (box.bottom * height + 9_999) // 10_000),
    )


def _redacted_crop(page: Image.Image, region: LocatedVisualRegion) -> bytes:
    crop_box = _pixel_box(region, width=page.width, height=page.height)
    crop = page.crop(crop_box).convert("L")
    drawing = ImageDraw.Draw(crop)
    for redaction in region.redaction_boxes:
        left = max(0, redaction.left * page.width // 10_000 - crop_box[0])
        top = max(0, redaction.top * page.height // 10_000 - crop_box[1])
        right = min(
            crop.width,
            (redaction.right * page.width + 9_999) // 10_000 - crop_box[0],
        )
        bottom = min(
            crop.height,
            (redaction.bottom * page.height + 9_999) // 10_000 - crop_box[1],
        )
        if left < right and top < bottom:
            drawing.rectangle((left, top, right, bottom), fill=255)
    output = io.BytesIO()
    crop.save(output, format="PNG", optimize=False)
    return output.getvalue()


def _candidate(
    *,
    document_id: str,
    physical_page: int,
    page_sha256: str,
    region: LocatedVisualRegion,
    crop_payload: bytes,
) -> ScienceVisualCandidate:
    body = {
        "document_id": document_id,
        "physical_page": physical_page,
        "page_image_sha256": page_sha256,
        "bounding_box": region.crop_bounding_box.model_dump(mode="json"),
        "representation_kind": "UNKNOWN",
        "rendering_mode": "MIXED",
        "visual_features": (),
        "authority_class": "UNKNOWN_REVIEW_REQUIRED",
        "review_state": "PENDING",
        "locator_score_milli": max(1, min(1000, region.ink_fraction_milli)),
    }
    identity = content_sha256(body).removeprefix("sha256:")
    candidate_id = "imgsciviscandidate_" + identity[:32]
    return ScienceVisualCandidate.model_validate(
        {
            "candidate_id": candidate_id,
            **body,
            "member_path": f"crops/{candidate_id}.png",
            "sha256": "sha256:" + hashlib.sha256(crop_payload).hexdigest(),
            "size_bytes": len(crop_payload),
        }
    )


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "not-installed"


def run_science_corpus_visual_pilot(
    *,
    workspace: Path,
    command_path: Path,
    now: datetime | None = None,
) -> LocalImageScienceCorpusVisualPilotResult:
    _require_workspace(workspace)
    command = load_command(command_path)
    plan = _load_plan(workspace, command)
    pdftoppm_version, tesseract_version = _verify_tools(plan)
    started_at = now or datetime.now(UTC)
    if started_at.tzinfo != UTC:
        raise ScienceCorpusVisualRunnerError("SCIENCE_VISUAL_PILOT_TIMESTAMP_INVALID")

    # Validate the complete immutable input population before creating any output member.
    for source in command.staged_sources:
        _read_regular(
            _member_path(workspace, source.staged_pdf_member),
            maximum_bytes=MAX_PDF_BYTES,
            expected_sha256=source.sha256,
            expected_bytes=source.bytes,
        )

    pages_root = workspace / "pages"
    crops_root = workspace / "crops"
    manifests_root = workspace / "manifests"
    _make_output_directory(pages_root)
    _make_output_directory(crops_root)
    _make_output_directory(manifests_root)

    page_images: list[ScienceVisualPageImage] = []
    candidates: list[ScienceVisualCandidate] = []
    omissions: list[ScienceVisualOmission] = []
    crop_hashes: set[str] = set()

    for source in command.staged_sources:
        pdf_path = _member_path(workspace, source.staged_pdf_member)
        _read_regular(
            pdf_path,
            maximum_bytes=MAX_PDF_BYTES,
            expected_sha256=source.sha256,
            expected_bytes=source.bytes,
        )
        rendered_pages = _render_pdf(
            pdf_path,
            expected_pages=source.page_count,
            dpi=plan.page_render_dpi,
        )
        document_root = pages_root / source.document_id
        _make_output_directory(document_root)
        for page_number, page_payload in enumerate(rendered_pages, start=1):
            page_member = f"pages/{source.document_id}/page-{page_number}.png"
            page_path = _member_path(workspace, page_member, require_exists=False)
            _write_exclusive(page_path, page_payload)
            page = _decode_png(page_payload)
            page_sha256 = "sha256:" + hashlib.sha256(page_payload).hexdigest()
            page_images.append(
                ScienceVisualPageImage(
                    document_id=source.document_id,
                    physical_page=page_number,
                    member_path=page_member,
                    sha256=page_sha256,
                    size_bytes=len(page_payload),
                    width_px=page.width,
                    height_px=page.height,
                )
            )
            try:
                regions = locate_visual_regions(
                    page,
                    context_bounding_box=None,
                    ocr_boxes=run_tesseract(page, executable=TESSERACT),
                )
            except CropLocatorError as exc:
                raise ScienceCorpusVisualRunnerError(exc.code) from exc
            accepted_on_page = 0
            for region in regions:
                if len(candidates) >= plan.max_visual_candidates:
                    break
                crop_payload = _redacted_crop(page, region)
                candidate = _candidate(
                    document_id=source.document_id,
                    physical_page=page_number,
                    page_sha256=page_sha256,
                    region=region,
                    crop_payload=crop_payload,
                )
                if candidate.sha256 in crop_hashes:
                    continue
                _write_exclusive(workspace / candidate.member_path, crop_payload)
                crop_hashes.add(candidate.sha256)
                candidates.append(candidate)
                accepted_on_page += 1
            if len(candidates) >= plan.max_visual_candidates and len(regions) > accepted_on_page:
                omissions.append(
                    ScienceVisualOmission(
                        document_id=source.document_id,
                        physical_page=page_number,
                        reason="CANDIDATE_LIMIT_REACHED",
                    )
                )
            elif accepted_on_page == 0:
                omissions.append(
                    ScienceVisualOmission(
                        document_id=source.document_id,
                        physical_page=page_number,
                        reason="NO_VISUAL_REGION",
                    )
                )

    completed_at = datetime.now(UTC) if now is None else now
    body = {
        "schema_version": "local-image-science-corpus-visual-pilot-result/1.0",
        "pilot_id": plan.pilot_id,
        "plan_sha256": plan.plan_sha256,
        "status": "SUCCEEDED",
        "page_images": tuple(
            value.model_dump(mode="json")
            for value in sorted(
                page_images,
                key=lambda value: (value.document_id, value.physical_page),
            )
        ),
        "visual_candidates": tuple(
            value.model_dump(mode="json")
            for value in sorted(candidates, key=lambda value: value.candidate_id)
        ),
        "omissions": tuple(
            value.model_dump(mode="json")
            for value in sorted(
                omissions,
                key=lambda value: (value.document_id, value.physical_page, value.reason),
            )
        ),
        "runtime": ScienceVisualPilotRuntime(
            python_version=sys.version.split()[0],
            pillow_version=_package_version("Pillow"),
            opencv_version="not-used",
            tesseract_version=tesseract_version,
            pdftoppm_version=pdftoppm_version,
        ).model_dump(mode="json"),
        "error_code": None,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
    }
    result = LocalImageScienceCorpusVisualPilotResult.model_validate(
        {**body, "result_sha256": content_sha256(body)}
    )
    validate_science_visual_pilot_result(plan, result)
    result_value = result.model_dump(mode="json")
    validate_contract("science-corpus-visual-pilot-result", result_value)
    _write_exclusive(workspace / command.result_member, _canonical_json(result_value))
    return result


def main(argv: tuple[str, ...] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2:
        print("SCIENCE_VISUAL_PILOT_USAGE_INVALID", file=sys.stderr)
        return 2
    try:
        result = run_science_corpus_visual_pilot(
            workspace=Path(arguments[0]),
            command_path=Path(arguments[1]),
        )
    except ScienceCorpusVisualRunnerError as exc:
        print(exc.code, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "pilot_id": result.pilot_id,
                "result_sha256": result.result_sha256,
                "status": result.status,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
