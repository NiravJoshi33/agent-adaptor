import { FormEvent, useCallback, useState } from "react";
import {
  getCapabilities,
  refreshCapabilities,
  updatePricing,
  enableCapability,
  disableCapability,
  type Capability,
} from "@/lib/api";
import { useApi } from "@/hooks/use-api";
import { PageHero } from "@/components/layout/PageHero";
import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Spinner";

export default function Capabilities() {
  const fetcher = useCallback(() => getCapabilities(), []);
  const { data, loading, refetch } = useApi(fetcher);
  const [refreshing, setRefreshing] = useState(false);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await refreshCapabilities();
      refetch();
    } finally {
      setRefreshing(false);
    }
  }

  const caps = data?.capabilities || [];

  return (
    <>
      <PageHero
        eyebrow="Provider Sovereignty"
        title="Capabilities"
        description="Review discovered endpoints, keep pricing tight, and gate what the agent is allowed to sell."
        compact
        callout={{
          label: "Policy",
          text: "Discovery is automatic. Monetization is curated.",
        }}
      />

      <Panel
        title="Capability Registry"
        action={
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="rounded-[10px] bg-text px-4 py-2 text-sm font-semibold text-white shadow-button transition-all hover:-translate-y-px hover:opacity-85 disabled:opacity-50"
          >
            {refreshing ? "Refreshing…" : "Refresh Spec"}
          </button>
        }
      >
        {loading ? (
          <Spinner />
        ) : caps.length === 0 ? (
          <EmptyState
            label="No capabilities"
            title="Nothing discovered yet"
            description="Refresh the spec or connect a source to populate the registry."
          />
        ) : (
          <div className="space-y-4">
            {caps.map((cap) => (
              <CapabilityRow
                key={cap.name}
                capability={cap}
                onUpdated={refetch}
              />
            ))}
          </div>
        )}
      </Panel>
    </>
  );
}

function CapabilityRow({
  capability: cap,
  onUpdated,
}: {
  capability: Capability;
  onUpdated: () => void;
}) {
  const pricing = cap.pricing || {
    model: "per_call",
    amount: 0,
    currency: "USDC",
    item_field: "",
    floor: 0,
    ceiling: 0,
  };

  const [form, setForm] = useState({
    model: pricing.model || "per_call",
    amount: pricing.amount ?? 0,
    currency: pricing.currency || "USDC",
    item_field: pricing.item_field || "",
    floor: pricing.floor ?? 0,
    ceiling: pricing.ceiling ?? 0,
  });
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await updatePricing(cap.name, form);
      onUpdated();
    } finally {
      setSaving(false);
    }
  }

  async function handleToggle() {
    setToggling(true);
    try {
      if (cap.enabled) {
        await disableCapability(cap.name);
      } else {
        await enableCapability(cap.name);
      }
      onUpdated();
    } finally {
      setToggling(false);
    }
  }

  return (
    <div className="rounded-xl border bg-white p-4 transition-shadow hover:shadow-hover-elevated">
      {/* Header */}
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-semibold text-text">{cap.name}</div>
          <div className="mt-0.5 text-xs text-text-3">
            {cap.description || cap.source_ref || ""}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge status={cap.status} />
          <span className="rounded-full border bg-black/[0.02] px-2.5 py-0.5 font-mono text-[0.6875rem] text-text-3">
            {cap.source}
          </span>
        </div>
      </div>

      {cap.drift_status && cap.drift_status !== cap.status && (
        <div className="mb-3 text-xs text-text-3">
          drift: {cap.drift_status.replace(/_/g, " ")}
        </div>
      )}

      {/* Pricing form */}
      <form onSubmit={handleSave}>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block">
            <span className="eyebrow">Amount</span>
            <input
              type="number"
              step="0.001"
              min="0"
              value={form.amount}
              onChange={(e) =>
                setForm({ ...form, amount: Number(e.target.value) })
              }
              className="mt-1 w-full rounded-[10px] border bg-input px-3 py-2 font-mono text-sm text-text focus:border-strong focus:outline-none"
            />
          </label>
          <label className="block">
            <span className="eyebrow">Model</span>
            <select
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              className="mt-1 w-full rounded-[10px] border bg-input px-3 py-2 text-sm text-text focus:border-strong focus:outline-none"
            >
              {["per_call", "per_item", "per_token", "quoted"].map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="eyebrow">Currency</span>
            <input
              value={form.currency}
              onChange={(e) => setForm({ ...form, currency: e.target.value })}
              className="mt-1 w-full rounded-[10px] border bg-input px-3 py-2 font-mono text-sm text-text focus:border-strong focus:outline-none"
            />
          </label>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <label className="block">
            <span className="eyebrow">Item Field</span>
            <input
              value={form.item_field}
              onChange={(e) => setForm({ ...form, item_field: e.target.value })}
              className="mt-1 w-full rounded-[10px] border bg-input px-3 py-2 text-sm text-text focus:border-strong focus:outline-none"
            />
          </label>
          <label className="block">
            <span className="eyebrow">Floor</span>
            <input
              type="number"
              step="0.001"
              min="0"
              value={form.floor}
              onChange={(e) =>
                setForm({ ...form, floor: Number(e.target.value) })
              }
              className="mt-1 w-full rounded-[10px] border bg-input px-3 py-2 font-mono text-sm text-text focus:border-strong focus:outline-none"
            />
          </label>
          <label className="block">
            <span className="eyebrow">Ceiling</span>
            <input
              type="number"
              step="0.001"
              min="0"
              value={form.ceiling}
              onChange={(e) =>
                setForm({ ...form, ceiling: Number(e.target.value) })
              }
              className="mt-1 w-full rounded-[10px] border bg-input px-3 py-2 font-mono text-sm text-text focus:border-strong focus:outline-none"
            />
          </label>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-[10px] bg-text px-4 py-2 text-sm font-semibold text-white shadow-button transition-all hover:-translate-y-px hover:opacity-85 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save pricing"}
          </button>
          <button
            type="button"
            onClick={handleToggle}
            disabled={toggling}
            className="rounded-[10px] border bg-white px-4 py-2 text-sm font-semibold text-text shadow-elevated transition-all hover:-translate-y-px hover:shadow-hover-elevated disabled:opacity-50"
          >
            {toggling
              ? "Updating…"
              : cap.enabled
                ? "Disable"
                : "Enable"}
          </button>
        </div>
      </form>
    </div>
  );
}
