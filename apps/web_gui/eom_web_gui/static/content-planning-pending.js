// One submitted operation per signed-in owner and browser tab. This is a replay
// envelope, not authority or a second source of saved content. Never store sessions.
const PREFIX = "eom:excel:pending:1:";
const MAX_BYTES = 4 * 1024 * 1024;
// Match the BFF byte limit, including Korean labels, before persisting a replay.
const utf8 = new TextEncoder();
const COMMANDS = new Set(["CREATE_CONTENT", "CREATE_EDITION", "COPY_EDITION", "EDIT_EDITION"]);
const KINDS = new Map([["commands", COMMANDS], ["prints", new Set(["RECORD_PRINT", "VOID_PRINT", "RECORD_PRINT_WITH_OUTPUT"])], ["deliveries", new Set(["PREPARE_DELIVERY"])], ["lifecycle", new Set(["CHANGE_LIFECYCLE"])]]);

function checked(value) {
  if (!value || Object.keys(value).sort().join() !== "body,key,path"
    || typeof value.key !== "string" || !/^studio:excel:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value.key)
    || !KINDS.get(value.path)?.has(value.body?.command_kind || value.body?.action_kind)) {
    throw new Error("이전 저장 요청을 안전하게 복원하지 못했습니다. 새로 저장하지 말고 관리자에게 알려 주세요.");
  }
  return value;
}

export function createPlanningPendingStore(storage) {
  const key = owner => PREFIX + owner;
  return {
    read(owner) {
      if (!owner || !storage) return null;
      const raw = storage.getItem(key(owner));
      if (raw === null) return null;
      if (utf8.encode(raw).byteLength > MAX_BYTES) throw new Error("복원할 저장 요청이 너무 큽니다.");
      return checked(JSON.parse(raw));
    },
    write(owner, operation) {
      if (!owner) throw new Error("로그인한 사용자 확인이 필요합니다.");
      const raw = JSON.stringify(checked(operation));
      if (utf8.encode(raw).byteLength > MAX_BYTES) throw new Error("저장할 배치가 너무 큽니다. 변경 구간을 나누어 저장해 주세요.");
      // Browsers without tab storage retain the existing in-memory replay path.
      // A storage failure is raised before POST, never after an ambiguous write.
      storage?.setItem(key(owner), raw);
    },
    clear(owner, operation) {
      if (!owner || !storage) return;
      const current = this.read(owner);
      if (current?.key === operation.key) storage.removeItem(key(owner));
    },
  };
}
