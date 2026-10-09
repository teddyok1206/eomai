# Scientific Studio 안내 모드

This is a local presentation feature, not a worker prompt, permission grant or
new API. Each page load starts OFF; no cookie, browser storage, DB state or
cross-user preference is written. OFF adds only the requested topbar switch.
It leaves existing content, actions and visibility/permission rules unchanged.

The audience is teachers and office managers without AI experience. Korean copy
explains what to enter, what to click and where to find results. Say “한글 파일”
for HWPX output and explain work slots as “작업 자리”; avoid protocol/AI jargon.
Do not promise automatic approval, edits to original PDFs, or new permissions.

`guide-content.js` owns reviewed Korean descriptions and stable control/view
lookup. `guide-mode.js` owns one reusable, initially hidden text-only tooltip.
Delegated pointer/focus handlers resolve only visible controls, including
dynamically rendered and disabled controls. Lookup is O(D + C) using keyed maps
over a target's ancestor depth D and small class list C; no repeated document
scan, per-control listeners, mutation observer or dependency is needed.

While ON, mouse hover or keyboard focus shows an explanation without submitting
requests or intercepting clicks. Escape, mode OFF, navigation clicks, leaving
the target/popup, resizing and page hide dismiss it. Scrolling dismisses hover
help; focused help is repositioned, or dismissed if its target leaves the viewport.
The popup stays hoverable and inside the viewport. Its temporary
`aria-describedby` token is removed without removing existing descriptions.
All copy uses `textContent`; document/item text is never interpreted as help HTML.

Tests cover default/returned OFF geometry and DOM state, disabled and dynamic
targets, native form/button behavior, existing ARIA descriptions, Escape,
navigation, viewport edges, keyboard use, touch focus and no network/storage.
New assets must be present in the wheel and exact installed RECORD inventory.
