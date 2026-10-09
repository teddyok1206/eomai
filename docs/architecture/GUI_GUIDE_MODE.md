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

## Verification and deployment — 2026-10-09 09:00 UTC

- Web source: `67fafe99fec99e1f9bcd2293fe970c9ed18d8449` (feature in
  `fd856241003c0689da192f6e8e9f7b851f160557`; header wrapping follow-up).
- Full Web suite: 292 PASS, including opt-in real Chromium interaction tests.
  Ruff format/lint, module syntax checks, and release-integrity mypy PASS.
- Wheel SHA-256:
  `693a0ed034d02a78e063c03d3cde391c16bf441c2a40bd848e3b3a3183d0deac`.
  Non-editable installed simulation and actual Web service identity both
  verified all 46 runtime files and RECORD descriptors.
- Authenticated HTTPS Chromium: desktop and 390px mobile PASS. Checked local
  default OFF, hover/focus/Space toggle, readable copy, popup hover/Escape,
  unchanged settled form geometry, viewport bounds, OFF ARIA cleanup, reload
  resetting to OFF, and absence of browser JS errors. Screenshots were visually
  inspected; the header's existing open/logout labels stay on one line.
- No work-submission requests were made by the browser check. One existing
  dashboard `POST /explorer/query` was a read-only query, not a mutation.
  Local tests also cover disabled/dynamic/hidden controls, native submission
  behavior, no HTML interpretation, and 320px viewport bounds.
- Only the Web wheel was installed/restarted. API remained at
  `d32f3ba75bc7a0b34305204d3dba43a009e99617`. API, Web and dedicated chat
  services were active; HTTPS readiness was READY. No new model, GPU, HWPX,
  migration, account/permission or canonical-data changes were performed.

The first live harness comparison ran before existing request-preparation reads
finished; its layout comparison was corrected to compare settled geometry.
The harness also initially misclassified the read-only Explorer POST as a
mutation and needed to await viewport resize before focusing a mobile control.
These checks were corrected without altering application behavior; the final
installed release passed. No claim of educational or Hancom layout review is
made by this UI-only acceptance.
