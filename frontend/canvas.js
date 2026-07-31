const $ = (id) => document.getElementById(id);

const optionDefaults = {
  deduplicate: true,
  resolution_filter: true,
  embedding: true,
  clustering: true,
  graph_filter: true,
  locate: true,
  retry: true,
  review: true,
  pixai: true,
  selection: true,
  caption: true,
};

const storedOptions = (() => {
  try {
    return JSON.parse(localStorage.getItem("loraforge-node-options") || "{}");
  } catch {
    return {};
  }
})();

const nodeOptions = { ...optionDefaults, ...storedOptions };
if (!nodeOptions.embedding) {
  nodeOptions.clustering = false;
  nodeOptions.graph_filter = false;
}
if (!nodeOptions.locate) nodeOptions.retry = false;
const nodeRegistry = new Map();
const edgePairs = [
  ["node-input", "node-scan"],
  ["node-scan", "node-resolution"],
  ["node-resolution", "node-embedding"],
  ["node-embedding", "node-clustering"],
  ["node-clustering", "node-graph"],
  ["node-graph", "node-locate"],
  ["node-locate", "node-retry"],
  ["node-retry", "review-panel"],
  ["review-panel", "node-pixai"],
  ["node-pixai", "node-selection"],
  ["node-selection", "node-caption"],
  ["node-caption", "node-output"],
];

let canvasScale = 0.62;
let canvasX = 24;
let canvasY = 28;
let panning = false;
let panOrigin = null;
let draggingNode = null;
let dragOrigin = null;
let focusedSection = null;
let savedCanvasView = null;
let directPixaiMode = localStorage.getItem("loraforge-direct-pixai") === "true";
let syncToolbarRunState = () => {};

const sectionGroups = {
  clustering: ["node-clustering"],
  locate: ["node-locate"],
  review: ["review-panel"],
  tagging: ["node-pixai", "node-selection", "node-caption"],
};

const directBypassNodes = [
  "node-scan",
  "node-resolution",
  "node-embedding",
  "node-clustering",
  "node-graph",
  "node-locate",
  "node-retry",
  "review-panel",
];

function element(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function glassButton(label, className = "") {
  const button = element("button", `liquid-control ${className}`.trim());
  button.type = "button";
  button.textContent = label;
  return button;
}

function canvasModuleSwitch() {
  const button = glassButton("", "canvas-module-switch");
  button.id = "canvas-module-switch";
  button.type = "button";
  button.setAttribute("role", "switch");
  button.title = "跳过视觉筛选，直接运行 PixAI 标注";
  const label = element("span", "module-switch-label", "跳过视觉筛选");
  const track = element("span", "module-switch-track");
  track.appendChild(element("i"));
  button.append(label, track);
  return button;
}

function nodeToggle(option, locked = false) {
  const button = element("button", "node-switch liquid-control");
  button.type = "button";
  button.dataset.nodeOption = option;
  button.setAttribute("role", "switch");
  button.disabled = locked;
  if (locked) {
    button.classList.add("active");
    button.setAttribute("aria-checked", "true");
  }
  button.title = locked ? "此节点为必需节点" : "启用或旁路此节点";
  button.appendChild(element("span", "switch-knob"));
  return button;
}

function nodeHeader(index, title, subtitle, option, locked = false) {
  const header = element("header", "flow-node-header");
  const identity = element("div", "flow-node-identity");
  identity.append(
    element("span", "flow-node-index", index),
    (() => {
      const copy = element("div", "flow-node-copy");
      copy.append(element("strong", "", title), element("small", "", subtitle));
      return copy;
    })(),
  );
  header.append(identity, nodeToggle(option, locked));
  return header;
}

function makeNode({
  id,
  index,
  title,
  subtitle,
  option,
  x,
  y,
  width,
  stage,
  locked = false,
  className = "",
}) {
  const node = element(
    "article",
    `flow-node liquid-panel ${className} ${stage ? "pipeline-node" : ""}`.trim(),
  );
  node.id = id;
  node.dataset.nodeOption = option;
  if (stage) node.dataset.stage = stage;
  node.style.left = `${x}px`;
  node.style.top = `${y}px`;
  node.style.width = `${width}px`;
  node.appendChild(nodeHeader(index, title, subtitle, option, locked));
  const body = element("div", "flow-node-body");
  node.appendChild(body);
  nodeRegistry.set(id, node);
  return { node, body };
}

function metric(label, id, initial = "—") {
  const item = element("div", "node-metric");
  item.append(element("span", "", label), element("strong", "", initial));
  item.lastElementChild.id = id;
  return item;
}

function previewTile(label, className) {
  const tile = element("div", `scan-preview-tile ${className}`);
  tile.append(element("span", "", label), element("i", "preview-landscape"));
  return tile;
}

function graphPreview() {
  const wrap = element("div", "graph-preview");
  wrap.innerHTML = `
    <svg viewBox="0 0 300 150" aria-label="Mutual Top-K graph preview">
      <g class="graph-lines">
        <path d="M25 82 L68 38 L109 73 L149 32 L192 66 L238 34 L277 78"/>
        <path d="M25 82 L73 118 L109 73 L153 119 L192 66 L235 116 L277 78"/>
        <path d="M68 38 L73 118 M109 73 L153 119 M149 32 L192 66 M192 66 L235 116"/>
        <path d="M73 118 L153 119 L235 116"/>
      </g>
      <g class="graph-dots">
        <circle cx="25" cy="82" r="6"/><circle cx="68" cy="38" r="7"/>
        <circle cx="73" cy="118" r="5"/><circle cx="109" cy="73" r="8"/>
        <circle cx="149" cy="32" r="5"/><circle cx="153" cy="119" r="7"/>
        <circle cx="192" cy="66" r="9"/><circle cx="235" cy="116" r="5"/>
        <circle cx="238" cy="34" r="6"/><circle cx="277" cy="78" r="7"/>
      </g>
    </svg>`;
  return wrap;
}

function embeddingPreview() {
  const preview = element("div", "embedding-preview");
  for (let index = 0; index < 56; index += 1) {
    const dot = element("i", "embedding-dot");
    dot.style.setProperty("--x", `${8 + ((index * 37) % 86)}%`);
    dot.style.setProperty("--y", `${10 + ((index * 53) % 78)}%`);
    dot.style.setProperty("--d", `${(index % 7) * -0.28}s`);
    dot.style.setProperty("--s", `${2 + (index % 4)}px`);
    preview.appendChild(dot);
  }
  return preview;
}

function resolutionPreview() {
  const preview = element("div", "resolution-preview");
  const bars = element("div", "resolution-bars");
  for (let index = 0; index < 34; index += 1) {
    const bar = element("i");
    const wave = 28 + ((index * 29) % 68);
    bar.style.height = `${wave}%`;
    bars.appendChild(bar);
  }
  const marker = element("span", "resolution-marker");
  marker.append(element("b", "", "1MP"), element("i"));
  preview.append(bars, marker);
  return preview;
}

function buildCanvas() {
  const oldShell = document.querySelector(".app-shell");
  if (!oldShell) {
    finishCanvasBoot();
    return;
  }

  const controlPanel = document.querySelector(".control-panel");
  const similarityModelField = document.querySelector(".similarity-model-field");
  const resolutionThresholdField = document.querySelector(".resolution-threshold-field");
  const completeLinkageField = document.querySelector(".complete-linkage-field");
  const graphSimilarityField = document.querySelector(".graph-similarity-field");
  const pipelinePanel = document.querySelector(".pipeline-panel");
  const statsPanel = document.querySelector(".stats-panel");
  const auditPanel = $("audit-panel");
  const locatePanel = $("locate-flow-panel");
  const logPanel = document.querySelector(".log-panel");
  const resultPanel = document.querySelector(".result-panel");
  const reviewPanel = $("review-panel");
  const curationPanel = $("curation-panel");
  const lightbox = $("review-lightbox");
  const languageSwitch = document.querySelector(".language-switch");
  const healthBadge = $("health-badge");

  const shell = element("div", "forge-canvas-shell");
  const topbar = element("header", "canvas-topbar liquid-panel");
  const brand = element("div", "canvas-brand");
  const logo = document.createElement("img");
  logo.src = "./loraforge-logo.png";
  logo.alt = "LoRAForge";
  const brandCopy = element("div", "canvas-brand-copy");
  brandCopy.append(
    element("strong", "", "LoRAForge"),
    element("span", "", "∞ 无限画布 · LoRA 数据集流水线"),
  );
  brand.append(logo, brandCopy);

  const topActions = element("div", "canvas-top-actions");
  const fitButton = glassButton("适应画布", "canvas-fit");
  fitButton.id = "canvas-fit";
  const zoomOut = glassButton("−", "canvas-zoom-button");
  zoomOut.id = "canvas-zoom-out";
  const zoomValue = element("span", "canvas-zoom-value", "62%");
  zoomValue.id = "canvas-zoom-value";
  const zoomIn = glassButton("+", "canvas-zoom-button");
  zoomIn.id = "canvas-zoom-in";
  const moduleSwitch = canvasModuleSwitch();
  const logButton = glassButton("日志", "canvas-log-button");
  logButton.id = "canvas-log-button";
  const focusExitButton = glassButton("返回画布", "canvas-focus-exit");
  focusExitButton.id = "canvas-focus-exit";
  const runButton = glassButton("▶ 运行流水线", "canvas-run primary");
  runButton.id = "canvas-run";
  if (languageSwitch) topActions.appendChild(languageSwitch);
  if (healthBadge) topActions.appendChild(healthBadge);
  topActions.append(
    moduleSwitch,
    logButton,
    focusExitButton,
    fitButton,
    zoomOut,
    zoomValue,
    zoomIn,
    runButton,
  );
  topbar.append(brand, topActions);

  const sidebar = element("aside", "canvas-sidebar liquid-panel");
  const navItems = [
    ["⌁", "聚簇", "clustering"],
    ["⌕", "检测", "locate"],
    ["✓", "复核", "review"],
    ["✦", "标注", "tagging"],
  ];
  navItems.forEach(([icon, label, section]) => {
    const button = glassButton("", "sidebar-item");
    button.dataset.canvasSection = section;
    button.append(element("b", "", icon), element("span", "", label));
    sidebar.appendChild(button);
  });

  const viewport = element("main", "canvas-viewport");
  viewport.id = "canvas-viewport";
  const world = element("div", "canvas-world");
  world.id = "canvas-world";
  const edges = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  edges.id = "canvas-edges";
  edges.classList.add("canvas-edges");
  edges.setAttribute("width", "2800");
  edges.setAttribute("height", "1800");
  edges.setAttribute("viewBox", "0 0 2800 1800");
  world.appendChild(edges);
  viewport.appendChild(world);

  const inspector = element("aside", "canvas-inspector liquid-panel");
  const inspectorHeader = element("div", "inspector-header");
  inspectorHeader.append(
    element("span", "eyebrow", "PIPELINE STATUS"),
    $("job-status"),
  );
  const progressWrap = pipelinePanel.querySelector(".progress-wrap");
  const progressMeta = pipelinePanel.querySelector(".progress-meta");
  const liveMetrics = element("div", "inspector-metrics");
  [
    ["发现", "metric-files"],
    ["去重", "metric-unique"],
    ["有效", "metric-valid"],
    ["簇", "metric-clusters"],
    ["检查", "metric-checked"],
    ["输出", "metric-output"],
  ].forEach(([label, id]) => {
    const source = $(id);
    const item = element("div");
    item.append(element("span", "", label), source);
    liveMetrics.appendChild(item);
  });
  inspector.append(inspectorHeader, progressWrap, progressMeta, liveMetrics);

  const logDrawer = element("aside", "log-drawer liquid-panel");
  logDrawer.id = "log-drawer";
  const drawerClose = glassButton("×", "drawer-close");
  drawerClose.id = "log-drawer-close";
  logPanel.querySelector(".section-title").appendChild(drawerClose);
  logDrawer.appendChild(logPanel);

  shell.append(topbar, sidebar, viewport, inspector, logDrawer);
  document.body.prepend(shell);

  const input = makeNode({
    id: "node-input", index: "00", title: "输入与运行",
    subtitle: "文件夹 · 本地模型", option: "input", locked: true,
    x: 70, y: 80, width: 360, className: "input-node",
  });
  input.body.appendChild($("job-form"));
  const standalonePixaiForm = $("standalone-pixai-form");
  standalonePixaiForm.classList.add("canvas-direct-settings");
  input.body.appendChild(standalonePixaiForm);
  input.body.appendChild(controlPanel.querySelector(".rule-strip"));

  const scan = makeNode({
    id: "node-scan", index: "01", title: "扫描 & 去重",
    subtitle: "SHA-256", option: "deduplicate", stage: "scan",
    x: 490, y: 80, width: 300,
  });
  const scanPreview = element("div", "scan-preview");
  scanPreview.append(
    previewTile("扫描前", "before"),
    element("span", "preview-arrow", "→"),
    previewTile("去重后", "after"),
  );
  const scanMetrics = element("div", "node-metrics two");
  scanMetrics.append(
    metric("发现文件", "node-files-found"),
    metric("重复移除", "node-duplicates"),
  );
  scan.body.append(scanPreview, scanMetrics);

  const resolution = makeNode({
    id: "node-resolution", index: "02", title: "分辨率过滤",
    subtitle: "任务级准入门槛", option: "resolution_filter", stage: "scan",
    x: 850, y: 80, width: 310,
  });
  resolution.body.append(resolutionPreview(), resolutionThresholdField);
  const resolutionMetrics = element("div", "node-metrics two");
  resolutionMetrics.append(
    metric("通过", "node-resolution-passed"),
    metric("过滤", "node-resolution-rejected"),
  );
  resolution.body.appendChild(resolutionMetrics);
  $("pipeline-min-resolution").classList.add("node-inline-detail");
  resolution.body.appendChild($("pipeline-min-resolution"));

  const embedding = makeNode({
    id: "node-embedding", index: "03", title: "Visual Embedding",
    subtitle: "448×448 · 1024d", option: "embedding", stage: "embedding",
    x: 1220, y: 80, width: 310,
  });
  embedding.body.append(embeddingPreview(), similarityModelField);
  const embeddingInfo = element("div", "node-info-row");
  embeddingInfo.append(
    $("pipeline-embedding-title"),
    $("pipeline-embedding-detail"),
  );
  embedding.body.append(embeddingInfo, metric("已处理", "node-embedding-processed"));

  const clustering = makeNode({
    id: "node-clustering", index: "04", title: "聚簇",
    subtitle: "Complete-linkage · medoid", option: "clustering", stage: "clustering",
    x: 1590, y: 60, width: 520, className: "wide-node clustering-node",
  });
  $("pipeline-cluster-threshold").classList.add("node-inline-detail");
  clustering.body.append(
    completeLinkageField,
    $("pipeline-cluster-threshold"),
    auditPanel,
  );

  const graph = makeNode({
    id: "node-graph", index: "05", title: "图筛选",
    subtitle: "Mutual Top-20 · 3-core", option: "graph_filter", stage: "graph",
    x: 480, y: 490, width: 350,
  });
  graph.body.append(graphPreview(), graphSimilarityField);
  const graphMetrics = element("div", "node-metrics two");
  graphMetrics.append(
    metric("保留簇", "node-graph-kept"),
    metric("输出候选", "metric-graph-output", "—"),
  );
  graph.body.appendChild(graphMetrics);

  const locate = makeNode({
    id: "node-locate", index: "06", title: "Locate 检测",
    subtitle: "水印 · 漫画 · 拼图", option: "locate", stage: "locate",
    x: 900, y: 470, width: 650, className: "wide-node locate-stage-node",
  });
  const retryInner = $("locate-retry-node");
  locate.body.appendChild(locatePanel);
  const locateMetrics = element("div", "node-metrics two compact-metrics");
  locateMetrics.append(
    metric("检查簇", "node-locate-checked"),
    metric("丢弃簇", "node-locate-dropped"),
  );
  locate.body.appendChild(locateMetrics);

  const retry = makeNode({
    id: "node-retry", index: "06.1", title: "候选重试",
    subtitle: "簇内备用候选 · 仅一次", option: "retry",
    x: 1610, y: 650, width: 330,
  });
  retry.body.appendChild(retryInner);

  reviewPanel.classList.add("flow-node", "liquid-panel", "review-stage-node");
  reviewPanel.dataset.nodeOption = "review";
  reviewPanel.style.left = "100px";
  reviewPanel.style.top = "920px";
  reviewPanel.style.width = "720px";
  reviewPanel.prepend(nodeHeader("07", "Review 复核", "默认通过 · 可移出", "review"));
  reviewPanel.hidden = false;
  nodeRegistry.set("review-panel", reviewPanel);

  curationPanel.classList.add("canvas-curation-root");
  curationPanel.hidden = false;
  world.appendChild(curationPanel);

  const pixai = makeNode({
    id: "node-pixai", index: "08", title: "PixAI 标注",
    subtitle: "general tags · 448×448", option: "pixai",
    x: 900, y: 1050, width: 430,
  });
  const curationHeading = curationPanel.querySelector(".curation-heading");
  const curationFlow = curationPanel.querySelector(".curation-flow");
  const curationProgress = curationPanel.querySelector(".curation-progress");
  const curationLive = $("curation-live");
  pixai.body.append(curationHeading, curationFlow, curationProgress, curationLive);

  const curationConfig = $("curation-config");
  curationConfig.hidden = false;
  const targetForm = $("curation-finalize-form");
  const distributionPanel = curationConfig.querySelector(".curation-distribution-panel");
  const targetHeading = targetForm.querySelector(".curation-subheading");
  const targetGrid = targetForm.querySelector(".curation-form-grid");
  const captionConfig = targetForm.querySelector(".curation-caption-config");

  const selection = makeNode({
    id: "node-selection", index: "09", title: "选择 & 分布",
    subtitle: "人数 · 取景 · 场景", option: "selection",
    x: 1390, y: 1030, width: 440,
  });
  selection.body.append(distributionPanel, targetHeading, targetGrid);

  const caption = makeNode({
    id: "node-caption", index: "10", title: "Caption 处理",
    subtitle: "规则链 · LoRA Prefix", option: "caption",
    x: 1890, y: 1030, width: 440,
  });
  caption.body.appendChild(captionConfig);
  targetForm.classList.add("canvas-split-form");
  targetForm.replaceChildren(selection.node, caption.node);
  curationConfig.replaceChildren(targetForm);

  const output = makeNode({
    id: "node-output", index: "11", title: "输出",
    subtitle: "训练图片 · Caption · 报告", option: "output",
    locked: true, stage: "output", x: 2240, y: 520, width: 470,
  });
  const completed = $("curation-completed");
  output.body.append(resultPanel, completed);

  [
    input.node,
    scan.node,
    resolution.node,
    embedding.node,
    clustering.node,
    graph.node,
    locate.node,
    retry.node,
    reviewPanel,
    pixai.node,
    curationConfig,
    output.node,
  ].forEach((node) => world.appendChild(node));

  if (lightbox) document.body.appendChild(lightbox);
  oldShell.remove();
  document.body.classList.add("canvas-ready");

  bindCanvasInteractions(viewport, world, edges);
  bindNodeToggles();
  bindToolbar(
    runButton,
    fitButton,
    zoomOut,
    zoomIn,
    moduleSwitch,
  );
  bindSidebar(logDrawer, logButton, focusExitButton);
  bindLiquidHighlights();
  applyDirectPixaiMode(moduleSwitch, runButton);
  drawEdges(edges);
  applyTransform();
  requestAnimationFrame(() => {
    fitCanvas(false);
    requestAnimationFrame(finishCanvasBoot);
  });
}

function finishCanvasBoot() {
  window.clearTimeout(window.__loraforgeCanvasBootFallback);
  document.documentElement.classList.remove("canvas-booting");
  $("canvas-boot-screen")?.remove();
}

function getPipelineOptions() {
  return {
    deduplicate: nodeOptions.deduplicate,
    resolution_filter: nodeOptions.resolution_filter,
    embedding: nodeOptions.embedding,
    clustering: nodeOptions.clustering,
    graph_filter: nodeOptions.graph_filter,
    locate: nodeOptions.locate,
    retry: nodeOptions.retry,
  };
}

function normalizeDependencies(changedOption) {
  if (changedOption === "embedding" && !nodeOptions.embedding) {
    nodeOptions.clustering = false;
    nodeOptions.graph_filter = false;
  }
  if (changedOption === "clustering" && nodeOptions.clustering) {
    nodeOptions.embedding = true;
  }
  if (changedOption === "graph_filter" && nodeOptions.graph_filter) {
    nodeOptions.embedding = true;
    nodeOptions.clustering = true;
  }
  if (changedOption === "locate" && !nodeOptions.locate) {
    nodeOptions.retry = false;
  }
  if (changedOption === "retry" && nodeOptions.retry) {
    nodeOptions.locate = true;
  }
}

function updateNodeOptionUi() {
  document.querySelectorAll("[data-node-option]").forEach((item) => {
    const option = item.dataset.nodeOption;
    if (!Object.hasOwn(nodeOptions, option)) return;
    const enabled = Boolean(nodeOptions[option]);
    if (item.classList.contains("node-switch")) {
      item.setAttribute("aria-checked", String(enabled));
      item.classList.toggle("active", enabled);
    } else {
      item.classList.toggle("node-disabled", !enabled);
    }
  });
  localStorage.setItem("loraforge-node-options", JSON.stringify(nodeOptions));
}

function bindNodeToggles() {
  updateNodeOptionUi();
  document.querySelectorAll(".node-switch:not(:disabled)").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const option = button.dataset.nodeOption;
      nodeOptions[option] = !nodeOptions[option];
      normalizeDependencies(option);
      updateNodeOptionUi();
      drawEdges($("canvas-edges"));
    });
  });

  document.addEventListener(
    "submit",
    (event) => {
      if (
        event.target.id === "curation-submit-form"
        && (!nodeOptions.review || !nodeOptions.pixai)
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showCanvasNotice("Review 或 PixAI 节点已关闭，无法进入标注阶段。");
      }
      if (
        event.target.id === "standalone-pixai-form"
        && !nodeOptions.pixai
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showCanvasNotice("PixAI 节点已关闭。");
      }
      if (
        event.target.id === "curation-finalize-form"
        && (!nodeOptions.selection || !nodeOptions.caption)
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showCanvasNotice("选择或 Caption 节点已关闭，无法生成训练集。");
      }
    },
    true,
  );
}

function bindCanvasInteractions(viewport, world, edges) {
  viewport.addEventListener(
    "wheel",
    (event) => {
      if (findScrollableAncestor(event.target, viewport)) return;
      event.preventDefault();
      const rect = viewport.getBoundingClientRect();
      const pointerX = event.clientX - rect.left;
      const pointerY = event.clientY - rect.top;
      const worldX = (pointerX - canvasX) / canvasScale;
      const worldY = (pointerY - canvasY) / canvasScale;
      const factor = event.deltaY < 0 ? 1.08 : 0.92;
      canvasScale = Math.min(1.35, Math.max(0.32, canvasScale * factor));
      canvasX = pointerX - worldX * canvasScale;
      canvasY = pointerY - worldY * canvasScale;
      applyTransform();
    },
    { passive: false },
  );

  viewport.addEventListener("pointerdown", (event) => {
    const isMiddlePan = event.button === 1;
    const isBlankLeftPan = (
      event.button === 0
      && !event.target.closest(".flow-node, button, input, select, textarea")
    );
    if (!isMiddlePan && !isBlankLeftPan) {
      return;
    }
    event.preventDefault();
    panning = true;
    panOrigin = { x: event.clientX - canvasX, y: event.clientY - canvasY };
    viewport.setPointerCapture(event.pointerId);
    viewport.classList.add("is-panning");
  });

  viewport.addEventListener("auxclick", (event) => {
    if (event.button === 1) event.preventDefault();
  });

  viewport.addEventListener("pointermove", (event) => {
    if (!panning || !panOrigin) return;
    canvasX = event.clientX - panOrigin.x;
    canvasY = event.clientY - panOrigin.y;
    applyTransform();
  });

  viewport.addEventListener("pointerup", (event) => {
    panning = false;
    panOrigin = null;
    viewport.classList.remove("is-panning");
    if (viewport.hasPointerCapture(event.pointerId)) {
      viewport.releasePointerCapture(event.pointerId);
    }
  });

  world.querySelectorAll(".flow-node-header").forEach((header) => {
    header.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || event.target.closest("button, input, select, textarea")) return;
      const node = header.closest(".flow-node");
      draggingNode = node;
      dragOrigin = {
        pointerX: event.clientX,
        pointerY: event.clientY,
        left: Number.parseFloat(node.style.left || "0"),
        top: Number.parseFloat(node.style.top || "0"),
      };
      header.setPointerCapture(event.pointerId);
      node.classList.add("is-dragging");
    });
    header.addEventListener("pointermove", (event) => {
      if (!draggingNode || !dragOrigin) return;
      const deltaX = (event.clientX - dragOrigin.pointerX) / canvasScale;
      const deltaY = (event.clientY - dragOrigin.pointerY) / canvasScale;
      draggingNode.style.left = `${dragOrigin.left + deltaX}px`;
      draggingNode.style.top = `${dragOrigin.top + deltaY}px`;
      drawEdges(edges);
    });
    header.addEventListener("pointerup", (event) => {
      if (draggingNode) draggingNode.classList.remove("is-dragging");
      draggingNode = null;
      dragOrigin = null;
      if (header.hasPointerCapture(event.pointerId)) {
        header.releasePointerCapture(event.pointerId);
      }
    });
  });
}

function findScrollableAncestor(target, boundary) {
  let current = target instanceof Element ? target : target?.parentElement;
  while (current && current !== boundary) {
    const style = window.getComputedStyle(current);
    const scrollsVertically = (
      /auto|scroll/.test(style.overflowY)
      && current.scrollHeight > current.clientHeight + 2
    );
    if (scrollsVertically) return current;
    current = current.parentElement;
  }
  return null;
}

function bindToolbar(
  runButton,
  fitButton,
  zoomOut,
  zoomIn,
  moduleSwitch,
) {
  const sourceRun = $("start-button");
  const directRun = $("standalone-pixai-button");
  runButton.addEventListener("click", () => {
    if (directPixaiMode) directRun.click();
    else sourceRun.click();
  });
  fitButton.addEventListener("click", () => {
    if (focusedSection) fitNodeGroup(sectionGroups[focusedSection], true);
    else fitCanvas(true);
  });
  zoomOut.addEventListener("click", () => {
    canvasScale = Math.max(0.32, canvasScale - 0.08);
    applyTransform();
  });
  zoomIn.addEventListener("click", () => {
    canvasScale = Math.min(1.35, canvasScale + 0.08);
    applyTransform();
  });
  moduleSwitch.addEventListener("click", () => {
    directPixaiMode = !directPixaiMode;
    applyDirectPixaiMode(moduleSwitch, runButton);
  });

  syncToolbarRunState = () => {
    runButton.disabled = directPixaiMode ? directRun.disabled : sourceRun.disabled;
    moduleSwitch.disabled = $("standalone-lora-prefix").disabled;
  };
  const observer = new MutationObserver(syncToolbarRunState);
  [sourceRun, directRun, $("standalone-lora-prefix")].forEach((item) => {
    observer.observe(item, {
      attributes: true,
      attributeFilter: ["disabled"],
    });
  });
  syncToolbarRunState();
}

function bindSidebar(logDrawer, logButton, focusExitButton) {
  document.querySelectorAll("[data-canvas-section]").forEach((button) => {
    button.addEventListener("click", () => {
      toggleSectionFocus(button.dataset.canvasSection);
    });
  });
  logButton.addEventListener("click", () => logDrawer.classList.toggle("open"));
  $("log-drawer-close").addEventListener("click", () => logDrawer.classList.remove("open"));
  focusExitButton.addEventListener("click", exitSectionFocus);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && focusedSection) exitSectionFocus();
  });
}

function applyDirectPixaiMode(moduleSwitch, runButton) {
  document.body.classList.toggle("canvas-direct-mode", directPixaiMode);
  moduleSwitch.classList.toggle("active", directPixaiMode);
  moduleSwitch.setAttribute("aria-checked", String(directPixaiMode));
  runButton.textContent = directPixaiMode ? "▶ 运行 PixAI" : "▶ 运行流水线";
  directBypassNodes.forEach((id) => {
    $(id)?.classList.toggle("direct-bypassed", directPixaiMode);
  });
  localStorage.setItem("loraforge-direct-pixai", String(directPixaiMode));
  syncToolbarRunState();
}

function toggleSectionFocus(section) {
  if (!Object.hasOwn(sectionGroups, section)) return;
  if (focusedSection === section) {
    exitSectionFocus();
    return;
  }
  if (!focusedSection) {
    savedCanvasView = {
      x: canvasX,
      y: canvasY,
      scale: canvasScale,
    };
  }
  focusedSection = section;
  const focusedIds = new Set(sectionGroups[section]);
  document.body.classList.add("canvas-section-focus");
  document.querySelectorAll(".flow-node").forEach((node) => {
    const focused = focusedIds.has(node.id);
    node.classList.toggle("section-focus-target", focused);
    node.classList.toggle("section-focus-hidden", !focused);
  });
  document.querySelectorAll("[data-canvas-section]").forEach((button) => {
    button.classList.toggle("active", button.dataset.canvasSection === section);
  });
  requestAnimationFrame(() => fitNodeGroup(sectionGroups[section], true));
}

function exitSectionFocus() {
  if (!focusedSection) return;
  focusedSection = null;
  document.body.classList.remove("canvas-section-focus");
  document.querySelectorAll(".flow-node").forEach((node) => {
    node.classList.remove("section-focus-target", "section-focus-hidden");
  });
  document.querySelectorAll("[data-canvas-section]").forEach((button) => {
    button.classList.remove("active");
  });
  if (savedCanvasView) {
    canvasX = savedCanvasView.x;
    canvasY = savedCanvasView.y;
    canvasScale = savedCanvasView.scale;
    $("canvas-world").classList.add("animate-transform");
    applyTransform();
    window.setTimeout(
      () => $("canvas-world").classList.remove("animate-transform"),
      320,
    );
  }
  savedCanvasView = null;
}

function fitNodeGroup(ids, animate = true) {
  const viewport = $("canvas-viewport");
  const nodes = ids.map((id) => $(id)).filter(Boolean);
  if (!viewport || !nodes.length) return;
  const minX = Math.min(...nodes.map((node) => node.offsetLeft));
  const minY = Math.min(...nodes.map((node) => node.offsetTop));
  const maxX = Math.max(...nodes.map((node) => node.offsetLeft + node.offsetWidth));
  const maxY = Math.max(...nodes.map((node) => node.offsetTop + node.offsetHeight));
  const rect = viewport.getBoundingClientRect();
  canvasScale = Math.min(
    1.18,
    Math.max(
      0.42,
      Math.min(
        (rect.width - 150) / Math.max(maxX - minX, 1),
        (rect.height - 110) / Math.max(maxY - minY, 1),
      ),
    ),
  );
  canvasX = (rect.width - (maxX - minX) * canvasScale) / 2 - minX * canvasScale;
  canvasY = (rect.height - (maxY - minY) * canvasScale) / 2 - minY * canvasScale;
  const world = $("canvas-world");
  world.classList.toggle("animate-transform", animate);
  applyTransform();
  window.setTimeout(() => world.classList.remove("animate-transform"), 320);
}

function bindLiquidHighlights() {
  document.addEventListener("pointermove", (event) => {
    const control = event.target.closest(".liquid-control, .liquid-panel");
    if (!control) return;
    const rect = control.getBoundingClientRect();
    control.style.setProperty("--glass-x", `${event.clientX - rect.left}px`);
    control.style.setProperty("--glass-y", `${event.clientY - rect.top}px`);
  });
}

function drawEdges(svg) {
  if (!svg) return;
  svg.replaceChildren();
  const marker = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  marker.innerHTML = `
    <linearGradient id="edge-gradient" x1="0" x2="1">
      <stop offset="0" stop-color="#CDD3E9"/>
      <stop offset="1" stop-color="#AEB7DA"/>
    </linearGradient>
    <marker id="edge-arrow" viewBox="0 0 10 10" refX="8" refY="5"
      markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#AEB7DA"/>
    </marker>`;
  svg.appendChild(marker);

  edgePairs.forEach(([sourceId, targetId], index) => {
    const source = $(sourceId);
    const target = $(targetId);
    if (!source || !target) return;
    const sourceEnabled = !source.classList.contains("node-disabled");
    const targetEnabled = !target.classList.contains("node-disabled");
    const x1 = source.offsetLeft + source.offsetWidth;
    const y1 = source.offsetTop + Math.min(source.offsetHeight * 0.35, 110);
    const x2 = target.offsetLeft;
    const y2 = target.offsetTop + Math.min(target.offsetHeight * 0.35, 110);
    const bend = Math.max(70, Math.abs(x2 - x1) * 0.42);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`);
    path.setAttribute("class", `canvas-edge ${sourceEnabled && targetEnabled ? "active" : "bypassed"}`);
    path.setAttribute("marker-end", "url(#edge-arrow)");
    path.style.setProperty("--edge-delay", `${index * -0.17}s`);
    svg.appendChild(path);
  });
}

function applyTransform() {
  const world = $("canvas-world");
  if (!world) return;
  world.style.transform = `translate3d(${canvasX}px, ${canvasY}px, 0) scale(${canvasScale})`;
  $("canvas-zoom-value").textContent = `${Math.round(canvasScale * 100)}%`;
}

function fitCanvas(animate = true) {
  const viewport = $("canvas-viewport");
  const nodes = [...document.querySelectorAll(".flow-node")];
  if (!viewport || !nodes.length) return;
  const minX = Math.min(...nodes.map((node) => node.offsetLeft));
  const minY = Math.min(...nodes.map((node) => node.offsetTop));
  const maxX = Math.max(...nodes.map((node) => node.offsetLeft + node.offsetWidth));
  const maxY = Math.max(...nodes.map((node) => node.offsetTop + node.offsetHeight));
  const rect = viewport.getBoundingClientRect();
  canvasScale = Math.min(
    0.78,
    Math.max(0.32, Math.min((rect.width - 120) / (maxX - minX), (rect.height - 100) / (maxY - minY))),
  );
  canvasX = (rect.width - (maxX - minX) * canvasScale) / 2 - minX * canvasScale;
  canvasY = (rect.height - (maxY - minY) * canvasScale) / 2 - minY * canvasScale;
  const world = $("canvas-world");
  world.classList.toggle("animate-transform", animate);
  applyTransform();
  window.setTimeout(() => world.classList.remove("animate-transform"), 320);
}

function centerNode(id) {
  const node = $(id);
  const viewport = $("canvas-viewport");
  if (!node || !viewport) return;
  const rect = viewport.getBoundingClientRect();
  canvasScale = Math.max(canvasScale, 0.72);
  canvasX = rect.width / 2 - (node.offsetLeft + node.offsetWidth / 2) * canvasScale;
  canvasY = rect.height / 2 - (node.offsetTop + node.offsetHeight / 2) * canvasScale;
  $("canvas-world").classList.add("animate-transform");
  applyTransform();
  window.setTimeout(() => $("canvas-world").classList.remove("animate-transform"), 320);
}

function showCanvasNotice(message) {
  let notice = $("canvas-notice");
  if (!notice) {
    notice = element("div", "canvas-notice liquid-panel");
    notice.id = "canvas-notice";
    document.body.appendChild(notice);
  }
  notice.textContent = message;
  notice.classList.add("show");
  window.clearTimeout(showCanvasNotice.timer);
  showCanvasNotice.timer = window.setTimeout(() => notice.classList.remove("show"), 2800);
}

window.LoRAForgeCanvas = {
  getPipelineOptions,
  fit: () => fitCanvas(true),
  centerNode,
};

try {
  buildCanvas();
} catch (error) {
  finishCanvasBoot();
  throw error;
}
