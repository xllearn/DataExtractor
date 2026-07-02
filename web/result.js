const WEB_APP_VERSION = "20260702_workbench";
const params = new URLSearchParams(window.location.search);
const jobId = params.get("job_id") || "";
const POLL_INTERVAL_MS = 1500;
const TERMINAL_STATUSES = new Set(["success", "failed", "cancelled", "archived"]);

let pollTimer = null;
let previewLoaded = false;

const elements = {
  jobIdText: document.querySelector("#jobIdText"),
  statusText: document.querySelector("#statusText"),
  previewMeta: document.querySelector("#previewMeta"),
  previewStatusText: document.querySelector("#previewStatusText"),
  riskText: document.querySelector("#riskText"),
  downloadBtn: document.querySelector("#downloadBtn"),
  cancelBtn: document.querySelector("#cancelBtn"),
  backBtn: document.querySelector("#backBtn"),
  currentTitleText: document.querySelector("#currentTitleText"),
  jobProgressBar: document.querySelector("#jobProgressBar"),
  jobProgressText: document.querySelector("#jobProgressText"),
  jobLogTail: document.querySelector("#jobLogTail"),
  jobSummaryPanel: document.querySelector("#jobSummaryPanel"),
  previewHead: document.querySelector("#previewHead"),
  previewBody: document.querySelector("#previewBody"),
};

function setText(node, value) {
  if (!node) return;
  node.textContent = value === null || value === undefined ? "" : String(value);
}

function setHidden(node, hidden) {
  if (!node) return;
  node.hidden = hidden;
}

function normalizePositiveInt(value, fallback = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) return fallback;
  return Math.floor(parsed);
}

function isTerminalStatus(status) {
  return TERMINAL_STATUSES.has(String(status || "").toLowerCase());
}

function statusLabel(status) {
  const normalized = String(status || "queued").toLowerCase();
  const labels = {
    queued: "排队中",
    running: "运行中",
    success: "成功",
    failed: "失败",
    cancelled: "已取消",
    archived: "已归档",
  };
  return labels[normalized] || normalized;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const text = await response.text();
  let payload = {};
  if (contentType.includes("application/json")) {
    try {
      payload = text ? JSON.parse(text) : {};
    } catch (_error) {
      payload = {detail: "Backend returned non-JSON content in a JSON response"};
    }
  } else {
    payload = {detail: text || response.statusText || "请求失败"};
  }
  if (!response.ok) {
    const error = new Error(String(payload.detail || payload.error || "请求失败"));
    error.status = response.status;
    error.errorType = payload.error_type || "";
    throw error;
  }
  return payload;
}

function renderPreview(payload) {
  elements.previewHead.replaceChildren();
  elements.previewBody.replaceChildren();

  const headers = Array.isArray(payload.headers) ? payload.headers : [];
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  setText(elements.previewMeta, `结果数据 · ${headers.length} 列 · ${rows.length} 行预览`);
  setText(elements.previewStatusText, rows.length ? "预览已加载" : "预览为空");

  const headRow = document.createElement("tr");
  for (const header of headers) {
    const cell = document.createElement("th");
    cell.textContent = header || "";
    headRow.appendChild(cell);
  }
  elements.previewHead.appendChild(headRow);

  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const value of row) {
      const cell = document.createElement("td");
      cell.textContent = value === null || value === undefined ? "" : String(value);
      tr.appendChild(cell);
    }
    elements.previewBody.appendChild(tr);
  }
}

async function loadPreview(url) {
  setText(elements.previewStatusText, "正在读取预览...");
  const payload = await fetchJson(url);
  renderPreview(payload);
  previewLoaded = true;
}

function updateProgress(job) {
  const total = normalizePositiveInt(job.progress_total, 0);
  const current = normalizePositiveInt(job.progress_current, 0);
  let percent = total > 0 ? Math.round((Math.min(current, total) / total) * 100) : 0;
  if (String(job.status || "") === "success") percent = 100;
  elements.jobProgressBar.value = percent;
  setText(elements.jobProgressText, `${current} / ${total || 0}`);
  setText(elements.currentTitleText, `当前文章：${job.current_title || "--"}`);
}

function renderLogLines(lines) {
  const safeLines = Array.isArray(lines) ? lines : [];
  setText(elements.jobLogTail, safeLines.length ? safeLines.join("\n") : "暂无日志");
}

async function loadJobLogs() {
  try {
    const payload = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/logs?tail=120`);
    renderLogLines(payload.lines);
  } catch (error) {
    renderLogLines([`日志读取失败：${error.message}`]);
  }
}

function renderJobSummary(payload) {
  const title = document.createElement("h2");
  title.textContent = "Summary";
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(payload || {}, null, 2);
  elements.jobSummaryPanel.replaceChildren(title, pre);
}

function renderSummaryMessage(message) {
  const title = document.createElement("h2");
  title.textContent = "Summary";
  const paragraph = document.createElement("p");
  paragraph.textContent = message;
  elements.jobSummaryPanel.replaceChildren(title, paragraph);
}

async function loadJobSummary() {
  try {
    const payload = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/summary`);
    renderJobSummary(payload);
  } catch (error) {
    const message = error.status === 404 ? "summary 尚未生成" : `summary 读取失败：${error.message}`;
    renderSummaryMessage(message);
  }
}

function stopPolling() {
  if (pollTimer) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function updateStatusClass(status) {
  elements.statusText.className = "result-badge";
  if (String(status || "") === "success") {
    elements.statusText.className = "result-badge result-badge-success";
  }
  if (String(status || "") === "failed" || String(status || "") === "cancelled") {
    elements.statusText.className = "result-badge error";
  }
}

async function renderJob(job) {
  setText(elements.statusText, job.message || statusLabel(job.status));
  updateStatusClass(job.status);
  updateProgress(job);
  elements.cancelBtn.disabled = isTerminalStatus(job.status);
  elements.downloadBtn.href = `/api/jobs/${encodeURIComponent(jobId)}/download`;
  setHidden(elements.downloadBtn, String(job.status || "") !== "success");

  if (!job.ocr_available) {
    setText(elements.riskText, "本次未使用 OCR，图片表格内容可能缺失。");
  }
  if (job.external_ocr_used) {
    setText(elements.riskText, "使用了外部 OCR 文本");
  }

  if (String(job.status || "") === "success" && !previewLoaded) {
    try {
      await loadPreview(job.preview_url || `/api/jobs/${encodeURIComponent(jobId)}/preview`);
    } catch (error) {
      setText(elements.previewStatusText, `预览读取失败：${error.message}`);
    }
  }
}

async function pollJob() {
  if (!jobId) {
    setText(elements.statusText, "缺少 job_id");
    elements.statusText.className = "result-badge error";
    elements.cancelBtn.disabled = true;
    return;
  }
  setText(elements.jobIdText, `job_id: ${jobId}`);
  if (!jobId.startsWith("job_")) {
    setText(elements.statusText, "任务编号格式不正确，请返回列表重新生成。");
    elements.statusText.className = "result-badge error";
    elements.cancelBtn.disabled = true;
    return;
  }
  try {
    const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
    await renderJob(job);
    await loadJobLogs();
    if (isTerminalStatus(job.status)) {
      stopPolling();
      await loadJobSummary();
      return;
    }
    pollTimer = window.setTimeout(pollJob, POLL_INTERVAL_MS);
  } catch (error) {
    stopPolling();
    if (error.status === 404 || error.errorType === "JobNotFound") {
      setText(elements.statusText, "任务不存在或已过期，请返回列表重新生成。");
    } else {
      setText(elements.statusText, error.message);
    }
    elements.statusText.className = "result-badge error";
    elements.cancelBtn.disabled = true;
  }
}

async function cancelJob() {
  if (!jobId || elements.cancelBtn.disabled) return;
  try {
    elements.cancelBtn.disabled = true;
    const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {method: "POST"});
    await renderJob(job);
    await loadJobLogs();
    await loadJobSummary();
    stopPolling();
  } catch (error) {
    setText(elements.statusText, error.message);
    elements.statusText.className = "result-badge error";
    elements.cancelBtn.disabled = false;
  }
}

if (elements.backBtn) {
  elements.backBtn.addEventListener("click", () => {
    window.location.href = "/";
  });
}

elements.cancelBtn.addEventListener("click", cancelJob);

renderSummaryMessage("暂无 summary");
pollJob();
