from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from eom_image_contracts import (
    LocalImageVisualReferenceAcquisitionCommand,
    LocalImageVisualReferenceDiscoveryCommand,
    LocalImageVisualReferenceIntent,
    VisualReferenceSource,
    content_json_bytes,
    content_sha256,
    validate_contract,
)
from eom_image_provider.reference_acquisition import (
    AcquiredReference,
    VisualReferenceAcquisitionError,
    WikimediaCommonsClient,
    _canonical_original_file_url,
    load_acquisition_inputs,
    run_visual_reference_acquisition,
    run_visual_reference_discovery,
)
from pydantic import ValidationError as PydanticValidationError


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _intent() -> LocalImageVisualReferenceIntent:
    body = {
        "schema_version": "local-image-visual-reference-intent/1.0",
        "intent_id": "imgrefintent_" + "1" * 32,
        "workflow_id": "workflow_" + "2" * 32,
        "image_step_run_id": "steprun_" + "3" * 32,
        "image_job_id": "job_" + "4" * 32,
        "visual_ordinal": 0,
        "drawing_sha256": "sha256:" + "5" * 64,
        "subject": "one compact car in side view isolated on white",
        "query_terms": ["compact car", "side view"],
        "candidates": [
            {
                "rank": 1,
                "provider": "WIKIMEDIA_COMMONS",
                "page_id": 101,
                "file_title": "File:Compact car side view.jpg",
                "canonical_page_url": (
                    "https://commons.wikimedia.org/wiki/File:Compact_car_side_view.jpg"
                ),
                "selection_rationale": "Unobstructed side profile.",
                "intended_use": "SUBJECT_MORPHOLOGY_REFERENCE",
                "license_expectation": "PUBLIC_DOMAIN_OR_CC0",
            }
        ],
        "primary_candidate_page_id": 101,
    }
    return LocalImageVisualReferenceIntent.model_validate(
        {**body, "intent_sha256": content_sha256(body)}
    )


def _intent_pointer(intent_bytes: bytes) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + "6" * 32,
        "artifact_revision_id": "rev_" + "7" * 32,
        "member_path": "manifests/visual-reference-intent.json",
        "schema_ref": ("eom://schemas/image-provider/local-image-visual-reference-intent/1.0"),
        "media_type": "application/json",
        "sha256": _sha(intent_bytes),
        "size_bytes": len(intent_bytes),
    }


def _command(intent_bytes: bytes) -> LocalImageVisualReferenceAcquisitionCommand:
    body = {
        "schema_version": "local-image-visual-reference-acquisition-command/1.0",
        "command_id": "imgrefcmd_" + "8" * 32,
        "attempt_id": "imgrefattempt_" + "9" * 32,
        "intent": _intent_pointer(intent_bytes),
        "intent_member_path": "input/visual-reference-intent.json",
        "observed_at": "2026-09-27T12:00:00Z",
        "max_original_bytes": 16_777_216,
        "timeout_seconds": 120,
    }
    return LocalImageVisualReferenceAcquisitionCommand.model_validate(
        {**body, "command_sha256": content_sha256(body)}
    )


def _discovery_command() -> LocalImageVisualReferenceDiscoveryCommand:
    identity_body = {
        "schema_version": "local-image-visual-reference-discovery-command/1.0",
        "workflow_id": "workflow_" + "2" * 32,
        "image_step_run_id": "steprun_" + "3" * 32,
        "image_job_id": "job_" + "4" * 32,
        "visual_ordinal": 0,
        "drawing_sha256": "sha256:" + "5" * 64,
        "subject": "one compact car in side view isolated on white",
        "query_terms": ["compact car", "side view"],
        "candidate_limit": 5,
        "observed_at": "2026-09-27T12:00:00Z",
        "timeout_seconds": 120,
    }
    command_id = "imgrefdiscover_" + content_sha256(identity_body).removeprefix("sha256:")[:32]
    body = {**identity_body, "command_id": command_id}
    return LocalImageVisualReferenceDiscoveryCommand.model_validate(
        {**body, "command_sha256": content_sha256(body)}
    )


def _source(original: bytes) -> VisualReferenceSource:
    return VisualReferenceSource(
        reference_id="imgref_" + "a" * 32,
        rank=1,
        page_id=101,
        page_revision_id=1001,
        file_title="File:Compact car side view.jpg",
        canonical_page_url=("https://commons.wikimedia.org/wiki/File:Compact_car_side_view.jpg"),
        original_file_url=("https://upload.wikimedia.org/wikipedia/commons/a/ab/Compact_car.jpg"),
        original_media_type="image/jpeg",
        original_size_bytes=len(original),
        original_sha256=_sha(original),
        original_width_px=1200,
        original_height_px=800,
        license_id="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        license_short_name="CC0 1.0",
        disposition="PRIMARY_CONDITIONING",
    )


class _StaticClient:
    def __init__(self, source: VisualReferenceSource, original: bytes) -> None:
        self.source = source
        self.original = original

    def acquire(
        self,
        intent: LocalImageVisualReferenceIntent,
        *,
        maximum_bytes: int,
        timeout_seconds: int,
    ) -> tuple[AcquiredReference, ...]:
        assert intent == _intent()
        assert maximum_bytes == 16_777_216
        assert timeout_seconds == 120
        return (AcquiredReference(source=self.source, original_bytes=self.original),)


class _Headers:
    def __init__(self, media_type: str, size: int | None = None) -> None:
        self.media_type = media_type
        self.size = size

    def get_content_type(self) -> str:
        return self.media_type

    def get(self, key: str) -> str | None:
        if key == "Content-Length" and self.size is not None:
            return str(self.size)
        return None


class _Response:
    def __init__(self, url: str, media_type: str, payload: bytes) -> None:
        self.url = url
        self.headers = _Headers(
            media_type, None if media_type == "application/json" else len(payload)
        )
        self.payload = payload
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        return self.payload if amount < 0 else self.payload[:amount]

    def close(self) -> None:
        self.closed = True

    def geturl(self) -> str:
        return self.url


class _Opener:
    def __init__(
        self,
        *,
        original: bytes,
        license_code: str = "cc-zero",
        license_url: str = "https://creativecommons.org/publicdomain/zero/1.0/",
    ) -> None:
        self.original = original
        self.license_code = license_code
        self.license_url = license_url
        self.calls: list[str] = []

    def open(self, request: Any, *, timeout: int) -> _Response:
        url = request.full_url
        self.calls.append(url)
        assert timeout == 120
        if url.startswith("https://commons.wikimedia.org/w/api.php?"):
            page = {
                "pageid": 101,
                "ns": 6,
                "title": "File:Compact car side view.jpg",
                "canonicalurl": (
                    "https://commons.wikimedia.org/wiki/File:Compact_car_side_view.jpg"
                ),
                "revisions": [{"revid": 1001}],
                "imageinfo": [
                    {
                        "url": (
                            "https://upload.wikimedia.org/wikipedia/commons/a/ab/Compact_car.jpg"
                            "?utm_source=commons.wikimedia.org&utm_campaign=imageinfo"
                            "&utm_content=original"
                        ),
                        "size": len(self.original),
                        "width": 1200,
                        "height": 800,
                        "mime": "image/jpeg",
                        "extmetadata": {
                            "License": {"value": self.license_code},
                            "LicenseShortName": {"value": "CC0 1.0"},
                            "LicenseUrl": {"value": self.license_url},
                        },
                    }
                ],
            }
            payload = json.dumps({"query": {"pages": [page]}}).encode()
            return _Response(url, "application/json", payload)
        return _Response(url, "image/jpeg", self.original)


class _DiscoveryOpener:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def open(self, request: Any, *, timeout: int) -> _Response:
        url = request.full_url
        self.calls.append(url)
        assert timeout == 120

        def page(*, index: int, page_id: int, title: str, license_code: str) -> dict[str, object]:
            canonical_title = title.replace(" ", "_")
            return {
                "pageid": page_id,
                "ns": 6,
                "title": title,
                "index": index,
                "canonicalurl": f"https://commons.wikimedia.org/wiki/{canonical_title}",
                "revisions": [{"revid": 1000 + page_id}],
                "imageinfo": [
                    {
                        "url": (
                            "https://upload.wikimedia.org/wikipedia/commons/"
                            f"a/ab/reference-{page_id}.jpg?utm_source=commons.wikimedia.org"
                            "&utm_campaign=imageinfo&utm_content=original"
                        ),
                        "size": 100_000,
                        "width": 1200,
                        "height": 800,
                        "mime": "image/jpeg",
                        "extmetadata": {
                            "License": {"value": license_code},
                            "LicenseShortName": {"value": license_code},
                            "LicenseUrl": {
                                "value": ("https://creativecommons.org/publicdomain/zero/1.0/")
                            },
                        },
                    }
                ],
            }

        payload = json.dumps(
            {
                "query": {
                    "pages": [
                        page(
                            index=3,
                            page_id=103,
                            title="File:Licensed compact car.jpg",
                            license_code="cc-by-sa-4.0",
                        ),
                        page(
                            index=2,
                            page_id=102,
                            title="File:Public compact car rear.jpg",
                            license_code="pd",
                        ),
                        page(
                            index=1,
                            page_id=101,
                            title="File:CC0 compact car side.jpg",
                            license_code="cc-zero",
                        ),
                    ]
                }
            }
        ).encode()
        return _Response(url, "application/json", payload)


def _public_resolver(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
    return [(2, 1, 6, "", ("208.80.154.224", 443))]


def test_acquisition_materializes_only_canonical_bundle_reference_and_result(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o1730)
    workspace.chmod(0o1730)
    intent = _intent()
    intent_bytes = content_json_bytes(intent.model_dump(mode="json"))
    command = _command(intent_bytes)
    original = b"untrusted-original-jpeg"
    normalized = b"normalized-png"
    clock = iter(
        (
            datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
            datetime(2026, 9, 27, 12, 0, 1, tzinfo=UTC),
        )
    )
    ticks = iter((1_000_000_000, 2_000_000_000))

    output = run_visual_reference_acquisition(
        command=command,
        intent=intent,
        workspace=workspace,
        client=_StaticClient(_source(original), original),  # type: ignore[arg-type]
        normalizer=lambda raw, media, width, height: normalized,
        now=lambda: next(clock),
        monotonic_ns=lambda: next(ticks),
    )

    assert output.result.status == "SUCCEEDED"
    assert output.result.bundle is not None
    assert output.reference_path is not None
    assert output.reference_path.read_bytes() == normalized
    assert output.bundle_path is not None
    assert output.bundle_path.read_bytes() == content_json_bytes(
        output.result.bundle.model_dump(mode="json")
    )
    assert output.result_path.read_bytes() == content_json_bytes(
        output.result.model_dump(mode="json")
    )
    for path in output.output_directory.rglob("*"):
        if path.is_file():
            assert path.stat().st_mode & 0o777 == 0o640
    assert not any(
        path.read_bytes() == original
        for path in output.output_directory.rglob("*")
        if path.is_file()
    )
    assert sorted(
        path.relative_to(output.output_directory).as_posix()
        for path in output.output_directory.rglob("*")
        if path.is_file()
    ) == [
        "manifests/visual-reference-bundle.json",
        "references/primary.png",
        "result.json",
    ]


def test_official_metadata_is_independently_verified() -> None:
    original = b"original-jpeg"
    opener = _Opener(original=original)
    client = WikimediaCommonsClient(opener=opener, address_resolver=_public_resolver)  # type: ignore[arg-type]

    acquired = client.acquire(_intent(), maximum_bytes=16_777_216, timeout_seconds=120)

    assert len(acquired) == 1
    assert acquired[0].original_bytes == original
    assert acquired[0].source.page_revision_id == 1001
    assert acquired[0].source.license_id == "CC0-1.0"
    assert acquired[0].source.original_file_url == (
        "https://upload.wikimedia.org/wikipedia/commons/a/ab/Compact_car.jpg"
    )
    assert opener.calls[-1] == acquired[0].source.original_file_url
    assert len(opener.calls) == 2


def test_upload_tracking_query_is_exactly_bounded_before_canonicalization() -> None:
    base = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Compact_car.jpg"

    assert (
        _canonical_original_file_url(
            base + "?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original"
        )
        == base
    )
    assert _canonical_original_file_url(base + "?token=secret") is None
    assert (
        _canonical_original_file_url(
            base + "?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail"
        )
        is None
    )


def test_accepted_license_code_uses_fixed_canonical_url() -> None:
    opener = _Opener(
        original=b"original-jpeg",
        license_url="http://creativecommons.org/publicdomain/zero/1.0/deed.en",
    )
    client = WikimediaCommonsClient(opener=opener, address_resolver=_public_resolver)  # type: ignore[arg-type]

    acquired = client.acquire(_intent(), maximum_bytes=16_777_216, timeout_seconds=120)

    assert acquired[0].source.license_url == ("https://creativecommons.org/publicdomain/zero/1.0/")


def test_discovery_uses_official_order_and_skips_incompatible_licenses() -> None:
    opener = _DiscoveryOpener()
    client = WikimediaCommonsClient(opener=opener, address_resolver=_public_resolver)  # type: ignore[arg-type]

    candidates = client.discover_candidates(
        subject="one compact car in side view isolated on white",
        candidate_limit=5,
        timeout_seconds=120,
    )

    assert tuple(value.page_id for value in candidates) == (101, 102)
    assert tuple(value.rank for value in candidates) == (1, 2)
    assert all(value.license_expectation == "PUBLIC_DOMAIN_OR_CC0" for value in candidates)
    assert len(opener.calls) == 1


def test_discovery_materializes_one_canonical_result_without_source_bytes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o1730)
    workspace.chmod(0o1730)
    clock = iter(
        (
            datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
            datetime(2026, 9, 27, 12, 0, 1, tzinfo=UTC),
        )
    )
    ticks = iter((1_000_000_000, 2_000_000_000))
    client = WikimediaCommonsClient(
        opener=_DiscoveryOpener(),  # type: ignore[arg-type]
        address_resolver=_public_resolver,
    )

    command = _discovery_command()
    validate_contract("visual-reference-discovery-command", command.model_dump(mode="json"))
    output = run_visual_reference_discovery(
        command=command,
        workspace=workspace,
        client=client,
        now=lambda: next(clock),
        monotonic_ns=lambda: next(ticks),
    )

    assert output.result.status == "SUCCEEDED"
    validate_contract("visual-reference-discovery-result", output.result.model_dump(mode="json"))
    assert tuple(value.page_id for value in output.result.candidates) == (101, 102)
    assert output.result_path.read_bytes() == content_json_bytes(
        output.result.model_dump(mode="json")
    )
    assert tuple(path.name for path in output.output_directory.iterdir()) == ("result.json",)


def test_non_public_domain_metadata_is_rejected() -> None:
    opener = _Opener(original=b"original-jpeg", license_code="cc-by-sa-4.0")
    client = WikimediaCommonsClient(opener=opener, address_resolver=_public_resolver)  # type: ignore[arg-type]

    with pytest.raises(VisualReferenceAcquisitionError, match="VISUAL_REFERENCE_LICENSE_REJECTED"):
        client.acquire(_intent(), maximum_bytes=16_777_216, timeout_seconds=120)


def test_private_dns_answer_is_rejected_before_http() -> None:
    opener = _Opener(original=b"original-jpeg")
    client = WikimediaCommonsClient(
        opener=opener,  # type: ignore[arg-type]
        address_resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )

    with pytest.raises(VisualReferenceAcquisitionError, match="VISUAL_REFERENCE_SOURCE_REJECTED"):
        client.acquire(_intent(), maximum_bytes=16_777_216, timeout_seconds=120)
    assert opener.calls == []


def test_failed_acquisition_publishes_only_stable_failure_result(tmp_path: Path) -> None:
    class _FailedClient:
        def acquire(self, *_args: object, **_kwargs: object) -> tuple[AcquiredReference, ...]:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_UNAVAILABLE")

    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o1730)
    workspace.chmod(0o1730)
    intent = _intent()
    intent_bytes = content_json_bytes(intent.model_dump(mode="json"))
    now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    output = run_visual_reference_acquisition(
        command=_command(intent_bytes),
        intent=intent,
        workspace=workspace,
        client=_FailedClient(),  # type: ignore[arg-type]
        now=iter((now, now + timedelta(seconds=1))).__next__,
        monotonic_ns=iter((1_000_000_000, 2_000_000_000)).__next__,
    )

    assert output.result.status == "FAILED"
    assert output.result.error_code == "VISUAL_REFERENCE_SOURCE_UNAVAILABLE"
    assert [path.name for path in output.output_directory.iterdir()] == ["result.json"]


def test_canonical_input_loader_rejects_hash_drift(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "input").mkdir(mode=0o750, parents=True)
    workspace.chmod(0o1730)
    intent = _intent()
    intended = content_json_bytes(intent.model_dump(mode="json"))
    command = _command(intended)
    command_path = workspace / "command.json"
    command_path.write_bytes(content_json_bytes(command.model_dump(mode="json")))
    command_path.chmod(0o440)
    (workspace / "input/visual-reference-intent.json").write_bytes(intended + b" ")
    (workspace / "input/visual-reference-intent.json").chmod(0o440)

    with pytest.raises(VisualReferenceAcquisitionError, match="VISUAL_REFERENCE_INPUT_INVALID"):
        load_acquisition_inputs(command_path=command_path, workspace=workspace)


def test_source_rejects_individually_valid_but_excessive_pixel_population() -> None:
    value = _source(b"original").model_dump(mode="json")
    value["original_width_px"] = 10_000
    value["original_height_px"] = 5_000

    with pytest.raises(PydanticValidationError, match="pixel bound"):
        VisualReferenceSource.model_validate(value)
