let duplicatesData = null;

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

function formatAmount(amount) {
  return amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
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
  const skippedNote = result.skipped > 0
    ? `<p class="muted">Rows skipped here were already in this file (same import). <a href="#import-duplicates">Check for cross-file duplicates</a> below if you imported overlapping exports.</p>`
    : "";

  el.innerHTML = `
    <p><strong>${escapeHtml(result.filename)}</strong> imported.</p>
    <p>${result.inserted} new transaction${result.inserted === 1 ? "" : "s"},
       ${result.skipped} duplicate${result.skipped === 1 ? "" : "s"} skipped.</p>
    ${skippedNote}
    ${errorList}
    ${moreErrors}
    <p class="muted">Refresh the <a href="/">dashboard</a> to see updated reports.</p>
  `;
  show("import-result");
}

function renderDuplicates(data) {
  duplicatesData = data;
  const summaryEl = document.getElementById("duplicates-summary");
  const tableEl = document.getElementById("duplicates-table");
  const actionsEl = document.getElementById("duplicates-actions");

  if (!data.group_count) {
    summaryEl.textContent = "No duplicates found.";
    tableEl.innerHTML = "";
    hide("duplicates-actions");
    return;
  }

  const groupWord = data.group_count === 1 ? "group" : "groups";
  const txWord = data.extra_row_count === 1 ? "transaction" : "transactions";
  summaryEl.textContent =
    `${data.extra_row_count} duplicate ${txWord} in ${data.group_count} ${groupWord} ` +
    "(same date, description, and amount from different imports).";

  const rows = data.groups.flatMap((group, groupIndex) => {
    const { date, description, amount } = group.key;
    return group.transactions.map((tx, txIndex) => {
      const groupClass = txIndex === 0 ? "duplicate-group-start" : "";
      const checked = tx.suggested_keep ? " checked" : "";
      return `
        <tr class="${groupClass}">
          <td>${formatDate(date)}</td>
          <td>${escapeHtml(description)}</td>
          <td class="num">${formatAmount(amount)}</td>
          <td>${escapeHtml(tx.source_account)}</td>
          <td>${escapeHtml(tx.category)}</td>
          <td class="num">
            <input type="radio" name="keep-${groupIndex}" value="${tx.id}"${checked}
                   aria-label="Keep transaction ${tx.id}">
          </td>
        </tr>
      `;
    });
  }).join("");

  tableEl.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Description</th>
          <th class="num">Amount</th>
          <th>Source account</th>
          <th>Category</th>
          <th class="num">Keep?</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
  show("duplicates-actions");
}

function getIdsToRemove() {
  if (!duplicatesData || !duplicatesData.groups.length) {
    return [];
  }

  const idsToRemove = [];
  duplicatesData.groups.forEach((group, groupIndex) => {
    const selected = document.querySelector(`input[name="keep-${groupIndex}"]:checked`);
    const keepId = selected ? Number(selected.value) : null;
    group.transactions.forEach((tx) => {
      if (tx.id !== keepId) {
        idsToRemove.push(tx.id);
      }
    });
  });
  return idsToRemove;
}

function getSuggestedRemoveIds() {
  if (!duplicatesData || !duplicatesData.groups.length) {
    return [];
  }

  const ids = [];
  duplicatesData.groups.forEach((group) => {
    group.transactions.forEach((tx) => {
      if (!tx.suggested_keep) {
        ids.push(tx.id);
      }
    });
  });
  return ids;
}

async function loadDuplicates() {
  const data = await fetchJson("/api/duplicates");
  renderDuplicates(data);
}

async function handleRemoveDuplicates(ids) {
  if (!ids.length) {
    setError("No duplicate transactions selected for removal.");
    return;
  }

  const txWord = ids.length === 1 ? "transaction" : "transactions";
  if (!window.confirm(`Remove ${ids.length} ${txWord}? This cannot be undone.`)) {
    return;
  }

  setError("");
  try {
    await fetchJson("/api/duplicates/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    });
    await Promise.all([loadDuplicates(), loadSources()]);
  } catch (err) {
    setError(err.message);
  }
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
    await Promise.all([loadSources(), loadDuplicates()]);
  } catch (err) {
    setError(err.message);
  } finally {
    submitBtn.disabled = false;
  }
}

async function init() {
  try {
    await Promise.all([loadSources(), loadDuplicates()]);
    hide("import-loading");
    show("import-upload");
    show("import-status");
    show("import-duplicates");
  } catch (err) {
    hide("import-loading");
    setError(err.message);
  }
}

document.getElementById("import-form").addEventListener("submit", handleUpload);
document.getElementById("duplicates-remove-btn").addEventListener("click", () => {
  handleRemoveDuplicates(getIdsToRemove());
});
document.getElementById("duplicates-remove-all-btn").addEventListener("click", () => {
  handleRemoveDuplicates(getSuggestedRemoveIds());
});
document.getElementById("duplicates-rescan-btn").addEventListener("click", async () => {
  setError("");
  try {
    await loadDuplicates();
  } catch (err) {
    setError(err.message);
  }
});
init();
