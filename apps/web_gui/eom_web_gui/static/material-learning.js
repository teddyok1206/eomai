const KINDS = Object.freeze({TEXTBOOK: "교과서", REFERENCE_BOOK: "참고서", WORKBOOK: "문제집", MOCK_EXAM: "모의고사", OTHER: "기타 자료"});
const STATES = Object.freeze({RECEIVED: "접수됨", PREPARING: "파일 준비 중", DISCOVERING: "자료 구성 확인 중", PROCESSING: "학습 중", WAITING_FOR_CAPACITY: "작업 자리 대기 중", PAUSED: "일시 정지", COMPLETED: "학습 완료", COMPLETED_WITH_EXCEPTIONS: "일부 확인 필요", FAILED: "처리 실패", CANCELLED: "취소됨", PENDING: "대기", READY: "실행 준비됨", RUNNING: "문항 읽는 중", RESULT_READY: "내용 확인 중", REGISTERED: "문항 등록됨", ANALYZING: "풀이·개념 분석 중", PUBLISHING: "그래프 연결 중", GRAPH_READY: "그래프 연결됨", EXCEPTION: "원본 확인 필요"});
const TASK_KINDS = Object.freeze({PREPARE: "파일 준비", DISCOVER: "구성 확인", EXPLANATION: "설명 지식", QUESTION: "문항"});
const TERMINAL = new Set(["COMPLETED", "COMPLETED_WITH_EXCEPTIONS", "FAILED", "CANCELLED"]);
const MAX_BYTES = 256 * 1024 * 1024;

export function materialLearningProgress(run) {
  const counters = new Map((run.task_counts || []).map(value => [value.state, value.count]));
  const total = [...counters.values()].reduce((sum, count) => sum + count, 0);
  return total ? `${counters.get("COMPLETED") || 0}/${total} 단계` : "파일 준비 대기";
}

export function createMaterialLearning({document, api, explainError = error => error.message}) {
  const $ = selector => document.querySelector(selector);
  let owner = null, active = false, version = 0, timer = null;
  let selected = null, intent = null, busy = false, receipts = new WeakMap();

  function node(tag, text, className = "") {
    const value = document.createElement(tag);
    value.className = className;
    if (text !== undefined) value.textContent = text;
    return value;
  }
  function message(text, error = false) {
    const value = $("#material-learning-message");
    value.className = `form-message${error ? " error" : ""}`;
    value.textContent = text;
  }
  function key() { return `material-${globalThis.crypto.randomUUID()}`; }
  function stopTimer() { if (timer !== null) clearTimeout(timer); timer = null; }
  function date(value) { return new Date(value).toLocaleString("ko-KR", {timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"}); }

  async function details(runId, token = version) {
    selected = runId;
    const result = await api(`/material-learning/${encodeURIComponent(runId)}`);
    if (!active || token !== version || selected !== runId) return;
    const target = $("#material-learning-detail");
    target.replaceChildren(node("h3", result.run.title));
    target.hidden = false;
    target.append(node("p", STATES[result.run.state] || result.run.state));
    if (["DISCOVERING", "PROCESSING", "WAITING_FOR_CAPACITY", "PAUSED"].includes(result.run.state)) {
      const action = result.run.state === "PAUSED" ? "RESUME" : "PAUSE";
      const button = node("button", action === "PAUSE" ? "잠시 멈추기" : "계속 학습하기", "button quiet");
      button.type = "button";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await api(`/material-learning/${encodeURIComponent(runId)}/control`, {method: "POST", mutation: true, body: {action, expected_updated_at: result.run.updated_at}});
          if (!active || token !== version || selected !== runId) return;
          message(action === "PAUSE" ? "지금 시작된 작업까지만 마친 뒤 기다립니다. 완료한 내용은 그대로 보관합니다." : "완료한 부분은 유지하고 남은 학습을 이어갑니다.");
          await refresh();
        } catch (error) {
          if (active && token === version && selected === runId) {
            message(`학습 상태를 바꾸지 못했습니다. ${explainError(error)} 진행 상태를 새로 확인해 주세요.`, true);
            button.disabled = false;
          }
        }
      });
      target.append(button);
    }
    if (result.run.error_code) target.append(node("p", `확인 코드: ${result.run.error_code}`, "form-message error"));
    const list = node("ol");
    for (const task of result.tasks) {
      list.append(node("li", `${TASK_KINDS[task.task_kind]} · ${STATES[task.state] || task.state}${task.error_code ? ` · 확인 코드: ${task.error_code}` : ""}`));
    }
    target.append(list);
    if (result.next_ordinal !== null) target.append(node("p", "앞부분 50단계를 표시했습니다. 전체 진행 상태는 위 목록에서 확인할 수 있습니다.", "muted-label"));
  }

  async function refresh() {
    if (!active || !owner) return;
    const token = version;
    stopTimer();
    try {
      const result = await api("/material-learning");
      if (!active || token !== version) return;
      const target = $("#material-learning-runs");
      target.replaceChildren();
      if (!result.runs.length) target.append(node("p", "아직 올린 자료가 없습니다.", "empty-state"));
      else {
        const table = node("table", undefined, "material-learning-table");
        const header = node("tr");
        for (const label of ["자료", "종류", "진행 상태", "완료 단계", "올린 시각", ""]) header.append(node("th", label));
        const head = node("thead"); head.append(header); table.append(head);
        const body = node("tbody");
        for (const run of result.runs) {
          const row = node("tr");
          row.setAttribute("aria-selected", String(run.run_id === selected));
          for (const text of [run.title, KINDS[run.material_kind], STATES[run.state] || run.state, materialLearningProgress(run), date(run.created_at)]) row.append(node("td", text));
          const action = node("td");
          const button = node("button", "상세 보기", "button quiet"); button.type = "button";
          button.addEventListener("click", () => details(run.run_id).catch(error => message(explainError(error), true)));
          action.append(button); row.append(action); body.append(row);
        }
        table.append(body); target.append(table);
      }
      if (selected && result.runs.some(run => run.run_id === selected)) await details(selected, token);
      if (active && token === version && result.runs.some(run => !TERMINAL.has(run.state))) timer = setTimeout(refresh, 8000);
    } catch (error) {
      if (active && token === version) message(`학습 상태를 불러오지 못했습니다. ${explainError(error)}`, true);
    }
  }

  async function upload(file, token) {
    const saved = receipts.get(file);
    if (saved) return saved;
    const pending = intent;
    let uploadKey = pending.keys.get(file);
    if (!uploadKey) { uploadKey = key(); pending.keys.set(file, uploadKey); }
    const result = await api(`/material-learning/sources?original_filename=${encodeURIComponent(file.name)}`, {
      method: "PUT", mutation: true, body: file,
      headers: {"Content-Type": "application/octet-stream", "Idempotency-Key": uploadKey, "X-EOM-Rights-Confirmed": "true"},
    });
    if (token !== version || !owner) throw new Error("계정이 바뀌었습니다. 다시 접속해 주세요.");
    receipts.set(file, result);
    return result;
  }

  async function submit(event) {
    event.preventDefault();
    if (busy || !owner) return;
    const form = $("#material-learning-form");
    if (!form.reportValidity()) return;
    const main = $("#material-main").files[0], solutions = $("#material-solutions").files[0] || null;
    if ([main, solutions].filter(Boolean).some(file => file.size < 8 || file.size > MAX_BYTES)) {
      message("파일 한 개의 크기는 256MB 이하여야 합니다.", true); return;
    }
    const uploadSpec = {
      schema_version: "material-learning-upload/1.0", title: $("#material-title").value.trim(),
      material_kind: $("#material-kind").value, source_description: $("#material-description").value.trim(),
      additional_instructions: $("#material-instructions").value.trim(), curriculum_unit_hints: [], rights_confirmed: true,
    };
    const signature = JSON.stringify(uploadSpec);
    if (!intent || intent.signature !== signature || intent.main !== main || intent.solutions !== solutions) intent = {signature, main, solutions, key: key(), keys: new Map()};
    const token = version;
    const controls = [...form.elements];
    busy = true; controls.forEach(control => { control.disabled = true; });
    const status = $("#material-learning-upload-status");
    try {
      message(""); status.textContent = "본문 파일을 보관하고 있습니다…";
      const sources = [{source_role: "MAIN", source_upload: await upload(main, token)}];
      if (solutions) {
        status.textContent = "해설 파일을 보관하고 있습니다…";
        sources.push({source_role: "SOLUTIONS", source_upload: await upload(solutions, token)});
      }
      status.textContent = "학습을 접수하고 있습니다…";
      const accepted = await api("/material-learning", {method: "POST", mutation: true, body: {upload: uploadSpec, sources, idempotency_key: intent.key}});
      if (token !== version) return;
      selected = accepted.run_id; intent = null; form.reset();
      message("자료를 접수했습니다. 페이지 준비부터 순서대로 처리하며, 이 화면을 닫아도 작업은 계속됩니다.");
      await refresh();
    } catch (error) {
      if (token === version) message(`자료를 접수하지 못했습니다. ${explainError(error)} 같은 파일로 다시 누르면 기존 접수를 확인합니다.`, true);
    } finally {
      busy = false; controls.forEach(control => { control.disabled = false; }); status.textContent = "";
    }
  }

  return {
    install() {
      $("#material-learning-form").addEventListener("submit", submit);
      $("#material-learning-refresh").addEventListener("click", refresh);
    },
    setOwner(value) {
      if (owner === value) return;
      owner = value; version += 1; selected = null; intent = null; receipts = new WeakMap(); stopTimer();
      $("#material-learning-runs").replaceChildren();
      $("#material-learning-detail").replaceChildren(); $("#material-learning-detail").hidden = true;
      $("#material-learning-form").reset(); message("");
    },
    open() { if (!active) { active = true; refresh(); } },
    close() { active = false; version += 1; stopTimer(); },
  };
}
