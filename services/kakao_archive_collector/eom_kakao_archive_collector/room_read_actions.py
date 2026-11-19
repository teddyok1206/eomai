"""Closed read-side actions for an already opened and independently pinned Kakao room."""

import asyncio
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from .profile import BrowserRuntimeError

_KEY = re.compile(r"[A-Za-z0-9_-]{1,128}")
_IMAGE = re.compile(
    r"/api/profiles/[A-Za-z0-9_-]{1,128}/chats/[A-Za-z0-9_-]{1,128}/"
    r"[A-Za-z0-9_-]{1,128}/[A-Za-z0-9_-]{1,128}/image"
)
_ACTION_SECONDS = 2.0
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class RoomReadAction(StrEnum):
    OPEN_EXPORT_MENU = "OPEN_EXPORT_MENU"
    EXPORT_CSV = "EXPORT_CSV"
    DOWNLOAD_IMAGE = "DOWNLOAD_IMAGE"


class RoomActionPage(Protocol):
    async def evaluate(self, expression: str, arg: object) -> object: ...


class RoomReadActionRefused(BrowserRuntimeError):
    """The fixed evaluator explicitly returned before it clicked."""


@dataclass(frozen=True, slots=True)
class RoomReadActivation:
    triggered: bool
    photo_url_digests: frozenset[str] = field(default_factory=frozenset, repr=False)


# Provider structure actually observed on a real popup. There is no click by a
# free-form selector, label, point, href or script supplied by a caller.
ROOM_READ_EXPRESSION = r"""async ({action, channel, room, image}) => {
  if (location.origin !== 'https://business.kakao.com' || !document.body ||
      window.top !== window || document.designMode === 'on') return 'UNAVAILABLE';
  const route = /^\/space\/[A-Za-z0-9_-]{1,128}\/channel\/([A-Za-z0-9_-]{1,128})\/chats(?:\/|$)/;
  if (route.exec(location.pathname)?.[1] !== channel) return 'UNAVAILABLE';
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  for (let count = 0; walker.nextNode(); count++)
    if (count === 8192) return 'UNAVAILABLE';

  const visible = node => node instanceof HTMLElement && node.isConnected &&
    !node.closest('[hidden],[inert],[aria-hidden="true"],[contenteditable],form') &&
    node.checkVisibility({visibilityProperty:true, opacityProperty:true});
  const unique = (root, selector) => {
    const matches = Array.from(root.querySelectorAll(selector)).filter(visible);
    return matches.length === 1 ? matches[0] : null;
  };
  const popup = unique(document, '.chat_popup');
  if (!popup) return 'UNAVAILABLE';
  const shownRoom = popup.getAttribute('data-chat-id');
  if (shownRoom !== null && shownRoom !== room) return 'UNAVAILABLE';
  const key = /^[A-Za-z0-9_-]{1,128}$/;
  const links = [];
  let verifiedLinks = 0;
  for (const link of popup.querySelectorAll('.item_chat .set_chat a.btn_save')) {
    if (!visible(link)) continue;
    const bubble = link.closest('.set_chat');
    if (!bubble || bubble.closest('.chat_popup') !== popup) return 'UNAVAILABLE';
    let url;
    try { url = new URL(link.href); } catch { return 'UNAVAILABLE'; }
    const segments = url.pathname.slice(1).split('/');
    const [api, profiles, sourceChannel, chats, sourceRoom, message, file, kind] = segments;
    if (segments.length !== 8 || api !== 'api' || profiles !== 'profiles' ||
        chats !== 'chats' || kind !== 'image' || !key.test(message) || !key.test(file) ||
        url.origin !== location.origin || url.username || url.password || url.search || url.hash ||
        sourceChannel !== channel || sourceRoom !== room)
      return 'UNAVAILABLE';
    verifiedLinks++;
    if (!bubble.querySelector('.box_package, .link_pic_temp') &&
        bubble.querySelectorAll('a.link_pic').length === 1 &&
        bubble.querySelectorAll('a.btn_save').length === 1 &&
        bubble.querySelector('a.link_pic img.thumb_g')) links.push({link, path:url.pathname});
  }
  if (!verifiedLinks && shownRoom === null) return 'UNAVAILABLE';
  const allMenus = Array.from(document.querySelectorAll('.menu_side_type2')).filter(visible);
  let target = null;
  if (action === 'OPEN_EXPORT_MENU') {
    if (allMenus.length === 1) return 'ALREADY_OPEN';
    if (allMenus.length !== 0) return 'UNAVAILABLE';
    target = unique(popup, '.popup_head .area_util button.btn_tooltip.btn_util.btn_menu');
  } else if (action === 'EXPORT_CSV') {
    if (allMenus.length !== 1) return 'UNAVAILABLE';
    const section = unique(allMenus[0], '.inner_menu .info_chat .wrap_write.wrap_down');
    if (!section) return 'UNAVAILABLE';
    const title = unique(section, ':scope > strong.tit_set');
    target = unique(section, ':scope > button.btn_g_m.btn_save');
    if (!title || title.textContent.trim() !== '대화 내보내기' ||
        !target || target.textContent.trim() !== '내 PC 저장') return 'UNAVAILABLE';
  } else if (action === 'DOWNLOAD_IMAGE') {
    if (allMenus.length !== 0) return 'UNAVAILABLE';
    const found = links.filter(entry => entry.path === image);
    if (found.length !== 1) return 'UNAVAILABLE';
    target = found[0].link;
  } else return 'UNAVAILABLE';

  if (!visible(target) || target.getAttribute('aria-disabled') === 'true' ||
      (target instanceof HTMLButtonElement &&
       (target.disabled || target.form || target.type === 'reset')))
    return 'UNAVAILABLE';
  target.scrollIntoView({block:'center', inline:'nearest', behavior:'instant'});
  const box = target.getBoundingClientRect();
  const x = box.left + box.width / 2, y = box.top + box.height / 2;
  const hit = document.elementFromPoint(x, y);
  if (!box.width || !box.height || !visible(target) || !hit || !target.contains(hit))
    return 'UNAVAILABLE';
  const photoUrls = () => {
    if (action !== 'DOWNLOAD_IMAGE' || !globalThis.crypto?.subtle) return [];
    const selected = target.closest('.set_chat')?.querySelector('a.link_pic');
    if (!selected || !visible(selected)) return [];
    const candidates = Array.from(
      popup.querySelectorAll('.item_chat a.link_pic, .item_chat a.link_pic_temp'));
    if (candidates.length > 64 || !candidates.includes(selected)) return [];
    const clean = value => {
      if (!value || value.length > 8192) return null;
      try {
        const url = new URL(value);
        return url.origin === 'https://k.kakaocdn.net' &&
          !url.username && !url.password && !url.hash ? url.href : null;
      } catch { return null; }
    };
    const urls = new Set(), usedElsewhere = new Set();
    for (const preview of candidates) {
      const images = preview.querySelectorAll('img');
      if (images.length > 16 || (preview === selected && images.length !== 1)) return [];
      const seen = preview === selected ? urls : usedElsewhere;
      const fields = [preview.hasAttribute('href') && preview.href,
        ...Array.from(images, node => node.currentSrc)];
      if (preview !== selected) fields.push(...Array.from(images, node => node.src));
      for (const field of fields) {
        const value = clean(field);
        if (value) seen.add(value);
      }
    }
    return [...urls].filter(url => !usedElsewhere.has(url));
  };
  const observed = photoUrls();
  // Select and activate the same DOM node atomically; no mouse coordinate fallback.
  target.click();
  if (observed.length) {
    try {
      const encoder = new TextEncoder();
      return await Promise.all(observed.map(async url => {
        const digest = await crypto.subtle.digest('SHA-256', encoder.encode(url));
        return Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2,'0')).join('');
      }));
    } catch { return 'TRIGGERED'; }
  }
  return 'TRIGGERED';
}"""


async def activate_room_read_action(
    page: RoomActionPage,
    action: RoomReadAction,
    *,
    channel_key: str,
    room_key: str,
    image_path: str | None = None,
) -> RoomReadActivation:
    """Run one fixed interaction and return ephemeral selected-photo evidence."""
    if (
        not isinstance(action, RoomReadAction)
        or not isinstance(channel_key, str)
        or not isinstance(room_key, str)
        or _KEY.fullmatch(channel_key) is None
        or _KEY.fullmatch(room_key) is None
        or (action is RoomReadAction.DOWNLOAD_IMAGE) != (image_path is not None)
        or (
            image_path is not None
            and (not isinstance(image_path, str) or _IMAGE.fullmatch(image_path) is None)
        )
    ):
        raise BrowserRuntimeError("KAKAO_ROOM_READ_ACTION_INVALID")
    try:
        response = await asyncio.wait_for(
            page.evaluate(
                ROOM_READ_EXPRESSION,
                {
                    "action": action.value,
                    "channel": channel_key,
                    "room": room_key,
                    "image": image_path,
                },
            ),
            timeout=_ACTION_SECONDS,
        )
    except Exception:
        # The remote evaluation may have reached the click before transport failure.
        raise BrowserRuntimeError("KAKAO_ROOM_READ_ACTION_UNCERTAIN") from None
    if response == "TRIGGERED":
        return RoomReadActivation(True)
    if response == "UNAVAILABLE":
        raise RoomReadActionRefused("KAKAO_ROOM_READ_ACTION_UNAVAILABLE")
    if response == "ALREADY_OPEN" and action is RoomReadAction.OPEN_EXPORT_MENU:
        return RoomReadActivation(False)
    if (
        action is RoomReadAction.DOWNLOAD_IMAGE
        and isinstance(response, list)
        and 1 <= len(response) <= 2
        and all(isinstance(value, str) and _SHA256_HEX.fullmatch(value) for value in response)
    ):
        return RoomReadActivation(True, frozenset(response))
    raise BrowserRuntimeError("KAKAO_ROOM_READ_ACTION_UNAVAILABLE")


async def trigger_room_read_action(
    page: RoomActionPage,
    action: RoomReadAction,
    *,
    channel_key: str,
    room_key: str,
    image_path: str | None = None,
) -> bool:
    """True is one requested click; False is an already open menu, not a download."""
    activation = await activate_room_read_action(
        page, action, channel_key=channel_key, room_key=room_key, image_path=image_path
    )
    return activation.triggered
