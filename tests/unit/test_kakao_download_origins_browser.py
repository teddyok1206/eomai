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
PAGE = "/space/synthetic/channel/p/chats/room"
IMAGE = "/api/profiles/p/chats/r/message/photo/image"
CDN = "https://k.kakaocdn.net/synthetic.png?signature=NEVER_PERSIST_QUERY"
HTML = """<!doctype html><html><head><meta charset=utf-8></head><body>
<div class=chat_popup>
 <div class=popup_head><div class=area_util>
   <button class="btn_tooltip btn_util btn_menu"
      onclick="document.querySelector('#menu').hidden=false">메뉴</button>
 </div></div>
 <div class=txt_chat>first line<br>second line<span contenteditable=true>NEVER_CAPTURE</span></div>
 <div class=txt_time>time <span>01:29</span></div>
 <input value=NEVER_CAPTURE_VALUE><textarea>NEVER_CAPTURE_TEXTAREA</textarea>
 <div contenteditable=true>NEVER_CAPTURE_EDITING</div>
 <form><div>NEVER_CAPTURE_FORM</div></form>
 <div style="display:none">NEVER_CAPTURE_HIDDEN</div>
 <button onclick="window.danger++">send</button>
 <button onclick="window.danger++">block</button>
 <div class=item_chat><div class=set_chat>
  <a class=link_pic><img class=thumb_g alt=photo></a>
  <a id=download class=btn_save href="/api/profiles/p/chats/r/message/photo/image">photo</a>
 </div></div>
</div>
<div id=menu class=menu_side_type2 hidden><div class=inner_menu><div class=info_chat>
 <div class="wrap_write wrap_down">
  <strong class=tit_set>대화 내보내기</strong>
  <button class="btn_g_m btn_save" onclick="saveCsv()">내 PC 저장</button>
 </div>
</div></div></div>
<script>
 window.danger=0;
 function saveCsv() {
  const file=document.createElement('a');
  file.href=URL.createObjectURL(new Blob(['DATE,USER,MESSAGE\\n'],{type:'text/csv'}));
  file.download='fixture.csv'; file.click();
 }
</script></body></html>""".encode()


@pytest.mark.parametrize("receiver", ["manual", "scoped", "room"])
def test_real_redirect_event_and_direct_dom_text_with_no_private_subtree(tmp_path, receiver):
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
from eom_kakao_archive_collector.open_room_capture import capture_open_room
from eom_kakao_archive_collector.profile import BrowserRuntimeError
from eom_kakao_archive_collector.room_read_actions import RoomReadAction, trigger_room_read_action
from eom_kakao_archive_collector.room_read_transfer import receive_room_transfer
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_kakao_archive_contracts.manual_download import ManualDownloadResult
from eom_kakao_archive_contracts.manual_observation import ManualPageObservation
async def main():
 with tempfile.TemporaryDirectory(prefix='kakao-redirect-test-',dir=Path.home()/'.cache') as folder:
  root=Path(folder); root.chmod(0o2750)
  if sys.argv[2] == 'manual':
   manager=ManualDownloads(ProfileFence(schema_version='kakao-profile-fence/1.0',
       profile_id='kakaoprofile_'+'1'*32,browser_run_id='kakaobrowserrun_'+'2'*32,
       fence_epoch=1,mode='MANUAL'),root=root)
   incoming=manager.incoming
  else:
   manager=None
   incoming=root/'incoming'; incoming.mkdir(mode=0o700); incoming.chmod(0o700)
   outputs=root/'outputs'; outputs.mkdir(); outputs.chmod(0o750)
  async with async_playwright() as sdk:
   browser=await sdk.chromium.launch(headless=True,channel='chromium',
       downloads_path=str(incoming),proxy={'server':sys.argv[1]},
       args=['--disable-quic','--ignore-certificate-errors',
             '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
   context=await browser.new_context(accept_downloads=True,ignore_https_errors=True)
   page=await context.new_page()
   if manager: manager.subscribe(page)
   await page.goto('https://business.kakao.com/space/synthetic/channel/p/chats/room')
   image_path='/api/profiles/p/chats/r/message/photo/image'
   if manager:
    async with page.expect_download(timeout=10000) as pending:
     assert await trigger_room_read_action(
       page, RoomReadAction.DOWNLOAD_IMAGE, channel_key='p', room_key='r', image_path=image_path)
    await pending.value
    await asyncio.gather(*tuple(manager._tasks)); await asyncio.sleep(0)
    assert manager.failure is None
    paths=list(manager.run.glob('kakaodownload_*/result.json')); assert len(paths)==1
    result=ManualDownloadResult.model_validate_json(paths[0].read_bytes())
    assert result.phase=='RECEIVED', result.error_code
    raw=(paths[0].parent/'page-observation.json').read_bytes()
    value=ManualPageObservation.model_validate_json(raw)
    assert value.status=='OBSERVED'
    assert value.target.kind=='SAME_ORIGIN_PATH'
    assert value.target.path==image_path
    document=value.document
   elif sys.argv[2] == 'scoped':
    destination=outputs/'photo.png'
    received=await receive_room_transfer(
      page, RoomReadAction.DOWNLOAD_IMAGE, channel_key='p', room_key='r',
      image_path=image_path, incoming=incoming, destination=destination)
    assert destination.read_bytes()==b'synthetic download bytes'
    assert received.payload.size_bytes==len(destination.read_bytes())
    assert (outputs/'photo.started').exists()
    document=received.document
    assert document is not None
    raw=document.model_dump_json().encode()
   else:
    capture=await capture_open_room(
      page,channel_key='p',room_key='r',incoming=incoming,outputs=outputs)
    assert capture.error_code is None and capture.csv and len(capture.photos)==1
    assert capture.unresolved_visible_bubbles==0
    assert (outputs/'source.csv').read_bytes()==b'DATE,USER,MESSAGE'+bytes([10])
    photo=capture.photos[0]
    assert (outputs/photo.member_name).read_bytes()==b'synthetic download bytes'
    assert photo.image_path==image_path
    document=photo.transfer.document
    assert document is not None
    raw=document.model_dump_json().encode()
    try:
     await capture_open_room(page,channel_key='p',room_key='r',incoming=incoming,outputs=outputs)
    except BrowserRuntimeError as e:
     assert e.code=='KAKAO_ROOM_TRANSFER_ALREADY_STARTED'
    else:
     raise AssertionError('a prior attempt cannot run twice')
   assert document and not document.truncated
   assert all(word not in raw for word in (
       b'NEVER_CAPTURE',b'NEVER_PERSIST_QUERY',b'k.kakaocdn.net'))
   body=[n.text for n in document.nodes if 'txt_chat' in n.classes]
   assert body==['first line'+chr(10)+'second line'], repr(body)
   assert any(n.text=='01:29' for n in document.nodes)
   assert any(n.text=='time ' for n in document.nodes)
   assert await page.evaluate('window.danger')==0
   if manager: await manager.close()
   await context.close(); await browser.close()
   print(json.dumps({'synthetic_real_chromium_redirect':'PASS','direct_text':'PASS',
       'private_subtrees':'EXCLUDED','dangerous_clicks':0,'live_provider':'NOT_USED'}))
asyncio.run(main())
"""
    with ThreadingHTTPServer(("127.0.0.1", 0), Proxy) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            process = subprocess.run(
                [
                    str(PYTHON),
                    "-B",
                    "-c",
                    script,
                    f"http://127.0.0.1:{server.server_port}",
                    receiver,
                ],
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
