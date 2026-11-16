"""Optional Caddy template against synthetic HTTP/UDS fixtures, never live configuration."""

import json
import shutil
import socket
import socketserver
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "config/caddy/kakao-remote.caddy"
AUTH_PATH = "/studio/api/v1/kakao-archive/remote/authorize"
REMOTE = "/studio/admin/remote/vnc.html"


@pytest.fixture(scope="module")
def caddy_proxy(tmp_path_factory):
    executable = shutil.which("caddy")
    if executable is None:
        pytest.skip("actual Caddy binary required for optional-template HTTP fixture")
    directory = tmp_path_factory.mktemp("kakao-caddy")
    state = {"status": 204, "auth": [], "remote": []}

    class Auth(BaseHTTPRequestHandler):
        def do_GET(self):
            state["auth"].append((self.path, dict(self.headers)))
            payload = b"false" if state["status"] == 200 else b""
            self.send_response(state["status"])
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    class Remote(BaseHTTPRequestHandler):
        def do_GET(self):
            state["remote"].append((self.path, dict(self.headers)))
            self.send_response(200)
            self.send_header("Set-Cookie", "must-not-reach-browser=1")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    class UnixHTTPServer(HTTPServer):
        address_family = socket.AF_UNIX

        def server_bind(self):
            socketserver.TCPServer.server_bind(self)
            self.server_name = "fixture"
            self.server_port = 0

    auth = ThreadingHTTPServer(("127.0.0.1", 0), Auth)
    remote_socket = directory / "gateway.sock"
    remote = UnixHTTPServer(str(remote_socket), Remote)
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    template = (
        TEMPLATE.read_text()
        .replace("127.0.0.1:8790", f"127.0.0.1:{auth.server_port}")
        .replace("/run/eom-kakao-remote/gateway.sock", str(remote_socket))
    )
    config = directory / "Caddyfile"
    config.write_text(
        "{\n admin off\n auto_https off\n}\n"
        f"http://127.0.0.1:{port} {{\n route {{\n{template}\n respond 404\n}}\n}}\n"
    )
    adapted = subprocess.run(
        [executable, "adapt", "--config", str(config), "--adapter", "caddyfile"],
        check=True,
        capture_output=True,
        timeout=10,
    )
    assert json.loads(adapted.stdout)["apps"]["http"]
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True) for server in (auth, remote)
    ]
    for thread in threads:
        thread.start()
    process = subprocess.Popen(
        [executable, "run", "--config", str(config), "--adapter", "caddyfile"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=3) as client:
            deadline = time.monotonic() + 8
            while True:
                try:
                    assert client.get("/ready").status_code == 404
                    break
                except httpx.TransportError:
                    assert process.poll() is None and time.monotonic() < deadline
                    time.sleep(0.03)
            yield client, state
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        for server in (auth, remote):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)


def test_template_is_not_imported_by_operational_caddyfile():
    assert "kakao-remote.caddy" not in (ROOT / "config/caddy/Caddyfile").read_text()


def test_caddy_overwrites_metadata_and_strips_credentials_before_fixed_socket(caddy_proxy):
    client, state = caddy_proxy
    state["status"] = 204
    response = client.get(
        REMOTE,
        headers={
            "Cookie": "synthetic-session=private",
            "Authorization": "Bearer synthetic",
            "X-CSRF-Token": "synthetic",
            "X-Forwarded-Method": "DELETE",
            "X-Forwarded-Uri": "/different",
            "X-EOM-Remote-Protocol": "fake",
            "X-EOM-Remote-Origin": "https://spoof.invalid",
            "Origin": "https://testserver.local",
        },
    )
    assert response.status_code == 200 and response.content == b"ok"
    path, headers = state["auth"][-1]
    headers = {key.lower(): value for key, value in headers.items()}
    assert path == AUTH_PATH
    assert headers["x-forwarded-method"] == "GET" and headers["x-forwarded-uri"] == REMOTE
    assert headers["x-eom-remote-protocol"] == "HTTP/1.1"
    assert headers["x-eom-remote-origin"] == "https://testserver.local"
    assert headers["cookie"] == "synthetic-session=private" and "authorization" not in headers
    path, headers = state["remote"][-1]
    assert path == "/vnc.html"
    forbidden = {
        "cookie",
        "authorization",
        "proxy-authorization",
        "x-csrf-token",
        "x-forwarded-method",
        "x-forwarded-uri",
    }
    assert not forbidden.intersection(key.lower() for key in headers)
    assert not any(key.lower().startswith("x-eom-remote-") for key in headers)
    assert "set-cookie" not in response.headers and response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "status,expected", [(200, 503), (202, 503), (302, 503), (401, 401), (403, 403), (503, 503)]
)
def test_only_204_can_forward_to_gateway(caddy_proxy, status, expected):
    client, state = caddy_proxy
    state["status"] = status
    before = len(state["remote"])
    response = client.get(REMOTE)
    assert response.status_code == expected and len(state["remote"]) == before


def test_caddy_denies_public_auth_endpoint_and_preserves_original_query_for_rejection(caddy_proxy):
    client, state = caddy_proxy
    before = len(state["auth"])
    assert client.get(AUTH_PATH, headers={"X-Forwarded-Uri": REMOTE}).status_code == 404
    assert len(state["auth"]) == before
    state["status"] = 403
    assert client.post(REMOTE + "?token=synthetic").status_code == 403
    _, headers = state["auth"][-1]
    headers = {key.lower(): value for key, value in headers.items()}
    assert headers["x-forwarded-method"] == "POST"
    assert headers["x-forwarded-uri"] == REMOTE + "?token=synthetic"


def test_ws_metadata_is_preserved_but_auth_precheck_is_not_an_upgrade(caddy_proxy):
    client, state = caddy_proxy
    state["status"] = 403
    assert (
        client.get(
            "/studio/admin/remote/websockify",
            headers={
                "Connection": "Upgrade",
                "Upgrade": "websocket",
                "Sec-WebSocket-Version": "13",
                "Sec-WebSocket-Key": "MDEyMzQ1Njc4OWFiY2RlZg==",
                "Origin": "https://testserver.local",
            },
        ).status_code
        == 403
    )
    _, headers = state["auth"][-1]
    headers = {key.lower(): value for key, value in headers.items()}
    assert headers["x-eom-remote-upgrade"] == "websocket"
    assert headers["x-eom-remote-connection"] == "Upgrade"
    assert headers["x-eom-remote-version"] == "13"
    assert headers["x-eom-remote-key"] == "MDEyMzQ1Njc4OWFiY2RlZg=="
    assert "upgrade" not in headers and "sec-websocket-key" not in headers
