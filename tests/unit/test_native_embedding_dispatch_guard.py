"""Actual private-file dispatch claims with synthetic systemd; no model or service writes."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    CpuHandoffIdentity,
    claim_native_cpu_dispatch,
)


def workspace(tmp_path, digest="sha256:" + "a" * 64):
    directory = tmp_path / "dispatch"
    directory.mkdir(mode=0o700)
    marker = directory / ".launch-started"
    marker.write_bytes(digest.encode("ascii"))
    marker.chmod(0o600)
    return directory, digest, CpuHandoffIdentity(os.geteuid(), os.getegid())


def test_one_durable_claim_survives_reentry_and_never_overwrites(tmp_path):
    directory, digest, owner = workspace(tmp_path)
    claim_native_cpu_dispatch(directory, digest, owner=owner)
    marker = directory / ".dispatch-attempted"
    before = marker.stat()
    with pytest.raises(CpuHandoffError, match="ALREADY_ATTEMPTED"):
        claim_native_cpu_dispatch(directory, digest, owner=owner)
    assert marker.read_bytes() == digest.encode("ascii")
    assert marker.stat().st_ino == before.st_ino
    assert marker.stat().st_mtime_ns == before.st_mtime_ns


def test_concurrent_claims_can_never_both_win(tmp_path):
    directory, digest, owner = workspace(tmp_path)

    def claim():
        try:
            claim_native_cpu_dispatch(directory, digest, owner=owner)
            return True
        except CpuHandoffError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: claim(), range(2))) == 1
    assert (directory / ".dispatch-attempted").read_bytes() == digest.encode("ascii")


@pytest.mark.parametrize("fault", ("missing", "changed", "mode", "symlink", "hardlink", "partial"))
def test_incomplete_or_changed_marker_never_authorizes_a_dispatch(tmp_path, fault):
    directory, digest, owner = workspace(tmp_path)
    marker = directory / ".launch-started"
    if fault == "missing":
        marker.unlink()
    if fault == "changed":
        marker.write_bytes(b"sha256:" + b"b" * 64)
    if fault == "mode":
        marker.chmod(0o644)
    if fault == "hardlink":
        os.link(marker, directory / "other")
    if fault == "symlink":
        marker.rename(directory / "other")
        marker.symlink_to("other")
    if fault == "partial":
        attempted = directory / ".dispatch-attempted"
        attempted.touch(mode=0o600)
    with pytest.raises((CpuHandoffError, OSError)):
        claim_native_cpu_dispatch(directory, digest, owner=owner)


@pytest.mark.parametrize("purpose", ("INDEX", "QUERY"))
def test_forgotten_systemd_handle_cannot_start_a_second_execution(tmp_path, monkeypatch, purpose):
    from eom_orchestrator import native_embedding_index_systemd as index_module
    from eom_orchestrator import native_embedding_query_systemd as query_module

    from tests.unit.test_native_embedding_index_handoff import prepared as index_prepared
    from tests.unit.test_native_embedding_index_systemd import setup_launcher as index_setup
    from tests.unit.test_native_embedding_query_handoff import prepared as query_prepared
    from tests.unit.test_native_embedding_query_systemd import setup_launcher as query_setup

    setup, prepare, module = (
        (index_setup, index_prepared, index_module)
        if purpose == "INDEX"
        else (query_setup, query_prepared, query_module)
    )
    adapter, calls = setup(tmp_path, monkeypatch, [("fresh", "fresh")] * 3)
    value = prepare()
    directory, digest, owner = workspace(tmp_path, value.association.association_sha256)
    monkeypatch.setattr(module, "fixed_owner_identity", lambda: owner)
    monkeypatch.setattr(
        module,
        "claim_native_cpu_dispatch",
        lambda *_a, **_kw: claim_native_cpu_dispatch(directory, digest, owner=owner),
    )
    for _ in range(2):
        with pytest.raises(ValueError, match="UNCERTAIN"):
            adapter.run(value)
    assert len(calls) == 1
    assert (directory / ".dispatch-attempted").is_file()
