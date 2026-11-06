// Published Graph index only. No generation, similarity calculation or write.
const LAYERS = Object.freeze({TEXTBOOK: "교과서", PAST_EXAM: "기출", CREATIVE: "창작", EXTERNAL: "외부", AI: "AI", CURRICULUM: "교육과정", GUIDE: "안내 자료", UNKNOWN: "분류 확인 필요"});
const TYPES = Object.freeze({CONCEPT: "개념", CLAIM: "설명", PROCESS: "과정", OBSERVABLE_PROPERTY: "성질", FORMULA: "수식", DATA_REPRESENTATION: "자료 표현", DOCUMENT_REVISION: "문서", DOCUMENT_SECTION: "문서 단원", FIGURE: "그림", TABLE: "표", EQUATION: "수식", ITEM_REVISION: "문항", ITEM_ELEMENT: "문항 요소", ASSESSMENT_PATTERN: "출제 유형", CURRICULUM_UNIT: "단원", ACHIEVEMENT_STANDARD: "성취 기준", CURRICULUM_FRAMEWORK_REVISION: "교육과정", ASSESSMENT_ITEM_OCCURRENCE: "시험 문항", ASSESSMENT_OCCURRENCE_REVISION: "시험"});
const RELATIONS = Object.freeze({CONTAINS_CURRICULUM_UNIT: "포함하는 단원", PRECEDES_CURRICULUM_UNIT: "먼저 배우는 단원", DEFINES_ACHIEVEMENT_STANDARD: "성취 기준", DEFINES: "정의", EXPLAINS: "설명", IS_A: "종류", PART_OF: "일부분", CAUSES: "원인", AFFECTS: "영향", DEPENDS_ON: "의존", CONTRASTS_WITH: "비교", REQUIRES_PREREQUISITE: "먼저 알아야 할 개념", SUPPORTS_CLAIM: "설명을 뒷받침", CONTRADICTS_CLAIM: "설명과 모순", ILLUSTRATES: "그림으로 표현", TABULATES: "표로 표현", EXPRESSES_AS_EQUATION: "수식으로 표현", DERIVED_FROM: "바탕 자료", CITES_SOURCE: "참고 자료", ALIGNS_WITH_CURRICULUM: "관련 교육과정", HAS_ITEM_ELEMENT: "문항 구성 요소", ASSESSES_CONCEPT: "평가하는 개념", REQUIRES_CONCEPT: "풀이에 필요한 개념", USES_SOURCE_EVIDENCE: "사용한 근거", REPRESENTS_CONCEPT: "표현하는 개념", SUPPORTS_STATEMENT: "진술을 뒷받침", CONTRADICTS_STATEMENT: "진술과 모순", PART_OF_INTERACTION: "상호 작용", USES_ASSESSMENT_PATTERN: "출제 유형", SIMILAR_TO_ITEM: "등록된 유사 관계", HAS_ASSESSMENT_ITEM: "시험에 포함된 문항", REPRESENTS_ITEM_REVISION: "등록 문항"});
const INITIAL_BOX = [-550, -370, 1100, 740];

function element(document, tag, text, className = "") {
  const value = document.createElement(tag);
  value.className = className;
  if (text !== undefined) value.textContent = text;
  return value;
}

// Adjacency + breadth-first rings: O(V + E), bounded to 120 visible nodes.
export function mapPositions(nodes, edges, focus) {
  const adjacency = new Map(nodes.map(node => [node.node_id, []]));
  for (const edge of edges) {
    adjacency.get(edge.from_node_id)?.push(edge.to_node_id);
    adjacency.get(edge.to_node_id)?.push(edge.from_node_id);
  }
  const root = adjacency.has(focus) ? focus : nodes[0]?.node_id;
  const depths = new Map(root ? [[root, 0]] : []);
  const queue = root ? [root] : [];
  for (let i = 0; i < queue.length; i++) {
    for (const id of adjacency.get(queue[i]) || []) {
      if (depths.has(id)) continue;
      depths.set(id, depths.get(queue[i]) + 1);
      queue.push(id);
    }
  }
  const rings = new Map();
  for (const node of nodes) {
    const depth = Math.min(4, depths.get(node.node_id) ?? 4);
    if (!rings.has(depth)) rings.set(depth, []);
    rings.get(depth).push(node.node_id);
  }
  const positions = new Map();
  for (const [depth, ids] of rings) ids.forEach((id, i) => {
    const angle = i / ids.length * Math.PI * 2 - Math.PI / 2;
    const radius = depth === 0 ? 0 : 85 + depth * 70;
    positions.set(id, {x: Math.cos(angle) * radius * 1.32, y: Math.sin(angle) * radius});
  });
  return positions;
}

export function createKnowledgeMap({document, api, openItem, previewItem}) {
  const $ = selector => document.querySelector(selector);
  let owner = null, active = false, loaded = false, sequence = 0, detailSequence = 0;
  let view = null, selected = null, nodes = new Map(), edges = new Map(), positions = new Map();
  let displayedLayer = "";
  let box = [...INITIAL_BOX], pan = null;
  const svgElement = (tag, attributes) => {
    const value = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [name, item] of Object.entries(attributes)) value.setAttribute(name, item);
    return value;
  };
  function message(text, error = false) {
    const value = $("#map-status");
    value.className = `form-message${error ? " error" : ""}`;
    value.textContent = text;
  }
  function pinQuery(extra = {}) {
    return new URLSearchParams({...extra, ...(view ? {
      graph_snapshot_revision_id: view.graph_snapshot_revision_id,
      snapshot_sha256: view.snapshot_sha256,
    } : {})});
  }
  function emptyInspector() {
    $("#map-inspector").replaceChildren(element(document, "h2", "연결을 살펴보세요"), element(document, "p", "점은 개념이나 자료, 선은 두 점의 관계입니다. 점이나 선을 눌러보세요.", "empty-state"));
  }
  async function load({fresh = false} = {}) {
    const request = ++sequence;
    ++detailSequence;
    const requestedLayer = $("#map-layer").value;
    message(requestedLayer ? `${LAYERS[requestedLayer]} 연결을 불러오고 있습니다.` : "그래프를 불러오고 있습니다.");
    try {
      const params = fresh ? new URLSearchParams({query: $("#map-query").value.trim()}) : pinQuery({query: $("#map-query").value.trim()});
      if (requestedLayer) params.set("layer", requestedLayer);
      const value = await api(`/knowledge-map?${params}`);
      if (!active || request !== sequence) return;
      if (!fresh && view && (value.graph_snapshot_revision_id !== view.graph_snapshot_revision_id || value.snapshot_sha256 !== view.snapshot_sha256)) throw new Error("조회하던 그래프 버전과 다릅니다.");
      displayedLayer = requestedLayer;
      view = value; loaded = true; selected = null;
      ++detailSequence;
      nodes = new Map(value.nodes.map(node => [node.node_id, node]));
      edges = new Map(value.edges.map(edge => [edge.edge_id, edge]));
      positions = mapPositions(value.nodes, value.edges, value.focus_node_id);
      emptyInspector(); fit(); render();
      message(value.nodes.length ? value.truncated ? "연결 일부를 표시했습니다. 점을 선택해 주변 연결을 펼쳐보세요." : "점을 누르면 관련 자료를 확인할 수 있습니다." : requestedLayer ? `${LAYERS[requestedLayer]}에서 해당 연결을 찾지 못했습니다.` : "해당 개념을 찾지 못했습니다. 짧은 핵심 단어로 찾아보세요.");
    } catch (error) {
      if (active && request === sequence) message(`그래프 조회 실패: ${error.message}`, true);
    }
  }
  function fit() { box = [...INITIAL_BOX]; $("#map-canvas").setAttribute("viewBox", box.join(" ")); }
  function render() {
    const svg = $("#map-canvas"), layer = displayedLayer;
    for (const button of document.querySelectorAll("#map-layer-controls button[data-layer]")) button.setAttribute("aria-pressed", String(button.dataset.layer === $("#map-layer").value));
    svg.replaceChildren();
    const visible = new Set([...nodes.values()].filter(node => !layer || !node.layers.length || node.layers.includes(layer)).map(node => node.node_id));
    for (const edge of edges.values()) {
      if (!visible.has(edge.from_node_id) || !visible.has(edge.to_node_id)) continue;
      const from = positions.get(edge.from_node_id), to = positions.get(edge.to_node_id);
      if (!from || !to) continue;
      const group = svgElement("g", {class: `map-edge${selected === edge.edge_id ? " selected" : ""}`, "data-edge-id": edge.edge_id, tabindex: "0", role: "button", "aria-label": `${nodes.get(edge.from_node_id).label} → ${RELATIONS[edge.edge_type] || edge.edge_type} → ${nodes.get(edge.to_node_id).label}`});
      const angle = Math.atan2(to.y - from.y, to.x - from.x) * 180 / Math.PI;
      const hit = svgElement("rect", {x: "0", y: "-7", height: "14", width: Math.hypot(to.x - from.x, to.y - from.y), transform: `translate(${from.x} ${from.y}) rotate(${angle})`, fill: "transparent", stroke: "none"});
      group.append(hit, svgElement("line", {x1: from.x, y1: from.y, x2: to.x, y2: to.y}));
      group.addEventListener("click", () => inspect("edge", edge.edge_id));
      group.addEventListener("keydown", event => {if (["Enter", " "].includes(event.key)) {event.preventDefault(); inspect("edge", edge.edge_id);}});
      svg.append(group);
    }
    const list = $("#map-node-list"); list.replaceChildren();
    for (const node of nodes.values()) {
      if (!visible.has(node.node_id)) continue;
      const position = positions.get(node.node_id);
      const group = svgElement("g", {transform: `translate(${position.x} ${position.y})`, class: `map-node${selected === node.node_id ? " selected" : ""}`, "data-node-id": node.node_id, "data-layer": layer && node.layers.includes(layer) ? layer : node.layers[0] || "CURRICULUM", tabindex: "0", role: "button", "aria-label": `${TYPES[node.node_type] || node.node_type}: ${node.label}`});
      const hit = svgElement("circle", {r: "19", fill: "transparent", class: "map-node-hit"});
      const circle = svgElement("circle", {r: node.node_type.includes("CURRICULUM") ? 10 : 7});
      const title = svgElement("title", {}); title.textContent = `${node.label}${node.layers.length ? ` · ${node.layers.map(key => LAYERS[key]).join(" · ")}` : ""}`;
      group.append(hit, circle, title);
      const sharedLayers = node.layers.filter(key => ["TEXTBOOK", "PAST_EXAM", "CREATIVE", "EXTERNAL", "AI"].includes(key));
      if (!layer && sharedLayers.length > 1) {
        const circumference = Math.PI * 22, segment = circumference / sharedLayers.length;
        sharedLayers.forEach((key, index) => group.append(svgElement("circle", {r: "11", class: "map-layer-ring", "data-layer": key, "stroke-dasharray": `${segment - 2} ${circumference - segment + 2}`, "stroke-dashoffset": -index * segment, transform: "rotate(-90)"})));
      }
      if (visible.size <= 45 || selected === node.node_id || node.node_type === "CURRICULUM_UNIT") {
        const label = svgElement("text", {x: "0", y: "25", "text-anchor": "middle"});
        label.textContent = node.label.length > 20 ? `${node.label.slice(0, 20)}…` : node.label;
        group.append(label);
      }
      const select = () => inspect("node", node.node_id);
      group.addEventListener("click", select);
      group.addEventListener("dblclick", () => inspect("node", node.node_id, true));
      group.addEventListener("keydown", event => {if (["Enter", " "].includes(event.key)) {event.preventDefault(); select();}});
      svg.append(group);
      const button = element(document, "button", node.label, "button quiet"); button.type = "button";
      button.addEventListener("click", select); list.append(button);
    }
    $("#map-count").textContent = `${visible.size}개 점 · 전체 ${view?.total_nodes.toLocaleString() || 0}개`;
  }
  async function inspect(kind, id, expand = false) {
    const request = ++detailSequence, current = sequence;
    selected = id; render();
    const row = kind === "node" ? nodes.get(id) : edges.get(id);
    const pane = $("#map-inspector");
    const heading = kind === "node" ? row.label : RELATIONS[row.edge_type] || row.edge_type;
    pane.replaceChildren(element(document, "h2", heading));
    if (kind === "node") pane.append(element(document, "p", `${TYPES[row.node_type] || row.node_type}${row.layers.length ? ` · ${row.layers.map(layer => LAYERS[layer]).join(" · ")}` : ""}`, "map-kind"));
    else pane.append(element(document, "p", `${nodes.get(row.from_node_id)?.label || ""} → ${nodes.get(row.to_node_id)?.label || ""}`, "map-kind"));
    const state = element(document, "p", "연결 근거를 확인하고 있습니다.", "muted-label"); pane.append(state);
    const isCurrent = () => active && current === sequence && request === detailSequence;
    try {
      const value = await api(`/knowledge-map?${pinQuery({[kind === "node" ? "node_id" : "edge_id"]: id, ...(displayedLayer ? {layer: displayedLayer} : {})})}`);
      if (!isCurrent()) return;
      if (value.graph_snapshot_revision_id !== view.graph_snapshot_revision_id || value.snapshot_sha256 !== view.snapshot_sha256) throw new Error("조회하던 그래프 버전과 다릅니다.");
      if (expand) replaceNeighborhood(value);
      state.textContent = value.sources.length ? "연결된 자료" : "교육과정 구조 또는 별도 근거 표시가 없는 연결입니다.";
      if (kind === "node") {
        const button = element(document, "button", "주변 연결 펼치기", "button secondary"); button.type = "button";
        button.addEventListener("click", () => {if (isCurrent()) replaceNeighborhood(value);}); pane.append(button);
      }
      for (const source of value.sources) {
        const card = element(document, "section", undefined, "map-source");
        card.append(element(document, "strong", `${LAYERS[source.layer]} · ${source.title}`));
        if (!source.available) card.append(element(document, "p", "이 자료는 현재 열 수 없습니다.", "muted-label"));
        if (source.available && source.item_id) {
          const button = element(document, "button", "DB에서 문항 열기", "button quiet"); button.type = "button";
          button.addEventListener("click", async () => {
            button.disabled = true;
            try {
              const entry = await api(`/knowledge-map/items/${encodeURIComponent(source.source_revision_id)}?${pinQuery({manifest_sha256: source.item_manifest_sha256})}`);
              if (isCurrent()) openItem(entry);
            } catch (error) {if (isCurrent()) message(`문항 열기 실패: ${error.message}`, true);}
            finally {button.disabled = false;}
          }); card.append(button);
          const preview = element(document, "button", "미리보기", "button quiet"); preview.type = "button";
          const root = element(document, "div", undefined, "map-preview"); root.hidden = true;
          preview.addEventListener("click", async () => {
            root.hidden = !root.hidden;
            if (root.hidden || root.childElementCount) return;
            preview.disabled = true;
            try {await previewItem({item_id: source.item_id, item_revision_id: source.source_revision_id}, root, isCurrent);}
            catch (error) {if (isCurrent()) root.textContent = error.message;}
            finally {preview.disabled = false;}
          }); card.append(preview, root);
        }
        const technical = element(document, "details", undefined, "technical-disclosure");
        technical.append(element(document, "summary", "자료 연결 정보"));
        const data = element(document, "dl");
        for (const [label, value] of [["원본 버전", source.source_revision_id], ["분석 기록", source.analysis_run_id], ["위치 참조", source.anchor_id], ["원본 검증값", source.source_sha256], ["발췌 검증값", source.excerpt_sha256]]) data.append(element(document, "dt", label), element(document, "dd", value));
        technical.append(data); card.append(technical); pane.append(card);
      }
      if (value.truncated) pane.append(element(document, "p", "연결·근거 일부만 표시했습니다. 다른 점을 선택하거나 개념을 검색해 범위를 좁힐 수 있습니다.", "muted-label"));
    } catch (error) {if (isCurrent()) state.textContent = `연결 조회 실패: ${error.message}`;}
  }
  function replaceNeighborhood(value) {
    // A bounded fresh neighborhood avoids an ever-growing client-side Graph.
    nodes = new Map(value.nodes.map(node => [node.node_id, node]));
    edges = new Map(value.edges.map(edge => [edge.edge_id, edge]));
    positions = mapPositions(value.nodes, value.edges, value.focus_node_id);
    fit(); render();
    message(value.truncated ? "주변 연결 일부를 표시했습니다. 다른 점을 눌러 계속 살펴볼 수 있습니다." : "선택한 점의 주변 연결입니다.");
  }
  return Object.freeze({
    install() {
      $("#map-search").addEventListener("submit", event => {event.preventDefault(); load();});
      $("#map-refresh").addEventListener("click", () => load({fresh: true}));
      $("#map-fit").addEventListener("click", fit);
      $("#map-layer").addEventListener("change", () => load());
      for (const button of document.querySelectorAll("#map-layer-controls button[data-layer]")) button.addEventListener("click", () => {
        $("#map-layer").value = button.dataset.layer;
        load();
      });
      const svg = $("#map-canvas");
      svg.addEventListener("wheel", event => {
        event.preventDefault();
        const ratio = event.deltaY > 0 ? 1.12 : 1 / 1.12;
        const width = Math.max(250, Math.min(4000, box[2] * ratio)), height = width * 740 / 1100;
        box = [box[0] + (box[2] - width) / 2, box[1] + (box[3] - height) / 2, width, height];
        svg.setAttribute("viewBox", box.join(" "));
      }, {passive: false});
      svg.addEventListener("pointerdown", event => {
        if (event.button !== 0 || event.target.closest(".map-node,.map-edge")) return;
        pan = {x: event.clientX, y: event.clientY, box: [...box]}; svg.setPointerCapture(event.pointerId);
      });
      svg.addEventListener("pointermove", event => {
        if (!pan) return;
        const bounds = svg.getBoundingClientRect(), scale = Math.min(bounds.width / pan.box[2], bounds.height / pan.box[3]);
        box = [pan.box[0] - (event.clientX - pan.x) / scale, pan.box[1] - (event.clientY - pan.y) / scale, pan.box[2], pan.box[3]];
        svg.setAttribute("viewBox", box.join(" "));
      });
      for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) svg.addEventListener(name, () => {pan = null;});
    },
    setOwner(value) {
      if (value === owner) return;
      owner = value; ++sequence; ++detailSequence; view = null; loaded = false;
      nodes.clear(); edges.clear(); selected = null;
      $("#map-query").value = ""; $("#map-layer").value = "";
      displayedLayer = "";
      for (const button of document.querySelectorAll("#map-layer-controls button[data-layer]")) button.setAttribute("aria-pressed", String(button.dataset.layer === ""));
      $("#map-canvas").replaceChildren(); $("#map-node-list").replaceChildren(); emptyInspector(); message("");
    },
    open() {active = true; if (!loaded) load();},
    close() {active = false; ++sequence; ++detailSequence;},
  });
}
