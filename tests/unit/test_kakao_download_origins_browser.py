"""Real Chromium, loopback TLS proxy and synthetic input. No live provider/profile."""

import json
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path("/opt/eom/conda/envs/eom-kakao-browser/bin/python")
BROWSERS = Path("/opt/eom/kakao-browser/playwright-1.65.2")
PAGE = "/space/synthetic/channel/example/chats/room"
IMAGE = "/api/profiles/p/chats/r/message/photo/image"
CDN = "https://k.kakaocdn.net/synthetic.png?signature=NEVER_PERSIST_QUERY"
HTML = b"""<!doctype html><html><head><meta charset=utf-8></head><body>
<div class=chat_popup>
 <div class=txt_chat>first line<br>second line<span contenteditable=true>NEVER_CAPTURE</span></div>
 <div class=txt_time>time <span>01:29</span></div>
 <input value=NEVER_CAPTURE_VALUE><textarea>NEVER_CAPTURE_TEXTAREA</textarea>
 <div contenteditable=true>NEVER_CAPTURE_EDITING</div>
 <form><div>NEVER_CAPTURE_FORM</div></form>
 <div style="display:none">NEVER_CAPTURE_HIDDEN</div>
 <button onclick="window.danger++">send</button>
 <button onclick="window.danger++">block</button>
 <a id=download class=btn_save href="/api/profiles/p/chats/r/message/photo/image">photo</a>
</div><script>window.danger=0;</script></body></html>"""


def test_real_redirect_event_and_direct_dom_text_with_no_private_subtree(tmp_path):
    if not PYTHON.is_file() or not BROWSERS.is_dir():
        pytest.skip("explicit installed browser environment is unavailable")
    key, certificate = tmp_path / "fixture.key", tmp_path / "fixture.crt"
    subprocess.run(
        [
            "/usr/bin/openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
            "-days",
            "1",
            "-subj",
            "/CN=synthetic-kakao-test",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
    )
    key.chmod(0o600)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, key)

    class Origin(BaseHTTPRequestHandler):
        def do_GET(self):
            host = self.headers.get("Host")
            if host == "business.kakao.com" and self.path == PAGE:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                body = HTML
            elif host == "business.kakao.com" and self.path == IMAGE:
                self.send_response(302)
                self.send_header("Location", CDN)
                body = b""
            elif (
                host == "k.kakaocdn.net"
                and self.path == "/synthetic.png?signature=NEVER_PERSIST_QUERY"
            ):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", "attachment; filename=synthetic.png")
                body = b"synthetic download bytes"
            else:
                self.send_response(403)
                body = b""
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass  # URLs and body are never test logs.

    class Proxy(BaseHTTPRequestHandler):
        def do_CONNECT(self):
            if self.path not in {"business.kakao.com:443", "k.kakaocdn.net:443"}:
                self.send_error(403)
                return
            self.connection.settimeout(10)
            self.send_response(200)
            self.end_headers()
            self.wfile.flush()
            try:
                with tls.wrap_socket(self.connection, server_side=True) as secured:
                    Origin(secured, self.client_address, self.server)
            except ssl.SSLError:
                return  # A synthetic browser probe can abandon an optional TLS connection.

        def log_message(self, *_args):
            pass

    script = r"""
import asyncio, json, sys, tempfile
from pathlib import Path
from playwright.async_api import async_playwright
from eom_kakao_archive_collector.manual_download import ManualDownloads
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_kakao_archive_contracts.manual_download import ManualDownloadResult
from eom_kakao_archive_contracts.manual_observation import ManualPageObservation
async def main():
 with tempfile.TemporaryDirectory(prefix='kakao-redirect-test-',dir=Path.home()/'.cache') as folder:
  root=Path(folder); root.chmod(0o2750)
  manager=ManualDownloads(ProfileFence(schema_version='kakao-profile-fence/1.0',
      profile_id='kakaoprofile_'+'1'*32,browser_run_id='kakaobrowserrun_'+'2'*32,
      fence_epoch=1,mode='MANUAL'),root=root)
  async with async_playwright() as sdk:
   browser=await sdk.chromium.launch(headless=True,channel='chromium',
       downloads_path=str(manager.incoming),proxy={'server':sys.argv[1]},
       args=['--disable-quic','--ignore-certificate-errors',
             '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
   context=await browser.new_context(accept_downloads=True,ignore_https_errors=True)
   page=await context.new_page()
   manager.subscribe(page)
   await page.goto('https://business.kakao.com/space/synthetic/channel/example/chats/room')
   async with page.expect_download(timeout=10000) as pending:
    await page.locator('#download').click()
   await pending.value
   await asyncio.gather(*tuple(manager._tasks)); await asyncio.sleep(0)
   assert manager.failure is None
   paths=list(manager.run.glob('kakaodownload_*/result.json')); assert len(paths)==1
   result=ManualDownloadResult.model_validate_json(paths[0].read_bytes())
   assert result.phase=='RECEIVED', result.error_code
   raw=(paths[0].parent/'page-observation.json').read_bytes()
   value=ManualPageObservation.model_validate_json(raw)
   assert value.status=='OBSERVED' and value.document and not value.document.truncated
   assert value.target.kind=='SAME_ORIGIN_PATH'
   assert value.target.path=='/api/profiles/p/chats/r/message/photo/image'
   assert all(word not in raw for word in (
       b'NEVER_CAPTURE',b'NEVER_PERSIST_QUERY',b'k.kakaocdn.net'))
   body=[n.text for n in value.document.nodes if 'txt_chat' in n.classes]
   assert body==['first line'+chr(10)+'second line'], repr(body)
   assert any(n.text=='01:29' for n in value.document.nodes)
   assert any(n.text=='time ' for n in value.document.nodes)
   assert await page.evaluate('window.danger')==0
   await manager.close(); await context.close(); await browser.close()
   print(json.dumps({'synthetic_real_chromium_redirect':'PASS','direct_text':'PASS',
       'private_subtrees':'EXCLUDED','dangerous_clicks':0,'live_provider':'NOT_USED'}))
asyncio.run(main())
"""
    with ThreadingHTTPServer(("127.0.0.1", 0), Proxy) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            process = subprocess.run(
                [str(PYTHON), "-B", "-c", script, f"http://127.0.0.1:{server.server_port}"],
                cwd=tmp_path,
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": str(Path.home()),
                    "LANG": "C.UTF-8",
                    "TZ": "UTC",
                    "PYTHONNOUSERSITE": "1",
                    "PLAYWRIGHT_BROWSERS_PATH": str(BROWSERS),
                    "PYTHONPATH": ":".join(
                        str(ROOT / name)
                        for name in (
                            "packages/kakao_archive_contracts",
                            "services/kakao_archive_collector",
                        )
                    ),
                },
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
                umask=0o077,
            )
        finally:
            server.shutdown()
            thread.join(timeout=3)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["synthetic_real_chromium_redirect"] == "PASS"
