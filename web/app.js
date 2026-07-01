const selectedIds = new Set();

const elements = {
  configStatus: document.querySelector("#configStatus"),
  refreshBtn: document.querySelector("#refreshBtn"),
  keywordInput: document.querySelector("#keywordInput"),
  searchBtn: document.querySelector("#searchBtn"),
  noOcrInput: document.querySelector("#noOcrInput"),
  noLlmInput: document.querySelector("#noLlmInput"),
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
};

function setStatus(text, isError = false) {
  elements.jobStatus.textContent = text || "";
  elements.jobStatus.className = isError ? "error" : "";
}

function updateSelection() {
  elements.selectionStatus.textContent = `已选择 ${selectedIds.size} 条`;
  elements.clearSelectionBtn.disabled = selectedIds.size === 0;
}

function setQueryEnabled(enabled) {
  const canQuery = Boolean(enabled);
  elements.searchBtn.disabled = !canQuery || state.loadingArticles;
  elements.extractBtn.disabled = !canQuery || state.extracting;
  elements.selectPageInput.disabled = !canQuery;
  elements.prevPageBtn.disabled = !canQuery || state.loadingArticles || state.currentPage <= 1;
  elements.nextPageBtn.disabled = !canQuery || state.loadingArticles || state.currentPage >= state.totalPages;
  elements.pageSizeSelect.disabled = !canQuery || state.loadingArticles;
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
    const message = payload.detail || payload.error || "请求失败";
    throw new Error(String(message));
  }
  return payload;
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
    link.textContent = "打开";
    cell.appendChild(link);
  } else {
    cell.textContent = value || "";
  }
  row.appendChild(cell);
}

function updatePagination(payload) {
  state.totalItems = Number(payload.total || 0);
  state.totalPages = Number(payload.total_pages || 0);
  state.currentPage = Number(payload.page || 1);
  state.pageSize = Number(payload.page_size || state.pageSize);
  elements.pageStatus.textContent = `第 ${state.totalPages ? state.currentPage : 0} / ${state.totalPages} 页`;
  elements.totalStatus.textContent = `总计 ${state.totalItems} 条`;
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
  const pathLabel = status.config_path ? `，配置：${status.config_path}` : "";
  elements.configStatus.textContent = `数据库：${databaseLabel}，LLM：${llmLabel}，OCR：${ocrLabel}${pathLabel}`;

  if (!state.ocrAvailable) {
    elements.noOcrInput.checked = true;
    elements.noOcrInput.disabled = true;
    elements.ocrWarning.textContent = "OCR 不可用，图片表格可能无法抽取";
  } else {
    elements.noOcrInput.disabled = false;
    elements.ocrWarning.textContent = "";
  }
  setQueryEnabled(state.safeToQuery);

  if (!state.safeToQuery) {
    selectedIds.clear();
    elements.selectPageInput.checked = false;
    updateSelection();
    updatePagination({total: 0, total_pages: 0, page: 0, page_size: state.pageSize});
    setEmptyRow("暂无数据，数据库未配置或查询失败");
    setStatus(status.database_status_reason || "数据库未配置，请用 --config 指定可用数据库配置后重启服务", true);
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
    checkbox.type = "checkbox";
    checkbox.dataset.id = item.id || "";
    checkbox.checked = selectedIds.has(item.id);
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
    setStatus("数据库未配置，请用 --config 指定可用数据库配置后重启服务", true);
    return;
  }
  state.loadingArticles = true;
  setQueryEnabled(true);
  setStatus("查询中...");
  try {
    const keyword = encodeURIComponent(elements.keywordInput.value.trim());
    const offset = Math.max(0, (page - 1) * state.pageSize);
    const payload = await fetchJson(`/api/articles?keyword=${keyword}&limit=${state.pageSize}&offset=${offset}`);
    renderArticles(payload.items);
    updatePagination(payload);
    setStatus(payload.items && payload.items.length ? "查询完成" : "暂无匹配数据");
  } catch (error) {
    renderArticles([]);
    updatePagination({total: 0, total_pages: 0, page: 0, page_size: state.pageSize});
    setStatus(error.message, true);
  } finally {
    state.loadingArticles = false;
    setQueryEnabled(state.safeToQuery);
  }
}

async function extractExcel() {
  if (!state.safeToQuery) {
    setStatus("数据库未配置，请用 --config 指定可用数据库配置后重启服务", true);
    return;
  }
  if (selectedIds.size === 0) {
    setStatus("请先选择至少一条数据", true);
    return;
  }

  state.extracting = true;
  setQueryEnabled(true);
  const riskText = state.ocrAvailable ? "" : "OCR 不可用：图片型表格无法被识别，抽取结果可能不完整";
  setStatus(riskText || "已创建任务，准备跳转结果页");
  try {
    const payload = await fetchJson("/api/extract", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        selected_ids: Array.from(selectedIds),
        mode: "merge",
        no_ocr: elements.noOcrInput.checked,
        no_llm: elements.noLlmInput.checked,
      }),
    });
    window.location.href = payload.result_page || `/web/result.html?job_id=${encodeURIComponent(payload.job_id)}`;
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
    input.checked = elements.selectPageInput.checked;
    if (input.checked) selectedIds.add(input.dataset.id);
    else selectedIds.delete(input.dataset.id);
  }
  updateSelection();
});

elements.clearSelectionBtn.addEventListener("click", () => {
  selectedIds.clear();
  for (const input of elements.articleBody.querySelectorAll("input[type=checkbox]")) {
    input.checked = false;
  }
  elements.selectPageInput.checked = false;
  updateSelection();
});

elements.refreshBtn.addEventListener("click", async () => {
  try {
    const status = await loadStatus();
    if (status.safe_to_query) await searchArticles(state.currentPage || 1);
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

loadStatus()
  .then((status) => {
    if (status.safe_to_query) return searchArticles(1);
    return null;
  })
  .catch((error) => setStatus(error.message, true));
