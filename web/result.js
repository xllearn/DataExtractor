const params = new URLSearchParams(window.location.search);
const jobId = params.get("job_id") || "";

const elements = {
  jobIdText: document.querySelector("#jobIdText"),
  statusText: document.querySelector("#statusText"),
  riskText: document.querySelector("#riskText"),
  downloadBtn: document.querySelector("#downloadBtn"),
  backBtn: document.querySelector("#backBtn"),
  previewHead: document.querySelector("#previewHead"),
  previewBody: document.querySelector("#previewBody"),
};

function setText(node, value) {
  node.textContent = value || "";
}

async function fetchJson(url) {
  const response = await fetch(url);
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
    throw new Error(String(payload.detail || payload.error || "请求失败"));
  }
  return payload;
}

function renderPreview(payload) {
  elements.previewHead.replaceChildren();
  elements.previewBody.replaceChildren();

  const headRow = document.createElement("tr");
  for (const header of payload.headers || []) {
    const cell = document.createElement("th");
    cell.textContent = header || "";
    headRow.appendChild(cell);
  }
  elements.previewHead.appendChild(headRow);

  for (const row of payload.rows || []) {
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
  const payload = await fetchJson(url);
  renderPreview(payload);
}

async function pollJob() {
  if (!jobId) {
    setText(elements.statusText, "缺少 job_id");
    elements.statusText.className = "error";
    return;
  }
  setText(elements.jobIdText, `job_id: ${jobId}`);
  try {
    const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
    setText(elements.statusText, job.message || job.status);
    if (!job.ocr_available) {
      setText(elements.riskText, "本次未成功 OCR，结果可能缺少图片中的保障责任表。");
    }
    if (job.external_ocr_used) {
      setText(elements.riskText, "使用了外部 OCR 文本");
    }
    if (job.status === "success") {
      elements.downloadBtn.href = job.download_url;
      elements.downloadBtn.hidden = false;
      await loadPreview(job.preview_url || `/api/jobs/${encodeURIComponent(jobId)}/preview`);
      return;
    }
    if (job.status === "failed") {
      setText(elements.statusText, job.error || "生成失败");
      elements.statusText.className = "error";
      return;
    }
    window.setTimeout(pollJob, 1000);
  } catch (error) {
    setText(elements.statusText, error.message);
    elements.statusText.className = "error";
  }
}

elements.backBtn.addEventListener("click", () => {
  window.location.href = "/";
});

pollJob();
