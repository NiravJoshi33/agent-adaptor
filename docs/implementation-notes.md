Good catch — here's the full document inline.

---

# Agent Adapter Runtime — Plugin Architecture

> Companion to the Agent Adapter Runtime PRD (v0.1, April 2026).
> Covers how adapters registered in-codebase work, what happens when a new plugin is installed from outside, and how add-on (non-mandatory) plugins integrate.

---

## 1. The Core Mental Model

The runtime codebase ships **interfaces and registries — not implementations**.

Every plugin plugs into one of three patterns:

| Pattern              | What it is                                                    | Core knows about it?                     |
| -------------------- | ------------------------------------------------------------- | ---------------------------------------- |
| **Swappable core**   | Replaces one mandatory module slot                            | Yes — abstract base lives in core        |
| **Payment adapter**  | Registered into `PaymentRegistry`, resolved via `canHandle()` | Yes — `PaymentAdapter` ABC lives in core |
| **Add-on extension** | Subscribes to lifecycle hooks, adds new behaviour             | No — core only emits events              |

The codebase tree reflects this:

```
agent_adapter/
├── wallet/
│   └── base.ts          ← WalletPlugin interface (abstract)
├── payments/
│   ├── base.ts          ← PaymentAdapter interface + PaymentRegistry
│   └── adapters/
│       ├── free.ts      ← FreeAdapter (always bundled)
│       └── x402.ts      ← X402Adapter (bundled, optional at runtime)
├── store/
│   └── base.ts          ← SecretsBackend interface
└── extensions/
    └── registry.ts      ← emit(), register() — knows nothing about any plugin
```

---

## 2. Situation A — Swappable Core Module (e.g. Wallet)

These plugins **replace a mandatory module** with an alternate implementation. The runtime always needs _a_ wallet — the plugin decides _which_ wallet.

### The Interface (ships in core)

```typescript
// wallet/base.ts
export interface WalletPlugin {
  getAddress(): Promise<string>;
  getBalance(chain?: string): Promise<{ sol: number; usdc: number }>;
  signMessage(msg: Uint8Array): Promise<Uint8Array>;
  signTransaction(tx: Transaction): Promise<Transaction>;
}
```

### Built-in Implementation (always in codebase)

```typescript
// wallet/adapters/solana-raw.ts
export class SolanaRawWallet implements WalletPlugin {
  constructor(
    private keypair: Keypair,
    private connection: Connection,
  ) {}

  async getAddress() {
    return this.keypair.publicKey.toBase58();
  }

  async getBalance() {
    const lamports = await this.connection.getBalance(this.keypair.publicKey);
    return { sol: lamports / 1e9, usdc: 0 };
  }

  async signMessage(msg: Uint8Array) {
    return sign(msg, this.keypair.secretKey);
  }

  async signTransaction(tx: Transaction) {
    tx.sign(this.keypair);
    return tx;
  }
}
```

### Installing an External Plugin

User runs:

```bash
npm install @ows/wallet-plugin
```

The package ships a class implementing `WalletPlugin` and declares itself:

```json
// node_modules/@ows/wallet-plugin/package.json
{
  "name": "@ows/wallet-plugin",
  "agentAdapter": {
    "pluginType": "wallet",
    "pluginId": "ows"
  }
}
```

```typescript
// inside @ows/wallet-plugin
import type { WalletPlugin } from "agent-adapter/wallet/base";

export class OWSWalletPlugin implements WalletPlugin {
  async getAddress() {
    /* OWS multi-chain logic via CAIP */
  }
  async getBalance(chain = "solana:mainnet") {
    /* ... */
  }
  async signMessage(msg) {
    /* ... */
  }
  async signTransaction(tx) {
    /* ... */
  }
}
```

User selects it in `agent-adapter.yaml`:

```yaml
wallet:
  provider: ows # was "solana-raw" before
```

Runtime wires it automatically on startup:

```typescript
// runtime/loader.ts
async function loadWallet(): Promise<WalletPlugin> {
  const { provider } = config.wallet;

  const registry: Record<string, () => Promise<WalletPlugin>> = {
    "solana-raw": async () => {
      const { SolanaRawWallet } = await import("../wallet/adapters/solana-raw");
      return new SolanaRawWallet(/* keypair, connection */);
    },
  };

  // Discover externally installed wallet plugins
  const installed = await discoverInstalledPlugins("wallet");
  for (const pkg of installed) {
    registry[pkg.pluginId] = async () => {
      const { default: Plugin } = await import(pkg.name);
      return new Plugin(config.wallet.config ?? {});
    };
  }

  const factory = registry[provider];
  if (!factory) {
    throw new Error(
      `Wallet provider "${provider}" not found. Is the package installed?`,
    );
  }

  return factory();
}
```

**Nothing else in the codebase changes.** The rest of the runtime always calls `wallet.getAddress()` — it doesn't care if OWS or raw Solana is underneath.

---

## 3. Situation B — Payment Adapters

Payment adapters are similar to swappable modules, but **multiple can be active at once**, and the runtime resolves which to use per-payment via `canHandle()`.

### The Interface (ships in core)

```typescript
// payments/base.ts
export interface PaymentAdapter {
  id: string;

  canHandle(challenge: PaymentChallenge): boolean;
  execute(
    challenge: PaymentChallenge,
    wallet: WalletPlugin,
  ): Promise<PaymentReceipt>;
  settle(session: PaymentSession): Promise<void>;
  refund(session: PaymentSession, reason: string): Promise<void>;
}

export type PaymentChallenge =
  | { type: "x402"; headers: Record<string, string> }
  | { type: "escrow"; platform: string; taskId: string; amount: number }
  | { type: "mpp"; sessionUrl: string }
  | { type: "free" };
```

### The Registry

```typescript
// payments/registry.ts
export class PaymentRegistry {
  private adapters: PaymentAdapter[] = [];

  register(adapter: PaymentAdapter) {
    this.adapters.push(adapter);
  }

  resolve(challenge: PaymentChallenge): PaymentAdapter {
    const adapter = this.adapters.find((a) => a.canHandle(challenge));
    if (!adapter) {
      throw new Error(
        `No payment adapter can handle challenge type: ${challenge.type}`,
      );
    }
    return adapter;
  }

  list() {
    return this.adapters.map((a) => a.id);
  }
}
```

### Adding `EscrowLockAdapter` (Not in Codebase Yet)

User installs:

```bash
npm install @agic/escrow-lock-adapter
```

The package ships:

```typescript
// inside @agic/escrow-lock-adapter
import type {
  PaymentAdapter,
  PaymentChallenge,
  PaymentReceipt,
} from "agent-adapter/payments/base";

export class EscrowLockAdapter implements PaymentAdapter {
  id = "solana_escrow";

  canHandle(challenge: PaymentChallenge): boolean {
    return challenge.type === "escrow";
  }

  async execute(challenge, wallet): Promise<PaymentReceipt> {
    if (challenge.type !== "escrow") throw new Error("Wrong challenge type");

    const tx = await this.buildEscrowLockTx({
      amount: challenge.amount,
      taskId: challenge.taskId,
    });

    const signed = await wallet.signTransaction(tx);
    const sig = await this.connection.sendRawTransaction(signed.serialize());

    return {
      protocol: "solana_escrow",
      txSignature: sig,
      amount: challenge.amount,
      lockedAt: new Date().toISOString(),
    };
  }

  async settle(session) {
    /* release escrow to provider */
  }
  async refund(session, reason) {
    /* return funds to requester */
  }

  private async buildEscrowLockTx(params: { amount: number; taskId: string }) {
    // PDA derivation + instruction building
  }
}
```

Runtime auto-registers it on startup:

```typescript
// runtime/loader.ts
async function loadPaymentAdapters(registry: PaymentRegistry) {
  // Always register built-ins
  registry.register(new FreeAdapter());
  registry.register(new X402Adapter());

  // Discover and register external payment plugins
  const installed = await discoverInstalledPlugins("payment");
  for (const pkg of installed) {
    const { default: AdapterClass } = await import(pkg.name);
    registry.register(new AdapterClass(config.payments?.[pkg.pluginId] ?? {}));
    console.log(`✓ Payment adapter registered: ${pkg.pluginId}`);
  }
}
```

When the agent needs to pay for an AGICitizens escrow:

```typescript
// agent tool: pay__execute
const challenge: PaymentChallenge = {
  type: "escrow",
  platform: "agicitizens",
  taskId: "task_xyz",
  amount: 0.05,
};

const adapter = paymentRegistry.resolve(challenge); // finds EscrowLockAdapter
const receipt = await adapter.execute(challenge, wallet);
```

**The agent doesn't know or care which adapter ran.** It issued a challenge; the registry found the right one.

---

## 4. Situation C — Add-On Extensions (Non-Mandatory)

These plugins **add new behaviour the core doesn't define at all**. They are not replacing anything. Examples: Telegram notifier, Prometheus exporter, Vault secrets, custom audit logger.

The core ships an event emitter. Add-ons subscribe to events they care about. The core **never imports them**.

### The Extension Interface (ships in core)

```typescript
// extensions/base.ts
export interface Extension {
  name: string;
  hooks: ExtensionHook[];
  initialize(runtime: RuntimeAPI): Promise<void>;
  shutdown(): Promise<void>;
}

export type ExtensionHook =
  | "on_job_complete"
  | "on_job_failed"
  | "on_low_balance"
  | "on_platform_registered"
  | "on_agent_error"
  | "on_capability_drift";
```

### The Extension Registry (ships in core)

```typescript
// extensions/registry.ts
export class ExtensionRegistry {
  private extensions: Extension[] = [];

  register(ext: Extension) {
    this.extensions.push(ext);
  }

  async emit(hook: ExtensionHook, payload: unknown) {
    await Promise.allSettled(
      this.extensions
        .filter((ext) => ext.hooks.includes(hook))
        .map((ext) => (ext as any)[hook]?.(payload)),
    );
  }
}
```

### Core Emits Events — Knows Nothing About Listeners

```typescript
// jobs/engine.ts
export class JobEngine {
  constructor(
    private db: Database,
    private extensions: ExtensionRegistry,
  ) {}

  async completeJob(jobId: string, output: unknown) {
    const job = this.db.updateJobStatus(jobId, "completed", output);
    // Core fires the event — has no idea who is listening
    await this.extensions.emit("on_job_complete", job);
  }

  async failJob(jobId: string, error: Error) {
    const job = this.db.updateJobStatus(jobId, "failed", {
      error: error.message,
    });
    await this.extensions.emit("on_job_failed", job);
  }
}
```

### The Telegram Notifier Plugin (completely outside codebase)

```bash
npm install agent-adapter-telegram-notifier
```

```typescript
// inside agent-adapter-telegram-notifier
import type { Extension, RuntimeAPI } from "agent-adapter/extensions/base";

export default class TelegramNotifier implements Extension {
  name = "telegram-notifier";
  hooks = ["on_job_complete", "on_job_failed", "on_low_balance"] as const;

  private botToken: string;
  private chatId: string;

  async initialize(runtime: RuntimeAPI) {
    this.botToken = await runtime.secrets.get("telegram_bot_token");
    this.chatId = runtime.config.extensions?.telegram?.chatId;
    console.log("✓ Telegram notifier initialized");
  }

  async on_job_complete(job: Job) {
    await this.send(
      `✅ Job done\n` +
        `Capability: ${job.capability}\n` +
        `Earned: ${job.payment_amount} ${job.payment_currency}\n` +
        `Platform: ${job.platform}`,
    );
  }

  async on_job_failed(job: Job) {
    await this.send(
      `❌ Job failed\n` +
        `Capability: ${job.capability}\n` +
        `Error: ${job.error}`,
    );
  }

  async on_low_balance({ sol, usdc }: { sol: number; usdc: number }) {
    await this.send(`⚠️ Low balance\nSOL: ${sol}\nUSDC: ${usdc}`);
  }

  async shutdown() {}

  private async send(text: string) {
    await fetch(`https://api.telegram.org/bot${this.botToken}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: this.chatId, text }),
    });
  }
}
```

User enables it in `agent-adapter.yaml`:

```yaml
extensions:
  telegram:
    chatId: "-1001234567890"
# bot token stored separately:
# agent-adapter secrets set telegram_bot_token <value>
```

Runtime discovers and loads it:

```typescript
async function loadExtensions(
  registry: ExtensionRegistry,
  runtime: RuntimeAPI,
) {
  const installed = await discoverInstalledPlugins("extension");

  for (const pkg of installed) {
    const { default: ExtClass } = await import(pkg.name);
    const ext = new ExtClass();
    await ext.initialize(runtime);
    registry.register(ext);
    console.log(`✓ Extension loaded: ${ext.name}`);
  }
}
```

The core `JobEngine` never changes. It still just calls `this.extensions.emit("on_job_complete", job)`. The Telegram notifier picks it up automatically.

---

## 5. Plugin Discovery

How does the runtime find installed plugins without knowing their names in advance?

### Option A — Package metadata scan (convenient)

Every plugin declares itself in `package.json`:

```json
{
  "name": "@agic/escrow-lock-adapter",
  "agentAdapter": {
    "pluginType": "payment",
    "pluginId": "solana_escrow"
  }
}
```

Runtime scans `node_modules` at startup:

```typescript
async function discoverInstalledPlugins(type: string) {
  const modulesDir = path.join(process.cwd(), "node_modules");
  const packages = await fs.readdir(modulesDir);
  const found = [];

  for (const pkg of packages) {
    try {
      const pkgJson = await readJson(
        path.join(modulesDir, pkg, "package.json"),
      );
      if (pkgJson.agentAdapter?.pluginType === type) {
        found.push({ name: pkg, pluginId: pkgJson.agentAdapter.pluginId });
      }
    } catch {
      /* not a plugin, skip */
    }
  }

  return found;
}
```

### Option B — Explicit config (recommended to start)

```yaml
plugins:
  wallet:
    - package: "@ows/wallet-plugin"
      id: ows
  payments:
    - package: "@agic/escrow-lock-adapter"
      id: solana_escrow
  extensions:
    - package: "agent-adapter-telegram-notifier"
```

Runtime only loads what's declared. No scanning. Most debuggable. **Start here.**

---

## 6. Full Comparison Table

|                      | Swappable Core                   | Payment Adapter                | Add-on Extension             |
| -------------------- | -------------------------------- | ------------------------------ | ---------------------------- |
| **Example**          | OWS Wallet, Vault Secrets        | EscrowLockAdapter, X402Adapter | TelegramNotifier, Prometheus |
| **Mandatory?**       | Yes — one must be active         | No — enable as many as needed  | No — pure opt-in             |
| **Core interface**   | `WalletPlugin`, `SecretsBackend` | `PaymentAdapter`               | `Extension`                  |
| **Multiple active?** | No — config picks one            | Yes — registry holds all       | Yes — all registered run     |
| **Resolved by**      | Config → factory map             | `canHandle(challenge)`         | Hook subscription            |
| **Core imports it?** | Via dynamic import in loader     | Via registry                   | Never directly               |

---

## 7. What Lives in Core vs Plugin

```
LIVES IN CORE — always
├── WalletPlugin interface
├── PaymentAdapter interface
├── Extension interface
├── PaymentRegistry class
├── ExtensionRegistry class
└── FreeAdapter (zero-dep default)

LIVES IN CORE — bundled for convenience
├── SolanaRawWallet
└── X402Adapter

LIVES IN PLUGIN PACKAGE — never in core
├── @ows/wallet-plugin          → OWSWalletPlugin
├── @agic/escrow-lock-adapter   → EscrowLockAdapter
├── agent-adapter-telegram       → TelegramNotifier
└── agent-adapter-prometheus     → PrometheusExtension
```

Core stays minimal and dependency-free. A provider who only needs x402 + raw Solana never pulls in OWS, Telegram, or Prometheus.

---

## 8. Plugin Author Checklist

1. **Identify the category** — swappable core, payment adapter, or add-on extension
2. **Implement the correct interface** — import from `agent-adapter/wallet/base`, `agent-adapter/payments/base`, or `agent-adapter/extensions/base`
3. **Declare in `package.json`**:
   ```json
   {
     "agentAdapter": {
       "pluginType": "payment",
       "pluginId": "my_adapter"
     }
   }
   ```
4. **Handle config via constructor** — runtime passes `config.payments?.my_adapter` or equivalent
5. **For payment adapters**: implement `canHandle()` narrowly — only return `true` for challenge types you genuinely support
6. **For extensions**: list only the hooks you implement in the `hooks` array
7. **Never import from `agent-adapter` internals** — only from published interface paths (`/base`, `/registry`)
8. **Handle `initialize()` / `shutdown()` gracefully** — runtime calls these on start and graceful stop
