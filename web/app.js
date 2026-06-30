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

function setStatus(text, isError = false) {
  elements.jobStatus.textContent = text;
  elements.jobStatus.className = isError ? "error" : "";
}

function updateSelection() {
  elements.selectionStatus.textContent = `已选择 ${selectedIds.size} 条`;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(payload.detail || "请求失败");
  }
  return payload;
}

async function loadStatus() {
  const status = await fetchJson("/api/config/status");
  elements.configStatus.textContent = `数据库：${status.database_configured ? "已配置" : "未配置"}，LLM：${status.llm_configured ? "已配置" : "未配置"}，OCR：${status.ocr_available ? "可用" : "不可用"}`;
}

function renderArticles(items) {
  elements.articleBody.innerHTML = "";
  for (const item of items) {
    const row = document.createElement("tr");
    const checked = selectedIds.has(item.id) ? "checked" : "";
    row.innerHTML = `
      <td><input type="checkbox" data-id="${item.id}" ${checked}></td>
      <td>${item.title || ""}</td>
      <td>${item.region || ""}</td>
      <td>${item.insurance_type || ""}</td>
      <td>${item.audit_time || ""}</td>
      <td>${item.source_url ? `<a href="${item.source_url}" target="_blank" rel="noreferrer">打开</a>` : ""}</td>
    `;
    elements.articleBody.appendChild(row);
  }
  updateSelection();
}

async function searchArticles() {
  setStatus("查询中...");
  const keyword = encodeURIComponent(elements.keywordInput.value.trim());
  const payload = await fetchJson(`/api/articles?keyword=${keyword}&limit=50&offset=0`);
  renderArticles(payload.items);
  setStatus(`已加载 ${payload.total} 条`);
}

async function extractExcel() {
  elements.downloadLink.hidden = true;
  setStatus("生成中...");
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

elements.refreshBtn.addEventListener("click", () => loadStatus().catch((error) => setStatus(error.message, true)));
elements.searchBtn.addEventListener("click", () => searchArticles().catch((error) => setStatus(error.message, true)));
elements.extractBtn.addEventListener("click", () => extractExcel().catch((error) => setStatus(error.message, true)));

loadStatus().catch((error) => setStatus(error.message, true));
searchArticles().catch((error) => setStatus(error.message, true));
