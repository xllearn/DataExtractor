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
  if (!node) return;
  node.textContent = value || "";
}

function setHidden(node, hidden) {
  if (!node) return;
  node.hidden = hidden;
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
  if (!jobId.startsWith("job_")) {
    setText(elements.statusText, "任务编号格式不正确，请返回列表重新生成。");
    elements.statusText.className = "error";
    return;
  }
  try {
    const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
    setText(elements.statusText, job.message || job.status);
    if (!job.ocr_available) {
      setText(elements.riskText, "本次未使用 OCR，图片表格内容可能缺失。");
    }
    if (job.external_ocr_used) {
      setText(elements.riskText, "使用了外部 OCR 文本");
    }
    if (job.status === "success") {
      if (elements.downloadBtn) {
        elements.downloadBtn.href = job.download_url;
        setHidden(elements.downloadBtn, false);
      }
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
    if (error.status === 404 || error.errorType === "JobNotFound") {
      setText(elements.statusText, "任务不存在或已过期，请返回列表重新生成。");
    } else {
      setText(elements.statusText, error.message);
    }
    elements.statusText.className = "error";
  }
}

if (elements.backBtn) {
  elements.backBtn.addEventListener("click", () => {
    window.location.href = "/";
  });
}

pollJob();
