"""Synthetic protected-file surrogates, never installed-release acceptance."""

import os
import tempfile
from pathlib import Path

import pytest
from eom_catalog_service import embedding_benchmark_controller_compatibility as module
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots


@pytest.fixture
def releases(monkeypatch):
    monkeypatch.setattr(
        module,
        "NumericalRuntimeFileSnapshots",
        lambda _owner: NumericalRuntimeFileSnapshots(os.getuid()),
    )
    with tempfile.TemporaryDirectory(prefix="eom-benchmark-compatibility-") as directory:
        temporary_root = Path(directory)
        monkeypatch.setattr(module, "_RELEASE_ROOT", temporary_root)
        sources = ("a" * 40, "b" * 40)
        for source in sources:
            root = temporary_root / source / "site-packages"
            root.mkdir(parents=True)
            for directory_path in (root, root.parent, root.parent.parent):
                directory_path.chmod(0o755)
            for name in module._MEASUREMENT_MEMBERS:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).parent.chmod(0o755)
                (root / name).write_text(name)
                (root / name).chmod(0o600)
        yield temporary_root, sources


def test_exact_measurement_bytes_allow_distinct_actual_sources(releases):
    _root, sources = releases
    capture = module.capture_equivalent_controller_measurements(sources)
    capture.assert_unchanged()


def test_identical_source_keeps_existing_no_filesystem_requirement(monkeypatch):
    monkeypatch.setattr(module, "_RELEASE_ROOT", Path("/not/installed"))
    module.capture_equivalent_controller_measurements(("a" * 40,) * 6).assert_unchanged()


@pytest.mark.parametrize("change", ["different", "missing", "writable", "symlink"])
def test_unverifiable_measurement_implementation_cannot_join_old_cohort(releases, change):
    root, sources = releases
    path = root / sources[1] / "site-packages" / module._MEASUREMENT_MEMBERS[0]
    if change == "different":
        path.write_text("changed timing or measurement code")
    elif change == "missing":
        path.unlink()
    elif change == "writable":
        path.chmod(0o666)
    else:
        path.unlink()
        path.symlink_to(path.with_name(Path(module._MEASUREMENT_MEMBERS[1]).name))
    with pytest.raises((ValueError, OSError)):
        module.capture_equivalent_controller_measurements(sources)


def test_snapshot_rejects_change_between_comparison_and_publication(releases):
    root, sources = releases
    capture = module.capture_equivalent_controller_measurements(sources)
    path = root / sources[0] / "site-packages" / module._MEASUREMENT_MEMBERS[0]
    path.write_text("different")
    with pytest.raises(ValueError):
        capture.assert_unchanged()


def test_duplicate_release_references_are_hashed_only_once(releases, monkeypatch):
    _root, sources = releases
    original = NumericalRuntimeFileSnapshots.observe_protected_member_bytes
    reads = []

    def observe(self, path, **kwargs):
        reads.append(path)
        return original(self, path, **kwargs)

    monkeypatch.setattr(NumericalRuntimeFileSnapshots, "observe_protected_member_bytes", observe)
    module.capture_equivalent_controller_measurements((sources[0], sources[1], sources[1]) * 2)
    assert len(reads) == len(set(reads)) == 2 * len(module._MEASUREMENT_MEMBERS)


@pytest.mark.parametrize("selected", [(), ("a" * 40,) * 7, ("../escape",), (True,), ["a" * 40]])
def test_invalid_selection_rejected_before_resolution(selected):
    with pytest.raises(ValueError, match="SELECTION_INVALID"):
        module.capture_equivalent_controller_measurements(selected)


def test_inventory_is_unique_and_covers_the_actual_root_and_timing_implementations():
    import eom_catalog_contracts
    import eom_orchestrator
    import eom_workflow

    members = module._MEASUREMENT_MEMBERS
    assert len(members) == len(set(members))
    packages = {
        "eom_catalog_service": Path(module.__file__).parent,
        "eom_orchestrator": Path(eom_orchestrator.__file__).parent,
        "eom_catalog_contracts": Path(eom_catalog_contracts.__file__).parent,
        "eom_workflow": Path(eom_workflow.__file__).parent,
    }
    assert all((packages[name.split("/")[0]] / name.split("/", 1)[1]).is_file() for name in members)
    assert {
        "eom_catalog_service/embedding_benchmark_cpu_driver.py",
        "eom_catalog_service/embedding_benchmark_cuda_driver.py",
        "eom_catalog_service/embedding_benchmark_timing_evidence.py",
        "eom_catalog_service/embedding_benchmark_root_control.py",
        "eom_catalog_service/embedding_benchmark_unit_policy.py",
    } <= set(members)
