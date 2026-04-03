# Agent Adapter Runtime — Staged Milestones

> OWS Hackathon (hackathon.openwallet.sh) build plan.
> Prioritized for strongest demo: wallet interoperability, payment flows, autonomous economic agency.

---

## Package Structure

Three publishable packages in a monorepo. `agent-adapter-contracts` is the stable center — ABCs + dataclasses shared between the runtime and all plugins.

```
PyPI
├── agent-adapter-contracts   ← ABCs + dataclasses only, versioned carefully
├── agent-adapter             ← the runtime (depends on contracts)
└── <plugins>                 ← each depends on contracts, never on runtime internals
```

```
agent-adaptor/                          ← monorepo root
├── packages/
│   ├── agent-adapter-contracts/        ← published: agent-adapter-contracts
│   │   ├── agent_adapter_contracts/
│   │   │   ├── wallet.py               ← WalletPlugin ABC
│   │   │   ├── payments.py             ← PaymentAdapter ABC, PaymentChallenge, PaymentReceipt
│   │   │   ├── extensions.py           ← Extension ABC, ExtensionHook
│   │   │   └── types.py               ← shared dataclasses (Capability, Job, PricingConfig...)
│   │   └── pyproject.toml              ← no dependencies (or near-zero)
│   │
│   ├── agent-adapter/                  ← published: agent-adapter
│   │   ├── agent_adapter/
│   │   │   ├── payments/
│   │   │   │   └── registry.py         ← PaymentRegistry (imports ABC from contracts)
│   │   │   ├── extensions/
│   │   │   │   └── registry.py         ← ExtensionRegistry
│   │   │   ├── wallet/
│   │   │   │   └── loader.py           ← resolves which WalletPlugin impl to use
│   │   │   ├── jobs/
│   │   │   ├── agent/
│   │   │   └── ...
│   │   └── pyproject.toml              ← depends on agent-adapter-contracts >=x,<2.0
│   │
│   └── plugins/                        ← bundled core plugins, each independently publishable
│       ├── wallet-solana-raw/
│       │   └── pyproject.toml          ← depends on agent-adapter-contracts >=x,<2.0
│       ├── wallet-ows/
│       ├── payment-free/
│       ├── payment-x402/
│       └── payment-escrow/
│
└── docs/
```

**Dependency flow at runtime:**

```
Plugin (implements ABC from contracts)
   ↓ registers into
Runtime (owns registries, calls ABC methods)
   ↑ both import from
Contracts (ABC definitions — the stable center)
```

---

## M1 — Must-Haves (Working Demo / Hackathon Submission)

> The minimum to show an agent autonomously discovering work, getting paid, and executing capabilities.
>
> Status legend: `Done` = landed, `Mostly done` = core behavior landed with small UX gaps, `Partial` = meaningful slice landed but milestone not complete, `Pending` = not started or not enough shipped yet.

| #   | Status | Feature                                                                                                                                        | PRD Ref         | Why it's critical                                                          |
| --- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------- | -------------------------------------------------------------------------- |
| 1   | Done | **Monorepo scaffold** — Python monorepo with `packages/` layout, `pyproject.toml` per package, CLI `init` + `start` (typer/click)              | §14             | Skeleton everything attaches to                                            |
| 2   | Done | **agent-adapter-contracts** — `WalletPlugin` ABC, `PaymentAdapter` ABC, `Extension` ABC, shared dataclasses (`PaymentChallenge`, `Capability`, `Job`, etc.) | Impl notes      | The stable center — must exist before runtime or plugins                   |
| 3   | Done | **Wallet core** — Keypair generation, import, `wallet__get_address`, `wallet__get_balance`, `wallet__sign_message`, `wallet__sign_transaction` | §8              | OWS hackathon = wallet is the centerpiece                                  |
| 4   | Done | **wallet-ows plugin** — OWS wallet as default plugin (swappable via config), `wallet-solana-raw` as fallback                                   | §8, Impl notes §2 | Hackathon headline: OWS wallet is default, but the plugin arch lets you swap |
| 5   | Done | **SQLite persistence** — Schema setup (wallet, secrets, state, jobs, platforms tables)                                                         | §9              | Durable state across restarts                                              |
| 6   | Done | **Secrets & state tools** — `secrets__store/retrieve/delete`, `state__set/get/list`                                                            | §9.3            | Agent needs credential + state persistence                                 |
| 7   | Done | **Capability registry** — Manual definitions + OpenAPI spec ingestion, `cap__*` tool generation                                                | §4              | Agent needs to know what it can do                                         |
| 8   | Done | **Embedded agent loop** — LLM integration (Anthropic), system prompt, tool dispatch, `status__whoami`                                          | §10             | The brain — this IS the product                                            |
| 9   | Done | **Core tools** — `net__http_request`, `net__fetch_spec`                                                                                        | §12.2           | Agent's hands for interacting with platforms                               |
| 10  | Done | **payment-free plugin** — `canHandle("free")`, no-op settle/refund                                                                             | §7.5            | Minimum viable payment (unblocks demo)                                     |
| 11  | Done | **payment-x402 plugin** — Handle 402 responses, sign payment, retry with proof                                                                 | §7.2            | The OWS-relevant payment flow for the demo                                 |
| 12  | Done | **Job engine** — 4-state lifecycle (pending → executing → completed/failed), payment status linking                                            | §6              | Track work performed                                                       |
| 13  | Done | **Plugin loading** — `PaymentRegistry`, `ExtensionRegistry`, wallet loader; resolve from config → import plugin → register                     | Impl notes §1-5 | OWS judges will look for extensibility — swappable wallet is the key pitch |

**Demo story:** Provider points adapter at an OpenAPI spec → adapter discovers capabilities → agent registers on a platform using OWS wallet-signed auth → discovers a task → bids → executes capability → gets paid via x402. Swap wallet to `solana-raw` with one config line. All autonomous.

---

## M2 — Value Adders (Polish + Stronger Demo)

> Features that significantly strengthen the hackathon presentation and judge appeal.

| #   | Status | Feature                                                                                           | PRD Ref | Why it adds value                          |
| --- | ------ | ------------------------------------------------------------------------------------------------- | ------- | ------------------------------------------ |
| 14  | Mostly done | **Dashboard — Overview page** — Wallet, balances, platforms, active jobs, earnings sparkline      | §15.3   | Visual demo > CLI-only demo at a hackathon |
| 15  | Partial | **Dashboard — Capabilities page** — Pricing editor, enable/disable toggles                        | §15.3   | Shows provider sovereignty in action       |
| 16  | Mostly done | **Dashboard — Agent page** — Decision log stream, tool call history, pause/resume                 | §15.3   | "Watch the agent think" is the wow factor  |
| 17  | Done | **payment-escrow plugin** — `pay_escrow__prepare_lock`, `sign_and_submit`, `check_status` (consumes platform-supplied program payload at runtime) | §7.3 | On-chain escrow = strong OWS/Solana story |
| 18  | Done | **Provider-customizable system prompt** — File-based override, `appendToDefault` mode             | §10.4   | Shows the "no-code strategy tuning" angle  |
| 19  | Done | **Spec change detection** — Hash-based diff, flag new/changed/stale capabilities                  | §4.3    | Shows production-readiness thinking        |
| 20  | Done | **Management API** — REST endpoints backing the dashboard (FastAPI)                               | §15.4   | Enables programmatic control               |
| 21  | Done | **CLI commands** — capability management, `agent decisions`, `platforms list/add`, `wallet address/balance/export/import`, `metrics export` | §14.3   | Clean developer UX for live demo           |

---

## M3 — Nice-to-Haves (Post-Hackathon / If Time Permits)

> Features that round out the product but aren't needed to win.

| #   | Status | Feature                                                                               | PRD Ref       | Notes                                                    |
| --- | ------ | ------------------------------------------------------------------------------------- | ------------- | -------------------------------------------------------- |
| 22  | Done | **Metrics & billing** — LLM cost tracking, profit margins, daily aggregation          | §11           | Important for real usage, not for demo                   |
| 23  | Mostly done | **Dashboard — Metrics page** — Charts, export to CSV                                  | §15.3         | Charts landed; CSV export is available via CLI/API, not the dashboard UI yet |
| 24  | Done | **MCP server ingestion** — Second capability source type                              | §4.1          | Broadens the story but OpenAPI is enough for demo        |
| 25  | Done | **MPP/Stripe adapter** — Fiat payment rails                                           | §7.4          | Nice for completeness, not hackathon-critical            |
| 26  | Done | **Platform driver interface** — Plugin API for community drivers plus `drivers list/install/remove` CLI | §13.4         | Extensibility story is covered by wallet/payment/plugins and provider-facing driver lifecycle commands |
| 27  | Done | **Optional tools** — SSE listener, heartbeat, webhook receiver, notifications, low-balance alerts | §12.5         | Operational polish                                       |
| 28  | Pending | **Dashboard — Prompt editor** — History, diff view, test against examples             | §10.5         | UX polish                                                |
| 29  | Partial | **Dashboard — Wallet page** — Tx history, export/import flows, faucet links           | §15.3         | Nice UX but CLI covers it                                |
| 30  | Done | **Plugin discovery** — site-packages scan via `pyproject.toml` entry points            | Impl notes §5 | Explicit config is enough initially                      |

---

## Suggested Sprint Plan

| Day       | Focus                | Milestones                                                          |
| --------- | -------------------- | ------------------------------------------------------------------- |
| **Day 1** | Foundation           | M1 #1-6 (scaffold, contracts pkg, wallet + OWS plugin, SQLite)     |
| **Day 2** | Brain + Capabilities | M1 #7-9 (registry, agent loop, core tools)                         |
| **Day 3** | Payments + Jobs      | M1 #10-13 (free + x402 plugins, job engine, plugin loading)        |
| **Day 4** | Demo Polish          | M2 #14-16 (dashboard overview, capabilities, agent pages)          |
| **Day 5** | Buffer + Stretch     | M2 #17-18 (escrow plugin, custom prompts) + demo prep              |
