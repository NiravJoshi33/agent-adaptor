"""Local dashboard pages rendered by the management API process."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from agent_adapter.runtime import RuntimeContext

_STATIC_DIR = Path(__file__).with_name("static")


def _shell(title: str, body: str, page_data: dict | None = None) -> str:
    data_attr = (
        f" data-page='{escape(json.dumps(page_data))}'" if page_data is not None else ""
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    <link rel="stylesheet" href="/dashboard/static/dashboard.css" />
  </head>
  <body class="dashboard-shell"{data_attr}>
    <div class="shell">
      <aside class="sidebar">
        <div class="sidebar-aura sidebar-aura-top"></div>
        <div class="sidebar-aura sidebar-aura-bottom"></div>
        <a class="brand" href="/dashboard/">
          <div class="brand-mark">A</div>
          <div class="brand-copy">
            <div class="eyebrow">Agent Adapter</div>
            <h1>Runtime</h1>
          </div>
        </a>
        <nav class="nav">
          <a href="/dashboard/">
            <span class="nav-index">01</span>
            <span class="nav-copy">
              <strong>Overview</strong>
              <small>Wallet and revenue pulse</small>
            </span>
          </a>
          <a href="/dashboard/capabilities">
            <span class="nav-index">02</span>
            <span class="nav-copy">
              <strong>Capabilities</strong>
              <small>Pricing, drift, availability</small>
            </span>
          </a>
          <a href="/dashboard/agent">
            <span class="nav-index">03</span>
            <span class="nav-copy">
              <strong>Agent</strong>
              <small>Decisions and execution</small>
            </span>
          </a>
          <a href="/dashboard/operations">
            <span class="nav-index">04</span>
            <span class="nav-copy">
              <strong>Operations</strong>
              <small>Wallet, heartbeats, events</small>
            </span>
          </a>
          <a href="/dashboard/metrics">
            <span class="nav-index">05</span>
            <span class="nav-copy">
              <strong>Metrics</strong>
              <small>Revenue, cost, performance</small>
            </span>
          </a>
          <a href="/dashboard/prompt">
            <span class="nav-index">06</span>
            <span class="nav-copy">
              <strong>Prompt</strong>
              <small>Provider instructions, live policy</small>
            </span>
          </a>
          <a href="/dashboard/wallet">
            <span class="nav-index">07</span>
            <span class="nav-copy">
              <strong>Wallet</strong>
              <small>Keys, balances, payment history</small>
            </span>
          </a>
        </nav>
        <div class="sidebar-footer">
          <div class="eyebrow">Local-First Control</div>
          <p>Self-hosted runtime for monetized APIs, wallet-backed execution, and autonomous agent operations.</p>
        </div>
      </aside>
      <main class="main">
        <div class="ambient ambient-one"></div>
        <div class="ambient ambient-two"></div>
        <div class="ambient ambient-grid"></div>
        <div class="main-inner">
          {body}
        </div>
      </main>
    </div>
    <script src="/dashboard/static/dashboard.js"></script>
  </body>
</html>"""


def mount_dashboard(app: FastAPI, runtime: RuntimeContext) -> None:
    app.mount("/dashboard/static", StaticFiles(directory=_STATIC_DIR), name="dashboard-static")

    @app.get("/dashboard/login", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_login(next: str = "/dashboard/"):
        next_path = next if next.startswith("/dashboard") else "/dashboard/"
        if next_path.startswith("/dashboard/login"):
            next_path = "/dashboard/"
        body = """
        <section class="hero compact">
          <div class="hero-copy">
            <div class="eyebrow">Protected Dashboard</div>
            <h2>Sign In</h2>
            <p>Remote management is enabled for this runtime. Enter the management token to start a browser session for the local control plane.</p>
          </div>
          <div class="hero-meta compact">
            <div class="hero-callout">
              <span class="label">Access</span>
              <strong>Browser session only. API routes still require the configured policy.</strong>
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-header">
            <h3>Management Login</h3>
          </div>
          <form id="management-login-form" class="stack-form">
            <label class="stack-field">
              <span>Management Token</span>
              <input id="management-login-token" name="token" type="password" autocomplete="current-password" placeholder="adapter.managementToken" />
            </label>
            <div class="action-row">
              <button type="submit" class="button">Start session</button>
              <span class="muted">The token is exchanged for a short browser session cookie.</span>
            </div>
            <p id="management-login-error" class="card-foot" hidden></p>
          </form>
        </section>
        """
        return _shell(
            "Dashboard Login",
            body,
            {"page": "login", "next": next_path},
        )

    @app.get("/dashboard/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_overview():
        status = await runtime.whoami()
        body = f"""
        <section class="hero">
          <div class="hero-copy">
            <div class="eyebrow">Local Provider Console</div>
            <h2>{escape(status['adapter_name'])}</h2>
            <p>Operate wallet-backed capabilities, pricing, and autonomous execution from one sharp runtime surface.</p>
            <div class="hero-actions">
              <a class="button ghost" href="/dashboard/capabilities">Tune capabilities</a>
              <a class="button secondary" href="/dashboard/agent">Inspect agent</a>
            </div>
          </div>
          <div class="hero-meta">
            <div class="status-pill"><span class="status-dot"></span>{escape(status['agent_status'])}</div>
            <div class="hero-callout">
              <span class="label">Runtime Mode</span>
              <strong>Local, paid, and always auditable</strong>
            </div>
          </div>
        </section>
        <section class="grid cards">
          <article class="card">
            <span class="label">Wallet</span>
            <strong>{escape(status['wallet'])}</strong>
            <p class="card-foot">Primary signing identity for provider execution.</p>
          </article>
          <article class="card">
            <span class="label">Balances</span>
            <strong>{status['balances'].get('sol', 0)} SOL / {status['balances'].get('usdc', 0)} USDC</strong>
            <p class="card-foot">Liquidity ready for execution and x402 settlement.</p>
          </article>
          <article class="card">
            <span class="label">Active Jobs</span>
            <strong>{status['active_jobs']}</strong>
            <p class="card-foot">In-flight capability runs being tracked by the runtime.</p>
          </article>
          <article class="card">
            <span class="label">Earnings Today</span>
            <strong>{status['earnings_today']} USDC</strong>
            <p class="card-foot">Revenue captured by this agent in the current local day.</p>
          </article>
        </section>
        <section class="panel">
          <div class="panel-header">
            <h3>Capability Snapshot</h3>
            <a href="/dashboard/capabilities">Open capability editor</a>
          </div>
          <div id="overview-capabilities" class="table-host"></div>
        </section>
        """
        return _shell("Overview", body, {"page": "overview", "status": status})

    @app.get("/dashboard/capabilities", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_capabilities():
        capabilities = await runtime.list_capabilities()
        body = """
        <section class="hero compact">
          <div class="hero-copy">
            <div class="eyebrow">Provider Sovereignty</div>
            <h2>Capabilities</h2>
            <p>Review discovered endpoints, keep pricing tight, and gate what the agent is allowed to sell.</p>
          </div>
          <div class="hero-meta compact">
            <div class="hero-callout">
              <span class="label">Policy</span>
              <strong>Discovery is automatic. Monetization is curated.</strong>
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-header">
            <h3>Capability Registry</h3>
            <button id="refresh-capabilities" class="button">Refresh Spec</button>
          </div>
          <div id="capabilities-table" class="table-host"></div>
        </section>
        """
        return _shell(
            "Capabilities",
            body,
            {"page": "capabilities", "capabilities": capabilities},
        )

    @app.get("/dashboard/agent", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_agent():
        status = await runtime.whoami()
        decisions = await runtime.list_decisions(25)
        body = """
        <section class="hero compact">
          <div class="hero-copy">
            <div class="eyebrow">Autonomous Operation</div>
            <h2>Agent</h2>
            <p>Inspect recent decisions, tool invocations, and operational state before you let the agent run wider.</p>
          </div>
          <div class="button-row">
            <button id="pause-agent" class="button">Pause</button>
            <button id="resume-agent" class="button secondary">Resume</button>
          </div>
        </section>
        <section class="grid agent-grid">
          <article class="panel">
            <div class="panel-header">
              <h3>Status</h3>
            </div>
            <div id="agent-status-card"></div>
          </article>
          <article class="panel">
            <div class="panel-header">
              <h3>Decision Log</h3>
            </div>
            <div id="decision-log"></div>
          </article>
        </section>
        """
        return _shell(
            "Agent",
            body,
            {"page": "agent", "status": status, "decisions": decisions},
        )

    @app.get("/dashboard/operations", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_operations():
        operations = await runtime.get_operations_overview()
        body = """
        <section class="hero compact">
          <div class="hero-copy">
            <div class="eyebrow">Runtime Operations</div>
            <h2>Operations</h2>
            <p>Keep the provider wallet, platform presence, webhook ingress, and recent execution activity visible from one operational surface.</p>
          </div>
          <div class="hero-meta compact">
            <div class="hero-callout">
              <span class="label">Ops Focus</span>
              <strong>Presence, liquidity, and inbound work signals stay visible while the agent runs.</strong>
            </div>
          </div>
        </section>
        <section class="grid cards metrics-cards">
          <article class="card">
            <span class="label">Signing Wallet</span>
            <strong id="ops-wallet-address"></strong>
            <p class="card-foot">Primary runtime identity used for signing and settlement.</p>
          </article>
          <article class="card">
            <span class="label">Balances</span>
            <strong id="ops-wallet-balances"></strong>
            <p class="card-foot">Live liquidity available for execution, settlement, and escrow.</p>
          </article>
          <article class="card">
            <span class="label">Heartbeats</span>
            <strong id="ops-heartbeat-count"></strong>
            <p class="card-foot">Tracked presence checks stored in the runtime state layer.</p>
          </article>
          <article class="card">
            <span class="label">Pending Events</span>
            <strong id="ops-pending-events"></strong>
            <p class="card-foot">Webhook and SSE messages waiting to be consumed or acknowledged.</p>
          </article>
        </section>
        <section class="grid metrics-grid">
          <article class="panel">
            <div class="panel-header">
              <h3>Heartbeat Presence</h3>
            </div>
            <div id="operations-heartbeats"></div>
          </article>
          <article class="panel">
            <div class="panel-header">
              <h3>Inbound Event Feed</h3>
            </div>
            <div id="operations-events"></div>
          </article>
        </section>
        <section class="grid metrics-grid">
          <article class="panel">
            <div class="panel-header">
              <h3>Connected Platforms</h3>
            </div>
            <div id="operations-platforms"></div>
          </article>
          <article class="panel">
            <div class="panel-header">
              <h3>Recent Job Activity</h3>
            </div>
            <div id="operations-jobs"></div>
          </article>
        </section>
        """
        return _shell(
            "Operations",
            body,
            {"page": "operations", "operations": operations},
        )

    @app.get("/dashboard/metrics", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_metrics():
        metrics = await runtime.get_metrics_summary(30)
        series = await runtime.get_metrics_timeseries(14)
        body = """
        <section class="hero compact">
          <div class="hero-copy">
            <div class="eyebrow">Economic Observability</div>
            <h2>Metrics</h2>
            <p>Track what the runtime is earning, what the agent is spending on inference, and which payment rails are actually pulling their weight.</p>
          </div>
          <div class="hero-meta compact">
            <div class="hero-callout">
              <span class="label">Margin Lens</span>
              <strong>Stable-coin revenue minus estimated LLM burn, visible in one place.</strong>
            </div>
          </div>
        </section>
        <section class="grid cards metrics-cards">
          <article class="card">
            <span class="label">Completed Jobs</span>
            <strong id="metrics-completed-jobs"></strong>
            <p class="card-foot">Successful runs in the selected reporting window.</p>
          </article>
          <article class="card">
            <span class="label">Revenue</span>
            <strong id="metrics-revenue-total"></strong>
            <p class="card-foot">Completed-job revenue grouped across payment currencies.</p>
          </article>
          <article class="card">
            <span class="label">LLM Cost</span>
            <strong id="metrics-llm-cost"></strong>
            <p class="card-foot">Estimated inference spend recorded from actual agent usage.</p>
          </article>
          <article class="card">
            <span class="label">Stable Margin</span>
            <strong id="metrics-margin"></strong>
            <p class="card-foot">Revenue in USD/USDC minus estimated LLM cost.</p>
          </article>
        </section>
        <section class="grid metrics-grid">
          <article class="panel">
            <div class="panel-header">
              <h3>Daily Revenue vs Cost</h3>
            </div>
            <div id="metrics-timeseries"></div>
          </article>
          <article class="panel">
            <div class="panel-header">
              <h3>Payment Mix</h3>
            </div>
            <div id="metrics-payment-mix"></div>
          </article>
        </section>
        <section class="grid metrics-grid">
          <article class="panel">
            <div class="panel-header">
              <h3>Job Outcomes</h3>
            </div>
            <div id="metrics-status-breakdown"></div>
          </article>
          <article class="panel">
            <div class="panel-header">
              <h3>LLM Usage</h3>
            </div>
            <div id="metrics-llm-usage"></div>
          </article>
        </section>
        """
        return _shell(
            "Metrics",
            body,
            {"page": "metrics", "metrics": metrics, "series": series},
        )

    @app.get("/dashboard/prompt", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_prompt():
        prompt = await runtime.get_prompt_settings()
        body = """
        <section class="hero compact">
          <div class="hero-copy">
            <div class="eyebrow">Provider Policy Surface</div>
            <h2>Prompt</h2>
            <p>Adjust the provider strategy layer live. Changes are persisted locally and hot-reloaded into the cached agent loop before the next run.</p>
          </div>
          <div class="hero-meta compact">
            <div class="hero-callout">
              <span class="label">Reload Model</span>
              <strong>File-backed prompt editing with append or replace control.</strong>
            </div>
          </div>
        </section>
        <section class="grid metrics-grid">
          <article class="panel">
            <div class="panel-header">
              <h3>Prompt Controls</h3>
            </div>
            <div id="prompt-editor"></div>
          </article>
          <article class="panel">
            <div class="panel-header">
              <h3>Effective Prompt</h3>
            </div>
            <div id="prompt-preview"></div>
          </article>
        </section>
        """
        return _shell(
            "Prompt",
            body,
            {"page": "prompt", "prompt": prompt},
        )

    @app.get("/dashboard/wallet", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_wallet():
        wallet = await runtime.get_wallet_overview()
        body = """
        <section class="hero compact">
          <div class="hero-copy">
            <div class="eyebrow">Wallet Control Plane</div>
            <h2>Wallet</h2>
            <p>Inspect the signing identity, check operational liquidity, move keys deliberately, and keep recent payment activity close to the runtime.</p>
          </div>
          <div class="hero-meta compact">
            <div class="hero-callout">
              <span class="label">Key Safety</span>
              <strong>Export is local-only. Import updates config and asks for a restart before the runtime switches identity.</strong>
            </div>
          </div>
        </section>
        <section class="grid cards metrics-cards">
          <article class="card">
            <span class="label">Address</span>
            <strong id="wallet-address"></strong>
            <p class="card-foot">Primary signing address used across capability execution and payment flows.</p>
          </article>
          <article class="card">
            <span class="label">Balances</span>
            <strong id="wallet-balances"></strong>
            <p class="card-foot">Operational liquidity currently visible to the runtime.</p>
          </article>
          <article class="card">
            <span class="label">Provider</span>
            <strong id="wallet-provider"></strong>
            <p class="card-foot">Current wallet plugin and cluster context.</p>
          </article>
          <article class="card">
            <span class="label">Low Balance</span>
            <strong id="wallet-alert"></strong>
            <p class="card-foot">Threshold tracking used by runtime notifications and alerts.</p>
          </article>
        </section>
        <section class="grid metrics-grid">
          <article class="panel">
            <div class="panel-header">
              <h3>Key Actions</h3>
            </div>
            <div id="wallet-actions"></div>
          </article>
          <article class="panel">
            <div class="panel-header">
              <h3>Funding Links</h3>
            </div>
            <div id="wallet-faucets"></div>
          </article>
        </section>
        <section class="panel">
          <div class="panel-header">
            <h3>Payment Activity</h3>
          </div>
          <div id="wallet-activity"></div>
        </section>
        """
        return _shell(
            "Wallet",
            body,
            {"page": "wallet", "wallet": wallet},
        )
