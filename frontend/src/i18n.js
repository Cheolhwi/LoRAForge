(() => {
  const supportedLanguages = new Set(["zh", "en"]);
  const queryLanguage = new URLSearchParams(window.location.search).get("lang");
  const storedLanguage = window.localStorage.getItem("loraforge-language");
  const language = supportedLanguages.has(queryLanguage)
    ? queryLanguage
    : (supportedLanguages.has(storedLanguage) ? storedLanguage : "zh");

  window.localStorage.setItem("loraforge-language", language);
  document.documentElement.lang = language === "en" ? "en" : "zh-CN";

  const exactTranslations = new Map(Object.entries({
    "LoRAForge · 数据集筛选编排器": "LoRAForge · Dataset Pipeline",
    "语言": "Language",
    "图片数据集筛选台": "Image Dataset Workbench",
    "∞ 无限画布 · LoRA 数据集流水线": "∞ Infinite canvas · LoRA dataset pipeline",
    "适应画布": "Fit canvas",
    "▶ 运行流水线": "▶ Run pipeline",
    "▶ 运行 PixAI": "▶ Run PixAI",
    "跳过视觉筛选": "Skip visual filtering",
    "跳过视觉筛选，直接运行 PixAI 标注": "Skip visual filtering and run PixAI tagging directly",
    "返回画布": "Back to canvas",
    "总览": "Overview",
    "筛选": "Filter",
    "检测": "Inspect",
    "复核": "Review",
    "标注": "Tagging",
    "日志": "Log",
    "输入与运行": "Input & run",
    "文件夹 · 本地模型": "Folders · local models",
    "扫描 & 去重": "Scan & deduplicate",
    "扫描前": "Before scan",
    "去重后": "After deduplication",
    "重复移除": "Duplicates removed",
    "分辨率过滤": "Resolution filter",
    "任务级准入门槛": "Per-job acceptance threshold",
    "聚簇": "Clustering",
    "图筛选": "Graph filter",
    "保留簇": "Kept clusters",
    "输出候选": "Output candidates",
    "Locate 检测": "Locate inspection",
    "丢弃簇": "Dropped clusters",
    "候选重试": "Candidate retry",
    "簇内备用候选 · 仅一次": "Backup candidate in cluster · once",
    "Review 复核": "Review",
    "默认通过 · 可移出": "Included by default · removable",
    "PixAI 标注": "PixAI tagging",
    "选择 & 分布": "Selection & distribution",
    "Caption 处理": "Caption processing",
    "规则链 · LoRA Prefix": "Rule chain · LoRA Prefix",
    "训练图片 · Caption · 报告": "Training images · captions · report",
    "此节点为必需节点": "This node is required",
    "启用或旁路此节点": "Enable or bypass this node",
    "Review 或 PixAI 节点已关闭，无法进入标注阶段。": "Review or PixAI is disabled, so tagging cannot start.",
    "PixAI 节点已关闭。": "The PixAI node is disabled.",
    "选择或 Caption 节点已关闭，无法生成训练集。": "Selection or Caption is disabled, so the training set cannot be generated.",
    "把去重、聚类、图筛选与视觉质检串成一条可观察的流水线。": "Turn deduplication, clustering, graph filtering, and visual inspection into one observable pipeline.",
    "正在连接后端": "Connecting to backend",
    "创建一次筛选任务": "Create a filtering job",
    "固定使用本地真实模型": "Local production models only",
    "图片文件夹": "Image folder",
    "请选择需要筛选的图片文件夹": "Select the image folder to process",
    "选择文件夹": "Choose folder",
    "输出文件夹（可选）": "Output folder (optional)",
    "不选择则输出到源目录下": "Leave empty to write under the source folder",
    "清除": "Clear",
    "视觉相似度模型": "Visual similarity model",
    "DINOv3（默认）": "DINOv3 (default)",
    "PixAI Embedding（实验）": "PixAI Embedding (experimental)",
    "图片准入门槛": "Image acceptance threshold",
    "标准 · ≥ 1MP": "Standard · ≥ 1MP",
    "兼容 720p · ≥ 1280×720": "720p compatible · ≥ 1280×720",
    "聚簇相似度": "Clustering similarity",
    "Complete-linkage 簇内最低相似度": "Minimum within-cluster similarity for Complete-linkage",
    "图筛选相似度": "Graph-filter similarity",
    "建立 Mutual Top-20 边的最低相似度": "Minimum similarity for a Mutual Top-20 edge",
    "启动流水线": "Start pipeline",
    "跳过视觉筛选，直接标注所选文件夹": "Skip visual filtering and tag the selected folder",
    "仅在当前页面尚未启动上方流水线时可用；不会执行 SHA、视觉 Embedding、图筛选或 Locate。": "Available before the visual pipeline starts on this page. Skips SHA, visual embedding, graph filtering, and Locate.",
    "当前页面已经启动过视觉筛选流水线；直接 PixAI 入口已锁定。": "The visual pipeline has already started on this page, so Direct PixAI is locked.",
    "例如 artist_style": "For example: artist_style",
    "直接运行 PixAI": "Run PixAI directly",
    "过程预览": "Pipeline preview",
    "等待任务": "Waiting for a job",
    "去重 & 分辨率": "Deduplication & resolution",
    "水印 · 漫画 · 拼图": "Watermark · comic · collage",
    "输出数据集": "Write dataset",
    "准备就绪": "Ready",
    "实时指标": "Live metrics",
    "发现文件": "Files found",
    "去重后": "After deduplication",
    "有效图片（≥1MP）": "Eligible images (≥1MP)",
    "检查簇": "Clusters inspected",
    "输出图片": "Output images",
    "通过": "Passed",
    "重试": "Retry",
    "放弃": "Dropped",
    "分簇与图筛选预览": "Clustering and graph-filter preview",
    "流水线运行到 0.90 聚簇后，将在这里显示超低清缩略图。": "Very-low-resolution thumbnails will appear here after 0.90 clustering.",
    "等待聚簇": "Waiting for clustering",
    "筛选阶段": "Filtering stage",
    "0.90 聚簇": "0.90 clustering",
    "0.65 图筛选": "0.65 graph filter",
    "簇状态筛选": "Cluster status filter",
    "全部": "All",
    "保留": "Kept",
    "排除": "Excluded",
    "有效图片": "Eligible images",
    "保留图片": "Kept images",
    "排除图片": "Excluded images",
    "0.90 只负责把图片分组，不会在此处删除图片。": "0.90 only groups images; no images are removed at this step.",
    "等待 Complete-linkage 聚簇结果…": "Waiting for Complete-linkage clustering results…",
    "Locate Anything 检测流": "Locate Anything inspection flow",
    "尚未开始": "Not started",
    "等待 Locate 阶段": "Waiting for Locate",
    "当前候选": "Current candidate",
    "Locate Anything 当前检测图片": "Image currently inspected by Locate Anything",
    "等待候选图片": "Waiting for a candidate image",
    "水印检查": "Watermark check",
    "只要返回检测框，即标记为 not meet": "Any returned box marks the candidate as not meet",
    "等待输入": "Waiting for input",
    "漫画 / 拼图检查": "Comic / collage check",
    "返回两个及以上检测框，即标记为 not meet": "Two or more returned boxes mark the candidate as not meet",
    "候选判定": "Candidate decision",
    "等待两次检测": "Waiting for both checks",
    "簇内备用候选": "Backup candidate in cluster",
    "首次不通过时触发": "Used when the first candidate fails",
    "仅重试一次": "One retry only",
    "检测结果会依次出现在这里": "Inspection results will appear here in order",
    "水印框": "Watermark box",
    "漫画 / 拼图框": "Comic / collage box",
    "编排日志": "Pipeline log",
    "清空": "Clear",
    "启动任务后，这里会实时显示每个阶段的事件。": "Events from every stage will appear here after a job starts.",
    "候选结果": "Candidate results",
    "状态": "Status",
    "候选图": "Candidate",
    "簇": "Cluster",
    "方式": "Method",
    "原因": "Reason",
    "暂无结果": "No results yet",
    "最终数据集预览": "Final dataset preview",
    "任务完成后展示所有通过的图片": "All passed images will appear here after the job completes",
    "图片已移出最终数据集": "Image removed from the final dataset",
    "撤销": "Undo",
    "当前展示图片默认通过": "Displayed images are included by default",
    "不需要逐张确认；只需移出不合适的图片": "No per-image confirmation is needed; remove only unsuitable images",
    "标签、边际选样与 Caption": "Tagging, marginal sampling, and captions",
    "PixAI 只推理一次；选样只读取人数、取景和室外状态。": "PixAI runs once; sampling uses only subject count, framing, and outdoor status.",
    "等待 Submit": "Waiting for Submit",
    "边际分布选样": "Marginal-distribution sampling",
    "人数 · 取景 · 室外": "Subject count · framing · outdoor",
    "训练集输出": "Training dataset output",
    "图片 + UTF-8 caption": "Images + UTF-8 captions",
    "等待进入 PixAI 阶段": "Waiting to enter the PixAI stage",
    "当前 PixAI 标注图片": "Image currently being tagged by PixAI",
    "PixAI 派生分布": "PixAI-derived distribution",
    "最终训练集配置": "Final training dataset settings",
    "各组会在后端自动归一化": "Each group is normalized automatically",
    "目标图片数": "Target image count",
    "人数比例": "Subject-count ratio",
    "1 人": "1 person",
    "2 人": "2 people",
    "3+ 人": "3+ people",
    "取景比例": "Framing ratio",
    "全身": "Full body",
    "半身": "Half body",
    "头像": "Headshot",
    "室外比例": "Outdoor ratio",
    "室外": "Outdoor",
    "非室外": "Not outdoor",
    "Caption 标签阈值": "Caption tag threshold",
    "Caption 最多标签数（含 Prefix）": "Maximum caption tags (including prefix)",
    "额外 Denylist（逗号或换行分隔）": "Additional denylist (comma- or newline-separated)",
    "例如 lowres, blurry": "For example: lowres, blurry",
    "生成训练图片与 Caption": "Generate training images and captions",
    "训练数据集已生成": "Training dataset generated",
    "最终数据集图片查看器": "Final dataset image viewer",
    "关闭大图": "Close full-size image",
    "上一张图片": "Previous image",
    "下一张图片": "Next image",
    "移出最终数据集": "Remove from final dataset",
    "去重/分辨率": "Deduplication/resolution",
    "聚簇": "Clustering",
    "图筛选": "Graph filter",
    "输出": "Output",
    "PixAI 标注": "PixAI tagging",
    "选样与 Caption": "Sampling & captions",
    "检测到水印或署名": "Watermark or signature detected",
    "检测到漫画分镜或拼图": "Comic panels or collage detected",
    "等待选择…": "Waiting for selection…",
    "请在弹出的系统窗口中选择文件夹": "Choose a folder in the system dialog",
    "图片文件夹已选择": "Image folder selected",
    "输出文件夹已选择": "Output folder selected",
    "已取消文件夹选择": "Folder selection cancelled",
    "图节点 / 边": "Graph nodes / edges",
    "3-core 节点": "3-core nodes",
    "仍保留图片": "Images still kept",
    "此步排除": "Excluded at this step",
    "当前筛选条件下没有簇": "No clusters match the current filter",
    "LIVE · 正在检测": "LIVE · Inspecting",
    "正在检查备用候选": "Inspecting backup candidate",
    "模型推理中…": "Model inference…",
    "已跳过": "Skipped",
    "触发 not meet": "Triggered not meet",
    "未触发规则": "Rule not triggered",
    "MEET · 候选通过": "MEET · Candidate passed",
    "两项检查均满足规则": "Both checks satisfy the rules",
    "未通过检测": "Inspection failed",
    "无需重试": "No retry needed",
    "medoid 已通过": "Medoid passed",
    "等待备用候选": "Waiting for a backup candidate",
    "已选择备用候选": "Backup candidate selected",
    "备用候选通过": "Backup candidate passed",
    "备用候选不通过": "Backup candidate failed",
    "簇已放弃": "Cluster dropped",
    "没有可用备用候选": "No backup candidate available",
    "重试未通过": "Retry failed",
    "检测中断": "Inspection interrupted",
    "检测服务异常": "Inspection service error",
    "请检查后端日志": "Check the backend log",
    "已移出": "Removed",
    "重试通过": "Passed on retry",
    "最终数据集为空": "The final dataset is empty",
    "默认通过": "Included by default",
    "点击移出候选集": "Click to remove from candidates",
    "移出这张图片？": "Remove this image?",
    "图片会移入可恢复区，可以立即撤销。": "The image will be moved to a recoverable area and can be restored immediately.",
    "此提示只出现一次；以后点击对勾将直接移出。": "This notice appears only once. Future checkmark clicks will remove the image directly.",
    "暂不移出": "Keep for now",
    "移出图片": "Remove image",
    "上一页": "Previous page",
    "下一页": "Next page",
    "Review 页码": "Review page",
    "取景未知": "Framing unknown",
    "未知": "Unknown",
    "人数": "Subject count",
    "取景": "Framing",
    "场景": "Scene",
    "PixAI 模型运行中": "PixAI model running",
    "等待设置目标分布": "Waiting for target distribution",
    "正在生成训练集": "Generating training dataset",
    "后续流程失败": "Downstream pipeline failed",
    "输出目录不可用": "Output folder unavailable",
    "caption 已写入": "Caption written",
    "PixAI 标注完成": "PixAI tagging complete",
    "上次输出失败，可调整后重试": "The previous output failed; adjust the settings and retry",
    "训练图片与 Caption 输出完成": "Training images and captions written",
    "PixAI 标注失败，可重新直接运行": "PixAI tagging failed; Direct PixAI can be run again",
    "PixAI 标注失败，可重新 Submit": "PixAI tagging failed; submit again",
    "PixAI 标注失败": "PixAI tagging failed",
    "Review 已提交": "Review submitted",
    "正在移出…": "Removing…",
    "恢复中…": "Restoring…",
    "后端在线": "Backend online",
    "后端未连接": "Backend unavailable",
    "0.65 图筛选中": "0.65 graph filtering",
    "Locate 阶段已启动": "Locate stage started",
    "任务失败": "Job failed",
    "已完成": "Completed",
    "过程连接重试中": "Reconnecting to pipeline",
    "连接重试中": "Reconnecting",
    "最终数据集读取失败，请查看任务日志": "Could not read the final dataset; check the job log",
    "无法加载最终数据集": "Unable to load the final dataset",
    "任务已排队，等待第一条事件…": "Job queued; waiting for the first event…",
    "任务已排队": "Job queued",
    "创建失败": "Creation failed",
    "独立 PixAI 任务已排队，等待第一条事件…": "Direct PixAI job queued; waiting for the first event…",
    "独立 PixAI": "Direct PixAI",
    "PixAI 模型启动中": "Starting PixAI model",
    "正在枚举文件夹图片并加载 PixAI Tagger": "Scanning folder images and loading PixAI Tagger",
    "独立 PixAI 创建失败": "Could not create Direct PixAI job",
    "提交中…": "Submitting…",
    "正在加载 PixAI Tagger v0.9": "Loading PixAI Tagger v0.9",
    "正在开始…": "Starting…",
    "正在计算边际分布并生成 Caption": "Calculating marginal distributions and generating captions",
    "训练集生成失败": "Training dataset generation failed",
    "已恢复为自动输出目录": "Automatic output folder restored",
    "日志已清空。": "Log cleared.",
    "流水线运行失败": "Pipeline failed",
    "扫描阶段完成": "Scan stage complete",
    "建立 Mutual Top-20 图并迭代 3-core": "Building the Mutual Top-20 graph and iterating the 3-core",
    "只检查最大连通分量涉及的簇": "Inspecting only clusters in the largest connected component",
    "复制通过图片并写入 manifest.json": "Copying passed images and writing manifest.json",
    "输出阶段完成": "Output stage complete",
    "Locate Anything 检查完成": "Locate Anything inspection complete",
    "PixAI 标注完成，等待设置边际分布": "PixAI tagging complete; waiting for marginal-distribution settings",
    "PixAI 标注失败": "PixAI tagging failed",
    "训练图片与 caption 已输出": "Training images and captions written",
    "训练数据集生成失败": "Training dataset generation failed"
  }));

  const patternTranslations = [
    [/^有效图片（≥(.+)）$/, "Eligible images (≥$1)"],
    [/^\.env 默认 · ≥ (.+)$/, ".env default · ≥ $1"],
    [/^文件夹选择失败：(.+)$/s, "Folder selection failed: $1"],
    [/^流水线运行到 (.+) 聚簇后，将在这里显示超低清缩略图。$/, "Very-low-resolution thumbnails will appear here after $1 clustering."],
    [/^(.+) 只负责把图片分组，不会在此处删除图片。$/, "$1 only groups images; no images are removed at this step."],
    [/^([\d.]+) Mutual Top-(\d+)、(\d+)-core 与最大连通分量的最终去留$/, "Final keep/exclude result from $1 Mutual Top-$2, $3-core, and the largest connected component"],
    [/^相似度 ≥ ([\d.]+) 后形成 (\d+) 条 Mutual Top-(\d+) 边；(\d+)\/(\d+) 个簇节点进入 (\d+)-core，最大连通分量最终保留 (\d+) 个簇、排除 (\d+) 个簇。$/, "Similarity ≥ $1 created $2 Mutual Top-$3 edges; $4/$5 cluster nodes entered the $6-core, and the largest connected component kept $7 clusters and excluded $8."],
    [/^Complete-linkage similarity (.+) 的分组结果$/, "Complete-linkage similarity $1 grouping result"],
    [/^([\d.]+) 簇$/, "$1 clusters"],
    [/^([\d.]+) 聚簇$/, "$1 clustering"],
    [/^([\d.]+) 图筛选$/, "$1 graph filter"],
    [/^([\d.]+) 图筛选中$/, "$1 graph filtering"],
    [/^图片右上角的半透明数字是该图与 medoid 的余弦相似度；簇标题中的 MIN 是簇内最低两两相似度，直接对应 Complete-linkage ([\d.]+)。蓝色 M 表示 medoid。$/, "The translucent number on each image is its cosine similarity to the medoid. MIN is the lowest pairwise similarity in the cluster and directly corresponds to Complete-linkage $1. A blue M marks the medoid."],
    [/^保留 · (\d+) 图$/, "Kept · $1 images"],
    [/^排除 · (\d+) 图$/, "Excluded · $1 images"],
    [/^(\d+) 图 · MIN (.+)$/, "$1 images · MIN $2"],
    [/^(.+) · 与 medoid 相似度 (.+)$/, "$1 · similarity to medoid $2"],
    [/^([\d.]+) 已完成 · (\d+) 簇$/, "$1 complete · $2 clusters"],
    [/^图筛选完成 · 排除 (\d+) 簇$/, "Graph filter complete · $1 clusters excluded"],
    [/^准备 (\d+) 个簇$/, "Preparing $1 clusters"],
    [/^已完成 · (\d+) 个簇$/, "Complete · $1 clusters"],
    [/^已加载最终输出目录中的 (\d+) 张图片，点击缩略图可逐张检查$/, "Loaded $1 images from the final output folder. Select a thumbnail to inspect it."],
    [/^已加载最终输出目录中的 (\d+) 张图片，点击缩略图检查；点击右上角对勾可移出候选集$/, "Loaded $1 images from the final output folder. Select a thumbnail to inspect it, or use the top-right checkmark to remove it."],
    [/^已加载 (\d+) 张图片，每页显示 (\d+) 张；点击缩略图检查，点击对勾移出$/, "Loaded $1 images, displaying $2 per page. Select a thumbnail to inspect it or use the checkmark to remove it."],
    [/^本次任务没有通过并进入最终数据集的图片$/, "No images passed into the final dataset for this job"],
    [/^查看图片 (\d+)：(.+)$/, "View image $1: $2"],
    [/^将 (.+) 移出候选集$/, "Remove $1 from candidates"],
    [/^人数 (.+)$/, "Subjects $1"],
    [/^取景 (.+)$/, "Framing $1"],
    [/^场景 (.+)$/, "Scene $1"],
    [/^(\d+) 张训练图片与 Caption 已生成$/, "$1 training images and captions generated"],
    [/^PixAI 标注 (\d+)\/(\d+)$/, "PixAI tagging $1/$2"],
    [/^确定将“(.+)”移出最终数据集吗？\n\n文件会被移到可恢复区，可以立即撤销。$/s, "Remove “$1” from the final dataset?\n\nThe file will be moved to a recoverable area and can be restored immediately."],
    [/^“(.+)”已移出最终数据集$/, "“$1” was removed from the final dataset"],
    [/^移出失败：(.+)$/s, "Removal failed: $1"],
    [/^“(.+)”已恢复到最终数据集$/, "“$1” was restored to the final dataset"],
    [/^恢复失败：(.+)$/s, "Restore failed: $1"],
    [/^([\d.]+) 聚簇中$/, "$1 clustering"],
    [/^运行中 · (.+)$/, "Running · $1"],
    [/^(.+)失败$/, "$1 failed"],
    [/^独立模式 · 已跳过视觉筛选 · (\d+) 张原图进入 PixAI。$/, "Direct mode · visual filtering skipped · $1 source images sent to PixAI."],
    [/^(\d+) 张图片已提交 · LoRA Prefix: (.+)$/, "$1 images submitted · LoRA Prefix: $2"],
    [/^Submit 失败：(.+)$/s, "Submit failed: $1"],
    [/^扫描图片、SHA-256 去重并检查分辨率（≥ (.+)）$/, "Scanning images, deduplicating with SHA-256, and checking resolution (≥ $1)"],
    [/^生成 (.+)（(\d+) 维）$/, "Generating $1 ($2 dimensions)"],
    [/^(.+) 阶段完成$/, "$1 stage complete"],
    [/^Complete-linkage ([\d.]+) 聚簇并计算 medoid$/, "Complete-linkage $1 clustering and medoid calculation"],
    [/^得到 (\d+) 个 ([\d.]+) 簇$/, "Created $1 clusters at $2"],
    [/^最大连通分量涉及 (\d+) 个簇$/, "Largest connected component contains $1 clusters"],
    [/^准备检查 (\d+) 个簇$/, "Preparing to inspect $1 clusters"],
    [/^簇 (\d+)\/(\d+) 切换备用候选$/, "Cluster $1/$2 · switching to a backup candidate"],
    [/^检查簇 (\d+)\/(\d+)$/, "Inspecting cluster $1/$2"],
    [/^簇 (\d+)\/(\d+) · 载入 (.+)$/, "Cluster $1/$2 · loading $3"],
    [/^簇 (\d+)\/(\d+) · 水印检查中$/, "Cluster $1/$2 · checking for watermarks"],
    [/^簇 (\d+)\/(\d+) · 漫画\/拼图检查中$/, "Cluster $1/$2 · checking for comics/collages"],
    [/^簇 (\d+)\/(\d+) · 已检测到水印，跳过漫画\/拼图检查$/, "Cluster $1/$2 · watermark detected; skipping comic/collage check"],
    [/^簇 (\d+)\/(\d+) · 水印返回 (\d+) 个框$/, "Cluster $1/$2 · watermark check returned $3 boxes"],
    [/^簇 (\d+)\/(\d+) · 漫画\/拼图返回 (\d+) 个框$/, "Cluster $1/$2 · comic/collage check returned $3 boxes"],
    [/^簇 (\d+)\/(\d+) · 当前候选通过$/, "Cluster $1/$2 · current candidate passed"],
    [/^簇 (\d+)\/(\d+) · 当前候选不通过$/, "Cluster $1/$2 · current candidate failed"],
    [/^PixAI Tagger 准备标注文件夹中的 (\d+) 张图片$/, "PixAI Tagger is preparing to tag $1 images from the folder"],
    [/^PixAI Tagger 准备标注 (\d+) 张 Review 通过图片$/, "PixAI Tagger is preparing to tag $1 review-approved images"],
    [/^PixAI 标注 (\d+)\/(\d+) · (.+)$/, "PixAI tagging $1/$2 · $3"],
    [/^开始生成 (\d+) 组训练图片与 caption$/, "Starting generation of $1 training image/caption pairs"],
    [/^写入训练样本 (\d+)\/(\d+) · (.+)$/, "Writing training sample $1/$2 · $3"]
  ];

  function translate(value) {
    if (language !== "en" || typeof value !== "string" || !value.trim()) return value;
    const leading = value.match(/^\s*/)?.[0] || "";
    const trailing = value.match(/\s*$/)?.[0] || "";
    const core = value.slice(leading.length, value.length - trailing.length);
    let translated = exactTranslations.get(core);
    if (!translated) {
      for (const [pattern, replacement] of patternTranslations) {
        if (pattern.test(core)) {
          translated = core.replace(pattern, replacement);
          break;
        }
      }
    }
    return translated ? `${leading}${translated}${trailing}` : value;
  }

  const translatedAttributes = ["aria-label", "placeholder", "title"];
  const skippedTags = new Set(["SCRIPT", "STYLE", "NOSCRIPT"]);

  function translateElement(element) {
    if (!(element instanceof Element)) return;
    translatedAttributes.forEach((attribute) => {
      if (!element.hasAttribute(attribute)) return;
      const current = element.getAttribute(attribute);
      const translated = translate(current);
      if (translated !== current) element.setAttribute(attribute, translated);
    });
  }

  function translateTree(root) {
    if (language !== "en") return;
    if (root.nodeType === Node.TEXT_NODE) {
      if (skippedTags.has(root.parentElement?.tagName)) return;
      const translated = translate(root.nodeValue);
      if (translated !== root.nodeValue) root.nodeValue = translated;
      return;
    }
    if (root instanceof Element) translateElement(root);
    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
    );
    let node = walker.nextNode();
    while (node) {
      if (node.nodeType === Node.ELEMENT_NODE) {
        translateElement(node);
      } else if (!skippedTags.has(node.parentElement?.tagName)) {
        const translated = translate(node.nodeValue);
        if (translated !== node.nodeValue) node.nodeValue = translated;
      }
      node = walker.nextNode();
    }
  }

  document.querySelectorAll("[data-language]").forEach((button) => {
    const buttonLanguage = button.dataset.language;
    button.classList.toggle("active", buttonLanguage === language);
    button.setAttribute("aria-pressed", String(buttonLanguage === language));
    button.addEventListener("click", () => {
      if (!supportedLanguages.has(buttonLanguage) || buttonLanguage === language) return;
      window.localStorage.setItem("loraforge-language", buttonLanguage);
      const url = new URL(window.location.href);
      url.searchParams.set("lang", buttonLanguage);
      window.location.assign(url);
    });
  });

  window.LoRAForgeI18n = { language, translate };
  translateTree(document.documentElement);

  if (language === "en") {
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.type === "characterData") {
          if (skippedTags.has(mutation.target.parentElement?.tagName)) return;
          const translated = translate(mutation.target.nodeValue);
          if (translated !== mutation.target.nodeValue) mutation.target.nodeValue = translated;
          return;
        }
        if (mutation.type === "attributes") {
          translateElement(mutation.target);
          return;
        }
        mutation.addedNodes.forEach((node) => translateTree(node));
      });
    });
    observer.observe(document.documentElement, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: translatedAttributes,
    });
  }
})();

export {};
