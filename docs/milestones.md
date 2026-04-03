# Agent Adapter Runtime — Staged Milestones

> OWS Hackathon (hackathon.openwallet.sh) build plan.
> Prioritized for strongest demo: wallet interoperability, payment flows, autonomous economic agency.

---

## M1 — Must-Haves (Working Demo / Hackathon Submission)

> The minimum to show an agent autonomously discovering work, getting paid, and executing capabilities.

| #   | Feature                                                                                                                                        | PRD Ref         | Why it's critical                                                          |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------- | -------------------------------------------------------------------------- |
| 1   | **Project scaffold** — Python, config loader (`agent-adapter.yaml`), CLI `init` + `start` (click/typer)                                        | §14             | Skeleton everything attaches to                                            |
| 2   | **Wallet core** — Keypair generation, import, `wallet__get_address`, `wallet__get_balance`, `wallet__sign_message`, `wallet__sign_transaction` | §8              | OWS hackathon = wallet is the centerpiece                                  |
| 3   | **SQLite persistence** — Schema setup (wallet, secrets, state, jobs, platforms tables)                                                         | §9              | Durable state across restarts                                              |
| 4   | **Secrets & state tools** — `secrets__store/retrieve/delete`, `state__set/get/list`                                                            | §9.3            | Agent needs credential + state persistence                                 |
| 5   | **Capability registry** — Manual definitions + OpenAPI spec ingestion, `cap__*` tool generation                                                | §4              | Agent needs to know what it can do                                         |
| 6   | **Embedded agent loop** — LLM integration (Anthropic), system prompt, tool dispatch, `status__whoami`                                          | §10             | The brain — this IS the product                                            |
| 7   | **Core tools** — `net__http_request`, `net__fetch_spec`                                                                                        | §12.2           | Agent's hands for interacting with platforms                               |
| 8   | **Free payment adapter** — `canHandle("free")`, no-op settle/refund                                                                            | §7.5            | Minimum viable payment (unblocks demo)                                     |
| 9   | **x402 payment adapter** — Handle 402 responses, sign payment, retry with proof                                                                | §7.2            | The OWS-relevant payment flow for the demo                                 |
| 10  | **Job engine** — 4-state lifecycle (pending → executing → completed/failed), payment status linking                                            | §6              | Track work performed                                                       |
| 11  | **Plugin architecture** — `WalletPlugin` interface, `PaymentAdapter` + `PaymentRegistry`, `Extension` + `ExtensionRegistry`                    | Impl notes §1-4 | OWS judges will look for extensibility — swappable wallet is the key pitch |

**Demo story:** Provider points adapter at an OpenAPI spec → adapter discovers capabilities → agent registers on a platform using wallet-signed auth → discovers a task → bids → executes capability → gets paid via x402. All autonomous.

---

## M2 — Value Adders (Polish + Stronger Demo)

> Features that significantly strengthen the hackathon presentation and judge appeal.

| #   | Feature                                                                                           | PRD Ref | Why it adds value                          |
| --- | ------------------------------------------------------------------------------------------------- | ------- | ------------------------------------------ |
| 12  | **Dashboard — Overview page** — Wallet, balances, platforms, active jobs, earnings sparkline      | §15.3   | Visual demo > CLI-only demo at a hackathon |
| 13  | **Dashboard — Capabilities page** — Pricing editor, enable/disable toggles                        | §15.3   | Shows provider sovereignty in action       |
| 14  | **Dashboard — Agent page** — Decision log stream, tool call history, pause/resume                 | §15.3   | "Watch the agent think" is the wow factor  |
| 15  | **Solana escrow payment adapter** — `pay_escrow__prepare_lock`, `sign_and_submit`, `check_status` | §7.3    | On-chain escrow = strong OWS/Solana story  |
| 16  | **Provider-customizable system prompt** — File-based override, `appendToDefault` mode             | §10.4   | Shows the "no-code strategy tuning" angle  |
| 17  | **Spec change detection** — Hash-based diff, flag new/changed/stale capabilities                  | §4.3    | Shows production-readiness thinking        |
| 18  | **Management API** — REST endpoints backing the dashboard                                         | §15.4   | Enables programmatic control               |
| 19  | **CLI commands** — `capabilities list/price/enable`, `agent decisions`, `wallet balance`          | §14.3   | Clean developer UX for live demo           |

---

## M3 — Nice-to-Haves (Post-Hackathon / If Time Permits)

> Features that round out the product but aren't needed to win.

| #   | Feature                                                                          | PRD Ref       | Notes                                                    |
| --- | -------------------------------------------------------------------------------- | ------------- | -------------------------------------------------------- |
| 20  | **Metrics & billing** — LLM cost tracking, profit margins, daily aggregation     | §11           | Important for real usage, not for demo                   |
| 21  | **Dashboard — Metrics page** — Charts, export to CSV                             | §15.3         | Needs real data to be meaningful                         |
| 22  | **MCP server ingestion** — Second capability source type                         | §4.1          | Broadens the story but OpenAPI is enough for demo        |
| 23  | **MPP/Stripe adapter** — Fiat payment rails                                      | §7.4          | Nice for completeness, not hackathon-critical            |
| 24  | **Platform driver interface** — Plugin API for community drivers                 | §13.4         | Extensibility story is covered by wallet/payment plugins |
| 25  | **Optional tools** — SSE listener, heartbeat, webhook receiver, notifications    | §12.5         | Operational polish                                       |
| 26  | **Dashboard — Prompt editor** — History, diff view, test against examples        | §10.5         | UX polish                                                |
| 27  | **Dashboard — Wallet page** — Tx history, export/import flows, faucet links      | §15.3         | Nice UX but CLI covers it                                |
| 28  | **Plugin discovery** — `node_modules` scan via `agentAdapter` package.json field | Impl notes §5 | Explicit config (Option B) is enough initially           |

---

## Suggested Sprint Plan

| Day       | Focus                | Milestones                                                |
| --------- | -------------------- | --------------------------------------------------------- |
| **Day 1** | Foundation           | M1 #1-4 (scaffold, wallet, SQLite, secrets/state)         |
| **Day 2** | Brain + Capabilities | M1 #5-7 (registry, agent loop, core tools)                |
| **Day 3** | Payments + Jobs      | M1 #8-11 (free + x402 adapters, job engine, plugin arch)  |
| **Day 4** | Demo Polish          | M2 #12-14 (dashboard overview, capabilities, agent pages) |
| **Day 5** | Buffer + Stretch     | M2 #15-16 (escrow adapter, custom prompts) + demo prep    |
