// One saved assembly -> one durable build. A status read can never submit a build.
const LABELS = Object.freeze({
  REQUESTED: "제작 대기", RUNNING: "한글 파일 제작 중", VALIDATING: "완성 파일 확인 중",
  SUCCEEDED: "제작 완료", FAILED: "제작 실패",
});

export function createCuratedDeliveryControl({document, api, entry, setTimer = globalThis.setTimeout,
  clearTimer = globalThis.clearTimeout, storage = globalThis.sessionStorage}) {
  const root = document.createElement("span");
  root.className = "item-db-delivery";
  const action = document.createElement("button");
  action.type = "button";
  action.className = "button secondary";
  action.textContent = "HWPX 제작";
  const status = document.createElement("span");
  status.className = "item-db-delivery-status";
  status.setAttribute("aria-live", "polite");
  const download = document.createElement("a");
  download.className = "button secondary";
  download.textContent = "HWPX 다운로드";
  download.hidden = true;
  root.append(action, status, download);
  const base = `/item-db/assemblies/${encodeURIComponent(entry.assembly_id)}/hwpx-builds`;
  const input = {assembly_revision_id: entry.assembly_revision_id, manifest_sha256: entry.manifest_sha256};
  const storageKey = `eom:assembly-delivery:${entry.assembly_revision_id}`;
  let view = null;
  let busy = false;
  let disposed = false;
  let timer = null;
  let pendingKey = null;

  function key(replace = false) {
    if (!replace && pendingKey) return pendingKey;
    try { if (!replace) pendingKey = storage?.getItem(storageKey); } catch { /* Local storage is optional. */ }
    if (!pendingKey || replace) pendingKey = `studio:curated-hwpx:${crypto.randomUUID()}`;
    try { storage?.setItem(storageKey, pendingKey); } catch { /* The same in-memory key is retained. */ }
    return pendingKey;
  }

  function show(value) {
    if (value.assembly_id !== entry.assembly_id || value.assembly_revision_id !== entry.assembly_revision_id
      || !/^hwpxbuild_[0-9a-f]{32}$/.test(value.build_id) || !Object.hasOwn(LABELS, value.state)) {
      throw new Error("선택한 조립 순서의 제작 결과가 아닙니다.");
    }
    view = value;
    status.textContent = LABELS[value.state] + (value.failure_code ? ` · ${value.failure_code}` : "");
    action.textContent = value.state === "FAILED" ? "다시 제작" : "상태 확인";
    download.hidden = !(value.state === "SUCCEEDED" && value.download_available === true);
    if (!download.hidden) download.href = `/studio/api/v1${base}/${encodeURIComponent(value.build_id)}/download`;
    root.setAttribute("aria-busy", String(!["SUCCEEDED", "FAILED"].includes(value.state)));
    if (!["SUCCEEDED", "FAILED"].includes(value.state) && !disposed) {
      if (timer !== null) clearTimer(timer);
      timer = setTimer(() => {
        timer = null;
        if (!disposed && root.isConnected) refresh();
      }, 5000);
    }
  }

  async function guarded(work) {
    if (busy || disposed) return;
    busy = true;
    action.disabled = true;
    try { const value = await work(); if (!disposed) show(value); }
    catch (error) {
      if (!disposed) status.textContent = `제작 상태 확인 필요: ${error.message || "다시 눌러 확인해 주세요."}`;
      // Keep the same build/key. Observation failure never creates another build.
    } finally { busy = false; action.disabled = disposed; }
  }

  function refresh() {
    if (!view) return;
    return guarded(() => api(`${base}/${encodeURIComponent(view.build_id)}`));
  }

  action.addEventListener("click", () => {
    if (view && view.state !== "FAILED") return refresh();
    const retry = view?.state === "FAILED";
    return guarded(async () => {
      if (!retry) {
        const previous = await api(`${base}/latest?${new URLSearchParams(input)}`);
        if (previous) return previous;
      }
      status.textContent = "제작 요청을 보내고 있습니다.";
      return api(base, {method: "POST", mutation: true, body: input,
        headers: {"Idempotency-Key": key(retry)}});
    });
  });

  return {element: root, dispose() { disposed = true; if (timer !== null) clearTimer(timer); }};
}
