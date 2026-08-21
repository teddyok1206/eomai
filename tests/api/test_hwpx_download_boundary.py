from __future__ import annotations

import os
import socket
import threading
from pathlib import Path

from eom_api.services.hwpx_download_client import HwpxDownloadClient
from eom_hwpx_manager.application_service import SecureHwpxDownload
from eom_hwpx_manager.download_server import HwpxDownloadServer
from eom_identifiers import sha256_file

BUILD_ID = "hwpxbuild_" + "a" * 32


class FixtureDownloadService:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.requested: list[str] = []

    def secure_download(self, build_id: str) -> SecureHwpxDownload:
        self.requested.append(build_id)
        return SecureHwpxDownload(
            fd=os.open(self.output, os.O_RDONLY | os.O_CLOEXEC),
            filename="eom-fixture.hwpx",
            content_length=self.output.stat().st_size,
            sha256=sha256_file(self.output),
        )


def test_application_api_streams_through_private_manager_socket(tmp_path: Path) -> None:
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o750)
    runtime.chmod(0o750)
    socket_path = runtime / "manager.sock"
    output = tmp_path / "fixture.hwpx"
    output.write_bytes(b"TEST_ONLY_VALIDATED_HWPX")
    service = FixtureDownloadService(output)
    server = HwpxDownloadServer(
        service,  # type: ignore[arg-type]
        socket_path=socket_path,
        allowed_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        download = HwpxDownloadClient(socket_path).download(BUILD_ID)
        assert b"".join(download.iter_chunks()) == output.read_bytes()
        assert download.sha256 == sha256_file(output)
        assert service.requested == [BUILD_ID]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not socket_path.exists()


def test_download_boundary_has_no_nas_path_or_arbitrary_request_surface() -> None:
    api_unit = Path("infra/systemd/eom-api.service").read_text(encoding="utf-8")
    router = Path("apps/application_api/eom_api/routers/hwpx.py").read_text(encoding="utf-8")
    client = Path("apps/application_api/eom_api/services/hwpx_download_client.py").read_text(
        encoding="utf-8"
    )
    assert "InaccessiblePaths=/mnt/nas" in api_unit
    assert "hwpx_downloads.download(build_id)" in router
    assert "/mnt/nas" not in client
    assert "shell=True" not in client
    assert "command" not in client


def test_manager_rejects_non_protocol_request_without_file_access(tmp_path: Path) -> None:
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o750)
    runtime.chmod(0o750)
    output = tmp_path / "fixture.hwpx"
    output.write_bytes(b"TEST_ONLY_VALIDATED_HWPX")
    service = FixtureDownloadService(output)
    server = HwpxDownloadServer(
        service,  # type: ignore[arg-type]
        socket_path=runtime / "manager.sock",
        allowed_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(2)
        connection.connect(str(runtime / "manager.sock"))
        connection.sendall(b'{"operation":"download","path":"/etc/shadow"}\n')
        header = connection.recv(4096)
        connection.close()
        assert b"HWPX_DOWNLOAD_REQUEST_INVALID" in header
        assert service.requested == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
