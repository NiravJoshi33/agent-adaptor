import { useCallback } from "react";
import { Link } from "react-router-dom";
import { getStatus, type RuntimeStatus, type Capability } from "@/lib/api";
import { useApi } from "@/hooks/use-api";
import { PageHero } from "@/components/layout/PageHero";
import { Card } from "@/components/ui/Card";
import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Spinner";
import { formatMoney } from "@/lib/utils";

export default function Overview() {
  const fetcher = useCallback(() => getStatus(), []);
  const { data: status, loading } = useApi<RuntimeStatus>(fetcher);

  if (loading || !status) return <Spinner />;

  const caps = status.capabilities || [];

  return (
    <>
      <PageHero
        eyebrow="Local Provider Console"
        title={status.adapter_name}
        description="Operate wallet-backed capabilities, pricing, and autonomous execution from one sharp runtime surface."
        actions={
          <>
            <Link
              to="/dashboard/capabilities"
              className="inline-flex items-center rounded-[10px] bg-text px-4 py-2 text-[0.9375rem] font-semibold text-white shadow-button transition-all hover:-translate-y-px hover:opacity-85"
            >
              Tune capabilities
            </Link>
            <Link
              to="/dashboard/agent"
              className="inline-flex items-center rounded-[10px] border bg-white px-4 py-2 text-[0.9375rem] font-semibold text-text shadow-elevated transition-all hover:-translate-y-px hover:shadow-hover-elevated"
            >
              Inspect agent
            </Link>
          </>
        }
        callout={{
          label: "Runtime Mode",
          text: "Local, paid, and always auditable",
        }}
      />

      {/* Status pill */}
      <div className="mb-6 animate-fade-up stagger-1">
        <span className="inline-flex items-center gap-2 rounded-full border bg-white px-4 py-2 text-sm font-semibold capitalize shadow-subtle">
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]" />
          {status.agent_status}
        </span>
      </div>

      {/* Stat cards */}
      <div className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4 animate-fade-up stagger-2">
        <Card
          label="Wallet"
          value={
            <span className="break-all text-base font-bold">
              {status.wallet}
            </span>
          }
          foot="Primary signing identity for provider execution."
        />
        <Card
          label="Balances"
          value={`${status.balances?.sol ?? 0} SOL / ${status.balances?.usdc ?? 0} USDC`}
          foot="Liquidity ready for execution and x402 settlement."
        />
        <Card
          label="Active Jobs"
          value={status.active_jobs}
          foot="In-flight capability runs being tracked by the runtime."
        />
        <Card
          label="Earnings Today"
          value={formatMoney(status.earnings_today, "USDC")}
          foot="Revenue captured by this agent in the current local day."
        />
      </div>

      {/* Capability snapshot */}
      <Panel
        title="Capability Snapshot"
        action={
          <Link
            to="/dashboard/capabilities"
            className="text-sm font-medium text-rose-accent transition-colors hover:text-text"
          >
            Open capability editor
          </Link>
        }
        className="animate-fade-up stagger-3"
      >
        {caps.length === 0 ? (
          <EmptyState
            label="No capabilities"
            title="Nothing discovered yet"
            description="Refresh the spec or connect a source to populate the registry."
          />
        ) : (
          <CapabilityTable capabilities={caps} />
        )}
      </Panel>
    </>
  );
}

function CapabilityTable({ capabilities }: { capabilities: Capability[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b">
            <th className="eyebrow pb-3 pr-4">Name</th>
            <th className="eyebrow pb-3 pr-4">Status</th>
            <th className="eyebrow pb-3 pr-4">Pricing</th>
            <th className="eyebrow pb-3">Source</th>
          </tr>
        </thead>
        <tbody>
          {capabilities.map((cap) => (
            <tr key={cap.name} className="border-b last:border-b-0">
              <td className="py-3 pr-4">
                <div className="font-semibold text-text">{cap.name}</div>
                <div className="mt-0.5 text-xs text-text-3">
                  {cap.description || cap.source_ref || ""}
                </div>
              </td>
              <td className="py-3 pr-4">
                <Badge status={cap.status} />
                {cap.drift_status && cap.drift_status !== cap.status && (
                  <div className="mt-1 text-xs text-text-3">
                    drift: {cap.drift_status.replace(/_/g, " ")}
                  </div>
                )}
              </td>
              <td className="py-3 pr-4">
                {cap.pricing ? (
                  <span className="inline-flex items-center gap-1 rounded-full border bg-white px-3 py-1 font-mono text-xs text-rose-accent">
                    {cap.pricing.amount} {cap.pricing.currency}{" "}
                    <span className="text-text-4">({cap.pricing.model})</span>
                  </span>
                ) : (
                  <span className="text-xs text-text-4">Unset</span>
                )}
              </td>
              <td className="py-3">
                <span className="rounded-full border bg-black/[0.02] px-2.5 py-0.5 font-mono text-xs text-text-3">
                  {cap.source}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
