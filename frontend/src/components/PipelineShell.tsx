import logoUrl from "../../loraforge-logo.png";

export default function PipelineShell() {
  return (
    <>
    <div id="canvas-boot-screen" className="canvas-boot-screen" aria-hidden="true">
      <img src={logoUrl} alt="" />
      <div>
        <strong>LoRAForge</strong>
        <span>正在准备无限画布</span>
      </div>
      <i></i>
    </div>
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">LORAFORGE / PIPELINE ORCHESTRATOR</div>
          <h1>图片数据集筛选台</h1>
          <p>把去重、聚类、图筛选与视觉质检串成一条可观察的流水线。</p>
        </div>
        <div className="topbar-actions">
          <nav className="language-switch" aria-label="语言">
            <button type="button" data-language="zh">中文</button>
            <button type="button" data-language="en">English</button>
          </nav>
          <div id="health-badge" className="status-pill pending">正在连接后端</div>
        </div>
      </header>

      <main>
        <section className="control-panel glass-panel">
          <div className="section-title">
            <div>
              <span className="kicker">01 / INPUT</span>
              <h2>创建一次筛选任务</h2>
            </div>
            <span className="mode-note">固定使用本地真实模型</span>
          </div>
          <form id="job-form" className="job-form">
            <label className="folder-field">
              <span>图片文件夹</span>
              <div className="folder-picker">
                <input id="source-dir" required readOnly placeholder="请选择需要筛选的图片文件夹" />
                <button type="button" className="folder-select-button" data-folder-purpose="source" data-folder-target="source-dir">选择文件夹</button>
              </div>
            </label>
            <label className="folder-field">
              <span>输出文件夹（可选）</span>
              <div className="folder-picker with-clear">
                <input id="output-dir" readOnly placeholder="不选择则输出到源目录下" />
                <button type="button" className="folder-select-button" data-folder-purpose="output" data-folder-target="output-dir">选择文件夹</button>
                <button id="clear-output-dir" type="button" className="folder-clear-button" disabled>清除</button>
              </div>
            </label>
            <label className="small-field similarity-model-field">
              <span>视觉相似度模型</span>
              <select id="similarity-model" defaultValue="dinov3">
                <option value="dinov3">DINOv3（默认）</option>
                <option value="pixai">PixAI Embedding（实验）</option>
              </select>
            </label>
            <label className="small-field resolution-threshold-field">
              <span>图片准入门槛</span>
              <select id="minimum-pixels" defaultValue="1000000">
                <option value="1000000">标准 · ≥ 1MP</option>
                <option value="921600">兼容 720p · ≥ 1280×720</option>
              </select>
            </label>
            <label className="small-field complete-linkage-field">
              <span>聚簇相似度</span>
              <input
                id="complete-linkage-similarity"
                type="number"
                min="0"
                max="1"
                step="0.01"
                defaultValue="0.90"
                inputMode="decimal"
                required
              />
              <small>Complete-linkage 簇内最低相似度</small>
            </label>
            <label className="small-field graph-similarity-field">
              <span>图筛选相似度</span>
              <input
                id="graph-similarity"
                type="number"
                min="0"
                max="1"
                step="0.01"
                defaultValue="0.65"
                inputMode="decimal"
                required
              />
              <small>建立 Mutual Top-20 边的最低相似度</small>
            </label>
            <button id="start-button" type="submit">启动流水线 <span>→</span></button>
          </form>
          <form id="standalone-pixai-form" className="standalone-pixai">
            <div className="standalone-pixai-copy">
              <span className="kicker">DIRECT PIXAI</span>
              <strong>跳过视觉筛选，直接标注所选文件夹</strong>
              <small id="standalone-pixai-state">仅在当前页面尚未启动上方流水线时可用；不会执行 SHA、视觉 Embedding、图筛选或 Locate。</small>
            </div>
            <label>
              <span>LoRA Prefix</span>
              <input
                id="standalone-lora-prefix"
                required
                maxLength={64}
                pattern="[A-Za-z0-9][A-Za-z0-9_-]*"
                autoComplete="off"
                placeholder="例如 artist_style"
              />
            </label>
            <button id="standalone-pixai-button" type="submit" disabled>直接运行 PixAI <span>→</span></button>
          </form>
          <div className="rule-strip">
            <span id="rule-min-resolution">≥ 1MP</span><i>→</i><span id="rule-embedding-model">DINOv3 1024d</span><i>→</i><span id="rule-cluster-threshold">0.90 cluster</span><i>→</i><span id="rule-graph-threshold">0.65 Mutual Top-20</span><i>→</i><span>3-core</span><i>→</i><span>Locate Anything</span>
          </div>
        </section>

        <section className="hero-grid">
          <div className="pipeline-panel glass-panel">
            <div className="section-title compact">
              <div><span className="kicker">02 / LIVE FLOW</span><h2>过程预览</h2></div>
              <span id="job-status" className="status-pill pending">等待任务</span>
            </div>
            <div id="pipeline-canvas" className="pipeline-canvas">
              <div className="pipeline-node" data-stage="scan"><span className="node-index">01</span><strong>去重 & 分辨率</strong><small id="pipeline-min-resolution">SHA-256 · ≥ 1MP</small></div>
              <div className="flow-arrow">↘</div>
              <div className="pipeline-node" data-stage="embedding"><span className="node-index">02</span><strong id="pipeline-embedding-title">DINOv3 Embedding</strong><small id="pipeline-embedding-detail">ViT-L/16 · 1024d</small></div>
              <div className="flow-arrow">↘</div>
              <div className="pipeline-node" data-stage="clustering"><span className="node-index">03</span><strong>Complete-linkage</strong><small id="pipeline-cluster-threshold">similarity 0.90</small></div>
              <div className="flow-arrow">↘</div>
              <div className="pipeline-node" data-stage="graph"><span className="node-index">04</span><strong>Graph Filter</strong><small>Mutual Top-20 · 3-core</small></div>
              <div className="flow-arrow">↘</div>
              <div className="pipeline-node" data-stage="locate"><span className="node-index">05</span><strong>Locate Anything</strong><small>水印 · 漫画 · 拼图</small></div>
              <div className="flow-arrow">↘</div>
              <div className="pipeline-node" data-stage="output"><span className="node-index">06</span><strong>输出数据集</strong><small>manifest.json</small></div>
            </div>
            <div className="progress-wrap"><div id="progress-bar" className="progress-bar"></div></div>
            <div className="progress-meta"><span id="progress-message">准备就绪</span><span id="progress-value">0%</span></div>
          </div>

          <aside className="stats-panel glass-panel">
            <div className="section-title compact"><div><span className="kicker">03 / SIGNALS</span><h2>实时指标</h2></div></div>
            <div className="metrics-grid">
              <div className="metric"><span>发现文件</span><strong id="metric-files">—</strong></div>
              <div className="metric"><span>去重后</span><strong id="metric-unique">—</strong></div>
              <div className="metric"><span id="metric-valid-label">有效图片（≥1MP）</span><strong id="metric-valid">—</strong></div>
              <div className="metric"><span id="metric-clusters-label">0.90 簇</span><strong id="metric-clusters">—</strong></div>
              <div className="metric"><span>检查簇</span><strong id="metric-checked">—</strong></div>
              <div className="metric accent"><span>输出图片</span><strong id="metric-output">—</strong></div>
            </div>
            <div className="legend"><span className="dot green"></span>通过 <span className="dot amber"></span>重试 <span className="dot red"></span>放弃</div>
          </aside>
        </section>

        <section id="audit-panel" className="audit-panel glass-panel">
          <div className="section-title compact audit-heading">
            <div>
              <span className="kicker">04 / FILTER AUDIT</span>
              <h2>分簇与图筛选预览</h2>
              <p id="audit-description">流水线运行到 0.90 聚簇后，将在这里显示超低清缩略图。</p>
            </div>
            <span id="audit-status" className="status-pill pending">等待聚簇</span>
          </div>

          <div className="audit-toolbar">
            <div className="audit-tabs" role="tablist" aria-label="筛选阶段">
              <button id="audit-clustering-tab" className="audit-tab active" type="button" data-audit-view="clustering">0.90 聚簇</button>
              <button id="audit-graph-tab" className="audit-tab" type="button" data-audit-view="graph">0.65 图筛选</button>
            </div>
            <div id="audit-filters" className="audit-filters" aria-label="簇状态筛选">
              <button className="active" type="button" data-audit-filter="all">全部</button>
              <button type="button" data-audit-filter="kept">保留</button>
              <button type="button" data-audit-filter="excluded">排除</button>
            </div>
          </div>

          <div className="audit-metrics">
            <div><span id="audit-metric-a-label">有效图片</span><strong id="audit-metric-a">—</strong></div>
            <div><span id="audit-metric-b-label">0.90 簇</span><strong id="audit-metric-b">—</strong></div>
            <div><span id="audit-metric-c-label">保留图片</span><strong id="audit-metric-c">—</strong></div>
            <div className="audit-excluded-metric"><span id="audit-metric-d-label">排除图片</span><strong id="audit-metric-d">—</strong></div>
          </div>

          <div id="audit-note" className="audit-note">
            0.90 只负责把图片分组，不会在此处删除图片。
          </div>
          <div id="audit-clusters" className="audit-clusters">
            <div className="audit-empty">等待 Complete-linkage 聚簇结果…</div>
          </div>
        </section>

        <section id="locate-flow-panel" className="locate-flow-panel glass-panel">
          <div className="section-title compact locate-flow-heading">
            <div>
              <span className="kicker">05 / LOCATE LIVE GRAPH</span>
              <h2>Locate Anything 检测流</h2>
            </div>
            <div className="locate-run-meta">
              <span id="locate-cluster-progress">尚未开始</span>
              <span id="locate-live-status" className="status-pill pending">等待 Locate 阶段</span>
            </div>
          </div>

          <div className="locate-canvas">
            <div className="locate-graph">
              <article id="locate-candidate-node" className="locate-node candidate-node pending">
                <header>
                  <span className="node-port input-port"></span>
                  <div><small>IMAGE INPUT</small><strong>当前候选</strong></div>
                  <span className="node-port output-port"></span>
                </header>
                <div id="locate-image-stage" className="locate-image-stage empty">
                  <div id="locate-image-surface" className="locate-image-surface">
                    <img id="locate-preview-image" alt="Locate Anything 当前检测图片" />
                    <div id="locate-box-layer" className="locate-box-layer"></div>
                  </div>
                  <span id="locate-image-empty">等待候选图片</span>
                </div>
                <div className="locate-node-details">
                  <span id="locate-filename">—</span>
                  <span id="locate-attempt">MEDOID / ATTEMPT 1</span>
                </div>
              </article>

              <div id="locate-wire-input" className="locate-connector"><span></span></div>

              <div className="locate-check-stack">
                <article id="locate-watermark-node" className="locate-node check-node pending">
                  <header>
                    <span className="node-port input-port"></span>
                    <div><small>PROMPT A</small><strong>水印检查</strong></div>
                    <span className="node-port output-port"></span>
                  </header>
                  <p>只要返回检测框，即标记为 not meet</p>
                  <div className="node-readout"><span id="locate-watermark-state">等待输入</span><strong id="locate-watermark-count">—</strong></div>
                </article>

                <article id="locate-comic-node" className="locate-node check-node pending">
                  <header>
                    <span className="node-port input-port"></span>
                    <div><small>PROMPT B</small><strong>漫画 / 拼图检查</strong></div>
                    <span className="node-port output-port"></span>
                  </header>
                  <p>返回两个及以上检测框，即标记为 not meet</p>
                  <div className="node-readout"><span id="locate-comic-state">等待输入</span><strong id="locate-comic-count">—</strong></div>
                </article>
              </div>

              <div id="locate-wire-decision" className="locate-connector"><span></span></div>

              <article id="locate-decision-node" className="locate-node decision-node pending">
                <header>
                  <span className="node-port input-port"></span>
                  <div><small>BOOLEAN GATE</small><strong>候选判定</strong></div>
                  <span className="node-port output-port"></span>
                </header>
                <div id="locate-decision-icon" className="decision-icon">?</div>
                <strong id="locate-decision-state">等待两次检测</strong>
                <small id="locate-decision-reason">watermark = 0 · comic ≤ 1</small>
              </article>

              <div id="locate-wire-retry" className="locate-connector"><span></span></div>

              <article id="locate-retry-node" className="locate-node retry-node pending">
                <header>
                  <span className="node-port input-port"></span>
                  <div><small>FALLBACK BRANCH</small><strong>簇内备用候选</strong></div>
                  <span className="node-port output-port"></span>
                </header>
                <div className="retry-branch-mark">↻</div>
                <strong id="locate-retry-state">首次不通过时触发</strong>
                <small id="locate-retry-file">仅重试一次</small>
              </article>
            </div>
          </div>

          <div className="locate-trace">
            <span className="trace-label">RECENT RUNS</span>
            <div id="locate-recent-runs" className="locate-recent-runs">
              <span className="trace-empty">检测结果会依次出现在这里</span>
            </div>
            <div className="box-legend">
              <span><i className="watermark-box-color"></i>水印框</span>
              <span><i className="comic-box-color"></i>漫画 / 拼图框</span>
            </div>
          </div>
        </section>

        <section className="bottom-grid">
          <div className="log-panel glass-panel">
            <div className="section-title compact"><div><span className="kicker">06 / EVENT STREAM</span><h2>编排日志</h2></div><button id="clear-log" className="ghost-button">清空</button></div>
            <div id="event-log" className="event-log"><div className="empty-state">启动任务后，这里会实时显示每个阶段的事件。</div></div>
          </div>
          <div className="result-panel glass-panel">
            <div className="section-title compact"><div><span className="kicker">07 / OUTPUT</span><h2>候选结果</h2></div><span id="result-count" className="count-badge">0</span></div>
            <div className="table-wrap"><table><thead><tr><th>状态</th><th>候选图</th><th>簇</th><th>方式</th><th>原因</th></tr></thead><tbody id="result-body"><tr><td colSpan={5} className="empty-state">暂无结果</td></tr></tbody></table></div>
          </div>
        </section>

        <section id="review-panel" className="review-panel glass-panel" hidden>
          <div className="section-title compact review-heading">
            <div>
              <span className="kicker">08 / DATASET REVIEW</span>
              <h2>最终数据集预览</h2>
              <p id="review-summary">任务完成后展示所有通过的图片</p>
            </div>
            <div className="review-count-wrap">
              <strong id="review-count">0</strong>
              <span>IMAGES PASSED</span>
            </div>
          </div>
          <div id="review-notice" className="review-notice" hidden>
            <span id="review-notice-text">图片已移出最终数据集</span>
            <button id="review-undo" type="button">撤销</button>
          </div>
          <div className="review-submit-bar">
            <div className="review-submit-state">
              <span className="review-pass-mark">✓</span>
              <div>
                <strong>当前展示图片默认通过</strong>
                <span>不需要逐张确认；只需移出不合适的图片</span>
              </div>
            </div>
            <form id="curation-submit-form" className="curation-submit-form">
              <label>
                <span>LoRA Prefix</span>
                <input
                  id="lora-prefix"
                  required
                  maxLength={64}
                  pattern="[A-Za-z0-9][A-Za-z0-9_-]*"
                  autoComplete="off"
                  placeholder="例如 artist_style"
                />
              </label>
              <button id="curation-submit" type="submit">Submit → PixAI</button>
            </form>
          </div>
          <div id="review-pagination" className="review-pagination" hidden>
            <span id="review-page-range">1–1 / 1</span>
            <div>
              <button id="review-page-previous" type="button" aria-label="上一页">‹</button>
              <label>
                <span>PAGE</span>
                <input id="review-page-input" type="number" min="1" defaultValue="1" aria-label="Review 页码" />
                <small>/ <strong id="review-page-total">1</strong></small>
              </label>
              <button id="review-page-next" type="button" aria-label="下一页">›</button>
            </div>
          </div>
          <div id="review-gallery" className="review-gallery"></div>
        </section>

        <section id="curation-panel" className="curation-panel glass-panel" hidden>
          <div className="section-title compact curation-heading">
            <div>
              <span className="kicker">09 / PIXAI CURATION</span>
              <h2>标签、边际选样与 Caption</h2>
              <p id="curation-description">
                PixAI 只推理一次；选样只读取人数、取景和室外状态。
              </p>
            </div>
            <span id="curation-status" className="status-pill pending">等待 Submit</span>
          </div>

          <div className="curation-flow">
            <article className="curation-step" data-curation-stage="pixai">
              <span>01</span>
              <div><strong>PixAI Tagger</strong><small>general tags · 448×448</small></div>
            </article>
            <i>→</i>
            <article className="curation-step" data-curation-stage="selection">
              <span>02</span>
              <div><strong>边际分布选样</strong><small>人数 · 取景 · 室外</small></div>
            </article>
            <i>→</i>
            <article className="curation-step" data-curation-stage="caption">
              <span>03</span>
              <div><strong>训练集输出</strong><small>图片 + UTF-8 caption</small></div>
            </article>
          </div>

          <div className="curation-progress">
            <div className="progress-wrap"><div id="curation-progress-bar" className="progress-bar"></div></div>
            <div className="progress-meta">
              <span id="curation-progress-message">等待进入 PixAI 阶段</span>
              <span id="curation-progress-value">0%</span>
            </div>
          </div>

          <div id="curation-live" className="curation-live" hidden>
            <div className="curation-live-preview">
              <img id="curation-live-image" alt="当前 PixAI 标注图片" />
            </div>
            <div className="curation-live-data">
              <span className="eyebrow">CURRENT INFERENCE</span>
              <strong id="curation-live-name">—</strong>
              <div id="curation-live-features" className="curation-feature-pills"></div>
              <div id="curation-live-tags" className="curation-tag-list"></div>
            </div>
          </div>

          <div id="curation-config" className="curation-config" hidden>
            <div className="curation-distribution-panel">
              <div className="curation-subheading">
                <div>
                  <span className="eyebrow">CURRENT POOL</span>
                  <h3>PixAI 派生分布</h3>
                </div>
                <strong id="curation-tagged-count">0 IMAGES</strong>
              </div>
              <div id="curation-distributions" className="curation-distributions"></div>
            </div>

            <form id="curation-finalize-form" className="curation-target-form">
              <div className="curation-subheading">
                <div>
                  <span className="eyebrow">TARGET MARGINALS</span>
                  <h3>最终训练集配置</h3>
                </div>
                <span>各组会在后端自动归一化</span>
              </div>

              <div className="curation-form-grid">
                <label className="curation-size-field">
                  <span>目标图片数</span>
                  <input id="curation-target-size" type="number" min="1" max="10000" required />
                </label>
                <fieldset>
                  <legend>人数比例</legend>
                  <label><span>1 人</span><input id="target-people-1" type="number" min="0" step="1" defaultValue="85" /></label>
                  <label><span>2 人</span><input id="target-people-2" type="number" min="0" step="1" defaultValue="12" /></label>
                  <label><span>3+ 人</span><input id="target-people-3" type="number" min="0" step="1" defaultValue="3" /></label>
                </fieldset>
                <fieldset>
                  <legend>取景比例</legend>
                  <label><span>全身</span><input id="target-framing-full" type="number" min="0" step="1" defaultValue="30" /></label>
                  <label><span>半身</span><input id="target-framing-half" type="number" min="0" step="1" defaultValue="50" /></label>
                  <label><span>头像</span><input id="target-framing-head" type="number" min="0" step="1" defaultValue="20" /></label>
                </fieldset>
                <fieldset>
                  <legend>室外比例</legend>
                  <label><span>室外</span><input id="target-outdoors-true" type="number" min="0" step="1" defaultValue="40" /></label>
                  <label><span>非室外</span><input id="target-outdoors-false" type="number" min="0" step="1" defaultValue="60" /></label>
                </fieldset>
              </div>

              <div className="curation-caption-config">
                <label>
                  <span>Caption 标签阈值</span>
                  <input id="caption-threshold" type="number" min="0.05" max="0.95" step="0.05" defaultValue="0.50" />
                </label>
                <div className="caption-env-setting">
                  <span>Caption 最多标签数（含 Prefix）</span>
                  <strong id="caption-max-tags">48 · .env</strong>
                </div>
                <label>
                  <span>额外 Denylist（逗号或换行分隔）</span>
                  <textarea id="caption-denylist" rows={3} placeholder="例如 lowres, blurry"></textarea>
                </label>
                <button id="curation-finalize" type="submit">生成训练图片与 Caption</button>
              </div>
            </form>
          </div>

          <div id="curation-completed" className="curation-completed" hidden>
            <div>
              <span className="curation-complete-mark">✓</span>
              <div>
                <strong id="curation-completed-title">训练数据集已生成</strong>
                <span id="curation-output-path">—</span>
              </div>
            </div>
            <div id="curation-selected-gallery" className="curation-selected-gallery"></div>
          </div>
        </section>
      </main>
      <footer>LoRAForge / Visual Embedding → Graph Filter → Locate Anything → Review → PixAI → Caption</footer>
    </div>

    <div id="review-lightbox" className="review-lightbox" role="dialog" aria-modal="true" aria-label="最终数据集图片查看器" hidden>
      <button id="review-close" className="review-close" type="button" aria-label="关闭大图">×</button>
      <button id="review-previous" className="review-nav review-previous" type="button" aria-label="上一张图片">‹</button>
      <figure className="review-lightbox-content">
        <div className="review-full-image-wrap">
          <img id="review-full-image" alt="" />
          <span id="review-image-position" className="review-image-position">1 / 1</span>
        </div>
        <figcaption>
          <div className="review-image-info">
            <strong id="review-image-name">—</strong>
            <span id="review-image-meta">—</span>
          </div>
          <button id="review-remove" className="review-remove" type="button">移出最终数据集</button>
        </figcaption>
      </figure>
      <button id="review-next" className="review-nav review-next" type="button" aria-label="下一张图片">›</button>
    </div>

    <div
      id="review-remove-dialog"
      className="review-remove-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="review-remove-dialog-title"
      hidden
    >
      <section className="review-remove-dialog-card">
        <div className="review-remove-dialog-icon" aria-hidden="true">
          <span>✓</span>
          <i>−</i>
        </div>
        <div className="review-remove-dialog-copy">
          <small>REVIEW / QUICK REMOVE</small>
          <h2 id="review-remove-dialog-title">移出这张图片？</h2>
          <strong id="review-remove-dialog-filename">—</strong>
          <p>图片会移入可恢复区，可以立即撤销。</p>
          <p className="review-remove-dialog-once">此提示只出现一次；以后点击对勾将直接移出。</p>
        </div>
        <footer>
          <button id="review-remove-dialog-cancel" type="button">暂不移出</button>
          <button id="review-remove-dialog-confirm" type="button">移出图片</button>
        </footer>
      </section>
    </div>

    </>
  );
}
