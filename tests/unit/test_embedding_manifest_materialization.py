"""Owner-local manifest race reproduction; no DB, NAS or numerical execution."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest
from eom_orchestrator import embedding_artifact_store as store


def test_concurrent_replay_never_reads_a_manifest_while_its_first_writer_is_partial(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "owner-workspace"
    workspace.mkdir(mode=0o700)
    partial, release, second_started, second_done = Event(), Event(), Event(), Event()
    captured = []
    guard = Lock()
    write = os.write

    def slow_first_write(descriptor, payload):
        with guard:
            first = not captured
            if first:
                captured.append(descriptor)
        if first:
            written = write(descriptor, payload[:1])
            partial.set()
            assert release.wait(timeout=10)
            return written
        return write(descriptor, payload)

    monkeypatch.setattr(store.os, "write", slow_first_write)
    payload = b'{"complete":true}'

    def materialize(*, second=False):
        descriptor = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if second:
                second_started.set()
            store._materialize_manifest(descriptor, "shard.json", payload)
            with store._member(descriptor, "shard.json", 1024) as read:
                return read
        finally:
            if second:
                second_done.set()
            os.close(descriptor)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(materialize)
        try:
            assert partial.wait(timeout=10)
            second = executor.submit(materialize, second=True)
            assert second_started.wait(timeout=10)
            assert not second_done.wait(timeout=0.05)
        finally:
            release.set()
        assert first.result(timeout=10) == second.result(timeout=10) == payload
    assert (workspace / "shard.json").stat().st_nlink == 1


def test_failed_materialization_preserves_partial_file_and_releases_the_owner_lock(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "owner-workspace"
    workspace.mkdir(mode=0o700)
    write = os.write

    def interrupted(descriptor, payload):
        write(descriptor, payload[:1])
        raise OSError("synthetic interrupted local materialization")

    first_fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    second_fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with monkeypatch.context() as isolated:
            isolated.setattr(store.os, "write", interrupted)
            with pytest.raises(store.EmbeddingArtifactStoreError, match="WRITE_FAILED"):
                store._materialize_manifest(first_fd, "shard.json", b'{"complete":true}')
        # A separate open description can acquire the lock after the failed writer.
        import fcntl

        fcntl.flock(second_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(second_fd, fcntl.LOCK_UN)
        original = (workspace / "shard.json").read_bytes()
        store._materialize_manifest(second_fd, "shard.json", b'{"complete":true}')
        assert (workspace / "shard.json").read_bytes() == original == b"{"
    finally:
        os.close(first_fd)
        os.close(second_fd)
