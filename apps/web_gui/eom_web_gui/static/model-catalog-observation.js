// Reuses the official account OBSERVE command. No inference, login or policy mutation.
export function createModelCatalogObservation({api, isAdmin, delay = ms => new Promise(resolve => setTimeout(resolve, ms))}) {
  const pending = new Map();
  let epoch = 0;
  const current = version => isAdmin() && version === epoch;

  function reset() { epoch += 1; pending.clear(); }

  async function observe(account, version = epoch) {
    if (!current(version)) throw new Error("관리자 로그인이 필요합니다.");
    if (account.active_auth_enrollment_id) throw new Error("계정 로그인 변경이 진행 중입니다.");
    const existing = pending.get(account.binding_id);
    if (existing?.running) return existing.running;
    const intent = existing || {body: {
      command_type: "OBSERVE", resource_version: account.resource_version,
      idempotency_key: `studio:codex-account:${account.binding_id}:OBSERVE:${crypto.randomUUID()}`,
      reason_code: null,
    }};
    pending.set(account.binding_id, intent);
    intent.running = (async () => {
      // A failed HTTP acknowledgement replays the same key, never a second observation.
      if (!intent.commandId) {
        const result = await api(`/admin/codex-accounts/${encodeURIComponent(account.binding_id)}/commands`, {
          method: "POST", mutation: true, body: intent.body,
        });
        intent.commandId = result.command_id;
      }
      for (let attempt = 0; attempt < 90 && current(version); attempt += 1) {
        const result = await api(`/admin/codex-control-commands/${encodeURIComponent(intent.commandId)}`);
        if (!current(version)) throw new Error("로그인 상태가 변경되었습니다.");
        if (["SUCCEEDED", "FAILED"].includes(result.state)) {
          if (pending.get(account.binding_id) === intent) pending.delete(account.binding_id);
          if (result.state === "FAILED") throw new Error(result.error_code || "상태 확인 실패");
          return result;
        }
        await delay(1000);
      }
      throw new Error(current(version) ? "상태 확인 중입니다. 다시 누르면 같은 확인을 이어갑니다." : "로그인 상태가 변경되었습니다.");
    })();
    try { return await intent.running; }
    finally { intent.running = null; }
  }

  async function load(kind, {refresh = false} = {}) {
    const version = epoch;
    if (!current(version)) throw new Error("관리자 로그인이 필요합니다.");
    const relevant = accounts => accounts.filter(account => kind === "CHAT"
      ? account.assignment_purpose === "GENERAL_CHAT" : account.assignment_purpose !== "GENERAL_CHAT");
    let accounts = relevant(await api("/admin/codex-accounts"));
    let failures = [];
    if (refresh && current(version)) {
      const results = await Promise.allSettled(accounts.map(account => observe(account, version)));
      failures = results.flatMap((result, index) => result.status === "rejected"
        ? [`${accounts[index].slot_key}: ${result.reason.message}`] : []);
      if (!current(version)) throw new Error("로그인 상태가 변경되었습니다.");
      accounts = relevant(await api("/admin/codex-accounts"));
    }
    if (!current(version)) throw new Error("로그인 상태가 변경되었습니다.");
    const models = new Map();
    for (const account of accounts) {
      const catalog = account.model_catalog;
      const now = Date.now();
      if (catalog?.state !== "OBSERVED" || !(Date.parse(catalog.observed_at) <= now)
        || !(Date.parse(catalog.valid_until) > now)) continue;
      for (const model of catalog.models || []) {
        if (model.hidden) continue;
        if (!models.has(model.model)) models.set(model.model, new Set());
        for (const effort of model.supported_reasoning_efforts) models.get(model.model).add(effort);
      }
    }
    return {models: [...models].sort(([a], [b]) => a.localeCompare(b))
      .map(([model, efforts]) => ({model, efforts: [...efforts]})), failures};
  }
  return {load, observe, reset};
}
