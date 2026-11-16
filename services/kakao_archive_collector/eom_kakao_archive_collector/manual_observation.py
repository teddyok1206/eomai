"""Read a bounded, fixed DOM projection at download time. No input/control methods.

Only local evidence is returned. A matching path/label is not authority to admit
sources, associate a photo or click anything. Never persist URLs with query data.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

from eom_kakao_archive_contracts.manual_download import ManualDownloadStart
from eom_kakao_archive_contracts.manual_observation import (
    ManualDownloadTarget,
    ManualPageObservation,
)

OBSERVATION_SECONDS = 1.5
ORIGIN = "https://business.kakao.com"

# Code-owned expression, never model/client JavaScript or an RPC argument. The
# tree walker rejects credential/editing subtrees before examining descendants.
DOCUMENT_EXPRESSION = r"""() => {
  if (location.origin !== 'https://business.kakao.com' || !document.body ||
      document.body.hasAttribute('contenteditable')) return null;
  const blocked = new Set(['script','style','noscript','input','textarea','form',
    'iframe','object','embed']);
  const ids = ['data-id','data-chat-id','data-message-id','data-log-id'];
  const parentIndices = new Map();
  const nodes = [];
  let scanned = 0, textBudget = 65536, truncated = false;
  const clip = (value, maximum, usesBudget = false) => {
    if (!value || !value.trim()) return null;
    const bound = usesBudget ? Math.min(maximum, textBudget) : maximum;
    const points = Array.from(value.slice(0, maximum * 2 + 2));
    if (points.length > bound || value.length > maximum * 2 + 2) truncated = true;
    const result = points.slice(0, bound).join('');
    if (usesBudget) textBudget -= Array.from(result).length;
    return result || null;
  };
  const pathOf = (raw) => {
    if (!raw) return null;
    try {
      const u = new URL(raw, location.href);
      if (u.protocol !== 'https:' || u.origin !== location.origin || u.username || u.password)
        return null;
      if (u.pathname.length > 2048) { truncated = true; return null; }
      return u.pathname;
    } catch { return null; }
  };
  const afterSubtree = (node) => {
    let current = node;
    while (current && current !== document.body && !current.nextElementSibling)
      current = current.parentElement;
    return current && current !== document.body ? current.nextElementSibling : null;
  };
  const elements = [];
  let cursor = document.body.firstElementChild;
  while (cursor && scanned < 8192) {
    scanned++;
    const skipped = blocked.has(cursor.localName.toLowerCase()) ||
      cursor.hasAttribute('contenteditable') ||
      cursor.getAttribute('aria-hidden') === 'true';
    const style = skipped ? null : getComputedStyle(cursor);
    const hidden = style && (style.display === 'none' || style.visibility === 'hidden');
    if (!skipped && !hidden) elements.push(cursor);
    cursor = !skipped && !hidden && cursor.firstElementChild
      ? cursor.firstElementChild : afterSubtree(cursor);
  }
  if (cursor) truncated = true;
  for (const element of elements) {
    if (nodes.length === 2048) { truncated = true; break; }
    const parent = parentIndices.get(element.parentElement) ?? null;
    parentIndices.set(element, parent);
    const classes = Array.from(element.classList);
    if (classes.length > 8 || classes.some(value => value.length > 128)) truncated = true;
    const keptClasses = classes.filter(value => value.length <= 128).slice(0, 8);
    const role = clip(element.getAttribute('role'), 64);
    const label = clip(element.getAttribute('aria-label') || element.getAttribute('title') ||
      (element.tagName === 'IMG' ? element.getAttribute('alt') : null), 512, true);
    const text = element.children.length === 0 ? clip(element.textContent, 8192, true) : null;
    const identities = Object.fromEntries(ids.map(name => {
      const value = element.getAttribute(name);
      return [name, value && /^[A-Za-z0-9_-]{1,128}$/.test(value) ? value : null];
    }));
    const linkPath = element.tagName === 'A' ? pathOf(element.getAttribute('href')) : null;
    const isImage = element.tagName === 'IMG';
    if (!keptClasses.length && !role && !label && !text && !linkPath && !isImage &&
        !Object.values(identities).some(value => value !== null)) continue;
    const index = nodes.length;
    nodes.push({index, parent_index: parent, tag: element.localName.toLowerCase(),
      classes: keptClasses, role, label, text, identities, link_path: linkPath, is_image: isImage});
    parentIndices.set(element, index);
  }
  return {origin: location.origin, path: location.pathname, truncated, nodes};
}"""


class ReadOnlyPage(Protocol):
    @property
    def url(self) -> str: ...
    async def evaluate(self, expression: str) -> object: ...


def _same_origin_path(url: str) -> str | None:
    try:
        value = urlsplit(url)
        if (
            value.scheme != "https"
            or value.hostname != "business.kakao.com"
            or value.port not in {None, 443}
            or value.username is not None
            or value.password is not None
        ):
            return None
        path = value.path or "/"
        if not 1 <= len(path) <= 2048 or any(ord(char) <= 32 or ord(char) == 127 for char in path):
            return None
        return path
    except (ValueError, TypeError):
        return None


def download_target(url: str) -> ManualDownloadTarget:
    path = _same_origin_path(url)
    if path is not None:
        return ManualDownloadTarget(kind="SAME_ORIGIN_PATH", path=path)
    if url.startswith("blob:") and _same_origin_path(url[5:]) is not None:
        return ManualDownloadTarget(kind="BLOB", path=None)
    return ManualDownloadTarget(kind="UNAVAILABLE", path=None)


async def observe_download_page(
    page: ReadOnlyPage, started: ManualDownloadStart, *, download_url: str
) -> ManualPageObservation:
    identity = started.model_dump(exclude={"phase", "schema_version", "started_at"})
    base = dict(
        **identity,
        observed_at=datetime.now(UTC),
        target=download_target(download_url),
        status="UNAVAILABLE",
        document=None,
        error_code="UNSUPPORTED_ORIGIN",
    )
    try:
        page_path = _same_origin_path(page.url)
    except Exception:
        return ManualPageObservation.model_validate(base | {"error_code": "OBSERVATION_FAILED"})
    if page_path is None:
        return ManualPageObservation.model_validate(base)
    try:
        document = await asyncio.wait_for(page.evaluate(DOCUMENT_EXPRESSION), OBSERVATION_SECONDS)
    except TimeoutError:
        return ManualPageObservation.model_validate(base | {"error_code": "OBSERVATION_TIMEOUT"})
    except Exception:
        return ManualPageObservation.model_validate(base | {"error_code": "OBSERVATION_FAILED"})
    if document is None:
        return ManualPageObservation.model_validate(base)
    try:
        return ManualPageObservation.model_validate(
            base | {"status": "OBSERVED", "document": document, "error_code": None}
        )
    except ValueError:
        return ManualPageObservation.model_validate(base | {"error_code": "OBSERVATION_INVALID"})
