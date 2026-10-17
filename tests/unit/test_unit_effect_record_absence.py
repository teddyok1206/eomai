"""Real local directory IO, synthetic protected owner metadata; no runtime effects."""

import os

import pytest
from eom_catalog_service import unit_effect_records as owner

from tests.unit.test_embedding_native_probe_observation import ledger as ledger
from tests.unit.test_image_gpu_unit_lifetime import UNIT
from tests.unit.test_image_gpu_unit_lifetime import record_tree as record_tree
from tests.unit.test_image_gpu_unit_observation import image as image


def test_absent_ack_is_read_only_and_an_empty_or_partial_phase_is_never_absent(record_tree):
    ready, root = record_tree
    invocation = ready.unit.invocation_id
    owner.require_unit_effect_phase_absent(root, UNIT, invocation, "ack")
    assert not root.exists()
    descriptor = owner.reserve_unit_effect_phase(root, UNIT, invocation, "retirement")
    os.close(descriptor)
    owner.require_unit_effect_phase_absent(root, UNIT, invocation, "ack")
    descriptor = owner.reserve_unit_effect_phase(root, UNIT, invocation, "ack")
    try:
        with pytest.raises(owner.UnitEffectRecordError, match="RECORD_PHASE_PRESENT"):
            owner.require_unit_effect_phase_absent(root, UNIT, invocation, "ack")
        owner.write_unit_effect_record(descriptor, "intent.json", b"part")
        with pytest.raises(owner.UnitEffectRecordError, match="RECORD_PHASE_PRESENT"):
            owner.require_unit_effect_phase_absent(root, UNIT, invocation, "ack")
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("level", ("root", "unit", "invocation"))
def test_missing_ack_below_a_writable_directory_is_not_trusted(record_tree, level):
    ready, root = record_tree
    invocation = ready.unit.invocation_id
    descriptor = owner.reserve_unit_effect_phase(root, UNIT, invocation, "retirement")
    os.close(descriptor)
    path = {"root": root, "unit": root / UNIT, "invocation": root / UNIT / invocation}[level]
    path.chmod(0o777)
    with pytest.raises(owner.UnitEffectRecordError, match="RECORD_DIRECTORY_INVALID"):
        owner.require_unit_effect_phase_absent(root, UNIT, invocation, "ack")


def test_dangling_ack_phase_symlink_is_present_not_missing(record_tree):
    ready, root = record_tree
    invocation = ready.unit.invocation_id
    descriptor = owner.reserve_unit_effect_phase(root, UNIT, invocation, "retirement")
    os.close(descriptor)
    (root / UNIT / invocation / "ack").symlink_to(root / "does-not-exist")
    with pytest.raises(owner.UnitEffectRecordError, match="RECORD_PHASE_PRESENT"):
        owner.require_unit_effect_phase_absent(root, UNIT, invocation, "ack")


def test_nonroot_cannot_assert_phase_absence(record_tree, monkeypatch):
    ready, root = record_tree
    monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    with pytest.raises(owner.UnitEffectRecordError, match="OWNER_REQUIRED"):
        owner.require_unit_effect_phase_absent(root, UNIT, ready.unit.invocation_id, "ack")
    assert not root.exists()
