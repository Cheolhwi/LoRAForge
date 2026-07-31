const API = window.AUTO_CAT_API || "http://127.0.0.1:8000/api";
const UI_LANGUAGE = window.LoRAForgeI18n?.language || "zh";
const translate = window.LoRAForgeI18n?.translate || ((value) => value);
const REVIEW_REMOVE_CONFIRMATION_KEY = "loraforge-review-remove-confirmed-v1";
const REVIEW_PAGE_SIZE = 50;
let configuredClusterSimilarity = 0.90;
let configuredGraphSimilarity = 0.65;
let currentJob = null;
let eventSource = null;
let jobRunning = false;
let pickerOpen = false;
let visualPipelineStarted = false;
let reviewThumbnailsAvailable = false;
let lastEventId = 0;
let locateFlowState = { watermarkBoxes: [], comicBoxes: [] };
let reviewItems = [];
let reviewIndex = 0;
let reviewLastFocused = null;
let reviewUndo = null;
let reviewJobId = null;
let reviewLocked = false;
let reviewRemoveDialogResolve = null;
let reviewRemoveDialogTrigger = null;
let reviewRemovalConfirmationAcknowledged = false;
let reviewPage = 0;
let curationState = { status: "not_started", items: [] };
let auditState = {
  jobId: null,
  clusters: [],
  clusterSimilarity: configuredClusterSimilarity,
  graph: null,
  view: "clustering",
  filter: "all",
};

const $ = (id) => document.getElementById(id);
const stageNames = { scan: "去重/分辨率", embedding: "DINOv3", clustering: "聚簇", graph: "图筛选", locate: "Locate Anything", output: "输出", pixai: "PixAI 标注", caption: "选样与 Caption" };
const locateNodeStates = ["pending", "running", "completed", "passed", "not-meet", "failed", "skipped"];
const reasonLabels = {
  watermark_detected: "检测到水印或署名",
  comic_or_collage_detected: "检测到漫画分镜或拼图",
};

function setStatus(element, text, state = "pending") {
  element.textContent = text;
  element.className = `status-pill ${state}`;
}

function updateSimilarityModelUi() {
  const usePixAI = $("similarity-model").value === "pixai";
  stageNames.embedding = usePixAI ? "PixAI Embedding" : "DINOv3";
  $("rule-embedding-model").textContent = usePixAI
    ? "PixAI visual 1024d · EXP"
    : "DINOv3 1024d";
  $("pipeline-embedding-title").textContent = usePixAI
    ? "PixAI Visual Embedding"
    : "DINOv3 Embedding";
  $("pipeline-embedding-detail").textContent = usePixAI
    ? "Tagger v0.9 · native 1024d · EXP"
    : "ViT-L/16 · 1024d";
}

function resolutionThresholdLabel(minimumPixels) {
  if (minimumPixels === 1280 * 720) return "720p";
  if (minimumPixels === 1_000_000) return "1MP";
  return `${(minimumPixels / 1_000_000).toFixed(2).replace(/0+$/, "").replace(/\.$/, "")}MP`;
}

function updateResolutionThresholdUi() {
  const minimumPixels = Number($("minimum-pixels").value);
  const label = resolutionThresholdLabel(minimumPixels);
  $("rule-min-resolution").textContent = `≥ ${label}`;
  $("pipeline-min-resolution").textContent = `SHA-256 · ≥ ${label}`;
  const metricValidLabel = $("metric-valid-label");
  if (metricValidLabel) metricValidLabel.textContent = `有效图片（≥${label}）`;
}

function similarityThresholdValue(id, fallback) {
  const value = Number($(id).value);
  return Number.isFinite(value) && value >= 0 && value <= 1 ? value : fallback;
}

function updateFilteringThresholdUi() {
  configuredClusterSimilarity = similarityThresholdValue(
    "complete-linkage-similarity",
    configuredClusterSimilarity,
  );
  configuredGraphSimilarity = similarityThresholdValue(
    "graph-similarity",
    configuredGraphSimilarity,
  );
  const clusterLabel = configuredClusterSimilarity.toFixed(2);
  const graphLabel = configuredGraphSimilarity.toFixed(2);
  $("rule-cluster-threshold").textContent = `${clusterLabel} cluster`;
  $("rule-graph-threshold").textContent = `${graphLabel} Mutual Top-20`;
  $("pipeline-cluster-threshold").textContent = `similarity ${clusterLabel}`;
  const metricClustersLabel = $("metric-clusters-label");
  if (metricClustersLabel) metricClustersLabel.textContent = `${clusterLabel} 簇`;
  $("audit-clustering-tab").textContent = `${clusterLabel} 聚簇`;
  $("audit-graph-tab").textContent = `${graphLabel} 图筛选`;
  if (!auditState.clusters.length || $("audit-status").classList.contains("pending")) {
    auditState.clusterSimilarity = configuredClusterSimilarity;
    $("audit-metric-b-label").textContent = `${clusterLabel} 簇`;
    $("audit-description").textContent = `流水线运行到 ${clusterLabel} 聚簇后，将在这里显示超低清缩略图。`;
    $("audit-note").textContent = `${clusterLabel} 只负责把图片分组，不会在此处删除图片。`;
  }
}

function setDefaultMinimumPixels(value) {
  const minimumPixels = Number(value);
  if (!Number.isInteger(minimumPixels) || minimumPixels <= 0) return;
  const select = $("minimum-pixels");
  let option = Array.from(select.options).find((item) => Number(item.value) === minimumPixels);
  if (!option) {
    option = document.createElement("option");
    option.value = String(minimumPixels);
    option.textContent = `.env 默认 · ≥ ${resolutionThresholdLabel(minimumPixels)}`;
    select.appendChild(option);
  }
  select.value = String(minimumPixels);
  updateResolutionThresholdUi();
}

function updateControlAvailability() {
  $("start-button").disabled = jobRunning || pickerOpen || !$("source-dir").value;
  document.querySelectorAll(".folder-select-button").forEach((button) => {
    button.disabled = jobRunning || pickerOpen;
  });
  $("clear-output-dir").disabled = jobRunning || pickerOpen || !$("output-dir").value;
  $("similarity-model").disabled = jobRunning || pickerOpen;
  $("minimum-pixels").disabled = jobRunning || pickerOpen;
  $("complete-linkage-similarity").disabled = jobRunning || pickerOpen;
  $("graph-similarity").disabled = jobRunning || pickerOpen;
  const standalonePrefix = $("standalone-lora-prefix");
  const standaloneLocked = visualPipelineStarted;
  const standaloneReady = Boolean(
    $("source-dir").value
    && standalonePrefix.value.trim()
    && standalonePrefix.checkValidity(),
  );
  $("standalone-pixai-button").disabled = (
    jobRunning || pickerOpen || standaloneLocked || !standaloneReady
  );
  standalonePrefix.disabled = jobRunning || pickerOpen || standaloneLocked;
  $("standalone-pixai-form").classList.toggle("locked", standaloneLocked);
  $("standalone-pixai-state").textContent = standaloneLocked
    ? "当前页面已经启动过视觉筛选流水线；直接 PixAI 入口已锁定。"
    : "仅在当前页面尚未启动上方流水线时可用；不会执行 SHA、视觉 Embedding、图筛选或 Locate。";
}

async function chooseFolder(button) {
  const purpose = button.dataset.folderPurpose;
  const target = $(button.dataset.folderTarget);
  const originalLabel = button.textContent;
  pickerOpen = true;
  updateControlAvailability();
  button.textContent = "等待选择…";
  $("progress-message").textContent = "请在弹出的系统窗口中选择文件夹";
  try {
    const response = await fetch(
      `${API}/folders/select?purpose=${encodeURIComponent(purpose)}&locale=${encodeURIComponent(UI_LANGUAGE)}`,
    );
    if (!response.ok) {
      let detail = await response.text();
      try { detail = (JSON.parse(detail).detail || detail); } catch {}
      throw new Error(detail);
    }
    const payload = await response.json();
    if (!payload.cancelled && payload.path) {
      target.value = payload.path;
      target.title = payload.path;
      $("progress-message").textContent = purpose === "source" ? "图片文件夹已选择" : "输出文件夹已选择";
    } else {
      $("progress-message").textContent = "已取消文件夹选择";
    }
  } catch (error) {
    $("progress-message").textContent = `文件夹选择失败：${error.message}`;
  } finally {
    pickerOpen = false;
    button.textContent = originalLabel;
    updateControlAvailability();
  }
}

function updateMetrics(data) {
  const map = {
    "metric-files": data.files_found,
    "metric-unique": data.unique_images,
    "metric-valid": data.embedding_candidates,
    "metric-clusters": data.clusters,
    "metric-checked": data.checked_clusters,
    "metric-output": data.output_images,
    "node-files-found": data.files_found,
    "node-duplicates": data.duplicates,
    "node-resolution-passed": data.embedding_candidates,
    "node-resolution-rejected": data.resolution_rejected,
    "node-embedding-processed": data.embedding_candidates,
    "node-graph-kept": data.kept_clusters,
    "node-locate-checked": data.checked_clusters,
    "node-locate-dropped": data.dropped_clusters,
  };
  Object.entries(map).forEach(([id, value]) => {
    const element = $(id);
    const isDisplayValue = (
      typeof value === "number"
      ? Number.isFinite(value)
      : typeof value === "string"
    );
    if (element && isDisplayValue) element.textContent = String(value);
  });
}

function updateNodes(stage, status) {
  const order = ["scan", "embedding", "clustering", "graph", "locate", "output"];
  const current = order.indexOf(stage);
  document.querySelectorAll(".pipeline-node").forEach((node) => {
    const index = order.indexOf(node.dataset.stage);
    node.classList.remove("running", "completed", "failed");
    if (index < current || (index === current && status === "completed")) node.classList.add("completed");
    if (index === current && status === "running") node.classList.add("running");
    if (index === current && status === "failed") node.classList.add("failed");
  });
}

function resetAudit() {
  auditState = {
    jobId: null,
    clusters: [],
    clusterSimilarity: configuredClusterSimilarity,
    graph: null,
    view: "clustering",
    filter: "all",
  };
  setStatus($("audit-status"), "等待聚簇", "pending");
  const clusteringLabel = configuredClusterSimilarity.toFixed(2);
  const graphLabel = configuredGraphSimilarity.toFixed(2);
  $("audit-clustering-tab").textContent = `${clusteringLabel} 聚簇`;
  $("audit-graph-tab").textContent = `${graphLabel} 图筛选`;
  $("audit-description").textContent = `流水线运行到 ${clusteringLabel} 聚簇后，将在这里显示超低清缩略图。`;
  $("audit-note").textContent = `${clusteringLabel} 只负责把图片分组，不会在此处删除图片。`;
  ["a", "b", "c", "d"].forEach((key) => { $(`audit-metric-${key}`).textContent = "—"; });
  $("audit-clusters").innerHTML = '<div class="audit-empty">等待 Complete-linkage 聚簇结果…</div>';
  document.querySelectorAll(".audit-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.auditView === "clustering");
    button.disabled = button.dataset.auditView === "graph";
  });
  document.querySelectorAll(".audit-filters button").forEach((button) => {
    button.classList.toggle("active", button.dataset.auditFilter === "all");
    button.disabled = true;
  });
}

function renderAudit() {
  const isGraph = auditState.view === "graph";
  document.querySelectorAll(".audit-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.auditView === auditState.view);
    button.disabled = button.dataset.auditView === "graph" && !auditState.graph;
  });
  document.querySelectorAll(".audit-filters button").forEach((button) => {
    button.disabled = !isGraph || !auditState.graph;
    button.classList.toggle("active", button.dataset.auditFilter === auditState.filter);
  });

  if (!auditState.clusters.length) {
    $("audit-clusters").innerHTML = '<div class="audit-empty">等待 Complete-linkage 聚簇结果…</div>';
    return;
  }

  const totalImages = auditState.clusters.reduce((sum, cluster) => sum + cluster.size, 0);
  let visibleClusters = auditState.clusters;
  const keptIds = new Set(auditState.graph?.kept_cluster_ids || []);
  if (isGraph && auditState.graph) {
    if (auditState.filter === "kept") visibleClusters = visibleClusters.filter((cluster) => keptIds.has(cluster.cluster_id));
    if (auditState.filter === "excluded") visibleClusters = visibleClusters.filter((cluster) => !keptIds.has(cluster.cluster_id));
    const graphSimilarity = Number(auditState.graph.similarity);
    const graphSimilarityLabel = Number.isFinite(graphSimilarity)
      ? graphSimilarity.toFixed(2)
      : configuredGraphSimilarity.toFixed(2);
    $("audit-graph-tab").textContent = `${graphSimilarityLabel} 图筛选`;
    $("audit-description").textContent = `${graphSimilarityLabel} Mutual Top-${auditState.graph.top_k}、${auditState.graph.core_degree}-core 与最大连通分量的最终去留`;
    $("audit-metric-a-label").textContent = "图节点 / 边";
    $("audit-metric-a").textContent = `${auditState.graph.graph_nodes} / ${auditState.graph.graph_edges}`;
    $("audit-metric-b-label").textContent = "3-core 节点";
    $("audit-metric-b").textContent = auditState.graph.core_nodes;
    $("audit-metric-c-label").textContent = "保留图片";
    $("audit-metric-c").textContent = auditState.graph.kept_images;
    $("audit-metric-d-label").textContent = "排除图片";
    $("audit-metric-d").textContent = auditState.graph.excluded_images;
    $("audit-note").textContent = `相似度 ≥ ${auditState.graph.similarity} 后形成 ${auditState.graph.graph_edges} 条 Mutual Top-${auditState.graph.top_k} 边；${auditState.graph.core_nodes}/${auditState.graph.graph_nodes} 个簇节点进入 ${auditState.graph.core_degree}-core，最大连通分量最终保留 ${auditState.graph.kept_clusters} 个簇、排除 ${auditState.graph.excluded_clusters} 个簇。`;
  } else {
    const clusteringLabel = Number(auditState.clusterSimilarity).toFixed(2);
    $("audit-description").textContent = `Complete-linkage similarity ${clusteringLabel} 的分组结果`;
    $("audit-metric-a-label").textContent = "有效图片";
    $("audit-metric-a").textContent = totalImages;
    $("audit-metric-b-label").textContent = `${clusteringLabel} 簇`;
    $("audit-metric-b").textContent = auditState.clusters.length;
    $("audit-metric-c-label").textContent = "仍保留图片";
    $("audit-metric-c").textContent = totalImages;
    $("audit-metric-d-label").textContent = "此步排除";
    $("audit-metric-d").textContent = 0;
    $("audit-note").textContent = `图片右上角的半透明数字是该图与 medoid 的余弦相似度；簇标题中的 MIN 是簇内最低两两相似度，直接对应 Complete-linkage ${clusteringLabel}。蓝色 M 表示 medoid。`;
  }

  const container = $("audit-clusters");
  container.replaceChildren();
  if (!visibleClusters.length) {
    const empty = document.createElement("div");
    empty.className = "audit-empty";
    empty.textContent = "当前筛选条件下没有簇";
    container.appendChild(empty);
    return;
  }

  visibleClusters.forEach((cluster) => {
    const kept = keptIds.has(cluster.cluster_id);
    const card = document.createElement("article");
    card.className = `audit-cluster ${isGraph && auditState.graph ? (kept ? "kept" : "excluded") : ""}`;
    const header = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = `CLUSTER #${cluster.cluster_id}`;
    const state = document.createElement("span");
    state.className = "audit-cluster-state";
    const minimumSimilarity = Number(cluster.minimum_similarity);
    const minimumSimilarityLabel = Number.isFinite(minimumSimilarity) ? minimumSimilarity.toFixed(3) : "—";
    state.textContent = isGraph && auditState.graph
      ? (kept ? `保留 · ${cluster.size} 图` : `排除 · ${cluster.size} 图`)
      : `${cluster.size} 图 · MIN ${minimumSimilarityLabel}`;
    header.append(title, state);
    const members = document.createElement("div");
    members.className = "audit-members";
    cluster.members.forEach((member) => {
      const tile = document.createElement("div");
      tile.className = `audit-member ${member.role === "medoid" ? "medoid" : ""}`;
      const similarity = Number(member.similarity_to_medoid);
      const similarityLabel = Number.isFinite(similarity) ? similarity.toFixed(3) : "—";
      tile.title = `${member.filename}${member.role === "medoid" ? " · medoid" : ""} · 与 medoid 相似度 ${similarityLabel}`;
      const image = document.createElement("img");
      image.loading = "lazy";
      image.decoding = "async";
      image.src = `${API}/jobs/${encodeURIComponent(auditState.jobId)}/audit/thumbnail/${encodeURIComponent(member.image_id)}`;
      image.alt = member.filename;
      tile.appendChild(image);
      const similarityBadge = document.createElement("span");
      similarityBadge.className = "audit-similarity";
      similarityBadge.textContent = similarityLabel;
      tile.appendChild(similarityBadge);
      if (member.role === "medoid") {
        const badge = document.createElement("span");
        badge.className = "audit-medoid-badge";
        badge.textContent = "M";
        tile.appendChild(badge);
      }
      members.appendChild(tile);
    });
    card.append(header, members);
    container.appendChild(card);
  });
}

function updateAudit(payload, jobId) {
  if (!payload?.event) return;
  auditState.jobId = jobId;
  if (payload.event === "clusters_ready") {
    auditState.clusters = payload.clusters || [];
    auditState.clusterSimilarity = payload.similarity;
    auditState.view = "clustering";
    auditState.filter = "all";
    $("audit-clustering-tab").textContent = `${Number(auditState.clusterSimilarity).toFixed(2)} 聚簇`;
    setStatus($("audit-status"), `${Number(auditState.clusterSimilarity).toFixed(2)} 已完成 · ${auditState.clusters.length} 簇`, "completed");
    renderAudit();
  }
  if (payload.event === "graph_filtered") {
    auditState.graph = payload;
    auditState.view = "graph";
    auditState.filter = "excluded";
    $("audit-graph-tab").textContent = `${Number(payload.similarity).toFixed(2)} 图筛选`;
    setStatus($("audit-status"), `图筛选完成 · 排除 ${payload.excluded_clusters} 簇`, "completed");
    renderAudit();
  }
}

function setLocateNodeState(id, state) {
  const node = $(id);
  node.classList.remove(...locateNodeStates);
  node.classList.add(state);
}

function resetLocateFlow() {
  locateFlowState = { watermarkBoxes: [], comicBoxes: [] };
  ["locate-candidate-node", "locate-watermark-node", "locate-comic-node", "locate-decision-node", "locate-retry-node"].forEach((id) => setLocateNodeState(id, "pending"));
  ["locate-wire-input", "locate-wire-decision", "locate-wire-retry"].forEach((id) => {
    $(id).classList.remove("active", "completed");
  });
  $("locate-cluster-progress").textContent = "尚未开始";
  setStatus($("locate-live-status"), "等待 Locate 阶段", "pending");
  $("locate-image-stage").classList.add("empty");
  $("locate-preview-image").removeAttribute("src");
  $("locate-box-layer").replaceChildren();
  $("locate-filename").textContent = "—";
  $("locate-attempt").textContent = "MEDOID / ATTEMPT 1";
  $("locate-watermark-state").textContent = "等待输入";
  $("locate-watermark-count").textContent = "—";
  $("locate-comic-state").textContent = "等待输入";
  $("locate-comic-count").textContent = "—";
  $("locate-decision-icon").textContent = "?";
  $("locate-decision-state").textContent = "等待两次检测";
  $("locate-decision-reason").textContent = "watermark = 0 · comic ≤ 1";
  $("locate-retry-state").textContent = "首次不通过时触发";
  $("locate-retry-file").textContent = "仅重试一次";
  $("locate-recent-runs").innerHTML = '<span class="trace-empty">检测结果会依次出现在这里</span>';
}

function renderDetectionBoxes() {
  const layer = $("locate-box-layer");
  layer.replaceChildren();
  const groups = [
    ["watermark", "WATERMARK", locateFlowState.watermarkBoxes],
    ["comic", "COMIC", locateFlowState.comicBoxes],
  ];
  groups.forEach(([type, label, boxes]) => {
    boxes.forEach((box, index) => {
      if (!Array.isArray(box) || box.length < 4) return;
      const [rawX1, rawY1, rawX2, rawY2] = box.map((value) => Math.max(0, Math.min(1, Number(value))));
      const x1 = Math.min(rawX1, rawX2);
      const y1 = Math.min(rawY1, rawY2);
      const x2 = Math.max(rawX1, rawX2);
      const y2 = Math.max(rawY1, rawY2);
      const element = document.createElement("span");
      element.className = `detection-box ${type}`;
      element.style.left = `${x1 * 100}%`;
      element.style.top = `${y1 * 100}%`;
      element.style.width = `${(x2 - x1) * 100}%`;
      element.style.height = `${(y2 - y1) * 100}%`;
      const tag = document.createElement("b");
      tag.textContent = `${label} ${index + 1}`;
      element.appendChild(tag);
      layer.appendChild(element);
    });
  });
}

function addLocateTrace(flow) {
  const trace = $("locate-recent-runs");
  trace.querySelector(".trace-empty")?.remove();
  const eventKey = `${flow.cluster_id}:${flow.attempt}:${flow.filename}`;
  if (trace.querySelector(`[data-event-key="${CSS.escape(eventKey)}"]`)) return;
  const item = document.createElement("span");
  item.className = `trace-item ${flow.status}`;
  item.dataset.eventKey = eventKey;
  const label = document.createElement("span");
  const attempt = flow.attempt === 2 ? "retry" : "medoid";
  label.textContent = `${flow.cluster_index}/${flow.cluster_total} · cluster #${flow.cluster_id} · ${attempt} · ${flow.filename}`;
  item.title = label.textContent;
  item.appendChild(label);
  trace.appendChild(item);
  while (trace.children.length > 12) trace.firstElementChild.remove();
  trace.scrollLeft = trace.scrollWidth;
}

function renderLocateFlow(flow) {
  if (!flow || !flow.event) return;
  if (flow.cluster_total !== undefined) {
    const index = flow.cluster_index || 0;
    const clusterId = flow.cluster_id === undefined ? "" : ` · CLUSTER #${flow.cluster_id}`;
    $("locate-cluster-progress").textContent = `${index}/${flow.cluster_total}${clusterId}`;
  }

  if (flow.event === "pipeline_started") {
    setStatus($("locate-live-status"), `准备 ${flow.cluster_total} 个簇`, "running");
    return;
  }

  if (flow.event === "candidate_loaded") {
    locateFlowState = { watermarkBoxes: [], comicBoxes: [] };
    renderDetectionBoxes();
    setStatus($("locate-live-status"), "LIVE · 正在检测", "running");
    setLocateNodeState("locate-candidate-node", "running");
    setLocateNodeState("locate-watermark-node", "pending");
    setLocateNodeState("locate-comic-node", "pending");
    setLocateNodeState("locate-decision-node", "pending");
    $("locate-wire-input").className = "locate-connector active";
    $("locate-wire-decision").className = "locate-connector";
    $("locate-filename").textContent = flow.filename || "—";
    $("locate-filename").title = flow.source || flow.filename || "";
    $("locate-attempt").textContent = `${flow.candidate_role === "backup_retry" ? "BACKUP" : "MEDOID"} / ATTEMPT ${flow.attempt}`;
    $("locate-watermark-state").textContent = "等待输入";
    $("locate-watermark-count").textContent = "—";
    $("locate-comic-state").textContent = "等待输入";
    $("locate-comic-count").textContent = "—";
    $("locate-decision-icon").textContent = "?";
    $("locate-decision-state").textContent = "等待两次检测";
    $("locate-decision-reason").textContent = "watermark = 0 · comic ≤ 1";
    if (flow.preview) {
      $("locate-preview-image").src = flow.preview;
      $("locate-image-stage").classList.remove("empty");
    }
    if (flow.attempt === 1) {
      setLocateNodeState("locate-retry-node", "pending");
      $("locate-wire-retry").className = "locate-connector";
      $("locate-retry-state").textContent = "首次不通过时触发";
      $("locate-retry-file").textContent = "仅重试一次";
    } else {
      setLocateNodeState("locate-retry-node", "running");
      $("locate-wire-retry").className = "locate-connector completed";
      $("locate-retry-state").textContent = "正在检查备用候选";
      $("locate-retry-file").textContent = flow.filename || "—";
    }
    return;
  }

  if (flow.event === "check_running") {
    const id = flow.check === "watermark" ? "locate-watermark-node" : "locate-comic-node";
    setLocateNodeState(id, "running");
    $(`locate-${flow.check}-state`).textContent = "模型推理中…";
    $(`locate-${flow.check}-count`).textContent = "…";
    $("locate-wire-input").className = "locate-connector completed";
    return;
  }

  if (flow.event === "check_skipped") {
    const id = flow.check === "watermark" ? "locate-watermark-node" : "locate-comic-node";
    setLocateNodeState(id, "skipped");
    $(`locate-${flow.check}-state`).textContent = "已跳过";
    $(`locate-${flow.check}-count`).textContent = "SKIP";
    $("locate-wire-decision").className = "locate-connector active";
    return;
  }

  if (flow.event === "check_completed") {
    const failedRule = flow.check === "watermark" ? flow.box_count > 0 : flow.box_count > 1;
    const id = flow.check === "watermark" ? "locate-watermark-node" : "locate-comic-node";
    setLocateNodeState(id, failedRule ? "not-meet" : "completed");
    $(`locate-${flow.check}-state`).textContent = failedRule ? "触发 not meet" : "未触发规则";
    $(`locate-${flow.check}-count`).textContent = `${flow.box_count} BOX`;
    locateFlowState[`${flow.check}Boxes`] = flow.boxes || [];
    renderDetectionBoxes();
    $("locate-wire-decision").className = "locate-connector active";
    return;
  }

  if (flow.event === "candidate_result") {
    const passed = flow.status === "passed";
    setLocateNodeState("locate-candidate-node", "completed");
    setLocateNodeState("locate-decision-node", passed ? "passed" : "not-meet");
    $("locate-wire-decision").className = "locate-connector completed";
    $("locate-decision-icon").textContent = passed ? "✓" : "×";
    $("locate-decision-state").textContent = passed ? "MEET · 候选通过" : "NOT MEET";
    $("locate-decision-reason").textContent = passed ? "两项检查均满足规则" : (reasonLabels[flow.reason] || flow.reason || "未通过检测");
    if (flow.attempt === 1 && passed) {
      setLocateNodeState("locate-retry-node", "skipped");
      $("locate-retry-state").textContent = "无需重试";
      $("locate-retry-file").textContent = "medoid 已通过";
    } else if (flow.attempt === 1) {
      $("locate-wire-retry").className = "locate-connector active";
      $("locate-retry-state").textContent = "等待备用候选";
    }
    addLocateTrace(flow);
    return;
  }

  if (flow.event === "retry_scheduled") {
    setLocateNodeState("locate-retry-node", "running");
    $("locate-wire-retry").className = "locate-connector active";
    $("locate-retry-state").textContent = "已选择备用候选";
    $("locate-retry-file").textContent = flow.filename || "—";
    return;
  }

  if (flow.event === "cluster_result") {
    const passed = flow.status === "passed";
    if (flow.attempt === 2) {
      setLocateNodeState("locate-retry-node", passed ? "passed" : "failed");
      $("locate-retry-state").textContent = passed ? "备用候选通过" : "备用候选不通过";
    } else if (!passed) {
      setLocateNodeState("locate-retry-node", "failed");
      $("locate-retry-state").textContent = "簇已放弃";
      $("locate-retry-file").textContent = flow.retry_available === false ? "没有可用备用候选" : "重试未通过";
    }
    $("locate-wire-retry").className = `locate-connector ${flow.attempt === 2 ? "completed" : ""}`;
    return;
  }

  if (flow.event === "pipeline_completed") {
    setStatus($("locate-live-status"), `已完成 · ${flow.checked_clusters} 个簇`, "completed");
  }
}

function renderLocateFailure(message) {
  setStatus($("locate-live-status"), "检测中断", "failed");
  const active = document.querySelector(".locate-node.running");
  if (active) setLocateNodeState(active.id, "failed");
  $("locate-decision-state").textContent = "检测服务异常";
  $("locate-decision-reason").textContent = message || "请检查后端日志";
}

function addLog(event) {
  const log = $("event-log");
  log.querySelector(".empty-state")?.remove();
  const row = document.createElement("div");
  row.className = "event-row";
  const time = new Date(event.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const stage = document.createElement("span");
  stage.className = "event-stage";
  stage.textContent = stageNames[event.stage] || event.stage;
  const detail = document.createElement("span");
  detail.className = "event-message";
  detail.textContent = event.message;
  const timestamp = document.createElement("span");
  timestamp.className = "event-time";
  timestamp.textContent = time;
  row.append(stage, detail, timestamp);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

function renderResults(items) {
  const body = $("result-body");
  $("result-count").textContent = items.length;
  if (!items.length) { body.innerHTML = '<tr><td colspan="5" class="empty-state">暂无结果</td></tr>'; return; }
  body.innerHTML = items.map((item) => {
    const passed = item.status === "passed";
    const removed = item.status === "removed_by_review";
    const retry = item.candidate_role === "backup_retry";
    const statusClass = removed ? "result-removed" : (passed ? (retry ? "result-retry" : "result-pass") : "result-fail");
    const label = removed ? "已移出" : (passed ? (retry ? "重试通过" : "通过") : "放弃");
    const name = item.source.split(/[\\/]/).pop();
    return `<tr><td class="${statusClass}">${label}</td><td title="${item.source}">${name}</td><td>#${item.cluster_id}</td><td>${item.candidate_role}</td><td>${item.reason || "—"}</td></tr>`;
  }).join("");
}

function resetReview() {
  reviewItems = [];
  reviewIndex = 0;
  reviewUndo = null;
  reviewJobId = null;
  reviewLocked = false;
  reviewPage = 0;
  $("review-panel").hidden = true;
  $("review-notice").hidden = true;
  $("review-pagination").hidden = true;
  $("review-gallery").replaceChildren();
  $("lora-prefix").value = "";
  $("lora-prefix").disabled = false;
  $("curation-submit").disabled = true;
  closeReviewImage(false);
  resetCuration();
}

function reviewPageCount() {
  return Math.max(1, Math.ceil(reviewItems.length / REVIEW_PAGE_SIZE));
}

function updateReviewPagination() {
  const totalPages = reviewPageCount();
  const start = reviewItems.length ? reviewPage * REVIEW_PAGE_SIZE + 1 : 0;
  const end = Math.min((reviewPage + 1) * REVIEW_PAGE_SIZE, reviewItems.length);
  $("review-pagination").hidden = reviewItems.length <= REVIEW_PAGE_SIZE;
  $("review-page-range").textContent = `${start}–${end} / ${reviewItems.length}`;
  $("review-page-input").value = String(reviewPage + 1);
  $("review-page-input").max = String(totalPages);
  $("review-page-total").textContent = String(totalPages);
  $("review-page-previous").disabled = reviewPage === 0;
  $("review-page-next").disabled = reviewPage >= totalPages - 1;
}

function createReviewCard(item, index, pageOffset) {
  const sourceName = item.source.split(/[\\/]/).pop();
  const card = document.createElement("article");
  card.className = "review-card";

  const thumb = document.createElement("div");
  thumb.className = "review-thumb";
  const image = document.createElement("img");
  image.loading = pageOffset < 15 ? "eager" : "lazy";
  image.decoding = "async";
  image.fetchPriority = pageOffset < 10 ? "high" : "low";
  image.width = 320;
  image.height = 240;
  const reviewUrl = `${API}/jobs/${encodeURIComponent(item.jobId)}/review/${item.manifestIndex}`;
  image.src = reviewThumbnailsAvailable ? `${reviewUrl}/thumbnail` : reviewUrl;
  if (reviewThumbnailsAvailable) {
    image.addEventListener("error", () => {
      if (image.dataset.originalFallback) return;
      image.dataset.originalFallback = "1";
      image.src = reviewUrl;
    });
  }
  image.alt = sourceName;
  const position = document.createElement("span");
  const digits = Math.max(3, String(reviewItems.length).length);
  position.className = "review-card-index";
  position.textContent = `${String(index + 1).padStart(digits, "0")} / ${String(reviewItems.length).padStart(digits, "0")}`;
  const role = document.createElement("span");
  role.className = `review-card-role ${item.candidate_role === "backup_retry" ? "retry" : ""}`;
  role.textContent = item.candidate_role === "backup_retry" ? "RETRY PASS" : "MEDOID";
  thumb.append(image, position, role);

  const caption = document.createElement("div");
  caption.className = "review-card-caption";
  const name = document.createElement("strong");
  name.textContent = sourceName;
  name.title = item.source;
  const meta = document.createElement("span");
  meta.textContent = `CLUSTER #${item.cluster_id} · ATTEMPT ${item.locate_attempt}`;
  caption.append(name, meta);

  const openButton = document.createElement("button");
  openButton.type = "button";
  openButton.className = "review-card-open";
  openButton.setAttribute("aria-label", `查看图片 ${index + 1}：${sourceName}`);
  openButton.append(thumb, caption);
  openButton.addEventListener("click", () => openReviewImage(index, openButton));

  const passed = document.createElement("button");
  passed.type = "button";
  passed.className = "review-card-pass";
  passed.textContent = "✓";
  passed.title = "点击移出候选集";
  passed.setAttribute("aria-label", `将 ${sourceName} 移出候选集`);
  passed.disabled = reviewLocked;
  passed.addEventListener("click", () => removeReviewImageAt(index, passed));

  card.append(openButton, passed);
  return card;
}

function renderReviewPage(resetScroll = false) {
  const gallery = $("review-gallery");
  const previousScrollTop = resetScroll ? 0 : gallery.scrollTop;
  gallery.replaceChildren();
  updateReviewPagination();

  if (!reviewItems.length) {
    const empty = document.createElement("div");
    empty.className = "review-empty";
    empty.textContent = "最终数据集为空";
    gallery.appendChild(empty);
    return;
  }

  const start = reviewPage * REVIEW_PAGE_SIZE;
  const end = Math.min(start + REVIEW_PAGE_SIZE, reviewItems.length);
  const fragment = document.createDocumentFragment();
  for (let index = start; index < end; index += 1) {
    fragment.appendChild(createReviewCard(reviewItems[index], index, index - start));
  }
  gallery.appendChild(fragment);
  gallery.scrollTop = previousScrollTop;
}

function goToReviewPage(page) {
  const requestedPage = Math.trunc(Number(page) || 0);
  const nextPage = Math.max(0, Math.min(requestedPage, reviewPageCount() - 1));
  if (nextPage === reviewPage) {
    updateReviewPagination();
    return;
  }
  reviewPage = nextPage;
  renderReviewPage(true);
}

function renderReview(jobId, items) {
  const jobChanged = reviewJobId !== jobId;
  reviewJobId = jobId;
  reviewItems = items
    .map((item, manifestIndex) => ({ ...item, manifestIndex, jobId }))
    .filter((item) => item.status === "passed" && item.output);
  reviewPage = jobChanged ? 0 : Math.min(reviewPage, reviewPageCount() - 1);
  $("review-panel").hidden = false;
  $("review-count").textContent = reviewItems.length;
  $("curation-submit").disabled = reviewLocked || !reviewItems.length;
  $("review-summary").textContent = reviewItems.length
    ? `已加载 ${reviewItems.length} 张图片，每页显示 ${REVIEW_PAGE_SIZE} 张；点击缩略图检查，点击对勾移出`
    : "本次任务没有通过并进入最终数据集的图片";
  renderReviewPage(jobChanged);
}

function resetCuration() {
  curationState = { status: "not_started", items: [] };
  $("curation-description").textContent = "PixAI 只推理一次；选样只读取人数、取景和室外状态。";
  $("curation-panel").hidden = true;
  $("curation-live").hidden = true;
  $("curation-config").hidden = true;
  $("curation-completed").hidden = true;
  $("curation-progress-bar").style.width = "0%";
  $("curation-progress-value").textContent = "0%";
  $("curation-progress-message").textContent = "等待进入 PixAI 阶段";
  $("curation-finalize").disabled = true;
  setStatus($("curation-status"), "等待 Submit", "pending");
  document.querySelectorAll(".curation-step").forEach((step) => {
    step.classList.remove("running", "completed", "failed");
  });
}

function setReviewLocked(locked) {
  reviewLocked = locked;
  $("lora-prefix").disabled = locked;
  $("curation-submit").disabled = locked || !reviewItems.length;
  $("review-undo").disabled = locked;
  document.querySelectorAll(".review-card-pass").forEach((button) => {
    button.disabled = locked;
  });
  if (!$("review-lightbox").hidden) updateReviewImage();
}

function setCurationSteps(stage, status = "running") {
  const order = ["pixai", "selection", "caption"];
  const current = order.indexOf(stage);
  document.querySelectorAll(".curation-step").forEach((step) => {
    const index = order.indexOf(step.dataset.curationStage);
    step.classList.remove("running", "completed", "failed");
    if (index < current) step.classList.add("completed");
    if (index === current) step.classList.add(status);
  });
}

function featureDisplay(features) {
  if (!features) return [];
  const people = features.people_count?.value;
  const framingLabels = {
    full_body: "全身",
    half_body: "半身",
    headshot: "头像",
    unknown: "取景未知",
  };
  const outdoors = features.outdoors?.value;
  return [
    `人数 ${people === "3_plus" ? "3+" : people}`,
    `取景 ${framingLabels[features.framing?.value] || "未知"}`,
    `场景 ${outdoors === true ? "室外" : (outdoors === false ? "非室外" : "未知")}`,
  ];
}

function renderCurationFlow(flow, jobId) {
  if (!flow?.event) return;
  $("curation-panel").hidden = false;
  if (flow.event === "started") {
    setStatus($("curation-status"), "PixAI 模型运行中", "running");
    setCurationSteps("pixai", "running");
  }
  if (flow.event === "image_tagged") {
    $("curation-live").hidden = false;
    $("curation-live-image").src = `${API}/jobs/${encodeURIComponent(jobId)}/curation/image/${flow.manifest_index}`;
    $("curation-live-name").textContent = flow.filename;
    const features = $("curation-live-features");
    features.replaceChildren();
    featureDisplay(flow.selection_features).forEach((label) => {
      const pill = document.createElement("span");
      pill.textContent = label;
      features.appendChild(pill);
    });
    const tags = $("curation-live-tags");
    tags.replaceChildren();
    (flow.top_tags || []).forEach((entry) => {
      const tag = document.createElement("span");
      tag.textContent = `${entry.tag} `;
      const score = document.createElement("b");
      score.textContent = Number(entry.score).toFixed(2);
      tag.appendChild(score);
      tags.appendChild(tag);
    });
  }
  if (flow.event === "tagging_completed") {
    setCurationSteps("selection", "running");
    setStatus($("curation-status"), "等待设置目标分布", "pending");
  }
  if (flow.event === "finalize_started") {
    setCurationSteps("caption", "running");
    setStatus($("curation-status"), "正在生成训练集", "running");
  }
  if (flow.event === "pipeline_completed") {
    setCurationSteps("caption", "completed");
    setStatus($("curation-status"), "训练集已生成", "completed");
  }
  if (flow.event === "failed") {
    const failedStage = curationState.status === "finalizing" ? "caption" : "pixai";
    setCurationSteps(failedStage, "failed");
    setStatus($("curation-status"), "后续流程失败", "failed");
  }
}

function renderDistributions(distribution) {
  const container = $("curation-distributions");
  container.replaceChildren();
  const labels = {
    people_count: {
      title: "人数",
      values: { "1": "1 人", "2": "2 人", "3_plus": "3+ 人", unknown: "未知" },
    },
    framing: {
      title: "取景",
      values: { full_body: "全身", half_body: "半身", headshot: "头像", unknown: "未知" },
    },
    outdoors: {
      title: "场景",
      values: { true: "室外", false: "非室外", unknown: "未知" },
    },
  };
  const total = Number(distribution?.total || 0);
  Object.entries(labels).forEach(([dimension, definition]) => {
    const group = document.createElement("div");
    group.className = "distribution-group";
    const title = document.createElement("strong");
    title.textContent = definition.title;
    group.appendChild(title);
    Object.entries(definition.values).forEach(([key, label]) => {
      const count = Number(distribution?.[dimension]?.[key] || 0);
      const row = document.createElement("div");
      row.className = "distribution-row";
      const name = document.createElement("span");
      name.textContent = label;
      const track = document.createElement("span");
      track.className = "distribution-track";
      const fill = document.createElement("i");
      fill.style.width = `${total ? Math.round(count / total * 100) : 0}%`;
      track.appendChild(fill);
      const value = document.createElement("b");
      value.textContent = String(count);
      row.append(name, track, value);
      group.appendChild(row);
    });
    container.appendChild(group);
  });
}

function renderSelectedDataset(payload) {
  const selected = (payload.items || [])
    .filter((item) => item.selection?.selected)
    .sort((a, b) => a.selection.rank - b.selection.rank);
  $("curation-completed").hidden = false;
  $("curation-completed-title").textContent = `${selected.length} 张训练图片与 Caption 已生成`;
  $("curation-output-path").textContent = payload.training_output_dir || "输出目录不可用";
  $("curation-output-path").title = payload.training_output_dir || "";
  const gallery = $("curation-selected-gallery");
  gallery.replaceChildren();
  selected.forEach((item) => {
    const card = document.createElement("article");
    card.className = "curation-selected-card";
    const image = document.createElement("img");
    image.loading = "lazy";
    image.src = `${API}/jobs/${encodeURIComponent(payload.job_id)}/curation/image/${item.manifest_index}`;
    image.alt = item.path.split("/").pop();
    const caption = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = `${String(item.selection.rank).padStart(3, "0")} · ${item.path.split("/").pop()}`;
    const text = document.createElement("span");
    text.textContent = item.caption || "caption 已写入";
    text.title = item.caption || "";
    caption.append(name, text);
    card.append(image, caption);
    gallery.appendChild(card);
  });
}

async function loadCuration(jobId) {
  const response = await fetch(`${API}/jobs/${encodeURIComponent(jobId)}/curation`);
  if (!response.ok) return;
  const payload = await response.json();
  curationState = payload;
  if (payload.lora_prefix) {
    $("lora-prefix").value = payload.lora_prefix;
    $("standalone-lora-prefix").value = payload.lora_prefix;
  }

  if (payload.status === "not_started") {
    jobRunning = false;
    updateControlAvailability();
    setReviewLocked(false);
    $("curation-panel").hidden = true;
    return;
  }

  $("curation-panel").hidden = false;
  setReviewLocked(payload.status !== "failed");
  $("curation-live").hidden = !["tagging", "finalizing"].includes(payload.status);
  $("curation-config").hidden = payload.status !== "awaiting_selection";
  $("curation-completed").hidden = payload.status !== "completed";

  if (payload.status === "tagging") {
    jobRunning = true;
    updateControlAvailability();
    const total = Number(payload.total_images || 0);
    const tagged = Number(payload.tagged_images || 0);
    const percent = total ? Math.round(tagged / total * 100) : 0;
    setCurationSteps("pixai", "running");
    setStatus($("curation-status"), "PixAI 模型运行中", "running");
    $("curation-progress-bar").style.width = `${percent}%`;
    $("curation-progress-value").textContent = `${percent}%`;
    $("curation-progress-message").textContent = `PixAI 标注 ${tagged}/${total}`;
  }
  if (payload.status === "awaiting_selection") {
    jobRunning = true;
    updateControlAvailability();
    setCurationSteps("selection", "running");
    setStatus($("curation-status"), "等待设置目标分布", "pending");
    $("curation-progress-bar").style.width = "100%";
    $("curation-progress-value").textContent = "100%";
    $("curation-progress-message").textContent = "PixAI 标注完成";
    $("curation-tagged-count").textContent = `${payload.tagged_images} IMAGES`;
    $("curation-target-size").value = payload.tagged_images;
    $("curation-target-size").max = payload.tagged_images;
    $("curation-finalize").disabled = false;
    renderDistributions(payload.distribution);
    if (payload.error) {
      setStatus($("curation-status"), "上次输出失败，可调整后重试", "failed");
      $("curation-progress-message").textContent = payload.error;
    }
  }
  if (payload.status === "finalizing") {
    jobRunning = true;
    updateControlAvailability();
    setCurationSteps("caption", "running");
    setStatus($("curation-status"), "正在生成训练集", "running");
  }
  if (payload.status === "completed") {
    jobRunning = false;
    updateControlAvailability();
    setCurationSteps("caption", "completed");
    setStatus($("curation-status"), "训练集已生成", "completed");
    $("curation-progress-bar").style.width = "100%";
    $("curation-progress-value").textContent = "100%";
    $("curation-progress-message").textContent = "训练图片与 Caption 输出完成";
    renderSelectedDataset(payload);
  }
  if (payload.status === "failed") {
    jobRunning = false;
    updateControlAvailability();
    setCurationSteps("pixai", "failed");
    setStatus(
      $("curation-status"),
      payload.workflow === "pixai_only"
        ? "PixAI 标注失败，可重新直接运行"
        : "PixAI 标注失败，可重新 Submit",
      "failed",
    );
    $("curation-progress-message").textContent = payload.error || "PixAI 标注失败";
  }
}

function updateReviewImage() {
  const item = reviewItems[reviewIndex];
  if (!item) return;
  const sourceName = item.source.split(/[\\/]/).pop();
  $("review-full-image").src = `${API}/jobs/${encodeURIComponent(item.jobId)}/review/${item.manifestIndex}`;
  $("review-full-image").alt = sourceName;
  $("review-image-name").textContent = sourceName;
  $("review-image-name").title = item.source;
  $("review-image-meta").textContent = `CLUSTER #${item.cluster_id} · ${item.candidate_role} · ATTEMPT ${item.locate_attempt}`;
  $("review-image-position").textContent = `${reviewIndex + 1} / ${reviewItems.length}`;
  $("review-previous").disabled = reviewIndex === 0;
  $("review-next").disabled = reviewIndex === reviewItems.length - 1;
  $("review-remove").disabled = reviewLocked;
  $("review-remove").textContent = reviewLocked ? "Review 已提交" : "移出最终数据集";
}

function openReviewImage(index, trigger) {
  reviewIndex = index;
  reviewLastFocused = trigger;
  updateReviewImage();
  $("review-lightbox").hidden = false;
  document.body.classList.add("review-open");
  $("review-close").focus();
}

function closeReviewImage(restoreFocus = true) {
  $("review-lightbox").hidden = true;
  $("review-full-image").removeAttribute("src");
  document.body.classList.remove("review-open");
  if (restoreFocus) reviewLastFocused?.focus();
  reviewLastFocused = null;
}

function moveReviewImage(offset) {
  const next = reviewIndex + offset;
  if (next < 0 || next >= reviewItems.length) return;
  reviewIndex = next;
  updateReviewImage();
}

async function responseError(response) {
  const text = await response.text();
  try {
    return JSON.parse(text).detail || text;
  } catch {
    return text || `HTTP ${response.status}`;
  }
}

function showReviewNotice(message, canUndo = false) {
  $("review-notice-text").textContent = message;
  $("review-undo").hidden = !canUndo;
  $("review-notice").hidden = false;
}

function reviewRemovalConfirmationSeen() {
  if (reviewRemovalConfirmationAcknowledged) return true;
  try {
    reviewRemovalConfirmationAcknowledged =
      window.localStorage.getItem(REVIEW_REMOVE_CONFIRMATION_KEY) === "1";
    return reviewRemovalConfirmationAcknowledged;
  } catch {
    return false;
  }
}

function rememberReviewRemovalConfirmation() {
  reviewRemovalConfirmationAcknowledged = true;
  try {
    window.localStorage.setItem(REVIEW_REMOVE_CONFIRMATION_KEY, "1");
  } catch {
    // Storage may be unavailable in private or restricted browser contexts.
  }
}

function requestReviewRemovalConfirmation(filename, trigger) {
  if (reviewRemovalConfirmationSeen()) return Promise.resolve(true);
  if (reviewRemoveDialogResolve) return Promise.resolve(false);

  reviewRemoveDialogTrigger = trigger;
  $("review-remove-dialog-filename").textContent = filename;
  $("review-remove-dialog").hidden = false;
  document.body.classList.add("review-confirm-open");
  $("review-remove-dialog-cancel").focus();
  return new Promise((resolve) => {
    reviewRemoveDialogResolve = resolve;
  });
}

function closeReviewRemovalConfirmation(confirmed) {
  const resolve = reviewRemoveDialogResolve;
  if (!resolve) return;
  if (confirmed) rememberReviewRemovalConfirmation();
  $("review-remove-dialog").hidden = true;
  document.body.classList.remove("review-confirm-open");
  reviewRemoveDialogResolve = null;
  const trigger = reviewRemoveDialogTrigger;
  reviewRemoveDialogTrigger = null;
  resolve(confirmed);
  if (!confirmed) trigger?.focus();
}

async function removeReviewImageAt(index, button) {
  if (reviewLocked) return;
  const item = reviewItems[index];
  if (!item) return;
  const filename = item.source.split(/[\\/]/).pop();
  const actionButton = button || $("review-remove");
  if (!await requestReviewRemovalConfirmation(filename, actionButton)) return;
  const originalLabel = actionButton.textContent;
  const isCardAction = actionButton.classList.contains("review-card-pass");
  actionButton.disabled = true;
  actionButton.classList.toggle("removing", isCardAction);
  actionButton.textContent = isCardAction ? "…" : "正在移出…";
  try {
    const response = await fetch(
      `${API}/jobs/${encodeURIComponent(item.jobId)}/review/${item.manifestIndex}`,
      { method: "DELETE" },
    );
    if (!response.ok) throw new Error(await responseError(response));
    const payload = await response.json();
    reviewUndo = { jobId: item.jobId, manifestIndex: item.manifestIndex, filename };
    if (!$("review-lightbox").hidden) closeReviewImage(false);
    showReviewNotice(`“${filename}”已移出最终数据集`, true);
    $("metric-output").textContent = payload.output_images;
    await loadManifest(item.jobId);
  } catch (error) {
    showReviewNotice(`移出失败：${error.message}`, false);
  } finally {
    if (actionButton.isConnected) {
      actionButton.disabled = false;
      actionButton.classList.remove("removing");
      actionButton.textContent = originalLabel;
    }
  }
}

async function removeCurrentReviewImage() {
  await removeReviewImageAt(reviewIndex, $("review-remove"));
}

async function undoReviewRemoval() {
  if (!reviewUndo || reviewLocked) return;
  const undo = reviewUndo;
  const button = $("review-undo");
  button.disabled = true;
  button.textContent = "恢复中…";
  try {
    const response = await fetch(
      `${API}/jobs/${encodeURIComponent(undo.jobId)}/review/${undo.manifestIndex}/restore`,
      { method: "POST" },
    );
    if (!response.ok) throw new Error(await responseError(response));
    const payload = await response.json();
    reviewUndo = null;
    $("metric-output").textContent = payload.output_images;
    showReviewNotice(`“${undo.filename}”已恢复到最终数据集`, false);
    await loadManifest(undo.jobId);
  } catch (error) {
    showReviewNotice(`恢复失败：${error.message}`, true);
  } finally {
    button.disabled = false;
    button.textContent = "撤销";
  }
}

async function checkHealth() {
  try {
    const response = await fetch(`${API}/health`);
    if (!response.ok) throw new Error();
    const payload = await response.json();
    reviewThumbnailsAvailable = payload.review_thumbnail === true;
    setDefaultMinimumPixels(payload.minimum_pixels);
    const captionThreshold = Number(payload.pixai_caption_threshold);
    if (Number.isFinite(captionThreshold)) $("caption-threshold").value = captionThreshold;
    const captionMaxTags = Number(payload.pixai_caption_max_tags);
    if (Number.isInteger(captionMaxTags)) {
      $("caption-max-tags").textContent = `${captionMaxTags} · .env`;
    }
    const clusterThreshold = Number(payload.complete_linkage_similarity);
    if (Number.isFinite(clusterThreshold)) {
      $("complete-linkage-similarity").value = clusterThreshold.toFixed(2);
    }
    const graphThreshold = Number(payload.graph_similarity);
    if (Number.isFinite(graphThreshold)) {
      $("graph-similarity").value = graphThreshold.toFixed(2);
    }
    updateFilteringThresholdUi();
    setStatus($("health-badge"), "后端在线", "completed");
  }
  catch { setStatus($("health-badge"), "后端未连接", "failed"); }
}

function listenToJob(jobId, startEventId = 0) {
  eventSource?.close();
  lastEventId = startEventId;
  const eventUrl = `${API}/jobs/${encodeURIComponent(jobId)}/events?last_event_id=${startEventId}`;
  eventSource = new EventSource(eventUrl);
  eventSource.onmessage = (message) => {
    const event = JSON.parse(message.data);
    const isCurationEvent = event.stage === "pixai" || event.stage === "caption";
    const eventId = Number(message.lastEventId || event.id || 0);
    if (eventId > 0 && eventId <= lastEventId) return;
    if (eventId > 0) lastEventId = eventId;
    addLog(event);
    if (isCurationEvent) {
      $("curation-panel").hidden = false;
      $("curation-progress-bar").style.width = `${Math.round(event.progress * 100)}%`;
      $("curation-progress-value").textContent = `${Math.round(event.progress * 100)}%`;
      $("curation-progress-message").textContent = event.message;
      setCurationSteps(event.stage === "pixai" ? "pixai" : "caption", event.status);
    } else {
      updateNodes(event.stage, event.status);
      $("progress-bar").style.width = `${Math.round(event.progress * 100)}%`;
      $("progress-value").textContent = `${Math.round(event.progress * 100)}%`;
      $("progress-message").textContent = event.message;
    }
    updateMetrics(event.data || {});
    if (event.data?.cluster_audit) updateMetrics(event.data.cluster_audit);
    if (event.data?.cluster_audit) updateAudit(event.data.cluster_audit, event.job_id);
    if (event.stage === "clustering" && event.status === "running") {
      if (event.data?.similarity !== undefined) {
        auditState.clusterSimilarity = event.data.similarity;
      }
      setStatus($("audit-status"), `${Number(auditState.clusterSimilarity).toFixed(2)} 聚簇中`, "running");
    }
    if (event.stage === "graph" && event.status === "running") {
      const graphSimilarity = Number(event.data?.similarity);
      if (Number.isFinite(graphSimilarity)) configuredGraphSimilarity = graphSimilarity;
      setStatus(
        $("audit-status"),
        `${configuredGraphSimilarity.toFixed(2)} 图筛选中`,
        "running",
      );
    }
    if (event.data?.locate_flow) renderLocateFlow(event.data.locate_flow);
    if (event.data?.curation_flow) renderCurationFlow(event.data.curation_flow, event.job_id);
    if (event.stage === "locate" && event.status === "running" && !event.data?.locate_flow) {
      setStatus($("locate-live-status"), "Locate 阶段已启动", "running");
    }
    if (event.status === "running" && !isCurationEvent) setStatus($("job-status"), `运行中 · ${stageNames[event.stage] || event.stage}`, "running");
    if (event.status === "failed") {
      if (isCurationEvent) {
        setStatus($("curation-status"), `${stageNames[event.stage]}失败`, "failed");
        jobRunning = false;
        eventSource?.close();
        currentJob = null;
        updateControlAvailability();
        loadCuration(jobId);
        return;
      }
      setStatus($("job-status"), "任务失败", "failed");
      if ($("locate-live-status").classList.contains("running") || event.stage === "locate") {
        renderLocateFailure(event.data?.error || event.message);
      }
      jobRunning = false;
      eventSource?.close();
      currentJob = null;
      updateControlAvailability();
    }
    if (event.status === "completed" && event.stage === "output") {
      setStatus($("job-status"), "已完成", "completed");
      jobRunning = false;
      eventSource?.close();
      currentJob = null;
      updateControlAvailability();
      loadManifest(jobId);
    }
    if (event.status === "completed" && event.stage === "pixai") {
      eventSource?.close();
      currentJob = null;
      loadCuration(jobId);
    }
    if (event.status === "completed" && event.stage === "caption") {
      jobRunning = false;
      eventSource?.close();
      currentJob = null;
      updateControlAvailability();
      loadCuration(jobId);
    }
  };
  eventSource.onerror = () => {
    if (!currentJob) return;
    if (curationState.status === "tagging" || curationState.status === "finalizing") {
      setStatus($("curation-status"), "过程连接重试中", "pending");
    } else {
      setStatus($("job-status"), "连接重试中", "pending");
    }
  };
}

async function loadManifest(jobId) {
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const response = await fetch(`${API}/jobs/${jobId}/manifest`);
    if (response.ok) {
      const items = (await response.json()).items;
      if (items.length) {
        renderResults(items);
        renderReview(jobId, items);
        await loadCuration(jobId);
        return;
      }
      const summaryResponse = await fetch(`${API}/jobs/${jobId}`);
      if (summaryResponse.ok && (await summaryResponse.json()).status === "completed") {
        renderResults(items);
        renderReview(jobId, items);
        await loadCuration(jobId);
        return;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  $("review-panel").hidden = false;
  $("review-summary").textContent = "最终数据集读取失败，请查看任务日志";
  $("review-gallery").innerHTML = '<div class="review-empty">无法加载最终数据集</div>';
}

$("job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!$("source-dir").value) return;
  const thresholdInputs = [
    $("complete-linkage-similarity"),
    $("graph-similarity"),
  ];
  const invalidThreshold = thresholdInputs.find((input) => !input.checkValidity());
  if (invalidThreshold) {
    invalidThreshold.reportValidity();
    return;
  }
  updateFilteringThresholdUi();
  jobRunning = true;
  updateControlAvailability();
  $("event-log").innerHTML = '<div class="empty-state">任务已排队，等待第一条事件…</div>';
  renderResults([]);
  resetAudit();
  resetLocateFlow();
  resetReview();
  document.querySelectorAll(".pipeline-node").forEach((node) => node.classList.remove("running", "completed", "failed"));
  $("progress-bar").style.width = "0%";
  try {
    const response = await fetch(`${API}/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_dir: $("source-dir").value,
        output_dir: $("output-dir").value || null,
        similarity_model: $("similarity-model").value,
        minimum_pixels: Number($("minimum-pixels").value),
        complete_linkage_similarity: configuredClusterSimilarity,
        graph_similarity: configuredGraphSimilarity,
        pipeline_options: window.LoRAForgeCanvas?.getPipelineOptions?.(),
      }),
    });
    if (!response.ok) throw new Error(await response.text());
    currentJob = await response.json();
    visualPipelineStarted = true;
    updateControlAvailability();
    setStatus($("job-status"), "任务已排队", "running");
    listenToJob(currentJob.job_id);
  } catch (error) {
    setStatus($("job-status"), "创建失败", "failed");
    $("progress-message").textContent = error.message;
    jobRunning = false;
    updateControlAvailability();
  }
});

$("standalone-pixai-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const prefix = $("standalone-lora-prefix").value.trim();
  if (
    visualPipelineStarted
    || jobRunning
    || !$("source-dir").value
    || !prefix
    || !$("standalone-lora-prefix").checkValidity()
  ) return;

  jobRunning = true;
  updateControlAvailability();
  $("event-log").innerHTML = '<div class="empty-state">独立 PixAI 任务已排队，等待第一条事件…</div>';
  renderResults([]);
  resetAudit();
  resetLocateFlow();
  resetReview();
  reviewJobId = null;
  $("curation-panel").hidden = false;
  $("curation-live").hidden = false;
  $("curation-config").hidden = true;
  $("curation-completed").hidden = true;
  setCurationSteps("pixai", "running");
  setStatus($("job-status"), "独立 PixAI", "running");
  setStatus($("curation-status"), "PixAI 模型启动中", "running");
  $("curation-progress-bar").style.width = "0%";
  $("curation-progress-value").textContent = "0%";
  $("curation-progress-message").textContent = "正在枚举文件夹图片并加载 PixAI Tagger";

  try {
    const response = await fetch(`${API}/pixai/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_dir: $("source-dir").value,
        output_dir: $("output-dir").value || null,
        lora_prefix: prefix,
      }),
    });
    if (!response.ok) throw new Error(await responseError(response));
    const payload = await response.json();
    reviewJobId = payload.job_id;
    currentJob = { job_id: payload.job_id };
    curationState = { status: "tagging", lora_prefix: prefix, items: [] };
    $("lora-prefix").value = prefix;
    $("curation-description").textContent = `独立模式 · 已跳过视觉筛选 · ${payload.source_images} 张原图进入 PixAI。`;
    listenToJob(payload.job_id, payload.event_cursor);
    $("curation-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    currentJob = null;
    reviewJobId = null;
    curationState = { status: "failed", items: [] };
    setStatus($("job-status"), "独立 PixAI 创建失败", "failed");
    setStatus($("curation-status"), "创建失败", "failed");
    $("curation-progress-message").textContent = error.message;
    jobRunning = false;
    updateControlAvailability();
  }
});

$("curation-submit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!reviewJobId || !reviewItems.length || reviewLocked) return;
  const prefix = $("lora-prefix").value.trim();
  if (!prefix) return;
  const button = $("curation-submit");
  button.disabled = true;
  button.textContent = "提交中…";
  try {
    const response = await fetch(`${API}/jobs/${encodeURIComponent(reviewJobId)}/curation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lora_prefix: prefix }),
    });
    if (!response.ok) throw new Error(await responseError(response));
    const payload = await response.json();
    curationState = { status: "tagging", lora_prefix: prefix, items: [] };
    setReviewLocked(true);
    $("review-notice").hidden = true;
    $("review-summary").textContent = `${reviewItems.length} 张图片已提交 · LoRA Prefix: ${prefix}`;
    $("curation-panel").hidden = false;
    $("curation-live").hidden = false;
    $("curation-config").hidden = true;
    $("curation-completed").hidden = true;
    setCurationSteps("pixai", "running");
    setStatus($("curation-status"), "PixAI 模型启动中", "running");
    $("curation-progress-bar").style.width = "0%";
    $("curation-progress-value").textContent = "0%";
    $("curation-progress-message").textContent = "正在加载 PixAI Tagger v0.9";
    jobRunning = true;
    currentJob = { job_id: reviewJobId };
    updateControlAvailability();
    listenToJob(reviewJobId, payload.event_cursor);
    $("curation-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showReviewNotice(`Submit 失败：${error.message}`, false);
    setReviewLocked(false);
  } finally {
    button.textContent = "Submit → PixAI";
    if (!reviewLocked) button.disabled = false;
  }
});

$("curation-finalize-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!reviewJobId || curationState.status !== "awaiting_selection") return;
  const button = $("curation-finalize");
  const payload = {
    target_size: Number($("curation-target-size").value),
    people_count_target: {
      "1": Number($("target-people-1").value),
      "2": Number($("target-people-2").value),
      "3_plus": Number($("target-people-3").value),
    },
    framing_target: {
      full_body: Number($("target-framing-full").value),
      half_body: Number($("target-framing-half").value),
      headshot: Number($("target-framing-head").value),
    },
    outdoors_target: {
      true: Number($("target-outdoors-true").value),
      false: Number($("target-outdoors-false").value),
    },
    caption_threshold: Number($("caption-threshold").value),
    denylist: $("caption-denylist").value
      .split(/[,\n]/)
      .map((tag) => tag.trim())
      .filter(Boolean),
  };
  button.disabled = true;
  button.textContent = "正在开始…";
  try {
    const response = await fetch(
      `${API}/jobs/${encodeURIComponent(reviewJobId)}/curation/finalize`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    if (!response.ok) throw new Error(await responseError(response));
    const result = await response.json();
    curationState.status = "finalizing";
    $("curation-config").hidden = true;
    setCurationSteps("caption", "running");
    setStatus($("curation-status"), "正在生成训练集", "running");
    $("curation-progress-bar").style.width = "0%";
    $("curation-progress-value").textContent = "0%";
    $("curation-progress-message").textContent = "正在计算边际分布并生成 Caption";
    jobRunning = true;
    currentJob = { job_id: reviewJobId };
    updateControlAvailability();
    listenToJob(reviewJobId, result.event_cursor);
  } catch (error) {
    setStatus($("curation-status"), "训练集生成失败", "failed");
    $("curation-progress-message").textContent = error.message;
    button.disabled = false;
  } finally {
    button.textContent = "生成训练图片与 Caption";
  }
});

$("source-dir").addEventListener("click", () => {
  document.querySelector('[data-folder-target="source-dir"]').click();
});
$("output-dir").addEventListener("click", () => {
  document.querySelector('[data-folder-target="output-dir"]').click();
});
document.querySelectorAll(".folder-select-button").forEach((button) => {
  button.addEventListener("click", () => chooseFolder(button));
});
$("clear-output-dir").addEventListener("click", () => {
  $("output-dir").value = "";
  $("output-dir").title = "";
  $("progress-message").textContent = "已恢复为自动输出目录";
  updateControlAvailability();
});
$("standalone-lora-prefix").addEventListener("input", updateControlAvailability);
$("similarity-model").addEventListener("change", updateSimilarityModelUi);
$("minimum-pixels").addEventListener("change", updateResolutionThresholdUi);
$("complete-linkage-similarity").addEventListener("input", updateFilteringThresholdUi);
$("graph-similarity").addEventListener("input", updateFilteringThresholdUi);
$("review-page-previous").addEventListener("click", () => goToReviewPage(reviewPage - 1));
$("review-page-next").addEventListener("click", () => goToReviewPage(reviewPage + 1));
$("review-page-input").addEventListener("change", (event) => {
  goToReviewPage(Number(event.currentTarget.value) - 1);
});
$("review-page-input").addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  goToReviewPage(Number(event.currentTarget.value) - 1);
});
$("clear-log").addEventListener("click", () => { $("event-log").innerHTML = '<div class="empty-state">日志已清空。</div>'; });
$("review-close").addEventListener("click", () => closeReviewImage());
$("review-previous").addEventListener("click", () => moveReviewImage(-1));
$("review-next").addEventListener("click", () => moveReviewImage(1));
$("review-remove").addEventListener("click", removeCurrentReviewImage);
$("review-undo").addEventListener("click", undoReviewRemoval);
$("review-remove-dialog-cancel").addEventListener("click", () => closeReviewRemovalConfirmation(false));
$("review-remove-dialog-confirm").addEventListener("click", () => closeReviewRemovalConfirmation(true));
$("review-remove-dialog").addEventListener("click", (event) => {
  if (event.target === $("review-remove-dialog")) closeReviewRemovalConfirmation(false);
});
$("review-lightbox").addEventListener("click", (event) => {
  if (event.target === $("review-lightbox")) closeReviewImage();
});
document.querySelectorAll(".audit-tab").forEach((button) => {
  button.addEventListener("click", () => {
    auditState.view = button.dataset.auditView;
    if (auditState.view === "clustering") auditState.filter = "all";
    if (auditState.view === "graph" && auditState.graph && auditState.filter === "all") {
      auditState.filter = "excluded";
    }
    renderAudit();
  });
});
document.querySelectorAll(".audit-filters button").forEach((button) => {
  button.addEventListener("click", () => {
    auditState.filter = button.dataset.auditFilter;
    renderAudit();
  });
});
document.addEventListener("keydown", (event) => {
  if (!$("review-remove-dialog").hidden) {
    if (event.key === "Escape") closeReviewRemovalConfirmation(false);
    return;
  }
  if ($("review-lightbox").hidden) return;
  if (event.key === "Escape") closeReviewImage();
  if (event.key === "ArrowLeft") moveReviewImage(-1);
  if (event.key === "ArrowRight") moveReviewImage(1);
});
resetAudit();
resetLocateFlow();
resetReview();
updateSimilarityModelUi();
updateResolutionThresholdUi();
updateFilteringThresholdUi();
updateControlAvailability();
checkHealth();
