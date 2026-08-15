const NS = "http://www.w3.org/2000/svg";

const POSITIONS = {
  "workflow-runner": [460, 30],
  orchestrator: [460, 145],
  authoring: [80, 295],
  image: [300, 295],
  review: [520, 295],
  "item-management": [740, 295],
  support: [940, 295],
  "human-approval": [460, 440],
  postgresql: [210, 585],
  nas: [710, 585],
};

const WIDTH = 180;
const HEIGHT = 74;

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function center(nodeId) {
  const [x, y] = POSITIONS[nodeId] || [0, 0];
  return [x + WIDTH / 2, y + HEIGHT / 2];
}

function lineEndpoints(sourceId, targetId) {
  const [sx, sy] = center(sourceId);
  const [tx, ty] = center(targetId);
  const dx = tx - sx;
  const dy = ty - sy;
  const distance = Math.max(Math.hypot(dx, dy), 1);
  const sourcePadding = 48;
  const targetPadding = 52;
  return [
    sx + (dx / distance) * sourcePadding,
    sy + (dy / distance) * sourcePadding,
    tx - (dx / distance) * targetPadding,
    ty - (dy / distance) * targetPadding,
  ];
}

export function renderGraph(svg, nodes, edges, onSelect, selectedNodeId) {
  const edgeLayer = svg.querySelector("#edge-layer");
  const nodeLayer = svg.querySelector("#node-layer");
  edgeLayer.replaceChildren();
  nodeLayer.replaceChildren();

  for (const edge of edges) {
    if (!POSITIONS[edge.source_node_id] || !POSITIONS[edge.target_node_id]) continue;
    const [x1, y1, x2, y2] = lineEndpoints(edge.source_node_id, edge.target_node_id);
    const line = svgElement("line", {
      x1, y1, x2, y2,
      class: `graph-edge edge-${edge.status.toLowerCase()}`,
      "marker-end": "url(#arrow)",
    });
    const title = svgElement("title");
    title.textContent = `${edge.interaction_type}: ${edge.summary}`;
    line.append(title);
    edgeLayer.append(line);
  }

  for (const node of nodes) {
    const [x, y] = POSITIONS[node.node_id] || [0, 0];
    const group = svgElement("g", {
      class: `graph-node status-${node.status.toLowerCase()}${selectedNodeId === node.node_id ? " selected" : ""}`,
      transform: `translate(${x} ${y})`,
      tabindex: "0",
      role: "button",
      "aria-label": `${node.display_name}, ${node.status}`,
    });
    group.append(svgElement("rect", { width: WIDTH, height: HEIGHT, rx: "6" }));
    group.append(svgElement("circle", { cx: "16", cy: "18", r: "5", class: "node-status-dot" }));
    const name = svgElement("text", { x: "29", y: "23", class: "node-name" });
    name.textContent = node.display_name;
    group.append(name);
    const identity = svgElement("text", { x: "16", y: "45", class: "node-identity" });
    identity.textContent = node.linux_user || node.node_type.replace("_", " ");
    group.append(identity);
    const status = svgElement("text", { x: "16", y: "63", class: "node-state" });
    status.textContent = node.status.replaceAll("_", " ");
    group.append(status);
    group.addEventListener("click", () => onSelect(node.node_id));
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") onSelect(node.node_id);
    });
    nodeLayer.append(group);
  }
}
