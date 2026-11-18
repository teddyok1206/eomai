"""Read-only comparison of a final MANUAL download and displayed photo fields."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from hashlib import sha256
from typing import Protocol
from urllib.parse import urlsplit

from .manual_observation import ReadOnlyPage, download_page_path


class PhotoDomFinding(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    LIMIT = "LIMIT"
    NONE = "NONE"
    MULTIPLE_CARDS = "MULTIPLE_CARDS"
    PHOTO_LINK = "PHOTO_LINK"
    DISPLAYED_IMAGE = "DISPLAYED_IMAGE"
    BOTH_FIELDS = "BOTH_FIELDS"


class PhotoDomPage(ReadOnlyPage, Protocol):
    async def evaluate(self, expression: str, arg: object = None) -> object: ...


_COMPARE_PHOTO_URL = r"""async ({path,digest}) => {
  const current = () => location.origin === 'https://business.kakao.com' &&
      location.pathname === path && window.top === window && !!document.body;
  if (!current() || !globalThis.crypto?.subtle) return 'UNAVAILABLE';
  const key = /^[A-Za-z0-9_-]{1,128}$/;
  const scope = path.slice(1).split('/');
  if (scope.length !== 6 || scope[0] !== 'space' || scope[2] !== 'channel' ||
      scope[4] !== 'chats' || ![scope[1],scope[3],scope[5]].every(p=>key.test(p)))
    return 'UNAVAILABLE';
  const withinBudget = () => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    for (let n = 0; walker.nextNode(); n++) if (n === 4096) return false;
    return true;
  };
  if (!withinBudget()) return 'LIMIT';
  const visible = e => e instanceof HTMLElement && e.isConnected &&
    !e.closest('form,[contenteditable],[hidden],[inert],[aria-hidden="true"]') &&
    e.checkVisibility({visibilityProperty:true,opacityProperty:true});
  const popups = Array.from(document.querySelectorAll('.chat_popup')).filter(visible);
  if (popups.length !== 1) return 'UNAVAILABLE';
  const popup = popups[0];
  const collect = () => {
    const links = Array.from(popup.querySelectorAll('.item_chat .set_chat a.btn_save'))
      .filter(visible);
    if (links.length > 64) return 'LIMIT';
    const rows = [];
    for (const link of links) {
      const origin = new URL(link.href);
      const keys = origin.pathname.slice(1).split('/');
      if (origin.origin !== location.origin || origin.username || origin.password ||
          origin.search || origin.hash || keys.length !== 8 || keys[0] !== 'api' ||
          keys[1] !== 'profiles' || keys[2] !== scope[3] || keys[3] !== 'chats' ||
          keys[4] !== scope[5] || !key.test(keys[5]) || !key.test(keys[6]) || keys[7] !== 'image')
        return 'UNAVAILABLE';
      const card = link.closest('.set_chat');
      if (card.closest('.chat_popup') !== popup) return 'UNAVAILABLE';
      const photo = Array.from(card.querySelectorAll('a.link_pic')).filter(visible);
      if (photo.length !== 1) return 'UNAVAILABLE';
      const previews = Array.from(photo[0].querySelectorAll('img')).filter(visible);
      if (previews.length !== 1) return 'UNAVAILABLE';
      rows.push([link, origin.href, photo[0], photo[0].hasAttribute('href') ? photo[0].href : '',
                 previews[0], previews[0].currentSrc]);
    }
    return rows;
  };
  const snapshot = collect();
  if (typeof snapshot === 'string') return snapshot;
  const encoder = new TextEncoder();
  const matches = async value => {
    if (!value || value.length > 8192) return false;
    const url = new URL(value);
    if (url.origin !== 'https://k.kakaocdn.net' || url.username || url.password) return false;
    const bytes = await crypto.subtle.digest('SHA-256',encoder.encode(url.href));
    return [...new Uint8Array(bytes)].map(n=>n.toString(16).padStart(2,'0')).join('') === digest;
  };
  const found = await Promise.all(snapshot.map(async row => [
    await matches(row[3]), await matches(row[5])
  ]));
  if (!current()) return 'UNAVAILABLE';
  if (!withinBudget()) return 'LIMIT';
  const after = collect();
  if (typeof after === 'string' || after.length !== snapshot.length ||
      after.some((row,i)=>row.some((value,j)=>value !== snapshot[i][j]))) return 'UNAVAILABLE';
  const candidates = found.filter(([link,image]) => link || image);
  if (candidates.length > 1) return 'MULTIPLE_CARDS';
  if (!candidates.length) return 'NONE';
  const [link,image] = candidates[0];
  return link && image ? 'BOTH_FIELDS' : link ? 'PHOTO_LINK' : 'DISPLAYED_IMAGE';
}"""


async def compare_displayed_photo_urls(
    page: PhotoDomPage, *, event_path: str | None, download_url: str
) -> PhotoDomFinding:
    """Return a finding, never an identifying URL, DOM ordinal or source authority."""
    if event_path is None or download_page_path(page) != event_path or len(download_url) > 8192:
        return PhotoDomFinding.UNAVAILABLE
    try:
        url = urlsplit(download_url)
        if (
            url.scheme != "https"
            or url.hostname != "k.kakaocdn.net"
            or url.port not in {None, 443}
            or url.username is not None
            or url.password is not None
        ):
            return PhotoDomFinding.UNAVAILABLE
        value = await asyncio.wait_for(
            page.evaluate(
                _COMPARE_PHOTO_URL,
                {"path": event_path, "digest": sha256(download_url.encode()).hexdigest()},
            ),
            timeout=0.75,
        )
        if isinstance(value, str) and download_page_path(page) == event_path:
            return PhotoDomFinding(value)
    except Exception:
        pass  # No browser exception text or raw URL is returned to the collector.
    return PhotoDomFinding.UNAVAILABLE
