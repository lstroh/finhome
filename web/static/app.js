"use strict";

const state = {
  months: [],
  selectedMonth: null,
  summary: null,
  trends: null,
  subscriptions: null,
  uncategorised: null,
  categoryOptions: [],
  uncategorisedSort: { key: "description", asc: true },
  drilldown: {
    month: null,
    category: null,
    data: null,
    loading: false,
    selectedSource: null,
  },
  currentMonth: null,
  savingCategoryId: null,
  search: { query: "", scope: "month", month: null, year: null, loading: false, data: null },
};

function fmtGbp(amount) {
  if (amount == null) return "—";
  const sign = amount < 0 ? "-" : "";
  return sign + "£" + Math.abs(amount).toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtPct(value) {
  if (value == null) return "—";
  return Math.abs(value).toFixed(1) + "%";
}

// Okabe-Ito + Paul Tol Bright — maximally distinct hues, colorblind-safe.
// Ordered so the first few colours have the highest pairwise contrast.
const SOURCE_COLOR_PALETTE = [
  "#0072B2", // blue
  "#D55E00", // vermillion
  "#009E73", // bluish green
  "#CC79A7", // reddish purple
  "#E69F00", // orange
  "#332288", // indigo
  "#117733", // forest green
  "#56B4E9", // sky blue
];

// Second pass uses entirely different hues (not lighter variants of the first set).
const SOURCE_COLOR_PALETTE_ALT = [
  "#EE6677", // coral
  "#44AA99", // cyan-teal
  "#AA3377", // magenta
  "#999933", // olive
  "#661100", // brown-red
  "#6699CC", // steel blue
  "#882255", // wine
  "#DDAA33", // gold
];

function sourceColor(index) {
  const slot = index % SOURCE_COLOR_PALETTE.length;
  const pass = Math.floor(index / SOURCE_COLOR_PALETTE.length);
  if (pass % 2 === 0) return SOURCE_COLOR_PALETTE[slot];
  return SOURCE_COLOR_PALETTE_ALT[slot];
}

function sourceLabel(sourceAccount) {
  const prefix = "credit_card_";
  if (sourceAccount.startsWith(prefix)) {
    return sourceAccount.slice(prefix.length) + " (credit card)";
  }
  return sourceAccount;
}

function buildSourceColorMap(transactions) {
  const accounts = [...new Set(transactions.map((t) => t.source_account))].sort();
  const map = {};
  accounts.forEach((account, index) => {
    map[account] = {
      index,
      color: sourceColor(index),
      label: sourceLabel(account),
    };
  });
  return map;
}

function renderSourceLegend(colorMap) {
  const entries = Object.entries(colorMap).sort((a, b) =>
    a[1].label.localeCompare(b[1].label)
  );
  if (entries.length === 0) return "";
  const items = entries.map(([, info]) => `
    <span class="source-legend-item">
      <span class="source-swatch" style="background: ${info.color}"></span>
      ${escapeHtml(info.label)}
    </span>
  `).join("");
  return `<div class="source-legend" aria-label="Account colours">${items}</div>`;
}

function filterTransactionsBySource(transactions, selectedSource) {
  if (!selectedSource) return transactions;
  return transactions.filter((t) => t.source_account === selectedSource);
}

function renderSourceFilterTabs(colorMap, selectedSource) {
  const entries = Object.entries(colorMap).sort((a, b) =>
    a[1].label.localeCompare(b[1].label)
  );
  if (entries.length <= 1) return "";

  const allActive = selectedSource == null;
  const allTab = `
    <button type="button" class="tab${allActive ? " active" : ""}" data-source="" aria-selected="${allActive ? "true" : "false"}">
      All
    </button>
  `;
  const accountTabs = entries.map(([account, info]) => {
    const active = selectedSource === account;
    return `
      <button type="button" class="tab${active ? " active" : ""}" data-source="${escapeHtml(account)}" aria-selected="${active ? "true" : "false"}" style="${active ? `--tab-accent: ${info.color}` : ""}">
        <span class="source-swatch" style="background: ${info.color}"></span>
        ${escapeHtml(info.label)}
      </button>
    `;
  }).join("");

  return `<div class="drilldown-tabs" role="tablist" aria-label="Filter by account">${allTab}${accountTabs}</div>`;
}

function bindSourceFilterTabs(panel) {
  panel.querySelectorAll(".drilldown-tabs .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const source = tab.dataset.source || null;
      state.drilldown.selectedSource = source;
      renderDrilldownPanel();
    });
  });
}

function renderTransactionRows(transactions, colorMap) {
  return transactions.map((t) => {
    const info = colorMap[t.source_account] || { color: "var(--border)" };
    return `
      <tr class="tx-source-row" style="--source-color: ${info.color}">
        <td>${escapeHtml(t.date)}</td>
        <td>${escapeHtml(t.description)}</td>
        <td>${escapeHtml(t.source_account)}</td>
        <td class="amount">${fmtGbp(t.amount)}</td>
        <td class="category-cell">${renderCategoryEditor(t)}</td>
      </tr>
    `;
  }).join("");
}

function renderTransactionTable(transactions, metaHtml, options = {}) {
  const { showLegend = true, colorMap: colorMapOverride, total } = options;
  const colorMap = colorMapOverride || buildSourceColorMap(transactions);
  const legend = showLegend ? renderSourceLegend(colorMap) : "";
  const txRows = renderTransactionRows(transactions, colorMap);
  const footer =
    total != null
      ? `<tfoot>
          <tr class="table-total-row">
            <td colspan="3"><strong>Total</strong></td>
            <td class="amount"><strong>${fmtGbp(total)}</strong></td>
            <td></td>
          </tr>
        </tfoot>`
      : "";
  return `
    ${metaHtml}
    ${legend}
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Description</th>
            <th>Account</th>
            <th class="amount">Amount</th>
            <th>Category</th>
          </tr>
        </thead>
        <tbody>${txRows}</tbody>
        ${footer}
      </table>
    </div>
  `;
}

function show(id) {
  document.getElementById(id).classList.remove("hidden");
}

function hide(id) {
  document.getElementById(id).classList.add("hidden");
}

function setError(message) {
  const el = document.getElementById("error");
  el.textContent = message;
  show("error");
}

function clearError() {
  hide("error");
  document.getElementById("error").textContent = "";
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

function categorySelectOptions(currentCategory) {
  const names = new Set(state.categoryOptions);
  if (currentCategory) names.add(currentCategory);
  const sorted = [...names].sort((a, b) => a.localeCompare(b));
  const options = sorted.map((name) =>
    `<option value="${escapeHtml(name)}"${name === currentCategory ? " selected" : ""}>${escapeHtml(name)}</option>`
  ).join("");
  return `${options}<option value="__custom__">Custom…</option>`;
}

function renderCategoryEditor(t) {
  const saving = state.savingCategoryId === t.id;
  return `
    <div class="category-editor" data-id="${t.id}">
      <select class="category-select" aria-label="Category for ${escapeHtml(t.description)}"${saving ? " disabled" : ""}>
        ${categorySelectOptions(t.category)}
      </select>
      <input type="text" class="category-custom hidden" placeholder="New category" maxlength="100" aria-label="Custom category">
      <button type="button" class="category-save"${saving ? " disabled" : ""}>${saving ? "Saving…" : "Save"}</button>
    </div>
  `;
}

function bindCategoryEditors(panel) {
  panel.querySelectorAll(".category-editor").forEach((editor) => {
    const select = editor.querySelector(".category-select");
    const customInput = editor.querySelector(".category-custom");
    const saveBtn = editor.querySelector(".category-save");

    select.addEventListener("change", () => {
      const isCustom = select.value === "__custom__";
      customInput.classList.toggle("hidden", !isCustom);
      if (isCustom) customInput.focus();
    });

    saveBtn.addEventListener("click", () => {
      const id = Number(editor.dataset.id);
      let category = select.value;
      if (category === "__custom__") {
        category = customInput.value.trim();
        if (!category) {
          setError("Enter a category name.");
          return;
        }
      }
      saveTransactionCategory(id, category);
    });
  });
}

async function saveTransactionCategory(transactionId, category) {
  clearError();
  state.savingCategoryId = transactionId;
  if (state.drilldown.data) renderDrilldownPanel();
  if (state.uncategorised) renderUncategorised(state.uncategorised);
  if (state.search.data) renderSearchResults();

  try {
    await fetchJson("/api/transaction/category", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: transactionId, category }),
    });
    state.savingCategoryId = null;
    await refreshAfterCategoryChange();
  } catch (err) {
    state.savingCategoryId = null;
    setError(err.message);
    if (state.drilldown.data) renderDrilldownPanel();
    if (state.uncategorised) renderUncategorised(state.uncategorised);
    if (state.search.data) renderSearchResults();
  }
}

async function refreshAfterCategoryChange() {
  const drillMonth = state.drilldown.month;
  const drillCategory = state.drilldown.category;
  const searchQuery = state.search.query;
  const searchScope = state.search.scope;
  const searchMonth = state.search.month;
  const searchYear = state.search.year;
  const hadSearchResults = Boolean(state.search.data);

  const summary = await fetchJson("/api/summary");
  state.summary = summary;
  state.trends = summary.trends || await fetchJson("/api/trends");
  state.subscriptions = summary.subscriptions;
  state.uncategorised = await fetchJson("/api/uncategorised");
  state.categoryOptions = await fetchJson("/api/categories");

  const monthData = await fetchJson(
    `/api/month?month=${encodeURIComponent(state.selectedMonth)}`
  );
  state.currentMonth = monthData;
  if (monthData.empty) {
    document.getElementById("summary-cards").innerHTML =
      `<p class="muted">No transactions for ${escapeHtml(monthData.month)}.</p>`;
    document.getElementById("category-table").innerHTML = "";
    document.getElementById("benchmark").innerHTML = "";
    document.getElementById("merchants").innerHTML = "";
  } else {
    renderCards(monthData);
    renderCategoryTable(monthData.categories);
    renderBenchmark(monthData.benchmark);
    renderMerchants(monthData.top_merchants);
  }
  renderUncategorisedBanner(summary.uncategorised_count);
  renderTrends(state.trends || { empty: true });
  renderSubscriptions(state.subscriptions);
  renderUncategorised(state.uncategorised);

  if (drillMonth && drillCategory) {
    const prevSource = state.drilldown.selectedSource;
    const data = await fetchJson(
      `/api/transactions?month=${encodeURIComponent(drillMonth)}` +
      `&category=${encodeURIComponent(drillCategory)}`
    );
    state.drilldown = {
      month: drillMonth,
      category: drillCategory,
      data,
      loading: false,
      selectedSource: prevSource,
    };
    renderDrilldownPanel();
    if (!data.empty && state.currentMonth && !state.currentMonth.empty) {
      renderCategoryTable(state.currentMonth.categories);
    }
  }

  if (hadSearchResults && searchQuery) {
    let url = `/api/search?q=${encodeURIComponent(searchQuery)}&scope=${encodeURIComponent(searchScope)}`;
    if (searchScope === "month") {
      url += `&month=${encodeURIComponent(searchMonth)}`;
    } else if (searchScope === "year") {
      url += `&year=${encodeURIComponent(searchYear)}`;
    }
    const data = await fetchJson(url);
    state.search = {
      query: searchQuery,
      scope: searchScope,
      month: searchScope === "month" ? searchMonth : null,
      year: searchScope === "year" ? searchYear : null,
      loading: false,
      data,
    };
    renderSearchResults();
  }
}

function renderCards(month) {
  const cards = document.getElementById("summary-cards");
  const netClass = month.net < 0 ? "negative" : month.net > 0 ? "positive" : "";
  cards.innerHTML = `
    <div class="card">
      <div class="card-label">Total spend</div>
      <div class="card-value negative">${fmtGbp(month.total_spend)}</div>
    </div>
    <div class="card">
      <div class="card-label">Income</div>
      <div class="card-value positive">${fmtGbp(month.income)}</div>
    </div>
    <div class="card">
      <div class="card-label">Net</div>
      <div class="card-value ${netClass}">${fmtGbp(month.net)}</div>
    </div>
  `;
}

function renderCategoryTable(categories) {
  const wrap = document.getElementById("category-table");
  if (!categories.length) {
    wrap.innerHTML = '<p class="muted" style="padding:1rem">No spending this month.</p>';
    return;
  }
  const maxPct = Math.max(...categories.map((c) => Math.abs(c.pct)), 1);
  const rows = categories.map((cat) => {
    const barWidth = (Math.abs(cat.pct) / maxPct) * 100;
    const selected =
      state.drilldown.category === cat.name &&
      state.drilldown.month === state.selectedMonth;
    return `
      <tr class="category-row clickable${selected ? " selected" : ""}"
          role="button" tabindex="0"
          aria-expanded="${selected ? "true" : "false"}">
        <td>${escapeHtml(cat.name)}</td>
        <td class="amount">${fmtGbp(cat.amount)}</td>
        <td class="amount">${fmtPct(cat.pct)}</td>
        <td class="bar-cell">
          <div class="bar-track"><div class="bar-fill" style="width:${barWidth}%"></div></div>
        </td>
      </tr>
    `;
  }).join("");
  wrap.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Category</th>
          <th class="amount">Amount</th>
          <th class="amount">Share</th>
          <th>Bar</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
  wrap.querySelectorAll(".category-row").forEach((row, i) => {
    const category = categories[i].name;
    row.addEventListener("click", () => toggleDrilldown(category));
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleDrilldown(category);
      }
    });
  });
}

function closeDrilldown() {
  state.drilldown = {
    month: null,
    category: null,
    data: null,
    loading: false,
    selectedSource: null,
  };
  hide("drilldown-panel");
  document.querySelectorAll(".category-row.selected").forEach((row) => {
    row.classList.remove("selected");
    row.setAttribute("aria-expanded", "false");
  });
}

function normalizeDrilldownSource(colorMap) {
  const { selectedSource } = state.drilldown;
  if (selectedSource && !colorMap[selectedSource]) {
    state.drilldown.selectedSource = null;
  }
}

function renderDrilldownPanel() {
  const panel = document.getElementById("drilldown-panel");
  const { month, category, data, loading } = state.drilldown;

  if (!category || !month) {
    hide("drilldown-panel");
    return;
  }

  show("drilldown-panel");
  panel.setAttribute("aria-label", `Transactions for ${category}`);

  if (loading) {
    panel.innerHTML = `
      <div class="drilldown-header">
        <h2>${escapeHtml(category)} — ${escapeHtml(month)}</h2>
        <button type="button" class="drilldown-close">Close</button>
      </div>
      <p class="muted">Loading…</p>
    `;
    panel.querySelector(".drilldown-close").addEventListener("click", closeDrilldown);
    return;
  }

  if (!data) {
    hide("drilldown-panel");
    return;
  }

  if (data.empty) {
    panel.innerHTML = `
      <div class="drilldown-header">
        <h2>${escapeHtml(data.category)} — ${escapeHtml(data.month)}</h2>
        <button type="button" class="drilldown-close">Close</button>
      </div>
      <p class="muted">No transactions in this category for this month.</p>
    `;
  } else {
    const colorMap = buildSourceColorMap(data.transactions);
    normalizeDrilldownSource(colorMap);
    const { selectedSource } = state.drilldown;
    const filtered = filterTransactionsBySource(data.transactions, selectedSource);
    const count = filtered.length;
    const total = filtered.reduce((sum, t) => sum + t.amount, 0);
    const metaHtml = `<p class="drilldown-meta">${count} transaction${count === 1 ? "" : "s"} · Total ${fmtGbp(total)} · Category changes apply to all matching descriptions.</p>`;
    const tabsHtml = renderSourceFilterTabs(colorMap, selectedSource);
    panel.innerHTML = `
      <div class="drilldown-header">
        <h2>${escapeHtml(data.category)} — ${escapeHtml(data.month)}</h2>
        <button type="button" class="drilldown-close">Close</button>
      </div>
      ${tabsHtml}
      ${renderTransactionTable(filtered, metaHtml, { showLegend: false, colorMap, total })}
    `;
    bindSourceFilterTabs(panel);
    bindCategoryEditors(panel);
  }
  panel.querySelector(".drilldown-close").addEventListener("click", closeDrilldown);
}

async function toggleDrilldown(category) {
  if (!state.selectedMonth) return;

  if (
    state.drilldown.category === category &&
    state.drilldown.month === state.selectedMonth
  ) {
    closeDrilldown();
    if (state.currentMonth && !state.currentMonth.empty) {
      renderCategoryTable(state.currentMonth.categories);
    }
    return;
  }

  state.drilldown = {
    month: state.selectedMonth,
    category,
    data: null,
    loading: true,
    selectedSource: null,
  };
  if (state.currentMonth && !state.currentMonth.empty) {
    renderCategoryTable(state.currentMonth.categories);
  }
  renderDrilldownPanel();

  try {
    const url =
      `/api/transactions?month=${encodeURIComponent(state.selectedMonth)}` +
      `&category=${encodeURIComponent(category)}`;
    const data = await fetchJson(url);
    state.drilldown = {
      month: state.selectedMonth,
      category,
      data,
      loading: false,
      selectedSource: null,
    };
    renderDrilldownPanel();
    if (state.currentMonth && !state.currentMonth.empty) {
      renderCategoryTable(state.currentMonth.categories);
    }
  } catch (err) {
    closeDrilldown();
    if (state.currentMonth && !state.currentMonth.empty) {
      renderCategoryTable(state.currentMonth.categories);
    }
    setError(err.message);
  }
}

function renderBenchmark(b) {
  const el = document.getElementById("benchmark");
  el.innerHTML = `
    <div class="benchmark-item"><span>Needs</span>${fmtGbp(b.needs)} (${fmtPct(b.needs_pct)} of spend)</div>
    <div class="benchmark-item"><span>Wants</span>${fmtGbp(b.wants)} (${fmtPct(b.wants_pct)} of spend)</div>
    <div class="benchmark-item"><span>Other</span>${fmtGbp(b.other)}</div>
    <div class="benchmark-item"><span>Implied savings rate</span>${b.savings_rate != null ? fmtPct(b.savings_rate) + " of income" : "—"}</div>
  `;
}

function renderMerchants(merchants) {
  const wrap = document.getElementById("merchants");
  if (!merchants.length) {
    wrap.innerHTML = '<p class="muted" style="padding:1rem">No merchants this month.</p>';
    return;
  }
  const rows = merchants.map((m) => `
    <tr>
      <td>${escapeHtml(m.description)}</td>
      <td class="amount">${fmtGbp(m.amount)}</td>
    </tr>
  `).join("");
  wrap.innerHTML = `
    <table>
      <thead><tr><th>Merchant</th><th class="amount">Amount</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderOverviewMonth(month) {
  closeDrilldown();
  state.currentMonth = month;
  if (month.empty) {
    document.getElementById("summary-cards").innerHTML =
      `<p class="muted">No transactions for ${escapeHtml(month.month)}.</p>`;
    document.getElementById("category-table").innerHTML = "";
    document.getElementById("benchmark").innerHTML = "";
    document.getElementById("merchants").innerHTML = "";
    return;
  }
  renderCards(month);
  renderCategoryTable(month.categories);
  renderBenchmark(month.benchmark);
  renderMerchants(month.top_merchants);
}

function renderUncategorisedBanner(count) {
  const banner = document.getElementById("uncat-banner");
  if (count > 0) {
    banner.textContent =
      `${count} transaction${count === 1 ? "" : "s"} uncategorised — check the Uncategorised tab and update rules/categories.py.`;
    show("uncat-banner");
  } else {
    hide("uncat-banner");
  }
}

function renderMonthSelect() {
  const select = document.getElementById("month-select");
  select.innerHTML = state.months.map((m) =>
    `<option value="${m}"${m === state.selectedMonth ? " selected" : ""}>${m}</option>`
  ).join("");
}

function renderTrends(data) {
  const el = document.getElementById("trends-content");
  if (data.empty) {
    el.innerHTML = '<p class="muted">No data imported yet.</p>';
    return;
  }
  if (data.insufficient_months) {
    el.innerHTML = '<p class="muted">Need at least 2 months of data for month-over-month comparison.</p>';
    return;
  }

  const months = data.months;
  const header = months.map((m) => `<th class="amount">${m}</th>`).join("");
  const body = data.categories.map((cat) => {
    const cells = months.map((m) => {
      const val = data.grid[cat][m];
      return `<td class="amount">${val ? fmtGbp(val) : "—"}</td>`;
    }).join("");
    return `<tr><td>${escapeHtml(cat)}</td>${cells}</tr>`;
  }).join("");
  const totalCells = months.map((m) =>
    `<td class="amount">${fmtGbp(data.totals[m])}</td>`
  ).join("");

  let anomaliesHtml = "";
  if (months.length >= 3) {
    const latest = months[months.length - 1];
    if (data.anomalies.length) {
      anomaliesHtml = `<div class="anomalies"><h2>Anomalies in ${latest}</h2>` +
        data.anomalies.map((a) => `
          <div class="anomaly ${a.direction}">
            <strong>${escapeHtml(a.category)}</strong> ${a.direction} ${a.change_pct.toFixed(0)}%
            (avg ${fmtGbp(a.prior_avg)} → ${fmtGbp(a.latest)})
          </div>
        `).join("") + "</div>";
    } else {
      anomaliesHtml = `<p class="muted anomalies">No significant anomalies in ${latest}.</p>`;
    }
  }

  el.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Category</th>${header}</tr></thead>
        <tbody>${body}</tbody>
        <tfoot><tr><td><strong>TOTAL</strong></td>${totalCells}</tr></tfoot>
      </table>
    </div>
    ${anomaliesHtml}
  `;
}

function renderSubscriptions(data) {
  const el = document.getElementById("subscriptions-content");
  if (!data.items.length) {
    el.innerHTML = '<p class="muted">No recurring subscriptions detected yet (need 3+ months of data).</p>';
    return;
  }
  const rows = data.items.map((item) => `
    <tr>
      <td>${escapeHtml(item.description)}</td>
      <td class="amount">${fmtGbp(item.avg_amount)}</td>
      <td class="amount">${item.months_seen}</td>
    </tr>
  `).join("");
  el.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Description</th>
            <th class="amount">Avg / charge</th>
            <th class="amount">Months seen</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="table-footer">
        Estimated total: ${fmtGbp(data.estimated_monthly)} / month
        (${fmtGbp(data.estimated_yearly)} / year)
      </div>
    </div>
  `;
}

function sortUncategorised(rows) {
  const { key, asc } = state.uncategorisedSort;
  return [...rows].sort((a, b) => {
    let cmp;
    if (key === "amount") {
      cmp = a.amount - b.amount;
    } else {
      cmp = a.description.localeCompare(b.description);
    }
    return asc ? cmp : -cmp;
  });
}

function renderUncategorised(rows) {
  const el = document.getElementById("uncategorised-content");
  if (!rows.length) {
    el.innerHTML = '<p class="muted">Nothing uncategorised — every transaction matched a rule.</p>';
    return;
  }
  const sorted = sortUncategorised(rows);
  const sortInd = (k) => {
    if (state.uncategorisedSort.key !== k) return "";
    return state.uncategorisedSort.asc ? "▲" : "▼";
  };
  const body = sorted.map((r) => `
    <tr>
      <td>${escapeHtml(r.description)}</td>
      <td class="amount">${fmtGbp(r.amount)}</td>
      <td class="category-cell">${renderCategoryEditor({ id: r.id, description: r.description, category: "Uncategorised" })}</td>
    </tr>
  `).join("");
  el.innerHTML = `
    <p class="muted">${rows.length} unique description${rows.length === 1 ? "" : "s"} need rules in rules/categories.py — or assign a category here to update all matching transactions.</p>
    <div class="table-wrap" style="margin-top:0.75rem">
      <table id="uncat-table">
        <thead>
          <tr>
            <th class="sortable" data-sort="description">Description <span class="sort-indicator">${sortInd("description")}</span></th>
            <th class="sortable amount" data-sort="amount">Amount <span class="sort-indicator">${sortInd("amount")}</span></th>
            <th>Category</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
  bindCategoryEditors(el);
  el.querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.uncategorisedSort.key === key) {
        state.uncategorisedSort.asc = !state.uncategorisedSort.asc;
      } else {
        state.uncategorisedSort = { key, asc: true };
      }
      renderUncategorised(state.uncategorised);
    });
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function uniqueYears(months) {
  return [...new Set(months.map((m) => m.slice(0, 4)))].sort();
}

function searchScopeLabel(scope, month, year) {
  if (scope === "month") return month;
  if (scope === "year") return year;
  return "all data";
}

function renderSearchScopeControls() {
  const scope = document.getElementById("search-scope").value;
  const monthLabel = document.getElementById("search-month-label");
  const monthSelect = document.getElementById("search-month");
  const yearLabel = document.getElementById("search-year-label");
  const yearSelect = document.getElementById("search-year");

  const showMonth = scope === "month";
  const showYear = scope === "year";

  monthLabel.classList.toggle("hidden", !showMonth);
  monthSelect.classList.toggle("hidden", !showMonth);
  yearLabel.classList.toggle("hidden", !showYear);
  yearSelect.classList.toggle("hidden", !showYear);
}

function renderSearchSelectors() {
  const monthSelect = document.getElementById("search-month");
  const yearSelect = document.getElementById("search-year");
  const years = uniqueYears(state.months);

  monthSelect.innerHTML = state.months.map((m) =>
    `<option value="${escapeHtml(m)}"${m === state.search.month ? " selected" : ""}>${escapeHtml(m)}</option>`
  ).join("");

  yearSelect.innerHTML = years.map((y) =>
    `<option value="${escapeHtml(y)}"${y === state.search.year ? " selected" : ""}>${escapeHtml(y)}</option>`
  ).join("");

  document.getElementById("search-scope").value = state.search.scope;
  document.getElementById("search-query").value = state.search.query;
  renderSearchScopeControls();
}

function renderSearchResults() {
  const container = document.getElementById("search-results");
  const { loading, data } = state.search;

  if (loading) {
    container.innerHTML = `<p class="muted">Searching…</p>`;
    return;
  }

  if (!data) {
    container.innerHTML = `<p class="muted">Enter a merchant or description and click Search.</p>`;
    return;
  }

  const scopeText = searchScopeLabel(data.scope, data.month, data.year);

  if (data.empty) {
    container.innerHTML = `
      <p class="search-meta">No matches for “${escapeHtml(data.query)}” in ${escapeHtml(scopeText)}.</p>
    `;
    return;
  }

  const metaHtml = `<p class="search-meta">${data.count} transaction${data.count === 1 ? "" : "s"} · Total ${fmtGbp(data.total)} · “${escapeHtml(data.query)}” in ${escapeHtml(scopeText)} · Category changes apply to all matching descriptions.</p>`;
  container.innerHTML = renderTransactionTable(data.transactions, metaHtml);
  bindCategoryEditors(container);
}

async function runSearch() {
  clearError();
  const query = document.getElementById("search-query").value.trim();
  const scope = document.getElementById("search-scope").value;
  const month = document.getElementById("search-month").value;
  const year = document.getElementById("search-year").value;

  if (!query) {
    setError("Enter a search term.");
    return;
  }

  state.search = {
    query,
    scope,
    month: scope === "month" ? month : null,
    year: scope === "year" ? year : null,
    loading: true,
    data: null,
  };
  renderSearchResults();

  const submitBtn = document.getElementById("search-submit");
  submitBtn.disabled = true;

  try {
    let url = `/api/search?q=${encodeURIComponent(query)}&scope=${encodeURIComponent(scope)}`;
    if (scope === "month") {
      url += `&month=${encodeURIComponent(month)}`;
    } else if (scope === "year") {
      url += `&year=${encodeURIComponent(year)}`;
    }
    const data = await fetchJson(url);
    state.search = {
      query,
      scope,
      month: scope === "month" ? month : null,
      year: scope === "year" ? year : null,
      loading: false,
      data,
    };
    renderSearchResults();
  } catch (err) {
    state.search.loading = false;
    state.search.data = null;
    renderSearchResults();
    setError(err.message);
  } finally {
    submitBtn.disabled = false;
  }
}

function switchView(view) {
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".view").forEach((section) => section.classList.add("hidden"));
  show(`view-${view}`);
}

async function loadMonth(month) {
  state.selectedMonth = month;
  const monthData = await fetchJson(`/api/month?month=${encodeURIComponent(month)}`);
  renderOverviewMonth(monthData);
}

async function init() {
  try {
    const summary = await fetchJson("/api/summary");
    hide("loading");

    if (summary.empty) {
      document.getElementById("empty").textContent = summary.message;
      show("empty");
      return;
    }

    state.summary = summary;
    state.months = await fetchJson("/api/months");
    state.selectedMonth = summary.latest_month;
    state.trends = summary.trends || await fetchJson("/api/trends");
    state.subscriptions = summary.subscriptions;
    state.uncategorised = await fetchJson("/api/uncategorised");
    state.categoryOptions = await fetchJson("/api/categories");

    renderMonthSelect();
    renderOverviewMonth(summary.month);
    renderUncategorisedBanner(summary.uncategorised_count);
    renderTrends(state.trends || { empty: true });
    renderSubscriptions(state.subscriptions);
    renderUncategorised(state.uncategorised);

    state.search.month = summary.latest_month;
    state.search.year = uniqueYears(state.months).slice(-1)[0] || null;
    renderSearchSelectors();
    renderSearchResults();

    switchView("overview");
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("hidden"));
    hide("view-trends");
    hide("view-subscriptions");
    hide("view-search");
    hide("view-uncategorised");
    show("view-overview");
  } catch (err) {
    hide("loading");
    setError(err.message);
  }
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
});

document.getElementById("month-select").addEventListener("change", async (e) => {
  clearError();
  try {
    await loadMonth(e.target.value);
  } catch (err) {
    setError(err.message);
  }
});

document.getElementById("search-scope").addEventListener("change", () => {
  state.search.scope = document.getElementById("search-scope").value;
  renderSearchScopeControls();
});

document.getElementById("search-submit").addEventListener("click", () => {
  runSearch();
});

document.getElementById("search-query").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    runSearch();
  }
});

init();
