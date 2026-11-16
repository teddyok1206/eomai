"""Opt-in actual installed Chromium using only anonymous local data-URL downloads."""

import os
import subprocess
from pathlib import Path

import pytest


def test_real_downloads_remain_after_context_close_without_external_site_or_profile():
    if os.environ.get("EOM_KAKAO_BROWSER_DOWNLOAD_TESTS") != "1":
        pytest.skip("opt in to anonymous installed Chromium download test")
    root = Path(__file__).resolve().parents[2]
    browser_python = Path("/opt/eom/conda/envs/eom-kakao-browser/bin/python")
    assert browser_python.is_file()
    program = r"""
import asyncio, json, os, tempfile
from pathlib import Path
from urllib.parse import quote
from playwright.async_api import async_playwright
from eom_kakao_archive_collector.manual_download import ManualDownloads
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_kakao_archive_contracts.manual_download import ManualDownloadResult
from eom_kakao_archive_contracts.render import sha256
os.umask(0o077)

async def main():
    with tempfile.TemporaryDirectory(
        prefix='eom-kakao-browser-download-',dir=Path.home()/'.cache') as tmp:
        base=Path(tmp); downloads=base/'downloads'
        downloads.mkdir(mode=0o2750);downloads.chmod(0o2750)
        fence=ProfileFence.model_validate(dict(schema_version='kakao-profile-fence/1.0',
            profile_id='kakaoprofile_'+'a'*32,browser_run_id='kakaobrowserrun_'+'b'*32,fence_epoch=1,mode='MANUAL'))
        manager=ManualDownloads(fence,root=downloads)
        raw='DATE,USER,MESSAGE\n2026-11-16 00:00:00,anonymous,synthetic question\n'.encode()
        async with async_playwright() as p:
            context=await p.chromium.launch_persistent_context(str(base/'empty-profile'),
                executable_path=p.chromium.executable_path,
                headless=True,chromium_sandbox=True,accept_downloads=True,downloads_path=str(manager.incoming))
            context.on('page',manager.subscribe)
            for page in context.pages:manager.subscribe(page)
            page=context.pages[0]
            for _ in range(2):
                html=('<a id="download" download="same.csv" href="data:text/csv;charset=utf-8,'
                    +quote(raw)+'">anonymous download</a>')
                await page.set_content(html)
                async with page.expect_download():
                    await page.locator('#download').click()
                await asyncio.gather(*tuple(manager._tasks))
                assert manager.failure is None
            await manager.close()
            await context.close()
        receipts=list(manager.run.glob('kakaodownload_*/result.json'))
        assert len(receipts)==2
        for receipt in receipts:
            result=ManualDownloadResult.model_validate_json(receipt.read_bytes())
            assert result.phase=='RECEIVED', result.model_dump(mode='json')
            assert result.member.sha256==sha256(raw)
            assert (receipt.parent/'payload.bin').read_bytes()==raw
        assert len({receipt.parent.name for receipt in receipts})==2
        print('ACTUAL_CHROMIUM_DOWNLOAD_CONTEXT_CLOSE=PASS captures=2 external_requests=0')

asyncio.run(main())
"""
    result = subprocess.run(
        [str(browser_python), "-B", "-c", program],
        cwd=root,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(Path.home()),
            "LANG": "C.UTF-8",
            "TZ": "UTC",
            "PLAYWRIGHT_BROWSERS_PATH": "/opt/eom/kakao-browser/playwright-1.65.2",
            "PYTHONPATH": ":".join(
                str(root / p)
                for p in (
                    "packages/kakao_archive_contracts",
                    "services/kakao_archive_collector",
                )
            ),
        },
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ACTUAL_CHROMIUM_DOWNLOAD_CONTEXT_CLOSE=PASS" in result.stdout


def test_real_read_only_document_observation_excludes_credentials_and_bounds_all_dom_visits():
    if os.environ.get("EOM_KAKAO_BROWSER_DOWNLOAD_TESTS") != "1":
        pytest.skip("opt in to anonymous installed Chromium document test")
    root = Path(__file__).resolve().parents[2]
    program = r'''
import asyncio, json, os, tempfile, time
from pathlib import Path
from playwright.async_api import async_playwright
from eom_kakao_archive_collector.manual_download import ManualDownloads
from eom_kakao_archive_collector.manual_observation import (
    DOCUMENT_EXPRESSION, download_page_path, observe_download_page)
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_kakao_archive_contracts.manual_download import ManualDownloadResult, ManualDownloadStart
from eom_kakao_archive_contracts.manual_observation import ManualPageObservation
os.umask(0o077)
html = """<!doctype html><html><body>
<h1>익명 합성 화면</h1>
<button onclick="window.danger++">전송</button>
<button onclick="window.danger++">차단하기</button>
<button onclick="window.danger++">상담 완료</button>
<div class="message" data-message-id="one"><span>동일한 질문</span></div>
<div class="message" data-message-id="two"><span>동일한 질문</span></div>
<a href="/api/profiles/example/chats/room/logs/one/image?credential=NEVER_OUTPUT#secret">
사진 다운로드</a>
<img alt="사진"
 src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">
<input type="password" value="NEVER_OUTPUT-password">
<textarea>NEVER_OUTPUT-textarea</textarea>
<form><span>NEVER_OUTPUT-form</span></form>
<div contenteditable="true">NEVER_OUTPUT-editor</div>
<div style="display:none">NEVER_OUTPUT-hidden</div>
<script type="application/json">NEVER_OUTPUT-script</script>
<svg><script type="application/json">NEVER_OUTPUT-svg-script</script></svg>
<span data-token="NEVER_OUTPUT-token">안전한 문자열</span>
<a id="download" download="anonymous.csv">합성 파일</a>
<script>window.danger=0;
document.getElementById('download').href=URL.createObjectURL(new Blob([
'DATE,USER,MESSAGE\\n2026-11-16 00:00:00,anonymous,synthetic\\n'],{type:'text/csv'}));
</script></body></html>"""

async def main():
    with tempfile.TemporaryDirectory(prefix='eom-kakao-dom-',dir=Path.home()/'.cache') as tmp:
        base=Path(tmp); downloads=base/'downloads'
        downloads.mkdir(mode=0o2750);downloads.chmod(0o2750)
        fence=ProfileFence.model_validate(dict(schema_version='kakao-profile-fence/1.0',
            profile_id='kakaoprofile_'+'a'*32,browser_run_id='kakaobrowserrun_'+'b'*32,
            fence_epoch=1,mode='MANUAL'))
        manager=ManualDownloads(fence,root=downloads)
        async with async_playwright() as p:
            context=await p.chromium.launch_persistent_context(str(base/'empty-profile'),
                executable_path=p.chromium.executable_path,headless=True,chromium_sandbox=True,
                accept_downloads=True,downloads_path=str(manager.incoming),service_workers='block')
            async def intercept(route):
                if route.request.url=='https://business.kakao.com/space/synthetic/channel/example/chats/room':
                    await route.fulfill(status=200,
                        content_type='text/html; charset=utf-8',body=html)
                else:
                    await route.abort()
            await context.route('**/*',intercept)
            context.on('page',manager.subscribe)
            for page in context.pages:manager.subscribe(page)
            page=context.pages[0]
            await page.goto('https://business.kakao.com/space/synthetic/channel/example/chats/room')
            async with page.expect_download():await page.locator('#download').click()
            await asyncio.gather(*tuple(manager._tasks))
            assert manager.failure is None
            receipts=list(manager.run.glob('kakaodownload_*/result.json'))
            assert len(receipts)==1
            capture=receipts[0].parent
            terminal=ManualDownloadResult.model_validate_json(receipts[0].read_bytes())
            assert terminal.phase=='RECEIVED'
            raw=(capture/'page-observation.json').read_bytes()
            observation=ManualPageObservation.model_validate_json(raw)
            assert observation.status=='OBSERVED' and observation.target.kind=='BLOB'
            assert observation.document is not None and not observation.document.truncated
            assert b'NEVER_OUTPUT' not in raw and b'credential' not in raw
            nodes=observation.document.nodes
            repeated=[node for node in nodes if node.text=='동일한 질문']
            assert len(repeated)==2 and repeated[0].parent_index!=repeated[1].parent_index
            identities={node.identities.data_message_id for node in nodes
                if node.identities.data_message_id}
            assert identities=={'one','two'}
            assert any(node.link_path=='/api/profiles/example/chats/room/logs/one/image'
                for node in nodes)
            assert any(node.is_image for node in nodes)
            assert await page.evaluate('window.danger')==0
            # Same-origin SPA navigation between the event and DOM read must not
            # attach another room's observation to the already received bytes.
            event_path=download_page_path(page)
            started=ManualDownloadStart.model_validate_json((capture/'started.json').read_bytes())
            set_path="path => history.replaceState({}, '', path)"
            other_path='/space/synthetic/channel/example/chats/other'
            await page.evaluate(set_path,other_path+'?credential=NEVER_OUTPUT')
            navigated=await observe_download_page(page,started,
                download_url='blob:https://business.kakao.com/anonymous',event_path=event_path)
            assert navigated.status=='UNAVAILABLE' and navigated.error_code=='OBSERVATION_INVALID'
            assert navigated.document is None and 'NEVER_OUTPUT' not in navigated.model_dump_json()
            await page.evaluate(set_path,event_path)
            class NavigatingPage:
                @property
                def url(self):return page.url
                async def evaluate(self,expression):
                    value=await page.evaluate(expression)
                    await page.evaluate(set_path,other_path)
                    return value
            during=await observe_download_page(NavigatingPage(),started,
                download_url='blob:https://business.kakao.com/anonymous',event_path=event_path)
            assert during.status=='UNAVAILABLE' and during.error_code=='OBSERVATION_INVALID'
            assert during.document is None
            await page.evaluate(set_path,event_path)
            await page.set_content('<html><body>'+('<span>문</span>'*3000)+'</body></html>')
            bounded=await page.evaluate(DOCUMENT_EXPRESSION)
            assert bounded['truncated'] and len(bounded['nodes'])==2048
            hidden_html='<div style="display:none">hidden</div>'*9000
            await page.set_content('<html><body>'+hidden_html+'</body></html>')
            started=time.monotonic()
            hidden=await page.evaluate(DOCUMENT_EXPRESSION)
            assert hidden['truncated'] and hidden['nodes']==[]
            assert time.monotonic()-started<3
            await page.set_content('<html><body><span>'+('😀'*9000)+'</span></body></html>')
            unicode=await page.evaluate(DOCUMENT_EXPRESSION)
            assert unicode['truncated'] and len(unicode['nodes'][0]['text'])==8192
            await manager.close()
            await context.close()
        assert (capture/'page-observation.json').read_bytes()==raw
        print('ACTUAL_CHROMIUM_READ_ONLY_DOM=PASS duplicate_occurrences=2 '
            'credential_fields=0 dangerous_clicks=0 external_requests=0')

asyncio.run(main())
'''
    result = subprocess.run(
        ["/opt/eom/conda/envs/eom-kakao-browser/bin/python", "-B", "-c", program],
        cwd=root,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(Path.home()),
            "LANG": "C.UTF-8",
            "TZ": "UTC",
            "PLAYWRIGHT_BROWSERS_PATH": "/opt/eom/kakao-browser/playwright-1.65.2",
            "PYTHONPATH": ":".join(
                str(root / p)
                for p in (
                    "packages/kakao_archive_contracts",
                    "services/kakao_archive_collector",
                )
            ),
        },
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ACTUAL_CHROMIUM_READ_ONLY_DOM=PASS" in result.stdout
