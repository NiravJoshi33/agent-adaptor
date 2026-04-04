import { FormEvent, useCallback, useState } from "react";
import {
  getWallet,
  exportWallet,
  importWallet,
  type WalletOverview,
} from "@/lib/api";
import { useApi } from "@/hooks/use-api";
import { PageHero } from "@/components/layout/PageHero";
import { Card } from "@/components/ui/Card";
import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Spinner";
import { formatMoney, formatTimestamp } from "@/lib/utils";

export default function Wallet() {
  const fetcher = useCallback(() => getWallet(), []);
  const { data: wallet, loading } = useApi<WalletOverview>(fetcher);

  if (loading || !wallet) return <Spinner />;

  return (
    <>
      <PageHero
        eyebrow="Wallet Control Plane"
        title="Wallet"
        description="Inspect the signing identity, check operational liquidity, move keys deliberately, and keep recent payment activity close to the runtime."
        compact
        callout={{
          label: "Key Safety",
          text: "Export is local-only. Import updates config and asks for a restart before the runtime switches identity.",
        }}
      />

      {/* Stat cards */}
      <div className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4 animate-fade-up stagger-1">
        <Card
          label="Address"
          value={
            <span className="break-all text-base font-bold">
              {wallet.address || "unknown"}
            </span>
          }
          foot="Primary signing address used across capability execution and payment flows."
        />
        <Card
          label="Balances"
          value={`${wallet.balances?.sol ?? 0} SOL / ${wallet.balances?.usdc ?? 0} USDC`}
          foot="Operational liquidity currently visible to the runtime."
        />
        <Card
          label="Provider"
          value={`${wallet.provider || "unknown"} / ${wallet.cluster || wallet.chain || "runtime default"}`}
          foot="Current wallet plugin and cluster context."
        />
        <Card
          label="Low Balance"
          value={
            wallet.low_balance?.active
              ? `${Object.keys(wallet.low_balance.below_threshold || {}).join(" + ")} low`
              : "healthy"
          }
          foot="Threshold tracking used by runtime notifications and alerts."
        />
      </div>

      {/* Key Actions + Funding */}
      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <KeyActionsPanel wallet={wallet} />

        <Panel title="Funding Links">
          {!wallet.faucet_links?.length ? (
            <EmptyState
              label="Funding Links"
              title="No faucet shortcuts for this wallet"
              description="Mainnet or custom wallet configurations usually require manual funding."
            />
          ) : (
            <div className="space-y-3">
              {wallet.faucet_links.map((link, i) => (
                <a
                  key={i}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block rounded-lg border p-3 transition-all hover:-translate-y-px hover:shadow-hover-elevated"
                >
                  <div className="text-sm font-semibold text-text">
                    {link.label}
                  </div>
                  <div className="mt-0.5 text-xs text-text-3 break-all">
                    {link.url}
                  </div>
                </a>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {/* Payment Activity */}
      <Panel title="Payment Activity">
        {!wallet.payment_activity?.length ? (
          <EmptyState
            label="Payment Activity"
            title="No payment activity recorded"
            description="Completed paid jobs and local settlement history will surface here."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b">
                  <th className="eyebrow pb-3 pr-4">Capability</th>
                  <th className="eyebrow pb-3 pr-4">Status</th>
                  <th className="eyebrow pb-3 pr-4">Payment</th>
                  <th className="eyebrow pb-3">When</th>
                </tr>
              </thead>
              <tbody>
                {wallet.payment_activity.map((row, i) => (
                  <tr key={i} className="border-b last:border-b-0">
                    <td className="py-3 pr-4">
                      <div className="font-semibold text-text">
                        {row.capability}
                      </div>
                      <div className="mt-0.5 text-xs text-text-3">
                        {row.platform || ""}
                      </div>
                    </td>
                    <td className="py-3 pr-4">
                      <Badge status={row.status || "pending"} />
                    </td>
                    <td className="py-3 pr-4">
                      <span className="inline-flex items-center gap-1 rounded-full border bg-white px-3 py-1 font-mono text-xs text-rose-accent">
                        {formatMoney(
                          row.payment_amount || 0,
                          row.payment_currency || "USDC",
                        )}
                        <span className="text-text-4">
                          ({row.payment_protocol || "unassigned"})
                        </span>
                      </span>
                    </td>
                    <td className="py-3 text-xs text-text-3">
                      {formatTimestamp(row.completed_at || row.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

function KeyActionsPanel({ wallet }: { wallet: WalletOverview }) {
  const [exportToken, setExportToken] = useState("");
  const [exportedSecret, setExportedSecret] = useState("");
  const [importKey, setImportKey] = useState("");
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState("");

  async function handleExport() {
    setExporting(true);
    try {
      const result = await exportWallet(exportToken);
      setExportedSecret(result.secret_key || "");
      setExportToken("");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  async function handleImport(e: FormEvent) {
    e.preventDefault();
    setImporting(true);
    try {
      const result = await importWallet(importKey);
      setImportKey("");
      setMessage(
        `Wallet import saved for ${result.address}. Restart required: ${result.restart_required ? "yes" : "no"}.`,
      );
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  return (
    <Panel title="Key Actions">
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <button
            onClick={handleExport}
            disabled={!wallet.export_supported || exporting}
            className="rounded-[10px] bg-text px-4 py-2 text-sm font-semibold text-white shadow-button transition-all hover:-translate-y-px hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {exporting ? "Exporting…" : "Export key"}
          </button>
          <span className="text-xs text-text-3">
            {wallet.export_supported
              ? "Requires a short-lived CLI export token."
              : "Current provider does not support export."}
          </span>
        </div>

        <label className="block">
          <span className="eyebrow">CLI Export Token</span>
          <input
            type="password"
            value={exportToken}
            onChange={(e) => setExportToken(e.target.value)}
            disabled={!wallet.export_supported}
            placeholder="agent-adapter wallet export-token"
            className="mt-1 w-full rounded-[10px] border bg-input px-3 py-2 font-mono text-sm text-text placeholder:text-text-4 focus:border-strong focus:outline-none disabled:opacity-50"
          />
        </label>

        <label className="block">
          <span className="eyebrow">Exported Secret</span>
          <textarea
            readOnly
            value={exportedSecret}
            rows={3}
            placeholder="Exported secret will appear here"
            className="mt-1 w-full resize-none rounded-[10px] border bg-input px-3 py-2 font-mono text-sm text-text placeholder:text-text-4 focus:border-strong focus:outline-none"
          />
        </label>

        <div className="border-t pt-4">
          <form onSubmit={handleImport} className="space-y-3">
            <label className="block">
              <span className="eyebrow">Import Solana Raw Secret</span>
              <textarea
                value={importKey}
                onChange={(e) => setImportKey(e.target.value)}
                rows={3}
                placeholder="Paste a base58 secret key"
                className="mt-1 w-full resize-none rounded-[10px] border bg-input px-3 py-2 font-mono text-sm text-text placeholder:text-text-4 focus:border-strong focus:outline-none"
              />
            </label>
            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={importing}
                className="rounded-[10px] border bg-white px-4 py-2 text-sm font-semibold text-text shadow-elevated transition-all hover:-translate-y-px hover:shadow-hover-elevated disabled:opacity-50"
              >
                {importing ? "Importing…" : "Import and persist"}
              </button>
              <span className="text-xs text-text-3">
                Restart required:{" "}
                {wallet.import_requires_restart ? "yes" : "no"}
              </span>
            </div>
          </form>
        </div>

        {message && (
          <p className="rounded-lg bg-input px-3 py-2 text-sm text-text-2">
            {message}
          </p>
        )}
      </div>
    </Panel>
  );
}
