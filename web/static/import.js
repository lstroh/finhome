function show(id) {
  document.getElementById(id).classList.remove("hidden");
}

function hide(id) {
  document.getElementById(id).classList.add("hidden");
}

function setError(message) {
  const el = document.getElementById("import-error");
  if (message) {
    el.textContent = message;
    show("import-error");
  } else {
    el.textContent = "";
    hide("import-error");
  }
}

async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.error || `Request failed (${resp.status})`);
  }
  return data;
}

function formatDate(isoDate) {
  if (!isoDate) return "—";
  const [year, month, day] = isoDate.split("-");
  if (!year || !month || !day) return isoDate;
  const d = new Date(Number(year), Number(month) - 1, Number(day));
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatDateTime(isoDateTime) {
  if (!isoDateTime) return "Unknown";
  const d = new Date(isoDateTime.endsWith("Z") ? isoDateTime : isoDateTime + "Z");
  if (Number.isNaN(d.getTime())) return isoDateTime;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderSourcesTable(sources) {
  const rows = sources.map((src) => `
    <tr>
      <td>${escapeHtml(src.label)}</td>
      <td>${formatDate(src.last_transaction_date)}</td>
      <td>${formatDateTime(src.last_import_at)}</td>
      <td class="num">${src.transaction_count.toLocaleString()}</td>
      <td class="num">${src.file_count.toLocaleString()}</td>
    </tr>
  `).join("");

  document.getElementById("sources-table").innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Source</th>
          <th>Last data</th>
          <th>Last uploaded</th>
          <th class="num">Transactions</th>
          <th class="num">Files</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderImportResult(result) {
  const el = document.getElementById("import-result");
  const errorList = result.errors && result.errors.length
    ? `<ul class="import-errors">${result.errors.slice(0, 10).map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul>`
    : "";
  const moreErrors = result.errors && result.errors.length > 10
    ? `<p class="muted">…and ${result.errors.length - 10} more errors</p>`
    : "";

  el.innerHTML = `
    <p><strong>${escapeHtml(result.filename)}</strong> imported.</p>
    <p>${result.inserted} new transaction${result.inserted === 1 ? "" : "s"},
       ${result.skipped} duplicate${result.skipped === 1 ? "" : "s"} skipped.</p>
    ${errorList}
    ${moreErrors}
    <p class="muted">Refresh the <a href="/">dashboard</a> to see updated reports.</p>
  `;
  show("import-result");
}

async function loadSources() {
  const sources = await fetchJson("/api/sources");
  renderSourcesTable(sources);
}

async function handleUpload(event) {
  event.preventDefault();
  setError("");

  const type = document.getElementById("import-type").value;
  const fileInput = document.getElementById("import-file");
  const submitBtn = document.getElementById("import-submit");
  const file = fileInput.files[0];

  if (!file) {
    setError("Please choose a CSV file.");
    return;
  }

  submitBtn.disabled = true;
  hide("import-result");

  try {
    const content = await file.text();
    const result = await fetchJson("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type,
        filename: file.name,
        content,
      }),
    });
    renderImportResult(result);
    fileInput.value = "";
    await loadSources();
  } catch (err) {
    setError(err.message);
  } finally {
    submitBtn.disabled = false;
  }
}

async function init() {
  try {
    await loadSources();
    hide("import-loading");
    show("import-upload");
    show("import-status");
  } catch (err) {
    hide("import-loading");
    setError(err.message);
  }
}

document.getElementById("import-form").addEventListener("submit", handleUpload);
init();
