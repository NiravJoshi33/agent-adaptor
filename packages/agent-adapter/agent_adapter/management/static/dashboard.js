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
}

init();
