# Agent Adapter Runtime — Product Requirements Document

**Version:** 0.1 — First Draft
**One-liner:** A self-hosted runtime that turns any API or MCP server into an autonomous economic agent — capable of discovering work, getting paid, and participating in agent economies — without the provider writing blockchain, payment, or platform-specific code.

---

## 1. Motivation

Today, if an API provider wants to participate in agent economies, they have to:

- Hand-roll integrations for each ecosystem (Claude tools, OpenAI Agents, MCP, custom SDKs)
- Implement one or more payment protocols (x402, MPP, on-chain escrow)
- Keep all of this updated as platforms and payment rails evolve

This doesn't scale. Every new agent host means a new integration. Every new payment rail means new code. Many providers just want: "Let agents and economies use and pay for my API. I'll keep focusing on my core service."

The Agent Adapter Runtime solves this. It wraps any HTTP API or MCP server as a set of capabilities, exposes those capabilities as jobs, and plugs into different payment protocols via adapters. The provider runs it on their own infrastructure, manages their own keys, and lets the runtime handle the economic plumbing.

AGICitizens is one consumer of this runtime, not the reason it exists. The runtime is platform-agnostic by design.

---

## 2. Core Design Principles

1. **Provider sovereignty** — the runtime is self-hosted and self-custodial. The provider controls their keys, their data, and their pricing. Nothing is custodial.
2. **Discovery is automatic, monetization is manual** — the runtime auto-discovers capabilities from specs. The provider decides which to enable and at what price. No capability goes live without explicit pricing.
3. **The agent decides** — the embedded LLM agent decides which platforms to join, which tasks to bid on, and what price to offer. The provider can influence behavior by customizing the system prompt — adjusting priorities, platform preferences, bidding strategy, or risk tolerance — but the agent makes the final call at runtime.
4. **One adapter, one agent** — each adapter instance is one economic identity with one wallet, one set of capabilities, and one agent brain. If a provider wants multiple personas, they run multiple instances.
5. **Platform-agnostic core** — the runtime knows HTTP, payments, and jobs. It does not know AGICitizens, Moltbook, or any specific platform. Platform-specific flows are the agent's responsibility, navigated by reading platform documentation.
6. **Platform drivers are optional** — for platforms with complex or brittle flows, community-built drivers can be installed as plugins. But the default path is the agent reading docs and using generic tools. If repeated agent failures occur on a platform, that's a signal the platform needs a driver — not that the runtime needs platform-specific code.
7. **Boring technology** — SQLite for local storage, standard HTTP for communication, existing Solana libraries for on-chain work. No novel infrastructure.

---

## 3. High-Level Architecture

```
┌───────────────────────────────────────────────────────────┐
│                  Agent Adapter Runtime                     │
│                  (single self-hosted process)              │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              Embedded Agent (LLM Brain)              │  │
│  │  Reads platform docs, plans actions, makes           │  │
│  │  economic decisions, navigates platform flows         │  │
│  │  Provider-customizable system prompt                  │  │
│  └────────────────────────┬────────────────────────────┘  │
│                           │ tool calls                     │
│                           ▼                                │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐       │
│  │  Capability   │  │  Payment     │  │  Core     │       │
│  │  Registry     │  │  Adapters    │  │  Tools    │       │
│  │              │  │              │  │           │       │
│  │  OpenAPI ──┐ │  │  x402       │  │  HTTP     │       │
│  │  MCP    ──┤ │  │  Escrow     │  │  Secrets  │       │
│  │  Manual ──┘ │  │  MPP        │  │  State    │       │
│  │              │  │  Free       │  │  Wallet   │       │
│  └──────────────┘  └──────────────┘  └───────────┘       │
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐       │
│  │  Job Engine   │  │  Persistence │  │  Mgmt API │       │
│  │  (tracking)   │  │  (SQLite)    │  │  + Dash   │       │
│  └──────────────┘  └──────────────┘  └───────────┘       │
│                                                           │
│  ┌──────────────┐  ┌──────────────────────────────┐       │
│  │  Metrics &    │  │  Platform Drivers             │       │
│  │  Billing      │  │  (optional plugins)           │       │
│  └──────────────┘  └──────────────────────────────┘       │
└────────────────────────┬──────────────────────────────────┘
                         │ capability calls
                         ▼
┌───────────────────────────────────────────────────────────┐
│        Target Service (Provider's API / MCP Server)       │
└───────────────────────────────────────────────────────────┘
```

The adapter is a single self-hosted process that contains everything: the LLM agent brain, the tool surface, persistence, the management dashboard, and the economic plumbing. One adapter instance = one agent identity = one wallet.

The process serves:

- An embedded LLM agent loop that drives all platform interactions and economic decisions
- A management API and dashboard for the provider (configuration, monitoring, prompt customization)
- Outbound HTTP to target services (capability execution) and platforms (registration, bidding, delivery)

---

## 4. Capability Layer

### 4.1 Capability Sources

The runtime discovers what the provider's service can do from three sources:

**OpenAPI spec:**

The runtime fetches an OpenAPI spec (URL or local file), parses operations, and generates capabilities. The provider selects which operations to expose — not every CRUD endpoint should become a capability.

```yaml
capabilities:
  source:
    type: "openapi"
    url: "https://api.my-service.com/openapi.json"
```

The runtime extracts operation IDs, input/output JSON schemas, descriptions, and auth requirements. These become the raw capability inventory.

**MCP server:**

The runtime connects to an MCP server, calls `tools/list`, and registers each tool as a capability (or a curated subset).

```yaml
capabilities:
  source:
    type: "mcp"
    server: "http://localhost:3001"
```

**Manual definitions:**

For services without a spec, or for curated high-level capabilities that combine multiple API calls:

```yaml
capabilities:
  source:
    type: "manual"
  definitions:
    - name: "full_audit"
      description: "Complete security audit of a smart contract"
      inputSchema:
        type: "object"
        properties:
          contract_code:
            type: "string"
        required: ["contract_code"]
      outputSchema:
        type: "object"
        properties:
          report:
            type: "string"
          severity:
            type: "string"
```

### 4.2 Capability Registry

Regardless of source, all capabilities are normalized into a single internal registry:

```
Capability:
  name: string              — unique identifier
  source: openapi | mcp | manual
  sourceRef: string         — operation ID, MCP tool name, or config key
  description: string       — human/LLM-readable description
  inputSchema: JSONSchema   — what the capability accepts
  outputSchema: JSONSchema  — what it returns
  enabled: boolean          — provider toggle
  pricing: PricingConfig    — set by provider (see §5)
```

The agent sees capabilities through the `status` tool and can enumerate them to decide which platforms and tasks to pursue.

### 4.3 Spec Change Detection

The runtime periodically re-fetches specs and compares content hashes.

- **New capability discovered** — added to registry as disabled, flagged in dashboard as "needs pricing"
- **Existing capability schema changed** — flagged for provider review, pricing preserved
- **Capability disappeared from spec** — flagged as stale, active jobs complete normally, no new work accepted

The runtime never silently monetizes a new capability. Discovery is automatic; activation is manual.

---

## 5. Pricing

### 5.1 Where Pricing Lives

Pricing is not in the OpenAPI spec or MCP tool listing — those standards have no pricing concept. Pricing is a local overlay stored in the adapter's SQLite database, managed by the provider through the dashboard or CLI.

When the adapter discovers capabilities from a spec, they appear as "discovered, no pricing set." Capabilities without pricing are not offered to platforms.

### 5.2 Pricing Models

| Model       | Description                        | Use Case                 |
| ----------- | ---------------------------------- | ------------------------ |
| `per_call`  | Flat fee per invocation            | Most API calls           |
| `per_item`  | Fee × count from input field       | Batch operations         |
| `per_token` | Fee based on input/output size     | LLM-wrapping services    |
| `quoted`    | No fixed price; agent bids per job | Variable-complexity work |

For `per_item`, the provider specifies a JSON path to the countable field:

```
pricing:
  model: per_item
  amount: 0.01
  currency: USDC
  itemField: input.leads.length
```

For `quoted`, the provider sets floor and ceiling bounds:

```
pricing:
  model: quoted
  currency: USDC
  floor: 1.00
  ceiling: 50.00
```

The agent uses the floor/ceiling to decide what price to bid. The adapter enforces: never bid below floor, never accept above ceiling.

### 5.3 Pricing Management

Pricing is managed through:

- **Dashboard** — the primary interface. Provider sees all capabilities with their pricing status, clicks to edit, can bulk-set defaults.
- **CLI** — for headless setups:
  ```bash
  agent-adapter capabilities list
  agent-adapter capabilities price enrich_lead --amount 0.02 --model per_call
  agent-adapter capabilities price-default --amount 0.05 --model per_call
  agent-adapter capabilities disable get_company_info
  ```
- **Management API** — for programmatic updates:
  ```
  PUT /manage/capabilities/enrich_lead/pricing
  { "amount": 0.03, "currency": "USDC", "model": "per_call" }
  ```

---

## 6. Job Model

### 6.1 Scope

A job represents **one unit of economic work from the provider's perspective**: the adapter received a request, executed a capability, and produced output.

A job does not model platform-specific task lifecycles. AGICitizens tasks go through OPEN → bids → acceptance → escrow → IN_PROGRESS → delivery → verification → rating → settlement. That's platform choreography — the agent navigates it using generic tools. The job engine only tracks what the adapter directly controls.

### 6.2 Job Structure

```json
{
  "id": "job_a1b2c3",
  "capability": "enrich_lead",
  "input": {
    "email": "alice@example.com",
    "company": "Acme Inc"
  },
  "output": null,
  "status": "pending",
  "payment": {
    "protocol": "solana_escrow",
    "status": "secured",
    "amount": 0.02,
    "currency": "USDC"
  },
  "platform": {
    "name": "agicitizens",
    "taskId": "task_xyz",
    "contractId": null
  },
  "created_at": "2026-04-01T12:00:00Z",
  "completed_at": null
}
```

### 6.3 Job Lifecycle

```
pending → executing → completed
                    → failed
```

That's it. Four states. The job engine tracks:

- Was the capability executed?
- What was the result?
- What's the payment status?

Everything else — bidding, negotiation, escrow locking, verification, rating — happens outside the job engine, driven by the agent through platform-specific API calls using generic HTTP and payment tools.

### 6.4 Relationship to Platform Lifecycles

The agent is responsible for translating between the job model and a platform's lifecycle. For AGICitizens:

| Platform Phase               | Who Handles It          | How                                                              |
| ---------------------------- | ----------------------- | ---------------------------------------------------------------- |
| Discover open tasks          | Agent                   | `net__http_request` to `GET /tasks?status=OPEN`                  |
| Bid on task                  | Agent                   | `net__http_request` to `POST /tasks/:id/bid`                     |
| Escrow lock after acceptance | Agent                   | `pay_escrow__*` tools                                            |
| Execute capability           | Job engine              | Runs the capability, tracks the job                              |
| Deliver output               | Agent                   | `net__http_request` to `POST /tasks/:id/deliver` with job output |
| Await verification           | Agent                   | Polls or listens via SSE                                         |
| Settlement                   | Agent + payment adapter | `pay_escrow__*` or handled by platform                           |

The job engine handles the middle step. The agent handles everything around it.

---

## 7. Payment Adapters

### 7.1 Abstract Interface

Each payment adapter implements three operations:

- `ensure_secured(job)` — "Is it economically safe to run this job?"
- `settle(job, outcome)` — "Release or finalize payment based on the outcome."
- `refund(job, reason)` — "Reverse or compensate."

### 7.2 x402 Adapter

x402 defines HTTP-native payment via 402 responses and signed payment proofs.

- `ensure_secured`: Send HTTP request. If 402 returned, parse payment metadata, sign payment transaction, retry with proof header.
- `settle`: Often implicit — payment is done at call time. Log and audit.
- `refund`: Protocol-dependent; may not be supported by all x402 implementations.

Agent-facing tools:

- `pay_x402__execute` — handle a 402 response end-to-end
- `pay_x402__check_requirements` — inspect what a 402 response demands without paying

### 7.3 Solana Escrow Adapter

For platforms like AGICitizens that use on-chain escrow.

- `ensure_secured`: Prepare and sign a Solana transaction that locks USDC into an escrow PDA.
- `settle`: Sign settle instruction (pay provider, pay verifier, update reputation via CPI).
- `refund`: Sign refund instruction.

Agent-facing tools:

- `pay_escrow__prepare_lock` — build an unsigned escrow lock transaction
- `pay_escrow__sign_and_submit` — sign and submit a prepared transaction
- `pay_escrow__check_status` — check escrow PDA state on-chain

### 7.4 MPP / Stripe Adapter

For fiat/card rails.

- `ensure_secured`: Create or join a payment session via MPP.
- `settle`: Capture the charge.
- `refund`: Reverse the charge.

Agent-facing tools:

- `pay_mpp__open_session`
- `pay_mpp__capture`
- `pay_mpp__refund`

### 7.5 Free Adapter

For testing, development, and free-tier APIs.

- `ensure_secured`: Always returns true.
- `settle`: No-op.
- `refund`: No-op.

### 7.6 Future Rails

New payment adapters are added via config:

```yaml
payments:
  - id: "sol_escrow"
    type: "solana_escrow"
    config:
      rpcUrl: "https://api.devnet.solana.com"
      usdcMint: "..."

  - id: "x402"
    type: "x402"

  - id: "mpp"
    type: "mpp_stripe"
    config:
      apiKey: "..."

  - id: "free"
    type: "free"
```

The provider enables whichever rails they want. The agent chooses the appropriate one based on platform requirements.

---

## 8. Wallet

### 8.1 Generation

On first setup, the adapter generates a Solana keypair. This is the adapter's economic identity — used for signing transactions, proving ownership, and receiving payments.

The keypair is encrypted at rest and stored locally. The provider never needs to interact with Solana tooling directly.

### 8.2 Import

Providers who already have a wallet can import it:

- From a keypair file
- From a base58-encoded private key
- From an environment variable

This supports production deployments where key management is handled externally.

### 8.3 Agent-Facing Wallet Tools

- `wallet__get_address` — returns the adapter's public key
- `wallet__get_balance` — checks SOL and token balances
- `wallet__sign_message` — sign arbitrary bytes (for challenge-response auth flows)
- `wallet__sign_transaction` — sign a prepared Solana transaction

---

## 9. Persistence Layer

### 9.1 Storage Engine

SQLite. Single file, zero configuration, no external dependencies. Lives in the adapter's data directory.

The adapter owns the schema. The agent never writes SQL. All persistence happens through high-level tools.

### 9.2 Schema

```sql
-- Provider's wallet
wallet (
  public_key TEXT PRIMARY KEY,
  encrypted_private_key BLOB,
  created_at TIMESTAMP
)

-- Encrypted credentials per platform
secrets (
  platform TEXT,
  key TEXT,
  encrypted_value BLOB,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  PRIMARY KEY (platform, key)
)

-- General-purpose key-value state with JSON values
state (
  namespace TEXT,
  key TEXT,
  data JSON,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  PRIMARY KEY (namespace, key)
)

-- Discovered capabilities with pricing overlay
capability_config (
  name TEXT PRIMARY KEY,
  enabled BOOLEAN DEFAULT false,
  pricing_amount REAL,
  pricing_currency TEXT,
  pricing_model TEXT,
  pricing_item_field TEXT,
  pricing_floor REAL,
  pricing_ceiling REAL,
  custom_description TEXT,
  source_hash TEXT,
  updated_at TIMESTAMP
)

-- Job tracking
jobs (
  id TEXT PRIMARY KEY,
  capability TEXT,
  platform TEXT,
  platform_ref TEXT,
  status TEXT DEFAULT 'pending',
  input_hash TEXT,
  output_hash TEXT,
  payment_protocol TEXT,
  payment_status TEXT,
  payment_amount REAL,
  payment_currency TEXT,
  llm_input_tokens INTEGER,       -- tokens consumed planning/executing this job
  llm_output_tokens INTEGER,
  llm_estimated_cost REAL,        -- computed from model pricing config
  created_at TIMESTAMP,
  completed_at TIMESTAMP
)

-- Agent decision log (for observability)
decision_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT,                    -- bid, skip, register, deliver, error_recovery
  platform TEXT,
  detail JSON,                    -- structured decision context
  created_at TIMESTAMP
)

-- Platform registrations
platforms (
  base_url TEXT PRIMARY KEY,
  platform_name TEXT,
  agent_id TEXT,
  registration_status TEXT,
  registered_at TIMESTAMP,
  last_active_at TIMESTAMP,
  metadata JSON
)
```

The `state` and `platforms.metadata` columns use SQLite's JSON support. The agent can store arbitrarily structured data and query into it with JSON path expressions. This gives fixed-table discipline with freeform JSON flexibility.

### 9.3 Agent-Facing Persistence Tools

- `secrets__store(platform, key, value)` — encrypted at rest, scoped by platform
- `secrets__retrieve(platform, key)` — returns decrypted value
- `secrets__delete(platform, key)`
- `state__set(namespace, key, data)` — general-purpose JSON key-value
- `state__get(namespace, key)` — returns JSON data
- `state__list(namespace, prefix?)` — list keys in a namespace

The agent uses these to persist API keys, agent IDs, registration metadata, and any operational state it needs across restarts. The adapter handles encryption, schema management, and migrations internally.

---

## 10. Embedded Agent

### 10.1 The Agent Is Part of the Adapter

The LLM agent is not a separate process or external dependency. It runs inside the adapter as an embedded agent loop. When the provider runs `agent-adapter start`, the agent starts with it.

This means the adapter is a complete autonomous economic actor out of the box. The provider doesn't need to wire up their own LLM, write orchestration code, or manage a separate agent process. They configure capabilities, set pricing, and start the adapter. The embedded agent handles everything else: reading platform docs, registering, discovering tasks, bidding, executing capabilities, delivering, and managing payments.

### 10.2 Agent Loop

The embedded agent runs a continuous planning loop:

```
1. Call status__whoami → get current state (balances, platforms, active jobs, capabilities)
2. For each registered platform:
   a. Check for pending actions or new tasks matching capabilities
   b. Evaluate opportunities against pricing config and current workload
   c. Bid on suitable tasks
   d. Execute accepted jobs (call cap__* tools)
   e. Deliver results
   f. Monitor payment settlement
3. For unregistered platforms (if platform discovery is enabled):
   a. Fetch platform docs
   b. Evaluate if platform is worth joining
   c. Register if capabilities match
4. Handle housekeeping: heartbeats, credential renewal, state cleanup
5. Sleep / wait for events, then repeat
```

The agent uses the same tool surface described in §11. The tools are not exposed externally — they exist solely for the embedded agent's use.

### 10.3 LLM Provider Configuration

The adapter needs an LLM to power the agent brain. The provider configures this during setup:

```yaml
agent:
  provider: "anthropic" # or "openai", "openrouter", etc.
  model: "claude-sonnet-4-20250514"
  apiKey: "${ANTHROPIC_API_KEY}" # from env var
  maxTokens: 4096
  temperature: 0
```

The adapter ships with support for major LLM providers. The provider supplies their own API key. The adapter does not include or subsidize LLM costs — the provider pays for their agent's intelligence directly.

### 10.4 Provider-Customizable System Prompt

The provider can customize the agent's behavior by editing a system prompt file. This is the primary mechanism for adjusting strategy without writing code.

The adapter ships with a default system prompt that covers:

- How to use each tool
- General platform interaction patterns
- Capability matching logic
- Error recovery strategies

The provider can override or extend this with their own instructions:

```yaml
agent:
  systemPromptFile: "./prompts/system.md" # provider's custom prompt
  appendToDefault: true # true = add to default, false = replace entirely
```

Example provider customizations:

```markdown
## My Pricing Strategy

- Never bid below 80% of my configured price
- For tasks with deadline under 5 minutes, add a 20% rush premium
- Prefer AGICitizens tasks over other platforms when available

## Platform Preferences

- Always register on AGICitizens first
- Only register on other platforms if I have spare capacity (< 3 active jobs)

## Risk Tolerance

- Don't accept tasks from requesters with reputation below 30
- Don't accept tasks with budget above 50 USDC until I have 10+ completed tasks

## Communication Style

- When bidding, mention my specific capabilities relevant to the task
- Keep delivery messages concise and technical
```

This keeps the adapter's economic behavior tunable without requiring code changes or driver development. The provider adjusts a markdown file, restarts (or the adapter hot-reloads), and the agent behaves differently.

### 10.5 Dashboard Prompt Editor

The dashboard includes a prompt editor page where the provider can:

- View the current combined system prompt (default + custom)
- Edit the custom prompt section
- See a history of prompt changes
- Test prompt changes against recent task examples before committing

### 10.6 Agent Observability

The dashboard surfaces what the agent is doing:

- **Decision log** — a stream of the agent's recent decisions: "Saw task X, decided not to bid (price below floor)," "Bid on task Y at $0.03," "Registered on platform Z"
- **Tool call history** — which tools the agent called, in what order, with what results
- **Error recovery attempts** — when the agent hit an error and how it responded

This is essential because the agent is autonomous. The provider needs visibility into why the agent did or didn't do something, without reading raw LLM logs.

---

## 11. Metrics and Billing

### 11.1 Purpose

The adapter tracks both earnings and costs so the provider can see actual profit margins per capability, per platform, and over time.

### 11.2 What Gets Tracked

**Earnings (per job):**

- Payment received (amount, currency, protocol)
- Platform the job came from
- Capability used
- Timestamp

**Costs (per job):**

- LLM tokens consumed by the agent brain for this job's planning and execution
- Estimated LLM cost based on provider's model pricing
- Target service cost (if the provider's API has metered billing — entered manually or via config)
- Solana transaction fees (SOL spent on escrow, registration, etc.)

**Aggregated metrics:**

- Revenue per capability (daily, weekly, monthly)
- Cost per capability
- Profit margin per capability
- Revenue per platform
- Total jobs completed, success rate, average earnings
- LLM token usage over time
- Wallet balance trend

### 11.3 LLM Cost Tracking

Since the agent runs on the provider's LLM API key, the adapter tracks token consumption per agent loop iteration and per job:

```sql
-- Added to jobs table
llm_input_tokens INTEGER,
llm_output_tokens INTEGER,
llm_estimated_cost REAL         -- computed from model pricing config
```

The provider configures their model's pricing:

```yaml
agent:
  model: "claude-sonnet-4-20250514"
  pricing:
    inputPer1kTokens: 0.003
    outputPer1kTokens: 0.015
```

The adapter multiplies token counts by these rates to estimate cost per job. This is approximate — the provider's actual bill comes from their LLM provider — but it's good enough for margin analysis.

### 11.4 Dashboard Metrics Page

The dashboard includes a metrics page showing:

- Earnings vs costs chart over time
- Profit margin per capability (bar chart)
- Platform comparison (which platform is most profitable?)
- LLM cost breakdown (how much of my earnings go to the agent's brain?)
- Wallet balance trend

### 11.5 Schema Additions

```sql
-- Metrics aggregation table (materialized daily)
daily_metrics (
  date TEXT,
  capability TEXT,
  platform TEXT,
  jobs_completed INTEGER,
  jobs_failed INTEGER,
  revenue REAL,
  llm_cost REAL,
  tx_fees REAL,
  service_cost REAL,
  net_profit REAL,
  PRIMARY KEY (date, capability, platform)
)
```

---

## 12. Tool Surface

### 12.1 Namespacing

Note: These tools are consumed by the embedded agent (§10), not exposed externally. The agent loop calls them during its planning and execution cycles.

All tools follow a namespace convention so routing is unambiguous:

```
prefix__tool_name

net__     → network/HTTP tools
pay_*__   → payment adapter tools (scoped by adapter)
cap__     → capability execution tools
wallet__  → wallet operations
secrets__ → credential management
state__   → general persistence
status__  → adapter introspection
```

### 12.2 Core Tools (Mandatory, Always Available)

**Network:**

- `net__http_request` — generic HTTP client with support for all methods, headers, body, and SSE streaming. This is how the agent interacts with any platform API.
- `net__fetch_spec` — fetch and parse an OpenAPI spec or MCP tool listing. Returns structured capability information.

**Wallet:**

- `wallet__get_address` — adapter's public key
- `wallet__get_balance` — SOL + token balances
- `wallet__sign_message` — sign arbitrary bytes
- `wallet__sign_transaction` — sign a prepared Solana transaction

**Secrets:**

- `secrets__store` — store encrypted credential
- `secrets__retrieve` — retrieve decrypted credential
- `secrets__delete` — delete credential

**State:**

- `state__set` — store JSON data
- `state__get` — retrieve JSON data
- `state__list` — list keys

**Status:**

- `status__whoami` — returns the adapter's full current state in one call:

```json
{
  "wallet": "So1abc...def",
  "sol_balance": 0.05,
  "usdc_balance": 12.5,
  "registered_platforms": [
    {
      "url": "https://api.agicitizens.com",
      "agent_id": "mybot.agicitizens",
      "status": "active",
      "last_active": "2026-04-01T11:55:00Z"
    }
  ],
  "capabilities": [
    {
      "name": "enrich_lead",
      "enabled": true,
      "pricing": { "model": "per_call", "amount": 0.02, "currency": "USDC" }
    }
  ],
  "active_jobs": 2,
  "jobs_completed_today": 14,
  "earnings_today": 0.28,
  "costs_today": 0.04,
  "net_profit_today": 0.24,
  "payment_adapters": ["x402", "solana_escrow"],
  "agent_status": "running"
}
```

This is the agent's grounding point at the start of every planning loop — a single call to understand the full current state before making decisions.

### 12.3 Payment Tools (Loaded Based on Config)

Each enabled payment adapter registers its own namespaced tools:

**x402:**

- `pay_x402__execute` — handle a 402 response end-to-end
- `pay_x402__check_requirements` — inspect payment demands without paying

**Solana Escrow:**

- `pay_escrow__prepare_lock` — build unsigned escrow transaction
- `pay_escrow__sign_and_submit` — sign and submit
- `pay_escrow__check_status` — check on-chain escrow state

**MPP:**

- `pay_mpp__open_session`
- `pay_mpp__capture`
- `pay_mpp__refund`

### 12.4 Capability Tools (Generated from Spec Ingestion)

Each enabled, priced capability gets a tool:

- `cap__enrich_lead` — execute the enrich_lead capability against the target service
- `cap__analyze_contract` — execute the analyze_contract capability

These are generated dynamically from the capability registry.

### 12.5 Optional Tools (Provider Selects During Setup)

- **Platform discovery** — auto-fetch and index platform docs (citizen.md, llms.txt, openapi.json) from known or provided URLs
- **Job history and analytics** — queryable log of past jobs, success rates, earnings over time
- **Heartbeat / availability broadcasting** — periodic pings to registered platforms to maintain online status
- **SSE listener** — subscribe to platform event streams for real-time task notifications
- **Webhook receiver** — accept inbound webhooks from platforms that push events
- **Notification bridge** — forward alerts to provider via Telegram or other channels
- **Metrics export** — export metrics to external systems (Prometheus, CSV, JSON API)

### 12.6 Platform Driver Tools (Optional Plugins)

Platform drivers, when installed, register their own namespaced tools:

- `drv_agic__register` — hypothetical AGICitizens driver tool
- `drv_agic__bid_on_task` — hypothetical

Drivers are community-built, installed by the provider, and entirely optional. The runtime functions without any drivers installed.

---

## 13. Platform Interaction Model

### 13.1 The Default Path: Agent-Driven Navigation

The default way the adapter interacts with any platform is through the agent reading platform documentation and using generic tools.

For AGICitizens, the flow would be:

1. Agent uses `net__http_request` to fetch `citizen.md` and `/openapi.json`
2. Agent reads the registration flow, checks name/wallet availability via API
3. Agent uses `pay_x402__execute` to handle the registration payment
4. Agent uses `secrets__store` to persist the returned API key
5. Agent uses `state__set` to record the platform registration
6. Agent discovers open tasks via `net__http_request` to `GET /tasks?status=OPEN`
7. Agent matches tasks against its capabilities (from `status__whoami`)
8. Agent bids using `net__http_request` to `POST /tasks/:id/bid`
9. On acceptance, agent uses `pay_escrow__*` tools to lock escrow
10. Agent executes the matching capability via `cap__*` tools
11. Agent delivers via `net__http_request` to `POST /tasks/:id/deliver`
12. Agent monitors via SSE or polling for verification and settlement

The runtime provides the muscle. The agent provides the brain.

### 13.2 When This Works

This approach works well for platforms that:

- Have clear, well-structured API documentation (OpenAPI spec, citizen.md, llms.txt)
- Have relatively linear flows without excessive branching
- Provide helpful error messages that let the agent self-correct
- Offer endpoints like `pending-actions` that reduce the agent's planning burden

### 13.3 When This Struggles

The agent-driven approach may struggle when:

- Platform flows have complex conditional branching
- Error messages are opaque and don't guide recovery
- Multiple platform API calls must be coordinated atomically
- The platform has undocumented requirements or implicit conventions

### 13.4 The Escalation Path: Platform Drivers

When repeated agent failures indicate that a platform's flows are too complex for LLM-driven navigation, the solution is a platform driver — not changes to the runtime core.

Platform drivers:

- Are separate packages, not part of the runtime repo
- Can be built by the platform itself, by the community, or by the provider
- Register higher-level tools that encapsulate multi-step platform flows
- Use the runtime's core abstractions (HTTP, payments, persistence) internally
- Are installed by the provider via the dashboard or CLI

The runtime provides a plugin interface for drivers. The spec for that interface is:

```typescript
interface PlatformDriver {
  name: string; // e.g. "agicitizens"
  namespace: string; // tool prefix, e.g. "drv_agic"
  tools: ToolDefinition[]; // tools this driver provides
  initialize(runtime: RuntimeAPI): Promise<void>;
  shutdown(): Promise<void>;
}
```

Drivers get access to the runtime's core APIs (HTTP client, payment adapters, persistence) and expose domain-specific tools that agents can use instead of raw HTTP calls.

### 13.5 The Declaration

The adapter's documentation and README should clearly state:

> The Agent Adapter Runtime provides platform-agnostic tools for economic participation. For platforms with clear, well-documented APIs, agents can navigate flows directly using generic HTTP and payment tools. For platforms with complex multi-step flows, optional platform drivers provide higher-level tools that encapsulate platform-specific choreography. The runtime ships with no platform drivers. Community-built drivers are welcome and can be installed as plugins.

---

## 14. Setup and Configuration

### 14.1 Interactive CLI Setup

First-run experience follows the checklist pattern (similar to Astro or Next.js CLI):

```
$ agent-adapter init

  Agent Adapter Runtime — Setup

  ─── Wallet ───────────────────────────────────

  ● Generate new wallet
  ○ Import existing keypair (file path)
  ○ Import from environment variable

  ✓ Wallet created: So1abc...def
  ✓ Keypair encrypted and stored at ./data/wallet.enc

  ─── Capability Source ────────────────────────

  Where are your capabilities defined?
  ● OpenAPI spec
    URL: https://api.my-service.com/openapi.json
    ✓ Found 12 operations

  ─── Agent Brain ──────────────────────────────

  LLM provider:
  ● Anthropic (Claude)
  ○ OpenAI
  ○ OpenRouter

  Model: claude-sonnet-4-20250514

  API key: (reads from ANTHROPIC_API_KEY env var)
  ✓ API key found

  ─── Payment Adapters ─────────────────────────

  How will your service get paid?
  (space to select, enter to confirm)

  ● x402 (HTTP-native payments)
  ○ Solana escrow (on-chain escrow for task economies)
  ○ MPP / Stripe (fiat/card rails)
  ● Free tier (testing / development)

  ─── Optional Tools ───────────────────────────

  ● Platform discovery (fetch and index platform docs)
  ● Heartbeat broadcasting
  ○ SSE listener
  ○ Webhook receiver
  ● Job history and analytics
  ● Metrics and billing
  ○ Notification bridge (Telegram)

  ─── Platform Drivers ─────────────────────────

  No drivers installed. Install later via CLI or dashboard.

  ─────────────────────────────────────────────

  ✓ Config written to ./agent-adapter.yaml
  ✓ Database initialized at ./data/adapter.db
  ✓ Default system prompt written to ./prompts/system.md
  ✓ Dashboard available at http://localhost:9090

  Next steps:
  1. Open the dashboard to set pricing for your capabilities
  2. Optionally edit ./prompts/system.md to customize agent behavior
  3. Run `agent-adapter start` to begin

```

### 14.2 Config File

The setup produces `agent-adapter.yaml`:

```yaml
adapter:
  name: "my-crm-agent"
  dataDir: "./data"
  dashboard:
    port: 9090
    bind: "127.0.0.1" # local-only by default

wallet:
  type: "generated" # or "imported"
  path: "./data/wallet.enc"

agent:
  provider: "anthropic" # anthropic | openai | openrouter
  model: "claude-sonnet-4-20250514"
  apiKey: "${ANTHROPIC_API_KEY}" # resolved from env var
  maxTokens: 4096
  temperature: 0
  systemPromptFile: "./prompts/system.md" # provider's custom prompt
  appendToDefault: true # true = extend default, false = replace
  pricing: # for LLM cost tracking
    inputPer1kTokens: 0.003
    outputPer1kTokens: 0.015
  loopInterval: 30 # seconds between agent planning loops

capabilities:
  source:
    type: "openapi"
    url: "https://api.my-service.com/openapi.json"
    refreshInterval: "1h" # re-fetch spec periodically

payments:
  - id: "x402"
    type: "x402"
  - id: "free"
    type: "free"

tools:
  optional:
    platformDiscovery: true
    heartbeat: true
    sseListener: false
    webhookReceiver: false
    jobHistory: true
    metrics: true
    notifications: false

drivers: []
```

Pricing for capabilities is not in the config file — it lives in the SQLite database and is managed through the dashboard or CLI.

### 14.3 CLI Commands

```bash
agent-adapter init                          # interactive setup
agent-adapter start                         # start the runtime + embedded agent
agent-adapter status                        # print current state (same as status__whoami)

# Capability management
agent-adapter capabilities list             # list all discovered capabilities
agent-adapter capabilities refresh          # re-fetch spec and update registry
agent-adapter capabilities price <n> --amount 0.02 --model per_call
agent-adapter capabilities price-default --amount 0.05 --model per_call
agent-adapter capabilities enable <n>
agent-adapter capabilities disable <n>

# Agent management
agent-adapter agent prompt                  # print current combined system prompt
agent-adapter agent prompt --edit           # open prompt file in $EDITOR
agent-adapter agent decisions               # tail recent agent decision log
agent-adapter agent pause                   # pause agent loop (adapter stays running)
agent-adapter agent resume                  # resume agent loop

# Platform management
agent-adapter platforms list                # list registered platforms
agent-adapter platforms add <url>           # trigger agent to register on a platform

# Wallet
agent-adapter wallet address                # print public key
agent-adapter wallet balance                # print balances
agent-adapter wallet export                 # export private key (with confirmation)
agent-adapter wallet import <path>          # import keypair

# Metrics
agent-adapter metrics summary               # print earnings, costs, margins
agent-adapter metrics export --format csv   # export metrics data

# Drivers
agent-adapter drivers list                  # list installed drivers
agent-adapter drivers install <path|url>    # install a platform driver
agent-adapter drivers remove <n>            # remove a driver
```

---

## 15. Dashboard

### 15.1 Purpose

A local web dashboard for the provider to monitor and configure the adapter without reading logs or querying the database.

### 15.2 Security Model

The dashboard is **local-only by default** — bound to `127.0.0.1`. It manages private keys and credentials, so it must never be exposed to the internet without the provider explicitly configuring authentication and TLS. If remote access is needed, the provider sets that up themselves.

### 15.3 Pages

**Overview / Home:**

- Wallet address (copyable)
- SOL and USDC balances
- Registered platforms with status
- Active jobs, completed today, earnings today
- Earnings vs costs sparkline (last 7 days)
- Adapter uptime and health indicator

**Capabilities:**

- Table of all discovered capabilities: name, source, pricing status, enabled/disabled, call count, success rate
- Capabilities without pricing flagged as "needs pricing"
- Inline pricing editor
- Bulk "set default pricing" action
- "Refresh from spec" button
- Toggle enable/disable per capability

**Platforms:**

- List of platforms the agent has registered on
- Per platform: URL, agent ID, registration status, API key status (stored/missing), last activity
- Per-platform earnings and job history summary
- "Register on new platform" action

**Jobs:**

- Sortable/filterable table: status, capability, platform, payment status, timestamps
- Click into a job for full detail: input summary, output summary, payment trace, LLM token cost

**Agent:**

- Current agent status: running, paused, or errored
- Decision log: stream of recent agent decisions with reasoning
- Tool call history: which tools called, in what order, results
- System prompt viewer and editor (default + custom, with diff view)
- Prompt change history
- "Pause agent" / "Resume agent" controls

**Metrics:**

- Earnings vs costs chart over time (daily, weekly, monthly)
- Profit margin per capability (bar chart)
- Platform comparison (which platform is most profitable?)
- LLM cost breakdown (what percentage of earnings goes to the agent brain?)
- Wallet balance trend
- Export to CSV

**Wallet:**

- Balances with refresh
- Recent transaction history
- "Export private key" behind confirmation dialog with warning and short-lived CLI-generated token
- "Import new keypair" option
- Fund wallet instructions (devnet faucet link or deposit address)

**Settings:**

- Payment adapters: which are enabled, configuration for each
- Agent LLM configuration: provider, model, token pricing
- Optional tools: toggle on/off
- Platform drivers: installed drivers, install new
- Config file viewer with validation
- Log tail viewer

### 15.4 Management API

The dashboard is backed by a local HTTP API. Advanced users can call it directly:

```
GET    /manage/status
GET    /manage/capabilities
PUT    /manage/capabilities/:name/pricing
PUT    /manage/capabilities/:name/toggle
POST   /manage/capabilities/refresh
GET    /manage/platforms
GET    /manage/jobs
GET    /manage/jobs/:id
GET    /manage/wallet
POST   /manage/wallet/export          # requires CLI-generated confirmation token
GET    /manage/agent/status
GET    /manage/agent/decisions?tail=50
GET    /manage/agent/prompt
PUT    /manage/agent/prompt
POST   /manage/agent/pause
POST   /manage/agent/resume
GET    /manage/metrics?period=7d
GET    /manage/metrics/export?format=csv
GET    /manage/config
PUT    /manage/config
GET    /manage/logs?tail=100
```

---

## 16. Platform Registration and Onboarding

### 16.1 How It Works

Registration on a platform is the embedded agent's responsibility. The agent reads platform documentation, discovers the registration flow, and executes it using the adapter's tools.

The adapter provides the infrastructure the agent needs:

- `wallet__get_address` for the wallet public key
- `wallet__sign_message` for challenge-response auth
- `pay_x402__execute` for registration payments
- `secrets__store` for persisting the returned API key
- `state__set` for recording registration metadata

The provider can influence which platforms the agent registers on via the custom system prompt (§10.4). For example: "Always register on AGICitizens first. Only register on other platforms if I have spare capacity."

### 16.2 Persistence of Registration Outcomes

The adapter stores registration results in the `platforms` table and credentials in the `secrets` table. This is critical: if the adapter process crashes after registration but before the agent persists the API key, the key must not be lost.

The default system prompt instructs the agent to call `secrets__store` immediately upon receiving any credential, before doing anything else with it. This is a hard safety rule in the default prompt, not just a best practice.

### 16.3 Recovery

If an API key is lost (database corruption, migration error), the agent uses wallet-based recovery if the platform supports it (e.g., AGICitizens' challenge-response key rotation). The adapter's wallet is the durable identity anchor. API keys are renewable; the wallet is not.

---

## 17. Error Handling and Failure Model

### 17.1 Capability Execution Failures

When a capability call fails (target service returns error, timeout, malformed response):

- The job engine marks the job as `failed` with the error detail
- The agent decides whether to retry, report, or abandon
- The adapter does not auto-retry — the agent controls retry strategy

### 17.2 Payment Failures

Payment failures are surfaced to the agent with structured error information:

- Insufficient balance → agent sees the shortfall amount
- Transaction rejected → agent sees the rejection reason
- Timeout → agent decides whether to retry or abort

### 17.3 Platform Interaction Failures

When the agent makes a wrong platform API call (wrong order, missing field, status conflict):

- The platform returns an error
- The agent reads the error and decides next steps
- If the platform has good error messages (like AGICitizens' structured errors), the agent can self-correct
- If the agent repeatedly fails on a specific platform flow, that's the signal for a platform driver

The adapter does not try to intercept or fix platform interaction errors. That's the agent's domain. Rate limiting toward platforms is also the agent's responsibility — the adapter does not enforce limits on the agent's outbound HTTP calls.

### 17.4 Spec Change Failures

When the provider's API or MCP server changes and a capability's schema evolves:

- Active jobs that were started under the old schema will likely fail when the target service rejects the old format
- The job engine marks them as `failed` with the error detail
- The adapter flags the capability as "schema changed" in the dashboard
- The agent stops bidding on new work for that capability until the provider reviews the change

This is an accepted tradeoff. The adapter cannot gracefully migrate in-flight jobs when the underlying service changes — that's a provider-side concern. The adapter's job is to detect the change, surface it, and stop taking new work until the provider confirms the new schema.

---

## 18. Technology

| Layer     | Choice                                   | Why                                                   |
| --------- | ---------------------------------------- | ----------------------------------------------------- |
| Runtime   | Node.js / TypeScript                     | Solana ecosystem alignment, MCP tooling compatibility |
| Agent LLM | Anthropic Claude (default), configurable | Best tool-use performance; provider can swap          |
| Storage   | SQLite                                   | Zero-config, single-file, self-hostable               |
| Solana    | @solana/web3.js + tweetnacl              | Standard Solana libraries                             |
| Dashboard | Embedded SPA served by runtime           | No separate build/process                             |
| Config    | YAML                                     | Human-readable, well-tooled                           |
| CLI       | Commander.js or similar                  | Standard Node CLI framework                           |

The adapter is a single process: embedded agent loop + tool surface + management API + dashboard. No external dependencies beyond an LLM API key and the provider's target service.

---

## 19. What This Is Not

- **Not a general-purpose agent framework** — the adapter is purpose-built for economic agency. It turns APIs into participants in agent economies. It's not a chatbot, an assistant, or a general orchestration tool.
- **Not a custodial wallet service** — the provider holds their own keys on their own infrastructure. The adapter never sends keys off-device.
- **Not an AGICitizens product** — AGICitizens is one platform the adapter can work with. The adapter works equally well with any platform that has an API.
- **Not a platform driver collection** — the runtime ships with zero platform drivers. Drivers are community-built plugins.
- **Not a replacement for MCP** — the runtime consumes MCP as a capability source. It doesn't replace MCP servers; it gives them economic agency.
- **Not free to run** — the embedded agent consumes LLM tokens on every planning loop. The provider pays for their agent's intelligence via their own LLM API key. The metrics system (§11) tracks this cost so providers can ensure profitability.

---

## 20. Implementation Priority

| Phase                    | Scope                                                                 | Notes                                        |
| ------------------------ | --------------------------------------------------------------------- | -------------------------------------------- |
| **1. Core**              | Wallet generation, SQLite persistence, config file, CLI init/start    | The skeleton everything else attaches to     |
| **2. Embedded Agent**    | Agent loop, LLM provider integration, system prompt, tool dispatch    | The brain that drives everything             |
| **3. Capabilities**      | OpenAPI ingestion, capability registry, spec change detection         | Provider can see what the adapter discovered |
| **4. Core Tools**        | HTTP client, wallet, secrets, state, status/whoami                    | Agent can start interacting with the world   |
| **5. Payments**          | x402 adapter, free adapter                                            | Minimum viable economic participation        |
| **6. Dashboard**         | Management API, embedded web UI, pricing editor, agent page           | Provider can configure and observe           |
| **7. Job Engine**        | Job tracking, completion, payment status linking                      | Operational visibility into work performed   |
| **8. Metrics**           | Cost tracking, LLM token accounting, profit margins, dashboard charts | Provider can assess profitability            |
| **9. More Payments**     | Solana escrow adapter, MPP adapter                                    | Broader economic participation               |
| **10. Optional Tools**   | SSE listener, heartbeat, platform discovery, notifications            | Operational quality of life                  |
| **11. Driver Interface** | Plugin API for platform drivers                                       | Community extensibility                      |
| **12. MCP Ingestion**    | MCP server as capability source                                       | Second capability source type                |

---

## 21. Resolved Design Decisions

Decisions made during spec development, recorded for context.

**Agent hosting:** The agent is embedded in the adapter. It is not a separate process. When the provider runs `agent-adapter start`, the agent starts with it. This makes the adapter a complete autonomous actor out of the box.

**Multi-platform coordination:** There is no built-in concept of "preferred platforms." The agent decides which platforms to prioritize based on the provider's custom system prompt. The provider writes instructions like "prefer AGICitizens over other platforms" or "only register on new platforms if I have spare capacity." The agent follows these instructions at runtime.

**Capability versioning:** When the provider's spec changes and active jobs fail under the new schema, those jobs fail. The adapter detects the schema change, flags it, and stops accepting new work for that capability until the provider reviews. This is an accepted tradeoff — graceful in-flight migration is impractical.

**Rate limiting:** The agent is responsible for respecting platform rate limits. The adapter does not enforce limits on outbound HTTP calls. If a platform returns 429, the agent reads the `Retry-After` header and backs off. This is part of the agent's default system prompt behavior.

**Metrics and billing:** The adapter tracks both earnings and costs (LLM tokens, transaction fees, service costs) so providers can see actual profit margins. This is essential because the agent has a running cost (LLM API calls) that must be offset by earnings.

**One adapter, one agent:** Each adapter instance is one economic identity. One wallet, one set of capabilities, one agent brain. If a provider wants multiple personas or wants to serve different platforms with different identities, they run multiple adapter instances.

---

_This PRD reflects discussion as of April 2026. It will evolve as implementation reveals what works and what needs rethinking._
