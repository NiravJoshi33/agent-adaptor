# Agent Adapter: Turning Any API into a Wallet-Backed Economic Agent

There is a familiar pattern in every new platform wave.

First, the technical possibility arrives. Then the ecosystem forms around it. Then the integration burden quietly shifts onto everyone who just wanted to keep building their actual product.

We think agent economies are entering that phase now.

AI agents can already reason through workflows, call tools, read docs, use APIs, and complete meaningful tasks with less and less human supervision. The interesting question is no longer whether agents can be useful. It is what infrastructure the rest of the internet needs once agents become real participants in economic exchange.

If an agent wants to buy work, sell work, hire another agent, or monetize access to a capability, what does the provider on the other side need in order to participate?

Today, the answer is usually too much.

An API provider who wants to serve agent economies is often expected to learn new wallet patterns, integrate payment rails, adapt to platform-specific task flows, and redesign their product around whatever marketplace happens to be popular at the moment. Even when the provider already has a perfectly functional API, a well-defined service, and a deployment stack they trust, they are asked to rebuild the edges just to become economically legible to agents.

That is the gap we wanted to close with Agent Adapter.

We built Agent Adapter for the Open Wallet hackathon as a self-hosted runtime that turns an existing API or MCP server into an economic agent. Instead of asking providers to rebuild their product for agent-native commerce, we wrap the product they already have. The runtime discovers capabilities, attaches pricing, connects a wallet, exposes a management surface, lets an embedded agent decide how to use those capabilities, and supports payment rails like x402 and MPP.

The core idea is simple.

Providers should not have to choose between participating in agent economies and keeping control over their own stack.

Agent Adapter is designed around provider sovereignty from the start. The provider keeps their API. They keep their wallet. They keep their keys. They keep their hosting. They keep their pricing policy. The runtime handles the economic glue around that service: capability discovery, tool exposure to the agent, wallet-backed execution, payment adapter resolution, job tracking, and a local control plane for operations.

That design choice shaped almost everything else.

We did not want discovery and monetization to be fused together. If a runtime automatically imported an API spec and immediately put every endpoint up for sale, it would be convenient, but it would also be reckless. Providers need a tighter policy boundary than that.

So Agent Adapter follows a different rule:

Discovery is automatic. Monetization is manual.

The runtime can discover capabilities from OpenAPI, MCP, or manual definitions. But a discovered capability does not go live just because it exists. The provider reviews what was found, decides which capabilities should be enabled, and sets pricing locally. That pricing does not live in somebody else's marketplace metadata. It lives with the provider.

That matters because the provider is the one bearing the operational and economic risk.

Some endpoints are cheap. Some are expensive. Some are safe to expose broadly. Some should be gated tightly. Some are stable enough for fixed pricing. Others should only be sold under quoted or bounded conditions. If agents are going to become buyers and sellers on the open internet, then the seller-side control plane has to be real, not symbolic.

That is why the local dashboard matters so much in this project.

The dashboard is not just a cosmetic admin panel. It is the provider's local control plane for wallet state, capability discovery, pricing overlays, prompt policy, metrics, operations, and agent status. It makes the runtime legible. You can see what capabilities were discovered, which ones are enabled, what they cost, what the wallet is doing, what the agent has been deciding, and what revenue has been captured.

We wanted the provider experience to feel like operating an economic runtime, not babysitting a fragile demo.

The wallet layer is another place where we wanted the architecture to stay practical.

The Open Wallet Standard is compelling because it creates a cleaner abstraction for agent-accessible wallets and policy controls without forcing one chain, one custody pattern, or one application stack. That fits this project well. The provider runtime should be able to plug into different wallet implementations and payment rails while preserving a stable operational model.

In Agent Adapter, wallets and payments are plugin-driven. A provider can swap wallet implementations, run multiple payment adapters at once, and let the runtime resolve the appropriate rail at execution time. The same runtime can support free flows for preview and testing, x402 for pay-per-call access, escrow for more structured settlement, and MPP-backed paths where they make sense. The goal is not to force one protocol. The goal is to make economic participation modular.

That modularity also shows up in how the runtime thinks about platforms.

We did not want to hard-code AGICitizens or any other marketplace into the core. The runtime is platform-agnostic on purpose. The default model is that the embedded agent reads platform docs, evaluates opportunities, decides what to do, and executes through a generic tool surface. If a specific platform has a brittle or highly custom integration, that can be added as a driver or plugin. But it is not the baseline assumption.

That distinction is important to us because it changes what kind of software this becomes.

Agent Adapter is not "an integration for one marketplace." It is infrastructure for providers who want to expose their capabilities to agent economies without surrendering their architecture to each new platform.

Our demo tries to make that concrete.

We show a provider-facing runtime wrapping existing APIs. The runtime discovers capabilities from specs, stores monetization settings locally, exposes those capabilities as tools, and gives the agent a wallet-backed execution environment. From there, the agent can discover work, decide how to respond, execute the right capability, and complete paid flows through the configured rail.

We also built the project so the demo can scale from safe preview to stronger proofs.

The local dashboard preview shows the product shape quickly: capability discovery, pricing, wallet state, operations, and prompt control in a self-hosted interface. The end-to-end simulations go further and show the agent registering, discovering tasks, executing work, and delivering outputs. The production-like demo tightens the story further with x402-backed payments and more complete job and decision tracking.

That progression matters because we wanted the repo to communicate more than one flashy moment.

We wanted it to show a practical path from "I have an API" to "I can participate in an agent economy."

The longer-term idea behind this project is not just a single runtime, but a broader plugin surface.

That is why the repo is split into a contracts package, the runtime package, and a growing set of plugins. Wallet plugins, payment adapters, extensions, and platform drivers can all be developed against a shared contract layer without depending on one monolithic application. We think this matters if agent economies are going to become a real ecosystem rather than a set of isolated demos. Providers, wallet teams, payment teams, and platform builders should be able to contribute interoperable pieces instead of re-implementing the whole stack from scratch.

The reason we find this exciting is that it shifts attention to a part of agent infrastructure that is still underbuilt.

There is a lot of energy around what agents can do. There is less attention on what it takes for existing businesses and services to let agents interact with them safely, economically, and without total reinvention.

That is the problem Agent Adapter is trying to solve.

Not how to build another agent from scratch.

How to make existing services economically usable by agents.

If agent economies are going to become real, the internet needs more than smart agents on the demand side. It also needs provider-side infrastructure that can expose capabilities, enforce pricing, connect wallets, process payments, and preserve operator control.

That is the layer we are building here.

Agent Adapter is our attempt to give providers a clean way to show up in agent economies without giving up sovereignty over their product, keys, wallet, or business model.

Built for the Open Wallet hackathon.
