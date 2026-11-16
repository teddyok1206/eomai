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
