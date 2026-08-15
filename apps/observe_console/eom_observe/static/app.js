import { apiGet, logout, streamUrl } from "./api.js";
import { renderGraph } from "./graph.js";
import { getState, receiveSnapshot, selectNode, setStreamConnected, subscribe, togglePaused } from "./state.js";

const elements = {
  connection: document.querySelector("#connection-status"),
  db: document.querySelector("#db-status"),
  snapshotTime: document.querySelector("#snapshot-time"),
  revision: document.querySelector("#revision"),
  pause: document.querySelector("#pause-button"),
  freshness: document.querySelector("#freshness"),
  graph: document.querySelector("#system-graph"),
  detailStatus: document.querySelector("#detail-status"),
  detail: document.querySelector("#detail-content"),
  queue: document.querySelector("#queue-list"),
  timeline: document.querySelector("#timeline-body"),
};

const metricIds = {
  active_workflows: "metric-workflows",
  waiting_approvals: "metric-approvals",
  queued_jobs: "metric-queued",
  running_jobs: "metric-running",
  failed_jobs_recent: "metric-failures",
  idle_workers: "metric-idle",
};

function text(value) {
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

function formatUtc(value) {
  if (!value) return "-";
  return new Date(value).toISOString().replace(".000Z", "Z");
}

function definitionList(values) {
  const list = document.createElement("dl");
  list.className = "definition-list";
  for (const [key, value] of Object.entries(values)) {
    const dt = document.createElement("dt");
    dt.textContent = key.replaceAll("_", " ");
    const dd = document.createElement("dd");
    dd.textContent = Array.isArray(value) ? value.join(", ") : text(value);
    list.append(dt, dd);
  }
  return list;
}

function renderNodeDetail(node) {
  elements.detail.replaceChildren();
  if (!node) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Select a component or timeline event.";
    elements.detail.append(empty);
    elements.detailStatus.textContent = "NONE";
    return;
  }
  elements.detailStatus.textContent = node.status;
  const identity = {
    name: node.display_name,
    type: node.node_type,
    role: node.role,
    linux_user: node.linux_user,
    slot: node.slot_id,
  };
  const activity = {
    workflow: node.current_workflow_id,
    step: node.current_step_key,
    attempt: node.attempt,
    job: node.current_job_id,
    elapsed_seconds: node.elapsed_seconds,
    last_event: node.last_event,
    last_event_at: formatUtc(node.last_event_at),
  };
  for (const [heading, values] of [["Identity", identity], ["Current activity", activity], ["Input metadata", node.input_summary], ["Output metadata", node.output_summary]]) {
    const title = document.createElement("h3");
    title.textContent = heading;
    elements.detail.append(title, definitionList(values));
  }
  if (node.last_error_code || node.last_error_summary) {
    const title = document.createElement("h3");
    title.textContent = "Error";
    elements.detail.append(title, definitionList({ code: node.last_error_code, summary: node.last_error_summary }));
  }
}

function renderQueue(snapshot) {
  const values = [
    ["Queued", snapshot.summary.queued_jobs],
    ["Running", snapshot.summary.running_jobs],
    ["Approval", snapshot.summary.waiting_approvals],
    ["Failed recent", snapshot.summary.failed_jobs_recent],
  ];
  elements.queue.replaceChildren();
  for (const [label, count] of values) {
    const row = document.createElement("div");
    const name = document.createElement("span");
    name.textContent = label;
    const value = document.createElement("strong");
    value.textContent = count;
    row.append(name, value);
    elements.queue.append(row);
  }
}

function filters() {
  return {
    workflow: document.querySelector("#filter-workflow").value.trim().toLowerCase(),
    job: document.querySelector("#filter-job").value.trim().toLowerCase(),
    role: document.querySelector("#filter-role").value.toLowerCase(),
    status: document.querySelector("#filter-status").value.trim().toLowerCase(),
    event: document.querySelector("#filter-event").value.trim().toLowerCase(),
    text: document.querySelector("#filter-text").value.trim().toLowerCase(),
  };
}

function eventVisible(event, activeFilters) {
  const route = `${event.source_node_id} ${event.target_node_id}`.toLowerCase();
  return (!activeFilters.workflow || (event.workflow_id || "").toLowerCase().includes(activeFilters.workflow))
    && (!activeFilters.job || (event.job_id || "").toLowerCase().includes(activeFilters.job))
    && (!activeFilters.role || route.includes(activeFilters.role))
    && (!activeFilters.status || event.status.toLowerCase().includes(activeFilters.status))
    && (!activeFilters.event || event.event_type.toLowerCase().includes(activeFilters.event))
    && (!activeFilters.text || `${event.summary} ${event.error_code || ""}`.toLowerCase().includes(activeFilters.text));
}

async function renderEventDetail(event) {
  elements.detailStatus.textContent = event.status;
  elements.detail.replaceChildren(definitionList({
    event: event.event_type,
    time_utc: formatUtc(event.timestamp),
    route: `${event.source_node_id} → ${event.target_node_id}`,
    workflow: event.workflow_id,
    step_run: event.step_run_id,
    job: event.job_id,
    artifact: event.artifact_id,
    revision: event.revision_id,
    status: event.status,
    summary: event.summary,
    error: event.error_code,
  }));
  const requests = [];
  if (event.workflow_id) requests.push(["Workflow detail", `/workflows/${encodeURIComponent(event.workflow_id)}`, "workflow"]);
  if (event.job_id) requests.push(["Job detail", `/jobs/${encodeURIComponent(event.job_id)}`, "job"]);
  if (event.artifact_id) requests.push(["Artifact detail", `/artifacts/${encodeURIComponent(event.artifact_id)}`, "artifact"]);
  for (const [heading, path, kind] of requests) {
    let detail;
    try {
      detail = await apiGet(path);
    } catch (_) {
      continue;
    }
    const title = document.createElement("h3");
    title.textContent = heading;
    const safe = {};
    for (const key of ["definition_key", "definition_version", "state", "stage", "current_step_key", "rework_cycle_count", "task_type", "protocol_version", "worker_role", "artifact_type", "approved"]) {
      if (detail[key] !== undefined) safe[key] = detail[key];
    }
    if (kind === "workflow") {
      safe.step_attempts = detail.step_runs.map((step) => `${step.step_key}#${step.attempt}:${step.state}`);
      safe.platform_jobs = detail.step_runs.map((step) => step.platform_job_id).filter(Boolean);
      safe.artifact_pointers = detail.step_runs
        .map((step) => `${step.output_summary.logical_artifact_id || "-"}/${step.output_summary.revision_id || "-"}`)
        .filter((pointer) => pointer !== "-/-");
      safe.approval_states = detail.approvals.map((approval) => approval.status);
      safe.event_sequence = detail.events.map((item) => item.event_type);
    } else if (kind === "job") {
      safe.worker_slot = detail.worker_slot_id;
      safe.worker_user = detail.worker_linux_user;
      safe.artifact = detail.artifact_id;
      safe.revision = detail.revision_id;
      safe.state_sequence = detail.events.map((item) => item.status);
    } else {
      safe.job = detail.job_id;
      safe.revisions = detail.revisions.map((revision) => `${revision.revision_id}:${revision.result_status || "unknown"}`);
    }
    elements.detail.append(title, definitionList(safe));
  }
}

function renderTimeline(snapshot) {
  const activeFilters = filters();
  const events = snapshot.recent_events.filter((event) => eventVisible(event, activeFilters)).slice(-100).reverse();
  elements.timeline.replaceChildren();
  for (const event of events) {
    const row = document.createElement("tr");
    row.tabIndex = 0;
    for (const value of [
      formatUtc(event.timestamp),
      event.event_type,
      `${event.source_node_id} → ${event.target_node_id}`,
      event.status,
      event.workflow_id || event.job_id || event.artifact_id || "-",
    ]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    row.addEventListener("click", () => renderEventDetail(event));
    row.addEventListener("keydown", (keyboardEvent) => {
      if (keyboardEvent.key === "Enter") renderEventDetail(event);
    });
    elements.timeline.append(row);
  }
}

function render(state) {
  elements.connection.classList.toggle("connected", state.streamConnected);
  elements.connection.classList.toggle("paused", state.paused);
  elements.connection.lastChild.textContent = state.paused ? "Paused" : state.streamConnected ? "Connected" : "Reconnecting";
  elements.pause.textContent = state.paused ? "▶" : "Ⅱ";
  elements.pause.title = state.paused ? "Resume updates" : "Pause updates";
  elements.pause.setAttribute("aria-label", elements.pause.title);
  const snapshot = state.snapshot;
  if (!snapshot) return;
  elements.db.textContent = snapshot.data_freshness.database.toUpperCase();
  elements.snapshotTime.textContent = formatUtc(snapshot.generated_at);
  elements.revision.textContent = snapshot.deployment_revision;
  elements.freshness.textContent = snapshot.data_freshness.database.toUpperCase();
  for (const [key, id] of Object.entries(metricIds)) document.querySelector(`#${id}`).textContent = snapshot.summary[key];
  renderGraph(elements.graph, snapshot.nodes, snapshot.edges, selectNode, state.selectedNodeId);
  renderNodeDetail(snapshot.nodes.find((node) => node.node_id === state.selectedNodeId));
  renderQueue(snapshot);
  renderTimeline(snapshot);
}

function connectStream() {
  const source = new EventSource(streamUrl());
  source.addEventListener("open", () => setStreamConnected(true));
  source.addEventListener("error", () => setStreamConnected(false));
  for (const eventName of ["snapshot", "delta"]) {
    source.addEventListener(eventName, (event) => receiveSnapshot(JSON.parse(event.data)));
  }
  source.addEventListener("degraded", () => setStreamConnected(true));
  source.addEventListener("recovered", async () => receiveSnapshot(await apiGet("/snapshot")));
}

for (const input of document.querySelectorAll(".filters input, .filters select")) {
  input.addEventListener("input", () => {
    const snapshot = getState().snapshot;
    if (snapshot) renderTimeline(snapshot);
  });
}
elements.pause.addEventListener("click", togglePaused);
document.querySelector("#logout-button").addEventListener("click", logout);
subscribe(render);
apiGet("/snapshot").then(receiveSnapshot).catch(() => setStreamConnected(false));
connectStream();
