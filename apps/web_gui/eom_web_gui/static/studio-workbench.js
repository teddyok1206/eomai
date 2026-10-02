const ACTION_LABELS = Object.freeze({
  OPEN_WORKFLOW: "제작 진행 열기",
  BUILD_REVIEW_HWPX: "HWPX 확인·승인",
  REVIEW_AND_APPROVE_ITEM: "HWPX 확인·승인",
  OPEN_ITEM: "문항 열기",
  OPEN_HWPX: "HWPX 열기",
});

const STATE_LABELS = Object.freeze({
  REQUESTED: "접수됨",
  RUNNING: "제작 중",
  AWAITING_HUMAN_APPROVAL: "승인 필요",
  PENDING: "승인 필요",
  APPROVED: "승인 완료",
});

export function renderStudioWorkbench({overview, root, counts, onOpen}) {
  counts.inProgress.textContent = String(overview.counts.in_progress);
  counts.approvalWaiting.textContent = String(overview.counts.approval_waiting);
  counts.hwpxAttention.textContent = String(overview.counts.hwpx_attention);
  counts.recentCompleted.textContent = String(overview.counts.recent_completed);
  root.replaceChildren();
  if (!overview.items.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "지금 확인할 작업이 없습니다.";
    root.append(empty);
    return;
  }
  for (const item of overview.items) {
    const article = document.createElement("article");
    article.className = "work-inbox-item";
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.title;
    const state = document.createElement("span");
    state.textContent = STATE_LABELS[item.state] || item.state;
    const time = document.createElement("small");
    time.textContent = new Intl.DateTimeFormat("ko-KR", {
      dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul",
    }).format(new Date(item.created_at));
    copy.append(title, state, time);
    const button = document.createElement("button");
    button.className = "button quiet";
    button.type = "button";
    button.textContent = ACTION_LABELS[item.next_action] || "열기";
    button.addEventListener("click", () => onOpen(item));
    article.append(copy, button);
    root.append(article);
  }
  if (overview.source_truncated) {
    const note = document.createElement("p");
    note.className = "muted-label";
    note.textContent = "최근 작업만 표시합니다.";
    root.append(note);
  }
}
