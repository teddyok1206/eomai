// Workbook bytes live only in the upload boundary. Tab storage retains a small,
// owner-scoped proposal pointer and replay key, never rows, files or credentials.
const PREFIX = "eom:excel:workbook:1:";
const MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const MAX_BYTES = 8 * 1024 * 1024;
const TYPES = Object.freeze({MOCK_EXAM: "모의고사", TEXTBOOK: "교재", WEEKLY: "주간지", OTHER: "기타"});
const STATUS = Object.freeze({MATCHED: "연결됨", MISSING: "DB에 없는 고유번호", AMBIGUOUS: "동일 번호가 여러 개", UNAVAILABLE: "원본 파일 확인 필요"});
// These are explicit owner rejections, not transport failures. A rejection on
// replay can still refer to an earlier committed import; never claim no save.
const REJECTED_IMPORT_CODES = new Set([
  "CURATED_SOURCE_STALE", "CURATED_SOURCE_POINTER_INVALID", "CURATED_SOURCE_SELECTION_INVALID",
  "CURATED_SOURCE_PERMISSION_DENIED", "CONTENT_PLANNING_PERMISSION_DENIED",
  "CONTENT_WORKBOOK_UNRESOLVED", "CONTENT_WORKBOOK_REQUEST_INVALID",
  "CONTENT_WORKBOOK_STRUCTURE_TOO_LARGE",
  "CONTENT_WORKBOOK_PROPOSAL_INVALID", "CONTENT_WORKBOOK_PROPOSAL_OWNER_MISMATCH",
]);
const REJECTED_IMPORT_GUIDANCE = "이 연결 내역으로 계속 저장할 수 없습니다. 이전 요청에서 이미 저장됐을 수 있으니 Excel 목록에서 기존 저장 여부를 확인한 뒤 이 연결 내역을 닫아 주세요.";
const POINTER_KEYS = ["artifact_id", "artifact_revision_id", "member_path", "schema_ref", "media_type", "sha256"];
const samePointer = (left, right) => POINTER_KEYS.every(key => left?.[key] === right?.[key]);
function checkedPin(value) {
  const p = value?.proposal;
  if (!value || Object.keys(value).sort().join() !== "key,proposal" || !p
    || Object.keys(p).sort().join() !== [...POINTER_KEYS].sort().join()
    || !/^artifact_[0-9a-f]{32}$/.test(p.artifact_id)
    || !/^rev_[0-9a-f]{32}$/.test(p.artifact_revision_id)
    || !/^sha256:[0-9a-f]{64}$/.test(p.sha256)
    || typeof p.member_path !== "string" || !p.member_path || p.member_path.length > 512
    || p.schema_ref !== "eom://schemas/content-planning/workbook-proposal/1.0"
    || p.media_type !== "application/json"
    || (value.key !== null && !/^studio:excel-import:[0-9a-f-]{36}$/.test(value.key))) {
    throw new Error("이전 엑셀 요청을 안전하게 복원하지 못했습니다. 새로 저장하지 말고 관리자에게 알려 주세요.");
  }
  return value;
}

export function createContentWorkbookImport({document, api, can, storage = globalThis.sessionStorage,
  isBlocked = () => false, beforeCommit = () => true, onStateChange = () => {}, onImported = () => {},
  confirm = text => globalThis.confirm(text)}) {
  const $ = suffix => document.getElementById(`excel-import-${suffix}`);
  const node = (tag, text, className = "") => {const n = document.createElement(tag); n.textContent = text; n.className = className; return n;};
  let owner = null, epoch = 0, active = false, busy = false, pin = null, preview = null, blocked = false;
  let uploadFile = null, uploadKey = null, saved = null, rejected = null;
  const readable = () => can("deliverable:read") && can("item:read") && can("content_intake:read");
  const writable = () => readable() && can("deliverable:create");
  const message = (text, error = false) => {$("message").textContent = text; $("message").className = `form-message${error ? " error" : ""}`;};
  function recordRejection(error) {
    if (pin?.key && REJECTED_IMPORT_CODES.has(error.code)) rejected = error.code;
    if (error.code === "CONTENT_WORKBOOK_STRUCTURE_TOO_LARGE") {
      preview = null;
      render();
    }
  }
  function persist(value) {
    if (!owner) throw new Error("로그인한 사용자를 확인해 주세요.");
    storage?.setItem(PREFIX + owner, JSON.stringify(checkedPin(value)));
    pin = value;
  }
  function sync() {
    $("panel").hidden = !readable();
    const unavailable = !owner || busy || blocked || isBlocked();
    $("file").disabled = unavailable || Boolean(pin?.key) || !writable();
    $("read").disabled = $("file").disabled;
    $("save").disabled = unavailable || Boolean(rejected) || !writable() || !preview?.can_commit
      || (!pin?.key && !$("confirm").checked)
      || (preview?.metadata.print_status === "PRINTED" && !can("usage:fulfill_plan"));
    $("save").textContent = pin?.key ? "같은 저장 요청 다시 확인" : "새 교재로 가져오기";
    $("confirm").disabled = unavailable || Boolean(pin?.key) || !preview?.can_commit;
    $("clear").disabled = unavailable || Boolean(pin?.key && !rejected) || !pin;
    $("clear").textContent = rejected ? "기존 저장 확인 후 연결 내역 닫기" : "확인 내역 닫기";
    $("refresh").hidden = !pin;
    $("refresh").disabled = unavailable || !readable();
    $("previous").disabled = unavailable || !preview || preview.offset === 0;
    $("next").disabled = unavailable || !preview || preview.next_offset === null;
    $("open").hidden = !saved;
    $("open").disabled = unavailable;
  }
  function setBusy(value) {busy = value; sync(); onStateChange();}
  function render() {
    $("preview").hidden = !preview;
    $("rows").replaceChildren();
    if (preview) {
      const m = preview.metadata;
      $("title").textContent = `${m.content_title} · ${m.edition_label}`;
      $("summary").textContent = `${TYPES[m.content_type]}${m.academic_year ? ` · ${m.academic_year}년` : ""} · 전체 ${preview.total_rows}문항 · 연결 ${preview.matched_rows} · 확인 필요 ${preview.unresolved_rows}${preview.duplicate_uses ? ` · 중복 사용 ${preview.duplicate_uses}회` : ""}`;
      $("filename").textContent = preview.original_filename;
      $("confirm-label").textContent = m.print_status === "PRINTED"
        ? `연결 내역을 확인했습니다. 새 교재와 인쇄 기록${m.printed_on ? ` (${m.printed_on})` : " (날짜 미상)"}을 함께 저장합니다.`
        : "연결 내역을 확인했습니다. 기존 교재를 바꾸지 않고 새 교재로 저장합니다.";
      $("notice").textContent = !preview.can_commit
        ? "확인이 필요한 고유번호를 엑셀에서 고친 뒤 다시 올려 주세요. 일부 문항만 저장하지 않습니다."
        : m.print_status === "PRINTED" && !can("usage:fulfill_plan")
          ? "인쇄 기록을 저장할 권한이 필요합니다. 관리자에게 알려 주세요."
          : preview.duplicate_uses ? "같은 문항을 여러 번 쓴 자리는 원래 순서대로 모두 보존합니다." : "";
      for (const {row, resolution} of preview.rows) {
        const tr = document.createElement("tr");
        for (const text of [String(row.row_number), [row.group_label, row.section_label].filter(Boolean).join(" / ") || "—", row.display_number || "—", row.external_number]) tr.append(node("td", text));
        const title = node("td", resolution.title || "");
        title.append(node("span", STATUS[resolution.status], resolution.status === "MATCHED" ? "excel-import-linked" : "excel-import-issue"));
        tr.append(title, node("td", row.points_milli === null ? "—" : String(row.points_milli / 1000)), node("td", row.note || "—"));
        $("rows").append(tr);
      }
      $("page").textContent = `${preview.offset + 1}–${preview.offset + preview.rows.length} / ${preview.total_rows}`;
    }
    sync();
  }
  async function readPage(offset = 0) {
    if (!owner || !pin || busy || blocked || !readable() || isBlocked()) return;
    const actor = epoch, expected = pin.proposal;
    setBusy(true); message("DB 연결 내역을 확인하고 있습니다…");
    try {
      const result = await api("/content-planning/imports/query", {method: "POST", mutation: true, body: {proposal: expected, offset, limit: 100}});
      if (actor !== epoch || !samePointer(expected, pin?.proposal)) return;
      if (!samePointer(result.proposal, expected) || result.offset !== offset) throw new Error("요청한 엑셀의 연결 내역과 다릅니다.");
      preview = result; render();
      message(rejected ? REJECTED_IMPORT_GUIDANCE : pin.key ? "이전 저장 요청이 남아 있습니다. 같은 저장 요청 다시 확인으로 결과를 이어서 확인해 주세요." : "연결 내역을 확인한 뒤 가져오기를 눌러 주세요. 아직 교재에 저장되지 않았습니다.", Boolean(rejected));
    } catch (error) {if (actor === epoch) {recordRejection(error); message(`연결 내역 확인 실패: ${error.message}${rejected ? ` ${REJECTED_IMPORT_GUIDANCE}` : ""}`, true);}}
    finally {if (actor === epoch) setBusy(false);}
  }
  async function upload() {
    if (!owner || busy || blocked || pin?.key || !writable() || isBlocked()) return;
    const file = $("file").files?.[0];
    if (!file || !/\.xlsx$/i.test(file.name) || file.size < 8 || file.size > MAX_BYTES) {
      message("양식에 맞는 .xlsx 파일을 골라 주세요. 파일 크기는 8 MB 이하여야 합니다.", true); return;
    }
    if (uploadFile !== file) {uploadFile = file; uploadKey = `studio:excel-upload:${crypto.randomUUID()}`;}
    const actor = epoch;
    setBusy(true); message("엑셀을 읽고 고유번호로 DB 문항을 연결하고 있습니다…");
    try {
      const result = await api(`/content-planning/imports?original_filename=${encodeURIComponent(file.name)}`, {
        method: "PUT", mutation: true, body: file,
        headers: {"Content-Type": MIME, "Idempotency-Key": uploadKey},
      });
      if (actor !== epoch) return;
      persist({proposal: result.proposal, key: null}); preview = result; saved = null;
      $("confirm").checked = false; render();
      message("연결 내역을 확인한 뒤 가져오기를 눌러 주세요. 아직 교재에 저장되지 않았습니다.");
    } catch (error) {if (actor === epoch) message(`엑셀 확인 실패: ${error.message}`, true);}
    finally {if (actor === epoch) setBusy(false);}
  }
  async function openSaved() {
    if (!saved || busy || isBlocked() || !beforeCommit()) return;
    const actor = epoch;
    setBusy(true);
    try {await onImported(saved);}
    catch (error) {if (actor === epoch) message(`저장은 완료됐지만 교재를 열지 못했습니다: ${error.message}`, true);}
    finally {if (actor === epoch) setBusy(false);}
  }
  async function commit() {
    if (!owner || busy || blocked || rejected || isBlocked() || !writable() || !preview?.can_commit
      || (preview.metadata.print_status === "PRINTED" && !can("usage:fulfill_plan"))
      || (!pin?.key && (!$("confirm").checked || !beforeCommit()))) return;
    const actor = epoch;
    setBusy(true); message("새 교재로 저장하고 있습니다…");
    try {
      const operation = {...pin, key: pin.key || `studio:excel-import:${crypto.randomUUID()}`};
      persist(operation); onStateChange();
      const result = await api("/content-planning/imports/commit", {method: "POST", mutation: true,
        body: {proposal: operation.proposal}, headers: {"Idempotency-Key": operation.key}});
      if (actor !== epoch) return;
      saved = result;
      // A received commit result is final. If opening its UI fails, retry only
      // the read/open callback, not the successful persistence command.
      storage?.removeItem(PREFIX + owner); pin = null; preview = null;
      $("file").value = ""; $("confirm").checked = false; render();
      message(`${result.composition.content_title} · ${result.composition.edition_label} 가져오기가 완료됐습니다.${result.print_record_id ? " 인쇄 기록도 저장했습니다." : ""}`);
      try {await onImported(result);}
      catch (error) {if (actor === epoch) message(`저장은 완료됐지만 교재를 열지 못했습니다: ${error.message}`, true);}
    } catch (error) {if (actor === epoch) {recordRejection(error); message(`가져오기 결과를 확인하지 못했습니다: ${error.message} ${rejected ? REJECTED_IMPORT_GUIDANCE : "같은 저장 요청 다시 확인을 눌러 주세요."}`, true);}}
    finally {if (actor === epoch) setBusy(false);}
  }
  return {
    locked: () => busy || Boolean(pin?.key && !rejected) || blocked,
    sync,
    setOwner(value) {
      if (value === owner) return;
      owner = value; epoch++; busy = false; pin = null; preview = null; saved = null; blocked = false; rejected = null; uploadFile = null; uploadKey = null;
      $("file").value = ""; $("confirm").checked = false; message("");
      try {
        const raw = owner && storage?.getItem(PREFIX + owner);
        if (raw) {if (raw.length > 4096) throw new Error("이전 엑셀 요청을 안전하게 복원하지 못했습니다."); pin = checkedPin(JSON.parse(raw));}
      } catch (error) {blocked = true; message(error.message, true);}
      render();
      if (pin) {$("panel").open = true; if (active) readPage();}
    },
    open() {active = true; if (pin && !preview) readPage();},
    close() {active = false;},
    install() {
      $("file").addEventListener("change", () => {
        if (busy || pin?.key || isBlocked()) return;
        try {
          if (owner) storage?.removeItem(PREFIX + owner);
          pin = null; preview = null; uploadFile = null; uploadKey = null;
          $("confirm").checked = false; render(); message("선택한 파일의 연결 내역을 확인해 주세요.");
        } catch (error) {blocked = true; sync(); message(error.message, true);}
      });
      $("form").addEventListener("submit", event => {event.preventDefault(); upload();});
      $("confirm").addEventListener("change", sync);
      $("save").addEventListener("click", commit);
      $("refresh").addEventListener("click", () => readPage(preview?.offset || 0));
      $("previous").addEventListener("click", () => readPage(Math.max(0, (preview?.offset || 0) - 100)));
      $("next").addEventListener("click", () => {if (preview && preview.next_offset !== null) readPage(preview.next_offset);});
      $("open").addEventListener("click", openSaved);
      $("clear").addEventListener("click", () => {
        if (busy || blocked || (pin?.key && !rejected) || isBlocked()) return;
        if (rejected && !confirm("이전 요청에서 교재가 이미 저장됐을 수 있습니다. Excel 목록에서 기존 저장 여부를 확인하셨나요? 확인했다면 이 화면의 연결 내역만 닫습니다. 기존 교재와 서버 기록은 삭제하지 않습니다.")) return;
        try {
          if (owner) storage?.removeItem(PREFIX + owner);
          pin = null; preview = null; rejected = null; uploadFile = null; uploadKey = null;
          $("file").value = ""; $("confirm").checked = false; render(); message(""); onStateChange();
        }
        catch (error) {message(error.message, true);}
      });
      sync();
    },
  };
}
