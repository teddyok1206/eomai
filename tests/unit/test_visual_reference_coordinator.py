from __future__ import annotations

import binascii
import hashlib
import os
import struct
import zlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageVisualReferenceIntent,
    VisualReferenceSource,
    content_json_bytes,
    content_sha256,
)
from eom_image_provider.reference_acquisition import (
    AcquiredReference,
    load_acquisition_inputs,
    run_visual_reference_acquisition,
)
from eom_orchestrator.file_set_control_artifacts import PublishedControlFileSet
from eom_orchestrator.settings import Settings
from eom_orchestrator.visual_reference_acquisition import (
    VisualReferenceAcquisitionCoordinator,
    VisualReferenceCoordinatorError,
)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body))


def _reference_png() -> bytes:
    width, height = 800, 504
    rows = b"".join(b"\x00" + b"\xc0\xc0\xc0" * width for _ in range(height))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            _chunk(b"IDAT", zlib.compress(rows, level=9)),
            _chunk(b"IEND", b""),
        )
    )


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
                "selection_rationale": "Clear side profile.",
                "intended_use": "SUBJECT_MORPHOLOGY_REFERENCE",
                "license_expectation": "PUBLIC_DOMAIN_OR_CC0",
            }
        ],
        "primary_candidate_page_id": 101,
    }
    return LocalImageVisualReferenceIntent.model_validate(
        {**body, "intent_sha256": content_sha256(body)}
    )


class _Publisher:
    def __init__(self) -> None:
        self.by_key: dict[str, PublishedControlFileSet] = {}
        self.calls = 0

    def publish(self, **kwargs: object) -> PublishedControlFileSet:
        members = kwargs["members"]
        assert isinstance(members, tuple)
        for member in members:
            payload = member.source.read_bytes()
            assert len(payload) == member.bytes
            assert "sha256:" + hashlib.sha256(payload).hexdigest() == member.sha256
        key = kwargs["idempotency_key"]
        assert isinstance(key, str)
        existing = self.by_key.get(key)
        if existing is not None:
            return existing
        self.calls += 1
        published = PublishedControlFileSet(
            job_id="job_" + f"{self.calls:032x}",
            artifact_id="artifact_" + f"{self.calls:032x}",
            artifact_revision_id="rev_" + f"{self.calls:032x}",
            primary_file=str(kwargs["primary_file"]),
            primary_sha256=members[0].sha256,
            manifest_sha256="sha256:" + f"{self.calls:064x}",
            nas_path=f"/test/{self.calls}",
        )
        self.by_key[key] = published
        return published


class _Client:
    def acquire(self, *_args: object, **_kwargs: object) -> tuple[AcquiredReference, ...]:
        original = b"untrusted-original"
        source = VisualReferenceSource(
            reference_id="imgref_" + "a" * 32,
            rank=1,
            page_id=101,
            page_revision_id=1001,
            file_title="File:Compact car side view.jpg",
            canonical_page_url=(
                "https://commons.wikimedia.org/wiki/File:Compact_car_side_view.jpg"
            ),
            original_file_url=(
                "https://upload.wikimedia.org/wikipedia/commons/a/ab/Compact_car.jpg"
            ),
            original_media_type="image/jpeg",
            original_size_bytes=len(original),
            original_sha256="sha256:" + hashlib.sha256(original).hexdigest(),
            original_width_px=1200,
            original_height_px=800,
            license_id="CC0-1.0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            license_short_name="CC0 1.0",
            disposition="PRIMARY_CONDITIONING",
        )
        return (AcquiredReference(source=source, original_bytes=original),)


def _coordinator(
    tmp_path: Path,
) -> tuple[VisualReferenceAcquisitionCoordinator, _Publisher, list[str]]:
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    root = tmp_path / "reference-workspaces"
    root.mkdir(mode=0o3770)
    root.chmod(0o3770)
    publisher = _Publisher()
    starts: list[str] = []

    def run(unit_name: str, timeout: int) -> None:
        starts.append(unit_name)
        assert timeout == 120
        command_id = unit_name.removeprefix("eom-image-reference-acquirer@").removesuffix(
            ".service"
        )
        workspace = root / command_id
        command, intent = load_acquisition_inputs(
            command_path=workspace / "command.json",
            workspace=workspace,
        )
        run_visual_reference_acquisition(
            command=command,
            intent=intent,
            workspace=workspace,
            client=_Client(),  # type: ignore[arg-type]
            normalizer=lambda *_args: _reference_png(),
        )

    settings = Settings(
        staging_root=staging,
        image_reference_workspace_root=root,
        image_reference_provider_group="test-group",
    )
    coordinator = VisualReferenceAcquisitionCoordinator(
        publisher=publisher,
        settings=settings,
        unit_runner=run,
        provider_uid=os.geteuid(),
        provider_gid=os.getegid(),
        workspace_root_uid=os.geteuid(),
    )
    return coordinator, publisher, starts


def test_coordinator_publishes_intent_and_bundle_once_and_returns_exact_pointer(
    tmp_path: Path,
) -> None:
    coordinator, publisher, starts = _coordinator(tmp_path)
    observed_at = datetime(2026, 9, 27, 14, 0, tzinfo=UTC)

    first = coordinator.acquire(
        intent=_intent(),
        source_commit="1" * 40,
        observed_at=observed_at,
    )
    second = coordinator.acquire(
        intent=_intent(),
        source_commit="1" * 40,
        observed_at=observed_at,
    )

    assert first.pointer == second.pointer
    assert publisher.calls == 2
    assert len(starts) == 1
    assert first.pointer.bundle_manifest.artifact_id == first.bundle_artifact.artifact_id
    assert first.pointer.reference_member.artifact_revision_id == (
        first.bundle_artifact.artifact_revision_id
    )
    assert first.acquisition_result.bundle is not None
    assert first.pointer.bundle_id == first.acquisition_result.bundle.bundle_id
    assert first.command.intent.artifact_id == first.intent_artifact.artifact_id


def test_coordinator_rejects_output_hash_drift_without_publishing_bundle(tmp_path: Path) -> None:
    coordinator, publisher, _starts = _coordinator(tmp_path)
    first = coordinator.acquire(
        intent=_intent(),
        source_commit="1" * 40,
        observed_at=datetime(2026, 9, 27, 14, 0, tzinfo=UTC),
    )
    workspace = coordinator.settings.image_reference_workspace_root / first.command.command_id
    reference = workspace / "output/references/primary.png"
    reference.chmod(0o640)
    reference.write_bytes(reference.read_bytes() + b"drift")
    reference.chmod(0o640)

    with pytest.raises(VisualReferenceCoordinatorError, match="VISUAL_REFERENCE_OUTPUT_INVALID"):
        coordinator.acquire(
            intent=_intent(),
            source_commit="1" * 40,
            observed_at=datetime(2026, 9, 27, 14, 0, tzinfo=UTC),
        )
    assert publisher.calls == 2


def test_coordinator_stages_canonical_intent_without_original_source_bytes(tmp_path: Path) -> None:
    coordinator, _publisher, _starts = _coordinator(tmp_path)
    published = coordinator.acquire(
        intent=_intent(),
        source_commit="1" * 40,
        observed_at=datetime(2026, 9, 27, 14, 0, tzinfo=UTC),
    )
    intent_path = (
        coordinator.settings.staging_root
        / "visual-reference-intents"
        / f"{_intent().intent_id}.json"
    )
    assert intent_path.read_bytes() == content_json_bytes(_intent().model_dump(mode="json"))
    workspace = coordinator.settings.image_reference_workspace_root / published.command.command_id
    assert not any(
        path.read_bytes() == b"untrusted-original"
        for path in workspace.rglob("*")
        if path.is_file()
    )
