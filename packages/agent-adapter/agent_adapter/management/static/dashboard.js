function pageData() {
  const raw = document.body.dataset.page;
  return raw ? JSON.parse(raw) : {};
}

function badge(status) {
  return `<span class="badge ${status}">${status.replace(/_/g, " ")}</span>`;
}

function formatPricing(pricing) {
  if (!pricing) {
    return `<span class="price-pill">Unset</span>`;
  }
  return `<span class="price-pill">${pricing.amount} ${pricing.currency} <span class="muted">(${pricing.model})</span></span>`;
}

function formatMoney(value, currency = "USD") {
  const amount = Number(value || 0);
  return `${amount.toFixed(amount >= 100 ? 0 : 3).replace(/\.?0+$/, "")} ${currency}`;
}

function setActiveNav() {
  const current = window.location.pathname;
  document.querySelectorAll(".nav a").forEach((link) => {
    const href = link.getAttribute("href");
    if (!href) return;
    const isOverview = href === "/dashboard/" && current === "/dashboard/";
    const isMatch = href !== "/dashboard/" && current.startsWith(href);
    link.classList.toggle("active", isOverview || isMatch);
  });
}

function renderCapabilities(capabilities, targetId) {
  const target = document.getElementById(targetId);
  if (!target) return;
  if (!capabilities.length) {
    target.innerHTML = `<div class="card"><span class="label">No capabilities</span><strong>Nothing discovered yet</strong><p class="card-foot">Refresh the spec or connect a source to populate the registry.</p></div>`;
    return;
  }
  target.innerHTML = `
    <table class="table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Status</th>
          <th>Pricing</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody>
        ${capabilities.map((cap) => `
          <tr>
            <td>
              <div class="capability-name">${cap.name}</div>
              <div class="capability-subtitle">${cap.description || cap.source_ref || ""}</div>
            </td>
            <td>
              <div class="status-stack">
                ${badge(cap.status)}
                ${cap.drift_status && cap.drift_status !== cap.status ? `<div class="drift-copy">drift: ${cap.drift_status.replace(/_/g, " ")}</div>` : `<div class="drift-copy">drift: unchanged</div>`}
              </div>
            </td>
            <td>${formatPricing(cap.pricing)}</td>
            <td><span class="source-chip">${cap.source}</span></td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function renderAgent(status, decisions) {
  const card = document.getElementById("agent-status-card");
  if (card) {
    card.innerHTML = `
      <div class="card">
        <span class="label">Status</span>
        <strong>${status.agent_status}</strong>
        <p class="agent-status-copy">${status.active_jobs} active jobs and ${status.jobs_completed_today} completed today. The runtime remains the source of truth for payment, job state, and tool execution.</p>
      </div>
    `;
  }

  const log = document.getElementById("decision-log");
  if (log) {
    log.classList.add("decision-log");
    if (!decisions.length) {
      log.innerHTML = `<div class="card"><span class="label">Decision Log</span><strong>No recent decisions</strong><p class="card-foot">Once the embedded agent plans or invokes tools, the recent trace will appear here.</p></div>`;
      return;
    }
    log.innerHTML = decisions.map((entry) => `
      <div class="decision-item">
        <div class="decision-header">
          <strong>${entry.action}</strong>
          <span class="decision-time">${entry.created_at || ""}</span>
        </div>
        <pre>${JSON.stringify(entry.detail, null, 2)}</pre>
      </div>
    `).join("");
  }
}

function renderMetrics(metrics, series) {
  const completedJobs = document.getElementById("metrics-completed-jobs");
  if (completedJobs) completedJobs.textContent = `${metrics.completed_jobs || 0}`;

  const revenueTotal = document.getElementById("metrics-revenue-total");
  if (revenueTotal) {
    const revenueByCurrency = metrics.revenue_by_currency || {};
    const text = Object.entries(revenueByCurrency).length
      ? Object.entries(revenueByCurrency)
          .map(([currency, value]) => formatMoney(value, currency))
          .join(" / ")
      : "0";
    revenueTotal.textContent = text;
  }

  const llmCost = document.getElementById("metrics-llm-cost");
  if (llmCost) {
    llmCost.textContent = formatMoney(
      metrics.llm_usage?.estimated_cost || 0,
      metrics.llm_usage?.currency || "USD",
    );
  }

  const margin = document.getElementById("metrics-margin");
  if (margin) {
    margin.textContent = formatMoney(
      metrics.estimated_stable_margin || 0,
      "USD/USDC",
    );
  }

  const timeseries = document.getElementById("metrics-timeseries");
  if (timeseries) {
    const maxValue = Math.max(
      1,
      ...series.map((point) => Math.max(Number(point.revenue || 0), Number(point.llm_cost || 0))),
    );
    timeseries.innerHTML = `
      <div class="metrics-chart">
        ${series.map((point) => `
          <div class="metrics-bar-group">
            <div class="metrics-bars">
              <div class="metrics-bar revenue" style="height:${Math.max((Number(point.revenue || 0) / maxValue) * 100, 4)}%"></div>
              <div class="metrics-bar cost" style="height:${Math.max((Number(point.llm_cost || 0) / maxValue) * 100, 4)}%"></div>
            </div>
            <div class="metrics-day">${point.day.slice(5)}</div>
          </div>
        `).join("")}
      </div>
      <div class="metrics-legend">
        <span><i class="legend-swatch revenue"></i>Revenue</span>
        <span><i class="legend-swatch cost"></i>LLM Cost</span>
      </div>
    `;
  }

  const paymentMix = document.getElementById("metrics-payment-mix");
  if (paymentMix) {
    const rows = metrics.revenue_by_payment_protocol || [];
    paymentMix.innerHTML = rows.length
      ? rows.map((row) => `
          <div class="metric-row">
            <div>
              <strong>${row.payment_protocol}</strong>
              <div class="muted">${row.jobs} jobs</div>
            </div>
            <div class="metric-value">${formatMoney(row.revenue, "USDC")}</div>
          </div>
        `).join("")
      : `<div class="card"><span class="label">Payment Mix</span><strong>No paid jobs yet</strong><p class="card-foot">Once the runtime starts completing paid work, protocol-level revenue will show up here.</p></div>`;
  }

  const statusBreakdown = document.getElementById("metrics-status-breakdown");
  if (statusBreakdown) {
    const rows = Object.entries(metrics.jobs_by_status || {});
    statusBreakdown.innerHTML = rows.length
      ? rows.map(([status, count]) => `
          <div class="metric-row">
            <div>${badge(status)}</div>
            <div class="metric-value">${count}</div>
          </div>
        `).join("")
      : `<div class="card"><span class="label">Job Outcomes</span><strong>No jobs recorded</strong><p class="card-foot">Job lifecycle data will appear here as soon as the runtime starts executing work.</p></div>`;
  }

  const llmUsage = document.getElementById("metrics-llm-usage");
  if (llmUsage) {
    const usage = metrics.llm_usage || {};
    const byModel = usage.by_model || [];
    llmUsage.innerHTML = `
      <div class="metrics-stack">
        <div class="metric-row">
          <div>
            <strong>Total Tokens</strong>
            <div class="muted">${usage.prompt_tokens || 0} prompt / ${usage.completion_tokens || 0} completion</div>
          </div>
          <div class="metric-value">${usage.total_tokens || 0}</div>
        </div>
        <div class="metric-row">
          <div>
            <strong>Average Completed Job</strong>
            <div class="muted">Completed job revenue in the reporting window</div>
          </div>
          <div class="metric-value">${formatMoney(metrics.avg_completed_job_value || 0, "USDC")}</div>
        </div>
        <div class="metric-subsection">
          <div class="label">Model Breakdown</div>
          ${byModel.length ? byModel.map((row) => `
            <div class="metric-row compact">
              <div>
                <strong>${row.model || "unknown"}</strong>
                <div class="muted">${row.calls} calls / ${row.total_tokens} tokens</div>
              </div>
              <div class="metric-value">${formatMoney(row.estimated_cost, usage.currency || "USD")}</div>
            </div>
          `).join("") : `<p class="card-foot">No LLM usage recorded yet.</p>`}
        </div>
      </div>
    `;
  }
}

async function postJSON(url) {
  const response = await fetch(url, { method: "POST" });
  return response.json();
}

async function init() {
  const data = pageData();
  setActiveNav();
  if (data.page === "overview") {
    renderCapabilities(data.status.capabilities || [], "overview-capabilities");
  }

  if (data.page === "capabilities") {
    renderCapabilities(data.capabilities || [], "capabilities-table");
    const refresh = document.getElementById("refresh-capabilities");
    if (refresh) {
      refresh.addEventListener("click", async () => {
        const payload = await postJSON("/manage/capabilities/refresh");
        renderCapabilities(payload.capabilities || [], "capabilities-table");
      });
    }
  }

  if (data.page === "agent") {
    renderAgent(data.status, data.decisions || []);
    const pause = document.getElementById("pause-agent");
    const resume = document.getElementById("resume-agent");
    if (pause) pause.addEventListener("click", () => postJSON("/manage/agent/pause"));
    if (resume) resume.addEventListener("click", () => postJSON("/manage/agent/resume"));
  }

  if (data.page === "metrics") {
    renderMetrics(data.metrics || {}, data.series || []);
  }
}

init();
