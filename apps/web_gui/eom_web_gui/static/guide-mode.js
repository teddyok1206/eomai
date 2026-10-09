import {resolveGuideTarget} from "./guide-content.js";

// One page-local tooltip. It never changes product state or control availability.
export function installGuideMode() {
  const toggle = document.getElementById("guide-mode-toggle");
  const tooltip = document.getElementById("guide-tooltip");
  const title = document.getElementById("guide-tooltip-title");
  const description = document.getElementById("guide-tooltip-description");
  let enabled = false;
  let active = null;
  let dismissed = null;
  let hoverDismissed = false;
  let closeTimer = null;

  function hide() {
    clearTimeout(closeTimer);
    closeTimer = null;
    if (active) {
      const tokens = (active.getAttribute("aria-describedby") || "").split(/\s+/).filter(token => token && token !== tooltip.id);
      if (tokens.length) active.setAttribute("aria-describedby", tokens.join(" "));
      else active.removeAttribute("aria-describedby");
    }
    active = null;
    tooltip.hidden = true;
    title.textContent = "";
    description.textContent = "";
  }

  function dismiss() {
    hoverDismissed = true;
    hide();
  }

  function position(element) {
    const margin = 12;
    const width = document.documentElement.clientWidth;
    const height = document.documentElement.clientHeight;
    tooltip.style.maxHeight = `${Math.max(40, height - margin * 2)}px`;
    const anchor = element.getBoundingClientRect();
    const box = tooltip.getBoundingClientRect();
    const beside = element.closest(".sidebar") && anchor.right + margin + box.width <= width - margin;
    const left = beside ? anchor.right + margin : anchor.left;
    const below = anchor.bottom + margin;
    const top = beside ? anchor.top : below + box.height <= height - margin ? below : anchor.top - box.height - margin;
    tooltip.style.left = `${Math.max(margin, Math.min(left, width - box.width - margin))}px`;
    tooltip.style.top = `${Math.max(margin, Math.min(top, height - box.height - margin))}px`;
  }

  function show(target) {
    if (!enabled) return;
    const value = resolveGuideTarget(target);
    if (!value) {
      if (active && !active.matches(":focus-within")) dismiss();
      return;
    }
    if (value.element === dismissed) return;
    clearTimeout(closeTimer);
    if (active === value.element && !tooltip.hidden) return;
    hide();
    active = value.element;
    title.textContent = value.title;
    description.textContent = value.description;
    const tokens = new Set((active.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
    tokens.add(tooltip.id);
    active.setAttribute("aria-describedby", [...tokens].join(" "));
    tooltip.hidden = false;
    position(active);
  }

  function contains(element, target) {
    return target instanceof Node && element?.contains(target);
  }

  function leave(event) {
    if (!enabled) return;
    if (dismissed && !contains(dismissed, event.relatedTarget)) dismissed = null;
    if (contains(active, event.relatedTarget) || contains(tooltip, event.relatedTarget)) return;
    if (event.type === "pointerout" && active?.matches(":focus-within")) return;
    clearTimeout(closeTimer);
    closeTimer = setTimeout(dismiss, 100);
  }

  toggle.setAttribute("aria-checked", "false");
  hide();
  toggle.addEventListener("click", () => {
    enabled = !enabled;
    toggle.setAttribute("aria-checked", String(enabled));
    dismissed = null;
    hoverDismissed = false;
    hide();
  });
  document.addEventListener("pointerover", event => {
    if (!enabled || hoverDismissed || event.pointerType === "touch") return;
    if (contains(tooltip, event.target)) {
      clearTimeout(closeTimer);
      return;
    }
    show(event.target);
  }, true);
  document.addEventListener("pointermove", event => {
    // Hiding the popup can expose another control under a stationary pointer.
    // Resume only on deliberate movement, never the resulting pointerover.
    if (!enabled || event.pointerType === "touch" || (!hoverDismissed && !tooltip.hidden)) return;
    hoverDismissed = false;
    show(event.target);
  }, true);
  document.addEventListener("pointerout", leave, true);
  document.addEventListener("focusin", event => {
    if (!enabled) return;
    hoverDismissed = false;
    show(event.target);
  });
  document.addEventListener("focusout", leave);
  document.addEventListener("keydown", event => {
    if (enabled && event.key === "Escape" && active) {
      dismissed = active;
      dismiss();
    }
  });
  document.addEventListener("click", event => {
    if (enabled && !contains(tooltip, event.target)) dismiss();
  }, true);
  document.addEventListener("scroll", event => {
    if (!enabled || contains(tooltip, event.target)) return;
    if (active?.isConnected && active.matches(":focus-within")) {
      const rect = active.getBoundingClientRect();
      if (rect.bottom > 0 && rect.top < document.documentElement.clientHeight &&
          rect.right > 0 && rect.left < document.documentElement.clientWidth) {
        position(active);
        return;
      }
    }
    dismiss();
  }, true);
  window.addEventListener("resize", dismiss);
  window.addEventListener("pagehide", dismiss);
}
