const selectedIds = new Set();
const WEB_APP_VERSION = "20260702_workbench";
const POLL_INTERVAL_MS = 1500;
const TERMINAL_STATUSES = new Set(["success", "failed", "cancelled", "archived"]);

const elements = {
  configStatus: document.querySelector("#configStatus"),
  databaseChip: document.querySelector("#databaseChip"),
  llmChip: document.querySelector("#llmChip"),
  ocrChip: document.querySelector("#ocrChip"),
  databaseStatusText: document.querySelector("#databaseStatusText"),
  llmStatusText: document.querySelector("#llmStatusText"),
  ocrStatusText: document.querySelector("#ocrStatusText"),
  versionStatusText: document.querySelector("#versionStatusText"),
  refreshBtn: document.querySelector("#refreshBtn"),
  keywordInput: document.querySelector("#keywordInput"),
  searchBtn: document.querySelector("#searchBtn"),
  modeMergeInput: document.querySelector("#modeMergeInput"),
  modeSingleInput: document.querySelector("#modeSingleInput"),
  noOcrInput: document.querySelector("#noOcrInput"),
  noLlmInput: document.querySelector("#noLlmInput"),
  promptVersionInput: document.querySelector("#promptVersionInput"),
  externalOcrInput: document.querySelector("#externalOcrInput"),
  extractBtn: document.querySelector("#extractBtn"),
  selectionStatus: document.querySelector("#selectionStatus"),
  jobStatus: document.querySelector("#jobStatus"),
  ocrWarning: document.querySelector("#ocrWarning"),
  clearSelectionBtn: document.querySelector("#clearSelectionBtn"),
  selectPageInput: document.querySelector("#selectPageInput"),
  articleBody: document.querySelector("#articleBody"),
  prevPageBtn: document.querySelector("#prevPageBtn"),
  nextPageBtn: document.querySelector("#nextPageBtn"),
  pageStatus: document.querySelector("#pageStatus"),
  pageSizeSelect: document.querySelector("#pageSizeSelect"),
  totalStatus: document.querySelector("#totalStatus"),
  currentJobPanel: document.querySelector("#currentJobPanel"),
  currentJobIdText: document.querySelector("#currentJobIdText"),
  currentJobStatusText: document.querySelector("#currentJobStatusText"),
  currentTitleText: document.querySelector("#currentTitleText"),
  jobProgressBar: document.querySelector("#jobProgressBar"),
  jobProgressText: document.querySelector("#jobProgressText"),
  jobLogTail: document.querySelector("#jobLogTail"),
  jobSummaryPanel: document.querySelector("#jobSummaryPanel"),
  jobDownloadLink: document.querySelector("#jobDownloadLink"),
  jobPreviewLink: document.querySelector("#jobPreviewLink"),
  jobSummaryBtn: document.querySelector("#jobSummaryBtn"),
  jobCancelBtn: document.querySelector("#jobCancelBtn"),
  jobRefreshBtn: document.querySelector("#jobRefreshBtn"),
  historyRefreshBtn: document.querySelector("#historyRefreshBtn"),
  jobHistoryBody: document.querySelector("#jobHistoryBody"),
};

const state = {
  safeToQuery: false,
  ocrAvailable: false,
  loadingArticles: false,
  extracting: false,
  currentPage: 1,
  pageSize: Number(elements.pageSizeSelect.value || 20),
  totalItems: 0,
  totalPages: 0,
  currentJobId: "",
  currentResultPage: "",
  pollTimer: null,
};

function setText(node, value) {
  if (!node) return;
  node.textContent = value === null || value === undefined ? "" : String(value);
}

function setHidden(node, hidden) {
  if (!node) return;
  node.hidden = hidden;
}

function setStatus(text, isError = false) {
  setText(elements.jobStatus, text || "");
  elements.jobStatus.className = isError ? "error" : "";
}

function setStatusChip(chip, textNode, enabled, readyText = "已配置", missingText = "未配置") {
  if (!chip || !textNode) return;
  textNode.textContent = enabled ? readyText : missingText;
  chip.classList.remove("status-chip-pending", "status-chip-ok", "status-chip-warn");
  chip.classList.add(enabled ? "status-chip-ok" : "status-chip-warn");
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

function getSelectedMode() {
  return elements.modeSingleInput && elements.modeSingleInput.checked ? "single" : "merge";
}

function updateSelection() {
  setText(elements.selectionStatus, `已选择 ${selectedIds.size} 条`);
  elements.clearSelectionBtn.disabled = selectedIds.size === 0;
  setQueryEnabled(state.safeToQuery);
}

function setQueryEnabled(enabled) {
  const canQuery = Boolean(enabled);
  elements.searchBtn.disabled = !canQuery || state.loadingArticles;
  elements.extractBtn.disabled = !canQuery || state.extracting || selectedIds.size === 0;
  elements.selectPageInput.disabled = !canQuery;
  elements.prevPageBtn.disabled = !canQuery || state.loadingArticles || state.currentPage <= 1;
  elements.nextPageBtn.disabled = !canQuery || state.loadingArticles || state.currentPage >= state.totalPages;
  elements.pageSizeSelect.disabled = !canQuery || state.loadingArticles;
  elements.modeMergeInput.disabled = state.extracting;
  elements.modeSingleInput.disabled = state.extracting;
  if (state.ocrAvailable) elements.noOcrInput.disabled = state.extracting;
  elements.noLlmInput.disabled = state.extracting;
  elements.promptVersionInput.disabled = state.extracting;
}

function setEmptyRow(message) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = 6;
  cell.className = "empty";
  cell.textContent = message;
  row.appendChild(cell);
  elements.articleBody.replaceChildren(row);
}

async function readJsonResponse(response) {
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

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  return readJsonResponse(response);
}

function isSafeHttpUrl(value) {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch (_error) {
    return false;
  }
}

function appendTextCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = value || "";
  row.appendChild(cell);
}

function appendSourceCell(row, value) {
  const cell = document.createElement("td");
  if (isSafeHttpUrl(value)) {
    const link = document.createElement("a");
    link.href = value;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.className = "source-link";
    link.textContent = "打开";
    cell.appendChild(link);
  } else {
    cell.textContent = value || "";
  }
  row.appendChild(cell);
}

function normalizePagination(payload = {}, itemCount = 0, requestedPage = state.currentPage) {
  const pageSize = Math.max(1, normalizePositiveInt(payload.page_size || payload.limit, state.pageSize || 20));
  const requested = Math.max(1, normalizePositiveInt(requestedPage, 1));
  const offset = normalizePositiveInt(payload.offset, (requested - 1) * pageSize);
  const minimumTotal = itemCount ? offset + itemCount : 0;
  const total = Math.max(normalizePositiveInt(payload.total, itemCount), minimumTotal);
  const computedTotalPages = total ? Math.ceil(total / pageSize) : 0;
  const totalPages = total ? Math.max(1, normalizePositiveInt(payload.total_pages, computedTotalPages)) : 0;
  let page = normalizePositiveInt(payload.page, offset ? Math.floor(offset / pageSize) + 1 : requested);
  if (totalPages) {
    page = Math.min(Math.max(1, page), totalPages);
  } else {
    page = 0;
  }
  return {total, totalPages, page, pageSize};
}

function updatePagination(payload, itemCount = 0, requestedPage = state.currentPage) {
  const pagination = normalizePagination(payload, itemCount, requestedPage);
  state.totalItems = pagination.total;
  state.totalPages = pagination.totalPages;
  state.currentPage = pagination.page;
  state.pageSize = pagination.pageSize;
  setText(elements.pageStatus, `第 ${state.totalPages ? state.currentPage : 0} / ${state.totalPages} 页`);
  setText(elements.totalStatus, `总计 ${state.totalItems} 条`);
  elements.selectPageInput.checked = false;
  setQueryEnabled(state.safeToQuery);
}

async function loadStatus() {
  const status = await fetchJson("/api/config/status");
  state.safeToQuery = Boolean(status.safe_to_query);
  state.ocrAvailable = Boolean(status.ocr_available);
  const databaseLabel = status.database_configured ? "已配置" : "未配置";
  const llmLabel = status.llm_configured ? "已配置" : "未配置";
  const ocrLabel = status.ocr_available ? "可用" : "不可用";
  setStatusChip(elements.databaseChip, elements.databaseStatusText, status.database_configured, databaseLabel, databaseLabel);
  setStatusChip(elements.llmChip, elements.llmStatusText, status.llm_configured, llmLabel, llmLabel);
  setStatusChip(elements.ocrChip, elements.ocrStatusText, status.ocr_available, ocrLabel, ocrLabel);
  setText(elements.configStatus, state.safeToQuery ? "可查询" : "未就绪");
  setText(elements.versionStatusText, WEB_APP_VERSION);

  if (!state.ocrAvailable) {
    elements.noOcrInput.checked = true;
    elements.noOcrInput.disabled = true;
    setText(elements.ocrWarning, "OCR 不可用，图片型表格可能无法抽取。请安装 OCR 依赖或提供外部 OCR 文本。");
  } else {
    elements.noOcrInput.checked = false;
    elements.noOcrInput.disabled = false;
    setText(elements.ocrWarning, "OCR 可用，有图片时将自动按低置信度策略使用 OCR");
  }
  setQueryEnabled(state.safeToQuery);

  if (!state.safeToQuery) {
    selectedIds.clear();
    elements.selectPageInput.checked = false;
    updateSelection();
    updatePagination({total: 0, total_pages: 0, page: 0, page_size: state.pageSize}, 0, 0);
    setEmptyRow("暂无数据，数据库未配置或查询失败");
    setStatus(status.database_status_reason || "数据库未配置，请确认服务启动配置后重试", true);
  } else {
    setStatus("");
  }
  return status;
}

function renderArticles(items) {
  elements.articleBody.replaceChildren();
  if (!items || items.length === 0) {
    setEmptyRow("暂无匹配数据");
    updateSelection();
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");
    const selectCell = document.createElement("td");
    const checkbox = document.createElement("input");
    const id = String(item.id || "");
    checkbox.type = "checkbox";
    checkbox.dataset.id = id;
    checkbox.checked = selectedIds.has(id);
    checkbox.disabled = !state.safeToQuery;
    selectCell.appendChild(checkbox);
    row.appendChild(selectCell);

    appendTextCell(row, item.title);
    appendTextCell(row, item.region);
    appendTextCell(row, item.insurance_type);
    appendTextCell(row, item.audit_time);
    appendSourceCell(row, item.source_url);
    elements.articleBody.appendChild(row);
  }
  updateSelection();
}

async function searchArticles(page = 1) {
  if (!state.safeToQuery) {
    setStatus("数据库未配置，请确认服务启动配置后重试", true);
    return;
  }
  state.loadingArticles = true;
  setQueryEnabled(true);
  setStatus("查询中...");
  try {
    const keyword = encodeURIComponent(elements.keywordInput.value.trim());
    const offset = Math.max(0, (page - 1) * state.pageSize);
    const payload = await fetchJson(`/api/articles?keyword=${keyword}&limit=${state.pageSize}&offset=${offset}`);
    const items = Array.isArray(payload.items) ? payload.items : [];
    renderArticles(items);
    updatePagination(payload, items.length, page);
    setStatus(items.length ? "查询完成" : "暂无匹配数据");
  } catch (error) {
    renderArticles([]);
    updatePagination({total: 0, total_pages: 0, page: 0, page_size: state.pageSize}, 0, 0);
    setStatus(error.message, true);
  } finally {
    state.loadingArticles = false;
    setQueryEnabled(state.safeToQuery);
  }
}

function updateProgress(job) {
  const total = normalizePositiveInt(job.progress_total, 0);
  const current = normalizePositiveInt(job.progress_current, 0);
  let percent = total > 0 ? Math.round((Math.min(current, total) / total) * 100) : 0;
  if (String(job.status || "") === "success") percent = 100;
  elements.jobProgressBar.value = percent;
  setText(elements.jobProgressText, `${current} / ${total || 0}`);
}

function setCurrentJobActions(jobId, job) {
  const resultPage = state.currentResultPage || `/web/result.html?job_id=${encodeURIComponent(jobId)}`;
  elements.jobPreviewLink.href = resultPage;
  setHidden(elements.jobPreviewLink, !jobId);

  elements.jobDownloadLink.href = `/api/jobs/${encodeURIComponent(jobId)}/download`;
  setHidden(elements.jobDownloadLink, String(job.status || "") !== "success");

  elements.jobSummaryBtn.disabled = !jobId;
  elements.jobCancelBtn.disabled = !jobId || isTerminalStatus(job.status);
}

function renderCurrentJob(job) {
  const jobId = String(job.job_id || state.currentJobId || "");
  if (jobId) {
    state.currentJobId = jobId;
  }
  setText(elements.currentJobIdText, jobId ? `job_id: ${jobId}` : "未创建任务");
  setText(elements.currentJobStatusText, statusLabel(job.status));
  elements.currentJobStatusText.className = String(job.status || "") === "success" ? "result-badge result-badge-success" : "result-badge";
  if (String(job.status || "") === "failed" || String(job.status || "") === "cancelled") {
    elements.currentJobStatusText.className = "result-badge error";
  }
  setText(elements.currentTitleText, `当前文章：${job.current_title || "--"}`);
  updateProgress(job);
  setCurrentJobActions(jobId, job);
}

function renderLogLines(lines) {
  const safeLines = Array.isArray(lines) ? lines : [];
  setText(elements.jobLogTail, safeLines.length ? safeLines.join("\n") : "暂无日志");
}

async function loadJobLogs(jobId) {
  if (!jobId) return;
  try {
    const payload = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/logs?tail=80`);
    renderLogLines(payload.lines);
  } catch (error) {
    renderLogLines([`日志读取失败：${error.message}`]);
  }
}

function renderJobSummary(payload) {
  const title = document.createElement("h3");
  title.textContent = "Summary";
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(payload || {}, null, 2);
  elements.jobSummaryPanel.replaceChildren(title, pre);
}

function renderSummaryMessage(message) {
  const title = document.createElement("h3");
  title.textContent = "Summary";
  const paragraph = document.createElement("p");
  paragraph.textContent = message;
  elements.jobSummaryPanel.replaceChildren(title, paragraph);
}

async function loadJobSummary(jobId) {
  if (!jobId) return;
  try {
    const payload = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/summary`);
    renderJobSummary(payload);
  } catch (error) {
    const message = error.status === 404 ? "summary 尚未生成" : `summary 读取失败：${error.message}`;
    renderSummaryMessage(message);
  }
}

function stopJobPolling() {
  if (state.pollTimer) {
    window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

async function pollCurrentJob() {
  const jobId = state.currentJobId;
  if (!jobId) return;
  try {
    const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
    renderCurrentJob(job);
    await loadJobLogs(jobId);
    if (isTerminalStatus(job.status)) {
      state.extracting = false;
      stopJobPolling();
      setQueryEnabled(state.safeToQuery);
      await loadJobSummary(jobId);
      await loadJobHistory();
      setStatus(statusLabel(job.status));
      return;
    }
    state.pollTimer = window.setTimeout(pollCurrentJob, POLL_INTERVAL_MS);
  } catch (error) {
    state.extracting = false;
    stopJobPolling();
    setQueryEnabled(state.safeToQuery);
    setStatus(error.message, true);
    renderLogLines([`任务状态读取失败：${error.message}`]);
  }
}

function startJobPolling(jobId) {
  if (!jobId) return;
  stopJobPolling();
  state.currentJobId = jobId;
  state.extracting = true;
  setQueryEnabled(state.safeToQuery);
  pollCurrentJob();
}

function createActionLink(label, href) {
  const link = document.createElement("a");
  link.href = href;
  link.className = "table-action-link";
  link.textContent = label;
  return link;
}

function createActionButton(label, action, jobId) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "table-action-button";
  button.dataset.action = action;
  button.dataset.jobId = jobId;
  button.textContent = label;
  return button;
}

function appendHistoryActions(cell, job) {
  const jobId = String(job.job_id || "");
  const resultHref = `/web/result.html?job_id=${encodeURIComponent(jobId)}`;
  cell.appendChild(createActionLink("预览", resultHref));
  cell.appendChild(createActionButton("summary", "summary", jobId));
  if (String(job.status || "") === "success") {
    cell.appendChild(createActionLink("下载", `/api/jobs/${encodeURIComponent(jobId)}/download`));
  }
  if (!isTerminalStatus(job.status)) {
    cell.appendChild(createActionButton("取消", "cancel", jobId));
  }
}

function renderJobHistory(payload) {
  const items = Array.isArray(payload.items) ? payload.items : [];
  elements.jobHistoryBody.replaceChildren();
  if (!items.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.className = "empty";
    cell.textContent = "暂无历史任务";
    row.appendChild(cell);
    elements.jobHistoryBody.appendChild(row);
    return;
  }

  for (const job of items) {
    const row = document.createElement("tr");
    appendTextCell(row, job.job_id);
    appendTextCell(row, statusLabel(job.status));
    appendTextCell(row, `${normalizePositiveInt(job.progress_current, 0)} / ${normalizePositiveInt(job.progress_total, 0)}`);
    appendTextCell(row, job.updated_at || job.created_at || "");
    const actionCell = document.createElement("td");
    actionCell.className = "history-actions";
    appendHistoryActions(actionCell, job);
    row.appendChild(actionCell);
    elements.jobHistoryBody.appendChild(row);
  }
}

async function loadJobHistory() {
  try {
    const payload = await fetchJson("/api/jobs?limit=20");
    renderJobHistory(payload);
  } catch (error) {
    renderJobHistory({items: []});
    setStatus(`历史任务读取失败：${error.message}`, true);
  }
}

async function cancelJob(jobId) {
  if (!jobId) return;
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {method: "POST"});
  const payload = await readJsonResponse(response);
  renderCurrentJob(payload);
  await loadJobLogs(jobId);
  await loadJobSummary(jobId);
  await loadJobHistory();
}

async function cancelCurrentJob() {
  const jobId = state.currentJobId;
  if (!jobId) return;
  try {
    elements.jobCancelBtn.disabled = true;
    await cancelJob(jobId);
    state.extracting = false;
    stopJobPolling();
    setQueryEnabled(state.safeToQuery);
    setStatus("任务已取消");
  } catch (error) {
    elements.jobCancelBtn.disabled = false;
    setStatus(error.message, true);
  }
}

async function extractExcel() {
  if (state.extracting) return;
  if (!state.safeToQuery) {
    setStatus("数据库未配置，请确认服务启动配置后重试", true);
    return;
  }
  if (selectedIds.size === 0) {
    setStatus("请先选择至少一条数据", true);
    return;
  }

  state.extracting = true;
  setQueryEnabled(true);
  const riskText = state.ocrAvailable ? "" : "OCR 不可用：图片型表格无法被识别，抽取结果可能不完整";
  setStatus(riskText || "正在创建任务...");
  renderSummaryMessage("等待任务生成 summary");
  renderLogLines(["等待任务启动..."]);
  try {
    const payload = await fetchJson("/api/extract", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        selected_ids: Array.from(selectedIds),
        mode: getSelectedMode(),
        no_ocr: elements.noOcrInput.checked,
        no_llm: elements.noLlmInput.checked,
        prompt_version: elements.promptVersionInput.value.trim(),
        external_ocr_text: elements.externalOcrInput.value.trim(),
      }),
    });
    if (!payload.job_id || !String(payload.job_id).startsWith("job_")) {
      throw new Error("后端返回的任务编号格式不正确，请刷新页面后重试");
    }
    if (payload.result_page) {
      state.currentResultPage = payload.result_page;
    } else {
      state.currentResultPage = `/web/result.html?job_id=${encodeURIComponent(payload.job_id)}`;
    }
    renderCurrentJob({
      job_id: payload.job_id,
      status: payload.status || "queued",
      progress_current: 0,
      progress_total: selectedIds.size,
      current_title: "",
    });
    setStatus("任务已创建，首页会持续刷新进度");
    await loadJobHistory();
    startJobPolling(payload.job_id);
  } catch (error) {
    setStatus(error.message, true);
    state.extracting = false;
    setQueryEnabled(state.safeToQuery);
  }
}

elements.articleBody.addEventListener("change", (event) => {
  const id = event.target.dataset.id;
  if (!id) return;
  if (event.target.checked) selectedIds.add(id);
  else selectedIds.delete(id);
  updateSelection();
});

elements.selectPageInput.addEventListener("change", () => {
  for (const input of elements.articleBody.querySelectorAll("input[type=checkbox]")) {
    const id = input.dataset.id || "";
    input.checked = elements.selectPageInput.checked;
    if (input.checked && id) selectedIds.add(id);
    else selectedIds.delete(id);
  }
  updateSelection();
});

function clearSelection() {
  selectedIds.clear();
  for (const input of elements.articleBody.querySelectorAll("input[type=checkbox]")) {
    input.checked = false;
  }
  elements.selectPageInput.checked = false;
  updateSelection();
}

elements.clearSelectionBtn.addEventListener("click", clearSelection);

elements.refreshBtn.addEventListener("click", async () => {
  try {
    const status = await loadStatus();
    if (status.safe_to_query) await searchArticles(state.currentPage || 1);
    await loadJobHistory();
    if (state.currentJobId) await pollCurrentJob();
  } catch (error) {
    setStatus(error.message, true);
  }
});

elements.searchBtn.addEventListener("click", () => {
  state.currentPage = 1;
  searchArticles(1);
});

elements.keywordInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    state.currentPage = 1;
    searchArticles(1);
  }
});

elements.prevPageBtn.addEventListener("click", () => {
  if (state.currentPage > 1) searchArticles(state.currentPage - 1);
});

elements.nextPageBtn.addEventListener("click", () => {
  if (state.currentPage < state.totalPages) searchArticles(state.currentPage + 1);
});

elements.pageSizeSelect.addEventListener("change", () => {
  state.pageSize = Number(elements.pageSizeSelect.value || 20);
  state.currentPage = 1;
  searchArticles(1);
});

elements.extractBtn.addEventListener("click", () => extractExcel());
elements.jobRefreshBtn.addEventListener("click", () => {
  if (state.currentJobId) pollCurrentJob();
});
elements.historyRefreshBtn.addEventListener("click", () => loadJobHistory());
elements.jobSummaryBtn.addEventListener("click", () => loadJobSummary(state.currentJobId));
elements.jobCancelBtn.addEventListener("click", () => cancelCurrentJob());

elements.jobHistoryBody.addEventListener("click", async (event) => {
  if (!(event.target instanceof Element)) return;
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const jobId = button.dataset.jobId || "";
  if (!jobId) return;
  state.currentJobId = jobId;
  state.currentResultPage = `/web/result.html?job_id=${encodeURIComponent(jobId)}`;
  if (button.dataset.action === "summary") {
    await loadJobSummary(jobId);
    await loadJobLogs(jobId);
    try {
      const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
      renderCurrentJob(job);
    } catch (error) {
      setStatus(error.message, true);
    }
  }
  if (button.dataset.action === "cancel") {
    await cancelCurrentJob();
  }
});

updateSelection();
renderSummaryMessage("暂无 summary");

loadStatus()
  .then((status) => {
    loadJobHistory();
    if (status.safe_to_query) return searchArticles(1);
    return null;
  })
  .catch((error) => setStatus(error.message, true));
