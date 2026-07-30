# Auto Cat Pipeline

一个本地优先、前后端分离的图片数据集筛选与 LoRA Caption 生成工具。它把图片去重、质量门槛、视觉聚类、连通性筛选、缺陷检测、人工复核、PixAI 标签清洗和数据集输出串成一条可观察、可审计的流水线。

项目固定使用真实本地模型，不提供演示模式或运行模式切换。DINOv3、Locate Anything 和 PixAI Tagger 都会执行真实推理。

## 核心能力

- 递归扫描 JPG、JPEG、PNG、WebP、BMP 和 TIFF 图片，执行 SHA-256 去重与分辨率过滤。
- 使用 DINOv3 或 PixAI visual embedding 完成相似图片聚类和 medoid 选择。
- 通过 Mutual Top-K、k-core 与最大连通分量筛掉孤立风格簇。
- 用 Locate Anything 检查水印、漫画和拼图，并为失败候选自动重试一次。
- 在 Review 界面中浏览、移除和恢复图片，再用 PixAI 完成标签、分布选样与 Caption 输出。
- 保留筛选事件、`manifest.json`、标签审计和选择报告，方便追踪每张图片的处理结果。

## 快速开始

### Windows 一键启动

1. 安装 Windows 10/11，并确保可以访问 Python 与模型下载源。
2. 检查仓库根目录中的 `.env`；首次运行前需按需设置 `HF_TOKEN`。
3. 双击 `start_services.bat`。
4. 浏览器会自动打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。

启动脚本会检查并安装 `uv`、Python 3.11、模型依赖和模型文件，然后依次启动 Locate Anything、后端与前端。健康的既有服务会直接复用。结束使用时双击 `stop_services.bat`；脚本会在确认进程属于本项目后停止 5173、8000 和 9000 端口上的服务。

### 手动启动

需要 Python 3.11 与 [uv](https://docs.astral.sh/uv/)。

```powershell
uv sync --extra models
uv run python scripts/bootstrap_models.py
uv run python scripts/locate_anything_server.py --host 127.0.0.1 --port 9000
```

另开一个终端启动后端：

```powershell
uv run uvicorn app.main:app --app-dir backend --reload --port 8000
```

再开一个终端启动前端：

```powershell
uv run python frontend/server.py
```

然后访问 [http://127.0.0.1:5173](http://127.0.0.1:5173)。后端 API 默认位于 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

## 工作流程

流水线顺序固定为：

1. SHA-256 去重，再按任务选择的分辨率门槛检查。网页端默认 `≥ 1MP`，也可选择兼容 720p 的 `≥ 921,600` 总像素门槛；横版 `1280×720` 与竖版 `720×1280` 均可通过。
2. 使用 DINOv3 ViT-L/16（默认）或 PixAI Tagger v0.9 原生 visual embedding（实验），两者均输出 1024 维并进行 L2 归一化。
3. Complete-linkage 0.90 聚簇。
4. 为每个簇计算 medoid 与备用候选顺序。
5. 用 medoid embedding 建立 Mutual Top-20 图，边相似度要求 ≥ 0.65。
6. 迭代 3-core，再保留最大连通分量。
7. 只对最大连通分量涉及的簇做 Locate Anything 检查。
8. 每张候选图分别检查水印、漫画/拼图；失败后从原始 0.90 簇中随机选另一张，只重试一次。
9. 将通过的候选图复制到输出目录并写入 `manifest.json`。
10. 用户在 Review 中默认通过全部输出图片，可移出不合适图片；Submit 时设置 LoRA Prefix。
11. `pixai-labs/pixai-tagger-v0.9` 对 Review 通过图片推理一次，保存 general tags，并派生人数、取景和室外状态。
12. 用户设置三组边际目标与最终数量，系统贪心填补分布缺口。
13. 仅为最终选中图片清洗标签、注入 LoRA Prefix，并输出图片与 UTF-8 `.txt` caption。

Locate 阶段提供类似 ComfyUI 的实时节点画布：显示当前 medoid 或备用候选、两类模型请求状态、返回框叠加、最终判定与一次重试分支。预览图使用模型实际检查的处理图压缩生成，检测框与画面保持对齐。

Complete-linkage 与图筛选阶段提供中途“筛选审计”面板。创建视觉筛选任务时可以选择 DINOv3 或实验性的 PixAI Embedding；后续 Complete-linkage、medoid、Mutual Top-20、3-core 和阈值保持一致，便于直接比较模型差异。0.90 页面按簇展示全部有效图片并标记 medoid；每张缩略图叠加它与 medoid 的余弦相似度，簇标题显示簇内最低两两相似度 `MIN`（直接对应 Complete-linkage 0.90），同时明确该步骤只分组、不删除图片。0.65 页面显示 Mutual Top-20 边数、3-core 节点数，以及最大连通分量最终保留/排除的簇数和图片数，并可只查看被排除簇。审计缩略图最长边限制为 96 像素、JPEG quality 38，并按需加载。

输出完成后，前端会显示最终通过图片的 Review 图库，支持缩略图懒加载、点击查看大图、上一张/下一张和键盘方向键浏览。Review 中可以把图片移出最终数据集：输出文件会移动到任务对应的隐藏恢复目录，任务统计和 `manifest.json` 同步更新，并支持立即撤销。图片只能通过当前任务 manifest 中已经复制到输出目录的记录读取，网页不能访问其他本机文件。

Review 中当前展示的图片默认全部通过。用户确认后输入只含字母、数字、下划线或连字符的 LoRA Prefix，再 Submit 进入 PixAI 后续流水线；Submit 后 Review 会锁定，避免标注过程中候选集变化。

也可以在首次启动视觉筛选流水线之前使用“直接运行 PixAI”。该入口递归读取所选文件夹中的受支持图片，不做 SHA 去重、1MP 分辨率检查、DINOv3、聚簇、图筛选或 Locate Anything，随后直接进入同一套 PixAI 标注、边际选样和 Caption 输出。独立模式只读取源图，所有 metadata、训练图片和 Caption 都写入指定输出目录；未指定时自动使用源目录下的 `pixai_dataset_{job_id}`。为了避免混淆，一旦当前网页已经启动过视觉筛选流水线，直接入口会锁定。

PixAI 阶段只保存 `general_tags`，不保存 character tags、copyright tags 或 IP 推断。选样只读取 `people_count`、`framing`、`outdoors` 三项派生字段；前端会展示当前边际分布，并允许设置人数、取景、室外目标比例、目标图片数、caption 阈值和额外 denylist。

Caption 现在按固定规则链生成：标签规范化 → 分层置信度过滤 → denylist → 人数/取景/室内外 `selection_features` 权威覆盖 → alias 合并 → 条件互斥与明确冲突对 → 概念支撑检查 → 已审核 `removable_parents` 精简 → 语义排序与长度裁剪 → 注入 LoRA Prefix → 输出 UTF-8 `.txt`。阈值和 denylist 会按 alias 等价类判断，但直到 selection 注入完成后才真正改成 canonical tag；selection 注入标签同时会继承长度保护。单人图会处理眼色、发色、发长、眼睛/嘴部状态、胸部尺寸、鞋袜、姿势和表情冲突；多人图自动关闭这些人物属性互斥，只保留全局背景、时间和视角规则，避免把不同角色的属性互相删除。冲突分差不足时采用保守弃权，会删除整组而不是随机猜一个标签。

默认 general threshold 为 0.50，抽象高风险标签为 0.65，互斥和冲突分差均为 0.15。软上限由 `.env` 的 `PIXAI_CAPTION_MAX_TAGS` 控制，默认 48；硬上限为 64。LoRA Prefix 和 selection features 注入的人数、取景标签不会因长度被删除。来源、水印、审查状态、站点管理标签和上游已经处理的不良质量标签均在默认 denylist 中；`sketch`、`lineart`、`monochrome`、`greyscale`、`unfinished` 不会默认删除。

每张最终图片会在 `pixai_tags.json` 中保存 `caption_tags` 和 `caption_audit`，所有删除项都会记录 `denylisted`、`selection_override`、`exclusive_loser`、`exclusive_ambiguous`、`pair_conflict_loser`、`pair_conflict_ambiguous`、`redundant_parent`、`missing_support` 或 `over_limit` 等原因。`redundant_parent` 还会记录触发删除的具体子标签。`selection_report.json` 会记录规则文件来源、PixAI general 词表数量、直接父子关系数、运行时祖先闭包关系数、阈值和生效 denylist。

父子精简不再把任意 Danbooru implication 直接当作删除规则。运行时只读取版本化的 `backend/app/pipeline/resources/pixai_parent_rules.json`；当前规则来自 PixAI v0.9 实际 `selected_tags.csv` 的 9,741 条 general 记录（规范化后 9,740 个有效标签），排除了 3,720 条 character tags。全部有效标签先由 `gpt-5.6-sol` 逐项归类，首轮 5,605 条候选关系再由独立的 `gpt-5.6-sol` 逐条二审，得到 5,320 条接受、254 条拒绝和 31 条歧义。只有二审接受的严格父子关系才会与人工 overrides 合并。

生产规则使用 schema v2，只在磁盘中保存经过传递约简的 4,705 条直接 DAG 边；加载时会完成 alias 归一化、环检测，并在内存中计算祖先闭包。所有 254 条 `reject` 和 31 条 `ambiguous` 二审关系都会进入阻止表；即使接受边的多层路径能够重新推导出其中某条关系，运行时也会明确扣除。加上 3 条既有人工保护关系，规则共保存 288 条阻止项，最终只有 6,880 条可用于 `removable_parents` 的运行关系，非 `accept` 二审关系为 0。兼容兄弟标签、不同属性维度、部件、动作和共现关系不会自动删除。规则文件丢失、损坏或 schema 不兼容时，默认给出 warning 并使用空规则继续；设置 `PIXAI_PARENT_RULES_STRICT=true` 可改为严格失败。

规则生成与维护：

```powershell
uv run python backend/scripts/merge_pixai_parent_llm_reviews.py
uv run python backend/scripts/finalize_pixai_parent_llm_validations.py
uv run python backend/scripts/generate_pixai_parent_rules.py
```

首轮合并器要求全部 9,740 个标签精确覆盖且范围不重叠；二审合并器要求每条首轮关系都有且只有一个 `accept`、`reject` 或 `ambiguous` 结论。审查摘要、二审报告、候选项和 proposed overrides 会在本地 resources 目录生成，但默认不纳入 Git；仓库只保留运行时规则与人工 overrides。二审合并器以 GPT 二审为权威输入，不会让旧 `add` 重新引入被拒绝、存疑或未经审查的关系；当前将 5,320 条接受关系传递约简为 4,705 条直接边，移除了 615 条冗余边。生成器会自动发现本机 `deepghs/pixai-tagger-v0.9-onnx` 模型快照中的 `selected_tags.csv`，读取 `pixai_parent_overrides.json`，稳定生成生产规则、审计报告和待检查候选。名称结构分析和未经确认的 active implication 只写入 `pixai_parent_review_candidates.json`，不会自动进入运行时。若已有明确带 `status=active` 的 Danbooru JSON 数组快照，可通过 `--aliases` 和 `--implications` 传入；非 active、缺失状态或无效关系会被忽略。发现未知标签、alias 归一化自环、父子环、被直接阻止的父子边或未约简的 schema v2 关系时会直接失败。

## 模型与环境配置

首次使用前，需要在 Hugging Face 同意 DINOv3 模型条款。模型文件较大，请预留足够的磁盘空间和下载时间。

项目根目录的 `.env` 是固定保留的本地运行配置。仓库中的 `HF_TOKEN` 保持为空；如需令牌，建议在启动终端中临时设置，避免把密钥提交到公开仓库：

```powershell
$env:HF_TOKEN="<your-token>"
```

常用配置：

```dotenv
DINO_MODEL_ID=facebook/dinov3-vitl16-pretrain-lvd1689m
LOCATE_ANYTHING_MODEL_ID=sahilchachra/LocateAnything-3B-AWQ-W4A16
LOCATE_ANYTHING_ENDPOINT=http://127.0.0.1:9000/v1/chat/completions
LOCATE_ANYTHING_MAX_TOKENS=1024
PIXAI_MODEL_ID=pixai-labs/pixai-tagger-v0.9
PIXAI_RUNTIME_MODEL_ID=deepghs/pixai-tagger-v0.9-onnx
PIXAI_CAPTION_THRESHOLD=0.50
PIXAI_CAPTION_MAX_TAGS=48
PIXAI_CAPTION_HARD_MAX_TAGS=64
```

DINOv3 适配器使用 Hugging Face `AutoImageProcessor` 与 `AutoModel`，会校验输出为 1024 维并进行 L2 归一化。PixAI Embedding 直接读取 `pixai-labs/pixai-tagger-v0.9` ONNX 模型自身的 `embedding` 输出，同样校验 1024 维并归一化；它不是把预测标签拼接成向量。PixAI 官方预处理本身就是双线性缩放到 448×448 后归一化。两种视觉基模都会把各自的 448×448 实际输入保存为任务级无损临时 PNG，Locate Anything 直接复用同一张图片；任务成功或失败后都会自动清理临时目录，最终清单和输出仍引用原图。Locate Anything 适配器默认使用可配置的 4bit AWQ W4A16 权重 `sahilchachra/LocateAnything-3B-AWQ-W4A16`；启动脚本会自动检查并下载它。生成上限默认限制为 1024 tokens，以降低长时间生成和 CUDA OOM 风险。若要换成其他量化格式，修改 `LOCATE_ANYTHING_MODEL_ID` 即可。

Locate Anything 适配器默认调用 OpenAI-compatible `/v1/chat/completions`，发送 data URL 图片和 prompt，并解析官方 `<box><x1><y1><x2><y2></box>` 输出；同时兼容自定义服务返回的 `boxes`、`results[].box`、`detections[].bbox`。服务返回坐标不参与通过/不通过判断，只判断 box 数量。

PixAI 使用 `pixai-labs/pixai-tagger-v0.9` 的公开 ONNX 转换仓库 `deepghs/pixai-tagger-v0.9-onnx`，通过 `dghs-imgutils` 本地推理。ONNX Runtime 固定在 CUDA 12 兼容版本，并在创建会话前复用 PyTorch CUDA 12.8 的 CUDA/cuDNN DLL；CUDA 不可用时仍可回退 CPU。

项目内置的无 GUI 服务启动方式：

```powershell
uv run python scripts/locate_anything_server.py --host 127.0.0.1 --port 9000
```

## 项目结构

```text
auto_cat/
├─ backend/
│  ├─ app/                  # FastAPI、任务管理与图像处理流水线
│  └─ scripts/              # PixAI 父子规则生成和审计工具
├─ frontend/                # 无构建步骤的 HTML/CSS/JavaScript 前端
├─ scripts/                 # 模型准备、Locate Anything 服务与停止脚本
├─ tests/                   # 核心算法和 PixAI 规则回归测试
├─ .env                     # 本地运行配置（随项目保留）
├─ pyproject.toml           # Python 依赖与工具配置
├─ start_services.bat       # Windows 一键启动
└─ stop_services.bat        # Windows 一键停止
```

`test_image/`、运行日志、缓存、模型下载和生成的数据集都属于本地实验产物，已在 `.gitignore` 中排除。`.env` 和 `tests/` 中的自动化回归测试会保留在仓库中。

## 开发与验证

安装默认依赖后运行：

```powershell
uv run pytest
uv run ruff check .
```

测试使用临时目录生成数据，不依赖根目录中的 `test_image/`。

## API

- `POST /api/jobs` 创建任务，JSON：`{"source_dir":"...","output_dir":"...","similarity_model":"dinov3|pixai"}`
- `POST /api/pixai/jobs` 跳过视觉筛选并直接创建 PixAI 任务，JSON：`{"source_dir":"...","output_dir":"...","lora_prefix":"artist_style"}`
- `GET /api/folders/select?purpose=source|output` 弹出本机文件夹选择窗口
- `GET /api/jobs` 查看任务列表
- `GET /api/jobs/{job_id}` 查看任务状态和统计
- `GET /api/jobs/{job_id}/events` 通过 SSE 查看实时编排事件
- `GET /api/jobs/{job_id}/audit/thumbnail/{image_id}` 查看筛选审计使用的超低清缩略图
- `GET /api/jobs/{job_id}/manifest` 查看输出清单
- `GET /api/jobs/{job_id}/review/{item_index}` 查看最终输出清单中的通过图片
- `DELETE /api/jobs/{job_id}/review/{item_index}` 将图片移出最终数据集
- `POST /api/jobs/{job_id}/review/{item_index}/restore` 恢复刚移出的图片
- `POST /api/jobs/{job_id}/curation` 提交 Review 并设置 LoRA Prefix
- `GET /api/jobs/{job_id}/curation` 查看 PixAI、选样和 caption 状态
- `GET /api/jobs/{job_id}/curation/image/{item_index}` 安全预览当前 PixAI 候选原图
- `POST /api/jobs/{job_id}/curation/finalize` 提交边际分布与 caption 配置
- `GET /api/health` 健康检查

前端只依赖这些 API，不读取后端文件系统，因此前后端是完全分离的。
