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
