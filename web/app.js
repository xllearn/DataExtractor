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
  downloadLink: document.querySelector("#downloadLink"),
  selectPageInput: document.querySelector("#selectPageInput"),
  articleBody: document.querySelector("#articleBody"),
};

const state = {
  safeToQuery: false,
  loadingArticles: false,
  extracting: false,
};

function setStatus(text, isError = false) {
  elements.jobStatus.textContent = text || "";
  elements.jobStatus.className = isError ? "error" : "";
}

function updateSelection() {
  elements.selectionStatus.textContent = `已选择 ${selectedIds.size} 条`;
}

function setQueryEnabled(enabled) {
  elements.searchBtn.disabled = !enabled || state.loadingArticles;
  elements.extractBtn.disabled = !enabled || state.extracting;
  elements.selectPageInput.disabled = !enabled;
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

async function loadStatus() {
  const status = await fetchJson("/api/config/status");
  state.safeToQuery = Boolean(status.safe_to_query);
  const databaseLabel = status.database_configured ? "已配置" : "未配置";
  const llmLabel = status.llm_configured ? "已配置" : "未配置";
  const ocrLabel = status.ocr_available ? "可用" : "不可用";
  const pathLabel = status.config_path ? `，配置：${status.config_path}` : "";
  elements.configStatus.textContent = `数据库：${databaseLabel}，LLM：${llmLabel}，OCR：${ocrLabel}${pathLabel}`;
  setQueryEnabled(state.safeToQuery);

  if (!state.safeToQuery) {
    selectedIds.clear();
    elements.selectPageInput.checked = false;
    updateSelection();
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
    setEmptyRow("暂无数据");
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

async function searchArticles() {
  if (!state.safeToQuery) {
    setStatus("数据库未配置，请用 --config 指定可用数据库配置后重启服务", true);
    return;
  }
  state.loadingArticles = true;
  setQueryEnabled(true);
  setStatus("查询中...");
  try {
    const keyword = encodeURIComponent(elements.keywordInput.value.trim());
    const payload = await fetchJson(`/api/articles?keyword=${keyword}&limit=50&offset=0`);
    renderArticles(payload.items);
    setStatus(`已加载 ${payload.total} 条`);
  } catch (error) {
    renderArticles([]);
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

  elements.downloadLink.hidden = true;
  state.extracting = true;
  setQueryEnabled(true);
  setStatus("生成中，请勿关闭页面；大批量请使用命令行");
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
    elements.downloadLink.href = payload.download_url;
    elements.downloadLink.hidden = false;
    setStatus("生成成功");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
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

elements.refreshBtn.addEventListener("click", async () => {
  try {
    const status = await loadStatus();
    if (status.safe_to_query) await searchArticles();
  } catch (error) {
    setStatus(error.message, true);
  }
});
elements.searchBtn.addEventListener("click", () => searchArticles());
elements.extractBtn.addEventListener("click", () => extractExcel());

loadStatus()
  .then((status) => {
    if (status.safe_to_query) return searchArticles();
    return null;
  })
  .catch((error) => setStatus(error.message, true));
