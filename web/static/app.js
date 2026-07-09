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
    sort: { key: "date", asc: true },
  },
  currentMonth: null,
  savingCategoryId: null,
  search: { query: "", scope: "month", month: null, year: null, loading: false, data: null, sort: { key: "date", asc: true } },
  transactions: { month: null, data: null, loading: false, selectedSource: null, sort: { key: "date", asc: true } },
  vsAverage: { month: null, data: null, loading: false },
  savingBudgetCategory: null,
  currentMonthProgress: { data: null, loading: false },
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

function fmtDiff(amount) {
  if (amount == null) return "—";
  if (amount === 0) return fmtGbp(0);
  const sign = amount > 0 ? "+" : "-";
  return sign + "£" + Math.abs(amount).toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtDiffPct(value) {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "" : "";
  return sign + value.toFixed(1) + "%";
}

function fmtMonthLabel(monthKey) {
  if (!monthKey) return "";
  const [year, month] = monthKey.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString("en-GB", {
    month: "long",
    year: "numeric",
  });
}

function fmtRemaining(remaining, overBudget) {
  if (remaining == null) return "—";
  if (remaining === 0) return fmtGbp(0);
  const amount = fmtGbp(Math.abs(remaining));
  if (overBudget) return `<span class="over-budget-text">${amount} over</span>`;
  return `${amount} left`;
}

function fmtPctOfIncome(pct) {
  if (pct == null) return "—";
  return pct.toFixed(1) + "% of avg income";
}

function summaryCardHtml(label, metric, spending) {
  const highlight = vsAvgHighlight(metric.diff_pct, metric.diff);
  return `
    <div class="card">
      <div class="card-label">${escapeHtml(label)}</div>
      <div class="card-value ${spending ? "negative" : "positive"}">${fmtGbp(metric.selected)}</div>
      <div class="card-sub muted">12-mo avg ${fmtGbp(metric.average)}</div>
      <div class="card-sub ${highlight}">${fmtDiff(metric.diff)} (${fmtDiffPct(metric.diff_pct)})</div>
    </div>
  `;
}

function profitLossCardHtml(label, amount) {
  const valueClass = amount < 0 ? "negative" : amount > 0 ? "positive" : "";
  return `
    <div class="card">
      <div class="card-label">${escapeHtml(label)}</div>
      <div class="card-value ${valueClass}">${fmtGbp(amount)}</div>
    </div>
  `;
}

function vsAvgHighlight(diffPct, diff) {
  if (diffPct == null) return "";
  if (Math.abs(diffPct) >= 30 && Math.abs(diff) > 20) {
    return diffPct > 0 ? "anomaly up" : "anomaly down";
  }
  return "";
}

function amountClass(amount) {
  if (amount > 0) return "amount positive";
  if (amount < 0) return "amount negative";
  return "amount";
}

function sortTransactions(transactions, { key, asc }) {
  return [...transactions].sort((a, b) => {
    let cmp;
    switch (key) {
      case "date":
        cmp = a.date.localeCompare(b.date);
        break;
      case "description":
        cmp = a.description.localeCompare(b.description);
        break;
      case "source_account":
        cmp = a.source_account.localeCompare(b.source_account);
        break;
      case "amount":
        cmp = a.amount - b.amount;
        break;
      case "category":
        cmp = a.category.localeCompare(b.category);
        break;
      default:
        cmp = 0;
    }
    if (cmp === 0 && key !== "description") {
      cmp = a.description.localeCompare(b.description);
    }
    return asc ? cmp : -cmp;
  });
}

function sortIndicator(sort, key) {
  if (sort.key !== key) return "";
  return sort.asc ? "▲" : "▼";
}

function bindTransactionSort(container, sortState, onUpdate) {
  container.querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sortState.key === key) {
        sortState.asc = !sortState.asc;
      } else {
        sortState.key = key;
        sortState.asc = true;
      }
      onUpdate();
    });
  });
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

function bindSourceFilterTabs(panel, onSelect) {
  panel.querySelectorAll(".drilldown-tabs .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const source = tab.dataset.source || null;
      onSelect(source);
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
        <td class="${amountClass(t.amount)}">${fmtGbp(t.amount)}</td>
        <td class="category-cell">${renderCategoryEditor(t)}</td>
      </tr>
    `;
  }).join("");
}

function renderTransactionTable(transactions, metaHtml, options = {}) {
  const { showLegend = true, colorMap: colorMapOverride, total, sort } = options;
  const colorMap = colorMapOverride || buildSourceColorMap(transactions);
  const legend = showLegend ? renderSourceLegend(colorMap) : "";
  const txRows = renderTransactionRows(transactions, colorMap);
  const footer =
    total != null
      ? `<tfoot>
          <tr class="table-total-row">
            <td colspan="3"><strong>Total</strong></td>
            <td class="${amountClass(total)}"><strong>${fmtGbp(total)}</strong></td>
            <td></td>
          </tr>
        </tfoot>`
      : "";
  const headers = sort
    ? `<tr>
          <th class="sortable" data-sort="date">Date <span class="sort-indicator">${sortIndicator(sort, "date")}</span></th>
          <th class="sortable" data-sort="description">Description <span class="sort-indicator">${sortIndicator(sort, "description")}</span></th>
          <th class="sortable" data-sort="source_account">Account <span class="sort-indicator">${sortIndicator(sort, "source_account")}</span></th>
          <th class="sortable amount" data-sort="amount">Amount <span class="sort-indicator">${sortIndicator(sort, "amount")}</span></th>
          <th class="sortable" data-sort="category">Category <span class="sort-indicator">${sortIndicator(sort, "category")}</span></th>
        </tr>`
    : `<tr>
          <th>Date</th>
          <th>Description</th>
          <th>Account</th>
          <th class="amount">Amount</th>
          <th>Category</th>
        </tr>`;
  return `
    ${metaHtml}
    ${legend}
    <div class="table-wrap">
      <table>
        <thead>
          ${headers}
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
    if (state.transactions.data) renderTransactionsView();
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

  if (state.vsAverage.month) {
    try {
      const vsData = await fetchJson(
        `/api/vs-average?month=${encodeURIComponent(state.vsAverage.month)}`
      );
      state.vsAverage = { month: state.vsAverage.month, data: vsData, loading: false };
      renderVsAverageView();
    } catch {
      /* keep previous vs-average data on refresh failure */
    }
  }

  if (state.currentMonthProgress.data) {
    try {
      const progressData = await fetchJson("/api/current-month");
      state.currentMonthProgress = { data: progressData, loading: false };
      renderCurrentMonthView();
    } catch {
      /* keep previous current-month data on refresh failure */
    }
  }

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
      sort: state.drilldown.sort,
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
      sort: state.search.sort,
    };
    renderSearchResults();
  }

  if (state.transactions.data && state.transactions.month) {
    const prevSource = state.transactions.selectedSource;
    const data = await fetchJson(
      `/api/transactions?month=${encodeURIComponent(state.transactions.month)}`
    );
    state.transactions = {
      month: state.transactions.month,
      data,
      loading: false,
      selectedSource: prevSource,
      sort: state.transactions.sort,
    };
    renderTransactionsView();
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
  const sort = state.drilldown.sort;
  state.drilldown = {
    month: null,
    category: null,
    data: null,
    loading: false,
    selectedSource: null,
    sort,
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
    const sorted = sortTransactions(filtered, state.drilldown.sort);
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
      ${renderTransactionTable(sorted, metaHtml, { showLegend: false, colorMap, total, sort: state.drilldown.sort })}
    `;
    bindSourceFilterTabs(panel, (source) => {
      state.drilldown.selectedSource = source;
      renderDrilldownPanel();
    });
    bindCategoryEditors(panel);
    bindTransactionSort(panel, state.drilldown.sort, renderDrilldownPanel);
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
    sort: state.drilldown.sort,
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
      sort: state.drilldown.sort,
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

function normalizeTransactionsSource(colorMap) {
  const { selectedSource } = state.transactions;
  if (selectedSource && !colorMap[selectedSource]) {
    state.transactions.selectedSource = null;
  }
}

function renderTransactionsMonthSelect() {
  const select = document.getElementById("transactions-month-select");
  if (!select) return;
  select.innerHTML = state.months.map((m) =>
    `<option value="${escapeHtml(m)}"${m === state.transactions.month ? " selected" : ""}>${escapeHtml(m)}</option>`
  ).join("");
}

function renderTransactionsView() {
  const container = document.getElementById("transactions-content");
  const { month, data, loading } = state.transactions;

  if (!month) {
    container.innerHTML = `<p class="muted">Select a month.</p>`;
    return;
  }

  if (loading) {
    container.innerHTML = `
      <div class="drilldown">
        <div class="drilldown-header">
          <h2>All transactions — ${escapeHtml(month)}</h2>
        </div>
        <p class="muted">Loading…</p>
      </div>
    `;
    return;
  }

  if (!data) {
    container.innerHTML = `
      <div class="drilldown">
        <div class="drilldown-header">
          <h2>All transactions — ${escapeHtml(month)}</h2>
        </div>
        <p class="muted">Could not load transactions. Check the error above and try again.</p>
      </div>
    `;
    return;
  }

  if (data.empty) {
    container.innerHTML = `
      <div class="drilldown">
        <div class="drilldown-header">
          <h2>All transactions — ${escapeHtml(data.month)}</h2>
        </div>
        <p class="muted">No transactions for this month.</p>
      </div>
    `;
    return;
  }

  const colorMap = buildSourceColorMap(data.transactions);
  normalizeTransactionsSource(colorMap);
  const { selectedSource } = state.transactions;
  const filtered = filterTransactionsBySource(data.transactions, selectedSource);
  const sorted = sortTransactions(filtered, state.transactions.sort);
  const count = filtered.length;
  const total = filtered.reduce((sum, t) => sum + t.amount, 0);
  const metaHtml = `<p class="drilldown-meta">${count} transaction${count === 1 ? "" : "s"} · Total ${fmtGbp(total)} · Category changes apply to all matching descriptions.</p>`;
  const tabsHtml = renderSourceFilterTabs(colorMap, selectedSource);
  container.innerHTML = `
    <div class="drilldown">
      <div class="drilldown-header">
        <h2>All transactions — ${escapeHtml(data.month)}</h2>
      </div>
      ${tabsHtml}
      ${renderTransactionTable(sorted, metaHtml, { showLegend: false, colorMap, total, sort: state.transactions.sort })}
    </div>
  `;
  bindSourceFilterTabs(container, (source) => {
    state.transactions.selectedSource = source;
    renderTransactionsView();
  });
  bindCategoryEditors(container);
  bindTransactionSort(container, state.transactions.sort, renderTransactionsView);
}

async function loadTransactionsMonth(month) {
  clearError();
  const sort = state.transactions.sort;
  state.transactions = {
    month,
    data: null,
    loading: true,
    selectedSource: null,
    sort,
  };
  renderTransactionsMonthSelect();
  renderTransactionsView();

  try {
    const data = await fetchJson(
      `/api/transactions?month=${encodeURIComponent(month)}`
    );
    state.transactions = {
      month,
      data,
      loading: false,
      selectedSource: null,
      sort,
    };
    renderTransactionsView();
  } catch (err) {
    state.transactions = {
      month,
      data: null,
      loading: false,
      selectedSource: null,
      sort,
    };
    renderTransactionsView();
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

function renderVsAverageMonthSelect() {
  const select = document.getElementById("vs-average-month-select");
  if (!select) return;
  select.innerHTML = state.months.map((m) =>
    `<option value="${escapeHtml(m)}"${m === state.vsAverage.month ? " selected" : ""}>${escapeHtml(m)}</option>`
  ).join("");
}

function renderVsAverage(data) {
  const el = document.getElementById("vs-average-content");
  if (data.empty) {
    el.innerHTML = '<p class="muted">No data imported yet.</p>';
    return;
  }
  if (data.insufficient_data) {
    el.innerHTML = '<p class="muted">Not enough data to compute a 12-month average.</p>';
    return;
  }

  let windowLabel;
  if (data.month_count === 1) {
    windowLabel = `${data.window_start} (1 month)`;
  } else if (data.month_count < 12) {
    windowLabel = `${data.window_start} to ${data.window_end} (${data.month_count} of 12 months in your data)`;
  } else {
    windowLabel = `${data.window_start} to ${data.window_end} (${data.month_count} months)`;
  }

  function summaryCard(label, metric, spending) {
    return summaryCardHtml(label, metric, spending);
  }

  const rows = data.categories.map((cat) => {
    const avgHighlight = vsAvgHighlight(cat.diff_pct, cat.diff);
    const budgetHighlight = cat.expected != null
      ? vsAvgHighlight(cat.expected_diff_pct, cat.expected_diff)
      : "";
    const displayBudget = cat.expected != null ? Math.abs(cat.expected) : "";
    const saving = state.savingBudgetCategory === cat.name;
    const budgetVs = cat.expected != null
      ? `${fmtDiff(cat.expected_diff)} (${fmtDiffPct(cat.expected_diff_pct)})`
      : "—";
    return `
      <tr class="${avgHighlight}">
        <td>${escapeHtml(cat.name)}</td>
        <td class="amount negative">${fmtGbp(cat.selected)}</td>
        <td class="amount">${fmtGbp(cat.average)}</td>
        <td class="amount budget-cell">
          <input type="number" class="budget-input" min="0" step="0.01"
            data-category="${escapeHtml(cat.name)}"
            data-original="${displayBudget}"
            value="${displayBudget}"
            placeholder="—"
            aria-label="Expected monthly budget for ${escapeHtml(cat.name)}"
            ${saving ? "disabled" : ""}>
        </td>
        <td class="amount ${budgetHighlight}">${budgetVs}</td>
        <td class="amount">${fmtDiff(cat.diff)}</td>
        <td class="amount">${fmtDiffPct(cat.diff_pct)}</td>
      </tr>
    `;
  }).join("");

  const total = data.total_spend;
  const budgetTotal = data.budget_total || {};
  const totalAvgHighlight = vsAvgHighlight(total.diff_pct, total.diff);
  const totalBudgetHighlight = budgetTotal.expected != null
    ? vsAvgHighlight(budgetTotal.expected_diff_pct, budgetTotal.expected_diff)
    : "";
  const totalBudgetVs = budgetTotal.expected != null
    ? `${fmtDiff(budgetTotal.expected_diff)} (${fmtDiffPct(budgetTotal.expected_diff_pct)})`
    : "—";
  const totalExpected = budgetTotal.expected != null
    ? fmtGbp(budgetTotal.expected)
    : "—";

  const footer = data.categories.length ? `
    <tfoot>
      <tr class="total-row">
        <td><strong>TOTAL</strong></td>
        <td class="amount negative"><strong>${fmtGbp(total.selected)}</strong></td>
        <td class="amount"><strong>${fmtGbp(total.average)}</strong></td>
        <td class="amount"><strong>${totalExpected}</strong></td>
        <td class="amount ${totalBudgetHighlight}"><strong>${totalBudgetVs}</strong></td>
        <td class="amount ${totalAvgHighlight}"><strong>${fmtDiff(total.diff)}</strong></td>
        <td class="amount"><strong>${fmtDiffPct(total.diff_pct)}</strong></td>
      </tr>
    </tfoot>
  ` : "";

  el.innerHTML = `
    <p class="muted">12-month average: ${escapeHtml(windowLabel)} — baseline is fixed to the most recent months; only the selected month column changes.</p>
    <div class="cards vs-average-cards">
      ${summaryCard("Income", data.income, false)}
      ${summaryCard("Total spend", data.total_spend, true)}
      ${profitLossCardHtml("Profit / loss", data.profit_loss)}
    </div>
    <h2>Spending by category vs average</h2>
    <p class="muted category-hint">Enter an expected monthly amount per category — saved locally in your database.</p>
    <div class="table-wrap">
      <table id="vs-average-table">
        <thead>
          <tr>
            <th>Category</th>
            <th class="amount">${escapeHtml(data.selected_month)}</th>
            <th class="amount">12-mo avg</th>
            <th class="amount">Expected</th>
            <th class="amount">vs budget</th>
            <th class="amount">Difference</th>
            <th class="amount">vs avg</th>
          </tr>
        </thead>
        <tbody>${rows || '<tr><td colspan="7" class="muted">No spending categories.</td></tr>'}</tbody>
        ${footer}
      </table>
    </div>
  `;
  bindBudgetInputs(el);
}

async function saveCategoryBudget(category, rawValue, originalValue) {
  const trimmed = String(rawValue).trim();
  const originalTrimmed = String(originalValue).trim();
  if (trimmed === originalTrimmed) return;

  let payload;
  if (trimmed === "") {
    payload = { category, amount: null };
  } else {
    const amount = parseFloat(trimmed);
    if (Number.isNaN(amount) || amount < 0) {
      setError("Budget must be a zero or positive number.");
      return;
    }
    payload = { category, amount };
  }

  state.savingBudgetCategory = category;
  renderVsAverageView();

  try {
    await fetchJson("/api/category/budget", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    clearError();
    if (state.vsAverage.month) {
      await loadVsAverageMonth(state.vsAverage.month);
    }
    if (state.currentMonthProgress.data) {
      await loadCurrentMonth();
    }
  } catch (err) {
    state.savingBudgetCategory = null;
    renderVsAverageView();
    setError(err.message);
  }
}

function bindBudgetInputs(container) {
  container.querySelectorAll(".budget-input").forEach((input) => {
    const save = () => {
      saveCategoryBudget(
        input.dataset.category,
        input.value,
        input.dataset.original
      );
    };
    input.addEventListener("blur", save);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        input.blur();
      }
    });
  });
}

function renderVsAverageView() {
  const container = document.getElementById("vs-average-content");
  if (state.vsAverage.loading) {
    container.innerHTML = '<p class="muted">Loading…</p>';
    return;
  }
  if (!state.vsAverage.data) {
    container.innerHTML = '<p class="muted">Select a month to compare against the 12-month average.</p>';
    return;
  }
  renderVsAverage(state.vsAverage.data);
}

async function loadVsAverageMonth(month) {
  clearError();
  state.vsAverage = { month, data: null, loading: true };
  renderVsAverageMonthSelect();
  renderVsAverageView();

  try {
    const data = await fetchJson(
      `/api/vs-average?month=${encodeURIComponent(month)}`
    );
    state.vsAverage = { month, data, loading: false };
    state.savingBudgetCategory = null;
    renderVsAverageView();
  } catch (err) {
    state.vsAverage = { month, data: null, loading: false };
    renderVsAverageView();
    setError(err.message);
  }
}

function renderCurrentMonth(data) {
  const el = document.getElementById("current-month-content");
  if (data.insufficient_data) {
    el.innerHTML = '<p class="muted">Not enough data yet for spending progress.</p>';
    return;
  }

  const windowLabel = `${data.window_start} – ${data.window_end}`;
  const totalOver = data.total_remaining < 0;
  const totalRemainingLabel = totalOver ? "Over budget" : "Remaining";
  const totalRemainingValue = totalOver
    ? `<span class="over-budget-text">${fmtGbp(Math.abs(data.total_remaining))}</span>`
    : fmtGbp(data.total_remaining);

  const rows = data.categories.map((cat) => {
    const expectedCell = cat.expected != null
      ? `${fmtGbp(cat.expected)}<span class="expected-source">${cat.expected_source === "budget" ? "budget" : "avg"}</span>`
      : "—";
    const barWidth = cat.progress_pct != null ? cat.progress_pct : 0;
    const barClass = cat.over_budget ? "bar-fill over" : "bar-fill";
    const trackClass = cat.over_budget ? "bar-track over" : "bar-track";
    return `
      <tr>
        <td>${escapeHtml(cat.name)}</td>
        <td class="amount negative">${fmtGbp(cat.spent)}</td>
        <td class="amount">${expectedCell}</td>
        <td class="amount">${fmtRemaining(cat.remaining, cat.over_budget)}</td>
        <td class="progress-cell">
          ${cat.expected != null
            ? `<div class="${trackClass}"><div class="${barClass}" style="width:${barWidth}%"></div></div>`
            : '<span class="muted">—</span>'}
        </td>
      </tr>
    `;
  }).join("");

  const footer = data.categories.length ? `
    <tfoot>
      <tr class="total-row">
        <td><strong>TOTAL</strong></td>
        <td class="amount negative"><strong>${fmtGbp(data.total_spend)}</strong></td>
        <td class="amount"><strong>${fmtGbp(data.total_expected)}</strong></td>
        <td class="amount"><strong>${fmtRemaining(data.total_remaining, totalOver)}</strong></td>
        <td></td>
      </tr>
    </tfoot>
  ` : "";

  el.innerHTML = `
    <h2>${escapeHtml(fmtMonthLabel(data.month))}</h2>
    <p class="muted">Expected amounts use your saved budgets where set; otherwise the 12-month average (${escapeHtml(windowLabel)}).</p>
    <div class="cards current-month-cards">
      ${summaryCardHtml("Income", data.income, false)}
      ${profitLossCardHtml("Profit / loss", data.profit_loss)}
    </div>
    <p class="muted">Average income is based on ${escapeHtml(windowLabel)}.</p>
    <div class="cards current-month-cards">
      <div class="card">
        <div class="card-label">Total spend</div>
        <div class="card-value negative">${fmtGbp(data.total_spend)}</div>
        <div class="card-sub muted">${fmtPctOfIncome(data.current_spend_pct_of_income_avg)}</div>
      </div>
      <div class="card">
        <div class="card-label">Total expected</div>
        <div class="card-value">${fmtGbp(data.total_expected)}</div>
        <div class="card-sub muted">${fmtPctOfIncome(data.expected_spend_pct_of_income_avg)}</div>
      </div>
      <div class="card">
        <div class="card-label">12-mo avg spend</div>
        <div class="card-value negative">${fmtGbp(data.total_spend_avg)}</div>
        <div class="card-sub muted">${fmtPctOfIncome(data.avg_spend_pct_of_income_avg)}</div>
      </div>
      <div class="card">
        <div class="card-label">${totalRemainingLabel}</div>
        <div class="card-value ${totalOver ? "over-budget-text" : ""}">${totalRemainingValue}</div>
      </div>
    </div>
    <h2>Spending by category</h2>
    <div class="table-wrap">
      <table id="current-month-table">
        <thead>
          <tr>
            <th>Category</th>
            <th class="amount">Spent</th>
            <th class="amount">Expected</th>
            <th class="amount">Remaining</th>
            <th>Progress</th>
          </tr>
        </thead>
        <tbody>${rows || '<tr><td colspan="5" class="muted">No spending categories.</td></tr>'}</tbody>
        ${footer}
      </table>
    </div>
  `;
}

function renderCurrentMonthView() {
  const container = document.getElementById("current-month-content");
  if (state.currentMonthProgress.loading) {
    container.innerHTML = '<p class="muted">Loading…</p>';
    return;
  }
  if (!state.currentMonthProgress.data) {
    container.innerHTML = '<p class="muted">Loading current month spending…</p>';
    return;
  }
  renderCurrentMonth(state.currentMonthProgress.data);
}

async function loadCurrentMonth() {
  clearError();
  state.currentMonthProgress = { data: null, loading: true };
  renderCurrentMonthView();

  try {
    const data = await fetchJson("/api/current-month");
    state.currentMonthProgress = { data, loading: false };
    renderCurrentMonthView();
  } catch (err) {
    state.currentMonthProgress = { data: null, loading: false };
    renderCurrentMonthView();
    setError(err.message);
  }
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

  const sorted = sortTransactions(data.transactions, state.search.sort);
  const metaHtml = `<p class="search-meta">${data.count} transaction${data.count === 1 ? "" : "s"} · Total ${fmtGbp(data.total)} · “${escapeHtml(data.query)}” in ${escapeHtml(scopeText)} · Category changes apply to all matching descriptions.</p>`;
  container.innerHTML = renderTransactionTable(sorted, metaHtml, { sort: state.search.sort });
  bindCategoryEditors(container);
  bindTransactionSort(container, state.search.sort, renderSearchResults);
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
    sort: state.search.sort,
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
      sort: state.search.sort,
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
  clearError();
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".view").forEach((section) => section.classList.add("hidden"));
  show(`view-${view}`);
  if (view === "transactions" && !state.transactions.data && !state.transactions.loading) {
    const month = state.transactions.month || state.selectedMonth;
    if (month) loadTransactionsMonth(month);
  }
  if (view === "vs-average" && !state.vsAverage.data && !state.vsAverage.loading) {
    const month = state.vsAverage.month || state.selectedMonth;
    if (month) loadVsAverageMonth(month);
  }
  if (view === "current-month" && !state.currentMonthProgress.data && !state.currentMonthProgress.loading) {
    loadCurrentMonth();
  }
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
    state.transactions.month = summary.latest_month;
    state.vsAverage.month = summary.latest_month;
    renderSearchSelectors();
    renderSearchResults();
    renderTransactionsMonthSelect();
    renderVsAverageMonthSelect();

    switchView("overview");
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("hidden"));
    hide("view-trends");
    hide("view-current-month");
    hide("view-vs-average");
    hide("view-subscriptions");
    hide("view-search");
    hide("view-transactions");
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

document.getElementById("transactions-month-select").addEventListener("change", (e) => {
  loadTransactionsMonth(e.target.value);
});

document.getElementById("vs-average-month-select").addEventListener("change", (e) => {
  loadVsAverageMonth(e.target.value);
});

init();
