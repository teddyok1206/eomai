"""Real Chromium, loopback TLS proxy and synthetic input. No live provider/profile."""

import json
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.unit.test_kakao_capture_contracts import command, inventory

ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path("/opt/eom/conda/envs/eom-kakao-browser/bin/python")
BROWSERS = Path("/opt/eom/kakao-browser/playwright-1.65.2")
PAGE = "/space/synthetic/channel/p/chats/room"
LIST = "/space/synthetic/channel/p/chats"
POPUP = LIST + "/r"
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
AUTO_HTML = HTML.replace(
    b"<div class=chat_popup>",
    b"""<ul class=list_chat>
      <li data-chat-id=other><button type=button data-chat-id=other
           onclick="window.danger++">Same name</button></li>
      <li data-chat-id=r><button type=button data-chat-id=r
           onclick="window.roomClicks++; document.querySelector('.chat_popup').hidden=false">
           Same name</button></li>
    </ul><script>window.roomClicks=0;</script><div class=chat_popup hidden>""",
    1,
)
PHOTO_NODE = HTML.split(b"<div class=item_chat>", 1)[1].split(b"<div id=menu", 1)[0]
TEXT_ONLY = AUTO_HTML.replace(
    b"<div class=item_chat>" + PHOTO_NODE,
    b"</div>",
    1,
).replace(b"<div class=chat_popup hidden>", b"<div class=chat_popup data-chat-id=r hidden>")


@pytest.mark.parametrize(
    "receiver",
    [
        "manual",
        "manual-direct-cdn",
        "manual-dom-link",
        "manual-dom-preview",
        "manual-dom-other-query",
        "manual-dom-multiple",
        "scoped",
        "room",
        "room-direct-cdn",
        "room-direct-link",
        "room-direct-preview",
        "room-direct-other-query",
        "room-direct-duplicate",
        "auto",
        "auto-persistent",
        "auto-persistent-other-page",
        "auto-text",
        "auto-popup",
        "auto-wrong-popup",
    ],
)
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
            route = urlsplit(self.path).path
            if (
                host == "business.kakao.com"
                and route == LIST
                and receiver == "auto-persistent-other-page"
            ):
                self.send_response(302)
                self.send_header("Location", "/synthetic-sign-in")
                body = b""
            elif host == "business.kakao.com" and route == "/synthetic-sign-in":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                body = b"<!doctype html><title>Synthetic sign-in page</title>"
            elif host == "business.kakao.com" and route in {PAGE, LIST, POPUP}:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                body = (
                    (TEXT_ONLY if receiver == "auto-text" else AUTO_HTML) if route == LIST else HTML
                )
                if route == LIST and receiver in {
                    "auto-popup",
                    "auto-wrong-popup",
                    "auto-persistent",
                }:
                    opened = PAGE if receiver == "auto-wrong-popup" else POPUP
                    body = body.replace(
                        b"document.querySelector('.chat_popup').hidden=false",
                        f"window.open('{opened}?tracking=fixture','selected')".encode(),
                    )
                if (
                    route == PAGE
                    and (receiver == "manual-direct-cdn" or receiver.startswith("room-direct-"))
                ) or (route == POPUP and receiver.startswith("manual-dom-")):
                    body = body.replace(
                        b"window.danger=0;",
                        (
                            "window.danger=0;document.getElementById('download').addEventListener("
                            "'click',e=>{e.preventDefault();location.assign('" + CDN + "');});"
                        ).encode(),
                    )
                if (route == POPUP and receiver.startswith("manual-dom-")) or (
                    route == PAGE
                    and receiver.startswith("room-direct-")
                    and receiver != "room-direct-cdn"
                ):
                    display = CDN + ("&different=1" if receiver.endswith("-other-query") else "")
                    if receiver.endswith("-preview"):
                        body = body.replace(
                            b"<img class=thumb_g alt=photo>",
                            f'<img class=thumb_g alt=photo src="{display}">'.encode(),
                            1,
                        )
                    else:
                        body = body.replace(
                            b"<a class=link_pic>",
                            f'<a class=link_pic href="{display}">'.encode(),
                            1,
                        )
                    if receiver in {"manual-dom-multiple", "room-direct-duplicate"}:
                        body = body.replace(
                            b"</div></div>\n</div>\n<div id=menu",
                            (
                                "</div></div><div class=item_chat><div class=set_chat>"
                                f'<a class=link_pic href="{CDN}">'
                                "<img class=thumb_g alt=photo></a><a class=btn_save "
                                'href="/api/profiles/p/chats/r/elsewhere/another/image">photo</a>'
                                "</div></div></div><div id=menu"
                            ).encode(),
                            1,
                        )
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
from types import SimpleNamespace
from unittest.mock import patch
from playwright.async_api import async_playwright
from eom_kakao_archive_collector import manual_driver
from eom_kakao_archive_collector.auto_room_browser import read_registered_room
from eom_kakao_archive_collector.manual_download import ManualDownloads
from eom_kakao_archive_collector.open_room_capture import capture_open_room_attempt
from eom_kakao_archive_collector.profile import BrowserRuntimeError
from eom_kakao_archive_collector.room_read_actions import RoomReadAction, trigger_room_read_action
from eom_kakao_archive_collector.room_read_transfer import receive_room_transfer
from eom_kakao_archive_contracts.auto_room_command import AutoRoomCommand
from eom_kakao_archive_contracts.capture import CaptureCommand
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_kakao_archive_contracts.manual_download import ManualDownloadResult
from eom_kakao_archive_contracts.manual_observation import ManualPageObservation
from eom_kakao_archive_contracts.open_room_download import OpenRoomDownloadReceipt
from eom_kakao_archive_contracts.render import canonical_bytes, sha256

async def persistent_auto(command, root, incoming, outputs):
 request=AutoRoomCommand(command=command,space_key='synthetic',channel_key='p',room_key='r')
 profile=root/'empty-profile'; profile.mkdir(mode=0o700)
 start=manual_driver._start_playwright
 async def with_loopback_proxy():
  sdk=await start()
  chromium=sdk.chromium
  async def launch(profile_path, **options):
   assert profile_path==str(profile) and options['env']['HOME']==str(profile)
   assert options['headless'] and options['chromium_sandbox'] and options['accept_downloads']
   assert options['executable_path']==chromium.executable_path
   # Only this fixture supplies a proxy/certificate exception. DNS stays isolated.
   return await chromium.launch_persistent_context(profile_path, **options,
       proxy={'server':sys.argv[1]},ignore_https_errors=True,
       args=['--disable-quic','--ignore-certificate-errors',
             '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
  return SimpleNamespace(stop=sdk.stop,chromium=SimpleNamespace(
      executable_path=chromium.executable_path,launch_persistent_context=launch))
 async def fixed_command(fence, stopping):
  assert not stopping.is_set() and fence==command.execution.fence
  return request
 with patch.object(manual_driver,'_start_playwright',with_loopback_proxy), \
      patch.object(manual_driver,'wait_for_room_command',fixed_command), \
      patch.object(manual_driver,'stage_room_workspace',lambda _: (incoming,outputs)), \
      patch.object(manual_driver.setup,'require_supervisor'), \
      patch.object(manual_driver.setup,'PROFILE',profile):
  sdk=await start()
  try:
   digest=manual_driver.setup.hash_executable(Path(sdk.chromium.executable_path))
  finally:
   await sdk.stop()
  config=manual_driver.setup.AutoSetup(command.execution.fence,digest)
  if sys.argv[2]=='auto-persistent-other-page':
   try:
    await manual_driver.run_auto(config,asyncio.Event())
   except BrowserRuntimeError as error:
    assert error.code=='KAKAO_AUTO_CHANNEL_NOT_CONFIRMED'
   else:
    raise AssertionError('a different page must not be read')
   assert not tuple(outputs.iterdir())
   print(json.dumps({'synthetic_real_chromium_redirect':'PASS','persistent_auto':'REFUSED'}))
   return
  await manual_driver.run_auto(config,asyncio.Event())
 evidence=(outputs/'open-room.json').read_bytes()
 proof=OpenRoomDownloadReceipt.decode(evidence)
 assert proof.command_sha256==sha256(canonical_bytes(command.model_dump(mode='json')))
 assert proof.raw_csv.sha256==sha256((outputs/'source.csv').read_bytes())
 assert len(proof.photos)==1 and proof.unresolved_visible_bubbles==0
 photo=proof.photos[0]
 assert photo.document.path=='/space/synthetic/channel/p/chats/r'
 assert photo.target=='/api/profiles/p/chats/r/message/photo/image'
 assert photo.sha256==sha256((outputs.parent/photo.relative_path).read_bytes())
 assert b'NEVER_PERSIST_QUERY' not in evidence
 print(json.dumps({'synthetic_real_chromium_redirect':'PASS','persistent_auto':'PASS'}))

async def main():
 command=CaptureCommand.model_validate_json(sys.argv[3])
 with tempfile.TemporaryDirectory(prefix='kakao-redirect-test-',dir=Path.home()/'.cache') as folder:
  root=Path(folder); root.chmod(0o2750)
  if sys.argv[2].startswith('manual'):
   manager=ManualDownloads(ProfileFence(schema_version='kakao-profile-fence/1.0',
       profile_id='kakaoprofile_'+'1'*32,browser_run_id='kakaobrowserrun_'+'2'*32,
       fence_epoch=1,mode='MANUAL'),root=root)
   incoming=manager.incoming
  else:
   manager=None
   incoming=root/'incoming'; incoming.mkdir(mode=0o700); incoming.chmod(0o700)
   outputs=root/command.execution.attempt_id/'outputs'; outputs.mkdir(parents=True)
   outputs.chmod(0o750)
  if sys.argv[2].startswith('auto-persistent'):
   await persistent_auto(command,root,incoming,outputs)
   return
  async with async_playwright() as sdk:
   browser=await sdk.chromium.launch(headless=True,channel='chromium',
       downloads_path=str(incoming),proxy={'server':sys.argv[1]},
       args=['--disable-quic','--ignore-certificate-errors',
             '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
   context=await browser.new_context(accept_downloads=True,ignore_https_errors=True)
   page=await context.new_page()
   if manager: manager.subscribe(page)
   if not sys.argv[2].startswith('auto'):
    suffix='r' if sys.argv[2].startswith('manual-dom-') else 'room'
    await page.goto('https://business.kakao.com/space/synthetic/channel/p/chats/'+suffix)
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
    if sys.argv[2]=='manual-direct-cdn' or sys.argv[2].startswith('manual-dom-'):
     assert value.target.kind=='UNAVAILABLE' and value.target.path is None
     assert (paths[0].parent/'payload.bin').read_bytes()==b'synthetic download bytes'
     decision=(paths[0].parent/'origin-diagnostic.txt').read_text()
     assert decision==('KAKAO_DOWNLOAD_ORIGIN mode=MANUAL '
        'code=INITIAL_PHOTO_REQUEST_NOT_OBSERVED candidates=0 '
        'source_get=NOT_CONFIRMED final_same_page=1 final_other_page=0'+chr(10))
     expected={'manual-direct-cdn':'UNAVAILABLE','manual-dom-link':'PHOTO_LINK',
               'manual-dom-preview':'DISPLAYED_IMAGE','manual-dom-other-query':'NONE',
               'manual-dom-multiple':'MULTIPLE_CARDS'}
     assert (paths[0].parent/'photo-dom-diagnostic.txt').read_text()==expected[sys.argv[2]]+chr(10)
    else:
     assert value.target.kind=='SAME_ORIGIN_PATH' and value.target.path==image_path
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
   elif sys.argv[2].startswith('room-direct-'):
    capture=await capture_open_room_attempt(
      page,command,channel_key='p',room_key='r',incoming=incoming,outputs=outputs)
    assert capture.error_code is None and capture.csv is not None, capture.error_code
    proof=OpenRoomDownloadReceipt.decode((outputs/'open-room.json').read_bytes())
    accepted=sys.argv[2] in {'room-direct-link','room-direct-preview'}
    if accepted:
     assert len(capture.photos)==len(proof.photos)==1
     assert capture.unresolved_visible_bubbles==proof.unresolved_visible_bubbles==0
     photo=proof.photos[0]
     assert photo.target==image_path
     assert (outputs.parent/photo.relative_path).read_bytes()==b'synthetic download bytes'
     assert photo.sha256==sha256((outputs.parent/photo.relative_path).read_bytes())
    else:
     missing=2 if sys.argv[2]=='room-direct-duplicate' else 1
     assert not capture.photos and not proof.photos
     assert capture.unresolved_visible_bubbles==proof.unresolved_visible_bubbles==missing
     assert not (outputs/'photo-1.bin').exists()
    assert b'NEVER_PERSIST_QUERY' not in (outputs/'open-room.json').read_bytes()
    assert (outputs/'source.csv').read_bytes()==b'DATE,USER,MESSAGE'+bytes([10])
    assert proof.raw_csv.sha256==sha256((outputs/'source.csv').read_bytes())
    assert await page.evaluate('window.danger')==0
    await context.close(); await browser.close()
    print(json.dumps({'synthetic_real_chromium_redirect':'PASS',
        'direct_cdn':'MATCHED' if accepted else 'UNRESOLVED'}))
    return
   else:
    if sys.argv[2].startswith('auto'):
     request=AutoRoomCommand(command=command,space_key='synthetic',channel_key='p',room_key='r')
     if sys.argv[2]=='auto-wrong-popup':
      try:
       await read_registered_room(page,request,incoming=incoming,outputs=outputs)
      except BrowserRuntimeError as error:
       assert error.code=='KAKAO_AUTO_ROOM_SELECTOR_UNVERIFIED'
      else:
       raise AssertionError('wrong popup must not be read')
      assert await page.evaluate('window.roomClicks')==1
      assert await page.evaluate('window.danger')==0
      assert not tuple(outputs.iterdir())
      await context.close(); await browser.close()
      print(json.dumps({'synthetic_real_chromium_redirect':'PASS','wrong_popup':'REFUSED'}))
      return
     await read_registered_room(page,request,incoming=incoming,outputs=outputs)
     assert await page.evaluate('window.roomClicks')==1
    else:
     capture=await capture_open_room_attempt(
       page,command,channel_key='p',room_key='r',incoming=incoming,outputs=outputs)
     assert capture.error_code is None and capture.csv and len(capture.photos)==1
     assert capture.unresolved_visible_bubbles==0
    evidence=(outputs/'open-room.json').read_bytes()
    proof=OpenRoomDownloadReceipt.decode(evidence)
    assert (outputs/'source.csv').read_bytes()==b'DATE,USER,MESSAGE'+bytes([10])
    if sys.argv[2]=='auto-text':
     assert not proof.photos and not (outputs/'photo-1.bin').exists()
     document=proof.csv_document
    else:
     photo=proof.photos[0]
     assert (outputs.parent/photo.relative_path).read_bytes()==b'synthetic download bytes'
     assert photo.target==image_path
     assert photo.sha256==sha256((outputs.parent/photo.relative_path).read_bytes())
     document=photo.document
    assert document is not None
    if sys.argv[2]=='auto-popup':
     assert document.path=='/space/synthetic/channel/p/chats/r'
    raw=document.model_dump_json().encode()
    assert proof.command_sha256==sha256(canonical_bytes(command.model_dump(mode='json')))
    assert proof.raw_csv.sha256==sha256((outputs/'source.csv').read_bytes())
    attempt_page=page if sys.argv[2]!='auto-popup' else context.pages[-1]
    try:
     await capture_open_room_attempt(
       attempt_page,command,channel_key='p',room_key='r',incoming=incoming,outputs=outputs)
    except BrowserRuntimeError as e:
     assert e.code=='KAKAO_ROOM_TRANSFER_ALREADY_STARTED'
    else:
     raise AssertionError('a prior attempt cannot run twice')
    assert (outputs/'open-room.json').read_bytes()==evidence
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
                    command(inventory=inventory()).model_dump_json(),
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
    result = json.loads(process.stdout)
    assert result["synthetic_real_chromium_redirect"] == "PASS"
    if receiver == "auto-persistent":
        assert result["persistent_auto"] == "PASS"
    elif receiver == "auto-persistent-other-page":
        assert result["persistent_auto"] == "REFUSED"
