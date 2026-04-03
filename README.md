# Agent Adapter Runtime

Turn any API or MCP server into a self-hosted economic agent.

Agent Adapter lets a provider wrap existing capabilities, attach pricing, connect a wallet, join agent platforms, execute work, and get paid without rebuilding their product around any one marketplace, payment rail, or blockchain stack.

This project is currently in **early alpha**. The core runtime works, the main architecture is in place, and there is meaningful test coverage, but the system is still evolving and some integrations are only validated locally or against sandbox/demo environments.

Built for the Open Wallet Foundation hackathon, this repo focuses on a practical provider runtime:

- discover capabilities from OpenAPI and MCP
- expose them to an agent as runtime tools
- price and enable them locally
- execute paid work through a wallet-backed runtime
- support multiple payment rails
- give the provider a local control plane for prompt, wallet, metrics, operations, and capability management

## Why This Exists

Most agent marketplaces assume providers will:

- rewrite their service around a platform
- integrate platform-specific task flows
- learn onchain payments and wallet plumbing
- give up control of pricing, identity, or infra

Agent Adapter takes the opposite approach.

Providers keep:

- their API or MCP server
- their wallet
- their hosting
- their pricing policy
- their platform choices

The runtime handles the glue:

- capability discovery
- tool exposure to the agent
- wallet-backed execution
- payment adapters
- job tracking
- management API and dashboard

## What Works Today

### Capability Sources

- OpenAPI capability discovery
- MCP tool discovery and execution
- dynamic `cap__*` tool generation inside the agent loop
- spec drift detection with local pricing overlays

### Agent Runtime

- configurable agent loop with prompt file support
- prompt append/replace modes
- prompt hot reload
- job creation and lifecycle tracking
- decision logging and management APIs

### Wallet and Payments

- wallet plugin architecture
- local preview wallet for dashboard/demo flows
- raw Solana wallet plugin
- OWS wallet plugin
- `free` payment adapter
- `x402` payment flow
- generic escrow rail with platform-supplied program payloads
- Stripe-backed MPP adapter
- buyer-side MPP challenge retry flow when an SPT is already available

### Platform and Operations

- platform driver interface
- driver discovery via entry points
- driver install/remove CLI
- webhook, SSE, and heartbeat tools
- outbound notification bridge via extension plugins

### Management Surface

- CLI for init, start, status, prompt, capabilities, metrics, drivers, platforms, and wallet actions
- management API
- local dashboard with overview, capabilities, agent, metrics, operations, prompt, and wallet pages

### Testing

- unit tests for discovery, execution, payments, drivers, and runtime behavior
- management surface tests for CLI/API/dashboard flows
- Surfpool-backed integration coverage for paid execution paths

## Architecture

At a high level:

1. A provider points the runtime at an OpenAPI spec or MCP server.
2. The runtime discovers capabilities and stores local monetization settings.
3. The agent receives those capabilities as real tools.
4. Tool execution flows through wallet, payment, job, and extension layers.
5. The provider manages everything through the CLI, API, or dashboard.

Core building blocks:

- `agent-adapter-contracts`
  Common contracts for wallets, payments, extensions, drivers, and runtime events.
- `agent-adapter`
  The runtime, CLI, management API, dashboard, stores, and orchestration logic.
- `packages/plugins/*`
  Bundled wallet, payment, and extension plugins.

## Repo Layout

```text
packages/
  agent-adapter/             Runtime, CLI, dashboard, API
  agent-adapter-contracts/   Shared plugin contracts
  plugins/                   Wallet, payment, and extension plugins
docs/
  agent-adapter-runtime-prd.md
  implementation-notes.md
  milestones.md
simulation/
  dashboard-preview.yaml     Easiest local preview config
  provider_api/              Demo provider API
tests/
  test_runtime_unit.py
  test_management_surface.py
  test_runtime_integration.py
```

## Quickstart

### Requirements

- Python `3.12` or `3.13`
- [`uv`](https://docs.astral.sh/uv/)

### Install

```bash
uv sync
```

### Run The Local Dashboard Preview

This is the fastest way to see the runtime without external dependencies.

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run agent-adapter --config simulation/dashboard-preview.yaml start --api-only
```

Then open:

```text
http://127.0.0.1:9090/dashboard/
```

Useful pages:

- `http://127.0.0.1:9090/dashboard/`
- `http://127.0.0.1:9090/dashboard/capabilities`
- `http://127.0.0.1:9090/dashboard/metrics`
- `http://127.0.0.1:9090/dashboard/operations`
- `http://127.0.0.1:9090/dashboard/prompt`
- `http://127.0.0.1:9090/dashboard/wallet`

## Common CLI Commands

```bash
uv run agent-adapter --config simulation/dashboard-preview.yaml status
uv run agent-adapter --config simulation/dashboard-preview.yaml capabilities list
uv run agent-adapter --config simulation/dashboard-preview.yaml prompt show
uv run agent-adapter --config simulation/dashboard-preview.yaml metrics summary --days 30
uv run agent-adapter --config simulation/dashboard-preview.yaml drivers list
uv run agent-adapter --config simulation/dashboard-preview.yaml wallet address
```

Initialize a fresh runtime:

```bash
uv run agent-adapter --config ./agent-adapter.yaml init --adapter-name my-agent --data-dir ./runtime-data
```

## Example Story

The intended product flow is:

1. discover an API or MCP tool surface
2. curate and price useful capabilities
3. connect a wallet
4. join a platform or respond to platform events
5. let the agent execute work through runtime tools
6. settle payments and track jobs locally
7. monitor outcomes through metrics, operations, and notifications

## OWS / Hackathon Relevance

This project is designed around the idea that agent providers should have a real wallet-backed runtime rather than a prompt wrapped around third-party infra.

OWS matters here because it makes the wallet layer a first-class runtime primitive:

- wallet identity
- signing
- transaction submission
- payment settlement
- provider-controlled custody

The broader goal is to make agent commerce work for ordinary service providers, not just teams willing to hand-roll wallet, chain, payment, and platform integrations from scratch.

## Testing

Run the main local test suites:

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run python -m unittest tests.test_runtime_unit tests.test_management_surface -v
python3 -m compileall packages/agent-adapter packages/agent-adapter-contracts packages/plugins tests
```

Surfpool-backed integration coverage is also available:

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run python -m unittest tests.test_runtime_integration -v
```

## Current Notes

- The dashboard preview uses a local preview wallet plugin, not a real chain wallet.
- Wallet import from the dashboard updates persisted config and requires a restart to swap the in-memory wallet.
- The buyer-side MPP flow assumes the runtime already has a valid shared payment token.
- The Stripe-backed MPP implementation follows the documented flow and local tests, but has not been fully validated against a live production Stripe machine-payments setup in this repo.

## Documentation

- [Product / runtime PRD](docs/agent-adapter-runtime-prd.md)
- [Implementation notes](docs/implementation-notes.md)
- [Milestones](docs/milestones.md)

## Status

The core runtime vision in the PRD is implemented:

- capability discovery
- dynamic tool exposure
- wallet-backed execution
- multiple payment rails
- platform drivers
- management API and dashboard
- metrics and operations tooling

What remains is mostly product polish, richer demo packaging, and deeper live validation against external payment providers and platforms.
