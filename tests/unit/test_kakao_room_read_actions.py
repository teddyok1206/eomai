"""Only an isolated synthetic browser may exercise these provider-shaped controls."""

import asyncio
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from eom_kakao_archive_collector.profile import BrowserRuntimeError
from eom_kakao_archive_collector.room_read_actions import RoomReadAction, trigger_room_read_action

from tests.unit.test_kakao_download_origins_browser import BROWSERS, PYTHON, ROOT

IMAGE = "/api/profiles/channel/chats/room/msg/file/image"


def test_invalid_action_is_not_evaluated_and_uncertain_is_not_retried():
    page = AsyncMock()
    with pytest.raises(BrowserRuntimeError, match="ACTION_INVALID"):
        asyncio.run(
            trigger_room_read_action(
                page,
                RoomReadAction.DOWNLOAD_IMAGE,
                channel_key="channel",
                room_key="room",
                image_path="https://other.invalid/" + IMAGE,
            )
        )
    page.evaluate.assert_not_awaited()
    page.evaluate.side_effect = OSError("not for logs")
    with pytest.raises(BrowserRuntimeError, match="ACTION_UNCERTAIN"):
        asyncio.run(
            trigger_room_read_action(
                page, RoomReadAction.EXPORT_CSV, channel_key="channel", room_key="room"
            )
        )
    page.evaluate.assert_awaited_once()


def test_fixed_room_controls_in_chromium_with_no_external_network(tmp_path: Path):
    if not PYTHON.is_file() or not BROWSERS.is_dir():
        pytest.skip("explicit installed Chromium fixture is unavailable")
    program = r"""
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright
from eom_kakao_archive_collector.profile import BrowserRuntimeError
from eom_kakao_archive_collector.room_read_actions import RoomReadAction as A
from eom_kakao_archive_collector.room_read_actions import trigger_room_read_action
from eom_kakao_archive_collector.room_read_transfer import receive_room_transfer

URL='https://business.kakao.com/space/work/channel/channel/chats'
IMAGE='/api/profiles/channel/chats/room/msg/file/image'
HTML='''<!doctype html><html lang="ko"><meta charset="utf-8">
<style>button,a { display:inline-block; padding:8px; }</style>
<div class="chat_popup">
  <div class="popup_head"><div class="area_util">
    <button class="btn_tooltip btn_util btn_menu" id="menu-button">방 메뉴</button>
  </div></div>
  <div class="item_chat"><div class="set_chat">
    <a class="link_pic item_expiry"><img class="thumb_g" alt="사진"></a>
    <a class="btn_save" id="photo" href="'''+IMAGE+'''" download>다운로드</a>
  </div></div>
  <button onclick="danger++">메시지 전송</button>
  <button onclick="danger++">상담 종료</button>
</div>
<div class="menu_side_type2" id="menu" hidden>
<div class="inner_menu"><div class="info_chat">
  <div class="wrap_write">
    <button class="btn_g_m btn_save" onclick="danger++">다른 기능</button>
  </div>
  <div class="wrap_write wrap_down">
    <strong class="tit_set">대화 내보내기</strong>
    <button class="btn_g_m btn_save" id="export">내 PC 저장</button>
  </div>
</div></div></div>
<script>
window.danger=0; window.intended={menu:0, csv:0, photo:0};
document.querySelector('#menu-button').onclick=()=>{
  intended.menu++; document.querySelector('#menu').hidden=false;
};
document.querySelector('#export').onclick=()=>{
  intended.csv++;
  const file=document.createElement('a'); file.download='fixture.csv';
  file.href=URL.createObjectURL(new Blob(['DATE,USER,MESSAGE\\n'],{type:'text/csv'})); file.click();
};
document.querySelector('#photo').onclick=(event)=>{
  event.preventDefault(); intended.photo++;
  const file=document.createElement('a'); file.download='fixture.png';
  file.href=URL.createObjectURL(new Blob(['synthetic fixture'])); file.click();
};
</script>'''

async def main():
  workspace=Path(sys.argv[1])
  incoming=workspace/'incoming'; incoming.mkdir(mode=0o700)
  outputs=workspace/'outputs'; outputs.mkdir(); outputs.chmod(0o750)
  async with async_playwright() as sdk:
    chromium=await sdk.chromium.launch(
        headless=True, channel='chromium', downloads_path=str(incoming),
        args=['--disable-quic', '--host-resolver-rules=MAP * ~NOTFOUND'])
    context=await chromium.new_context(service_workers='block', accept_downloads=True)
    async def route(request):
      if request.request.url == URL:
        await request.fulfill(status=200, content_type='text/html; charset=utf-8', body=HTML)
      else:
        await request.abort()
    await context.route('**/*',route)
    page=await context.new_page()
    async def act(action, room='room', path=None):
      return await trigger_room_read_action(
          page, action, channel_key='channel', room_key=room, image_path=path)
    async def refuse(action, room='room', path=None):
      try:
        await act(action,room,path)
      except BrowserRuntimeError as e:
        assert e.code == 'KAKAO_ROOM_READ_ACTION_UNAVAILABLE', e.code
      else:
        raise AssertionError('unsafe control was not refused')
    async def counts():
      assert await page.evaluate('window.danger') == 0
      return await page.evaluate('window.intended')

    await page.goto(URL)
    await refuse(A.OPEN_EXPORT_MENU,room='unwanted')
    await refuse(A.EXPORT_CSV)
    assert await act(A.OPEN_EXPORT_MENU)
    assert await act(A.OPEN_EXPORT_MENU) is False
    await page.locator('#export').evaluate("(button)=>button.textContent='상담 종료'")
    await refuse(A.EXPORT_CSV)
    await page.locator('#export').evaluate("(button)=>button.textContent='내 PC 저장'")
    await page.locator('#export').evaluate("(b)=>b.parentNode.append(b.cloneNode(true))")
    await refuse(A.EXPORT_CSV)
    await page.locator('button#export').last.evaluate("(b)=>b.remove()")
    await page.evaluate("()=>{ const cover=document.createElement('div'); cover.id='cover';"
        "cover.style='position:fixed;inset:0;z-index:10'; document.body.append(cover); }")
    await refuse(A.EXPORT_CSV)
    await page.locator('#cover').evaluate("(element)=>element.remove()")
    csv=outputs/'source.csv'
    result=await receive_room_transfer(
        page,A.EXPORT_CSV,channel_key='channel',room_key='room',incoming=incoming,destination=csv)
    assert csv.read_bytes() == b'DATE,USER,MESSAGE\n' and result.payload.size_bytes == 18
    assert result.document is not None
    await refuse(A.DOWNLOAD_IMAGE,path=IMAGE)
    await page.locator('#menu').evaluate("(node)=>node.hidden=true")
    await page.locator('#photo').evaluate("(a)=>a.href+='?signed=not-allowed'")
    await refuse(A.DOWNLOAD_IMAGE,path=IMAGE)
    await page.locator('#photo').evaluate("(a)=>a.href=a.href.split('?')[0]")
    async with page.expect_download(timeout=5000) as image:
      assert await act(A.DOWNLOAD_IMAGE,path=IMAGE)
    assert (await (await image.value).path()).read_bytes() == b'synthetic fixture'
    assert await counts() == {'menu':1,'csv':1,'photo':1}
    await page.locator('#photo').evaluate("(a)=>a.setAttribute('contenteditable','true')")
    await refuse(A.DOWNLOAD_IMAGE,path=IMAGE)
    await page.locator('#photo').evaluate("(a)=>a.removeAttribute('contenteditable')")
    await page.locator('.chat_popup').evaluate(
        "(node)=>node.parentNode.append(node.cloneNode(true))")
    await refuse(A.OPEN_EXPORT_MENU)
    assert await counts() == {'menu':1,'csv':1,'photo':1}
    await context.close()
    await chromium.close()
asyncio.run(main())
"""
    with tempfile.TemporaryDirectory(
        prefix="kakao-room-actions-", dir=Path.home() / ".cache"
    ) as workspace:
        process = subprocess.run(
            [str(PYTHON), "-B", "-c", program, workspace],
            cwd=tmp_path,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(Path.home()),
                "LANG": "C.UTF-8",
                "PYTHONNOUSERSITE": "1",
                "PLAYWRIGHT_BROWSERS_PATH": str(BROWSERS),
                "PYTHONPATH": str(ROOT / "services/kakao_archive_collector"),
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            umask=0o077,
        )
    assert process.returncode == 0, process.stderr
