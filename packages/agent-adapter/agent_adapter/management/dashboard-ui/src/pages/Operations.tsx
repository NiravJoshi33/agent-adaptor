import { useCallback } from "react";
import { getOperations, type OperationsOverview } from "@/lib/api";
import { useApi } from "@/hooks/use-api";
import { PageHero } from "@/components/layout/PageHero";
import { Card } from "@/components/ui/Card";
import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Spinner";
import { formatTimestamp, clipText, formatMoney } from "@/lib/utils";

export default function Operations() {
  const fetcher = useCallback(() => getOperations(), []);
  const { data: ops, loading } = useApi<OperationsOverview>(fetcher);

  if (loading || !ops) return <Spinner />;

  return (
    <>
      <PageHero
        eyebrow="Runtime Operations"
        title="Operations"
        description="Keep the provider wallet, platform presence, webhook ingress, and recent execution activity visible from one operational surface."
        compact
        callout={{
          label: "Ops Focus",
          text: "Presence, liquidity, and inbound work signals stay visible while the agent runs.",
        }}
      />

      {/* Stat cards */}
      <div className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4 animate-fade-up stagger-1">
        <Card
          label="Signing Wallet"
          value={
            <span className="break-all text-base font-bold">
              {ops.wallet || "unknown"}
            </span>
          }
          foot="Primary runtime identity used for signing and settlement."
        />
        <Card
          label="Balances"
          value={`${ops.balances?.sol ?? 0} SOL / ${ops.balances?.usdc ?? 0} USDC`}
          foot="Live liquidity available for execution, settlement, and escrow."
        />
        <Card
          label="Heartbeats"
          value={`${ops.heartbeats_total || 0} checks / ${ops.payment_adapters?.length || 0} rails`}
          foot="Tracked presence checks stored in the runtime state layer."
        />
        <Card
          label="Pending Events"
          value={`${ops.pending_events || 0} queued / ${ops.active_jobs || 0} active jobs`}
          foot="Webhook and SSE messages waiting to be consumed or acknowledged."
        />
      </div>

      {/* Heartbeats + Events */}
      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <Panel title="Heartbeat Presence">
          {!ops.heartbeats?.length ? (
            <EmptyState
              label="Heartbeat Presence"
              title="No heartbeats recorded"
              description="Use net__heartbeat to persist presence checks for platforms or upstream services."
            />
          ) : (
            <div className="space-y-3">
              {ops.heartbeats.map((hb, i) => (
                <div
                  key={i}
                  className="rounded-lg border p-3 transition-shadow hover:shadow-subtle"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-text">
                        {hb.key}
                      </div>
                      <div className="mt-0.5 text-xs text-text-3">
                        {(hb.data as Record<string, string>)?.method || "POST"}{" "}
                        {(hb.data as Record<string, string>)?.url || ""}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge
                        status={
                          Number(
                            (hb.data as Record<string, unknown>)
                              ?.status_code || 0,
                          ) >= 200 &&
                          Number(
                            (hb.data as Record<string, unknown>)
                              ?.status_code || 0,
                          ) < 300
                            ? "healthy"
                            : "degraded"
                        }
                      />
                      <span className="text-xs text-text-4">
                        {(hb.data as Record<string, string>)?.status_code ||
                          "n/a"}
                      </span>
                    </div>
                  </div>
                  <div className="mt-2 flex justify-between text-xs text-text-3">
                    <span>
                      Sent{" "}
                      {formatTimestamp(
                        (hb.data as Record<string, string>)?.sent_at ||
                          hb.updated_at,
                      )}
                    </span>
                    <span>
                      {clipText(
                        (hb.data as Record<string, string>)?.response_body ||
                          "",
                      )}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Inbound Event Feed">
          {!ops.events?.length ? (
            <EmptyState
              label="Inbound Event Feed"
              title="No inbound events yet"
              description="Webhook and SSE traffic will appear here as soon as platforms begin pushing work into the runtime."
            />
          ) : (
            <div className="space-y-3">
              {ops.events.map((evt) => (
                <div
                  key={evt.id}
                  className="rounded-lg border p-3 transition-shadow hover:shadow-subtle"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-text">
                        {evt.event_type || "event"}
                      </div>
                      <div className="mt-0.5 text-xs text-text-3">
                        {evt.channel || evt.source || ""}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge
                        status={evt.delivered_at ? "delivered" : "pending"}
                      />
                      <span className="text-xs text-text-4">
                        {formatTimestamp(evt.created_at)}
                      </span>
                    </div>
                  </div>
                  <pre className="mt-2 overflow-auto rounded-lg border bg-black/[0.02] p-2 font-mono text-xs leading-relaxed text-text-2">
                    {clipText(evt.payload || {}, 260)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {/* Platforms + Jobs */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Connected Platforms">
          {!ops.registered_platforms?.length ? (
            <EmptyState
              label="Connected Platforms"
              title="No platforms registered"
              description="Platform registrations stored in runtime state will show up here with agent identity and activity details."
            />
          ) : (
            <div className="space-y-3">
              {ops.registered_platforms.map((p, i) => (
                <div
                  key={i}
                  className="rounded-lg border p-3 transition-shadow hover:shadow-subtle"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-text">
                        {p.platform_name || p.base_url}
                      </div>
                      <div className="mt-0.5 text-xs text-text-3">
                        {p.base_url || ""}
                      </div>
                    </div>
                    <Badge
                      status={p.registration_status || "registered"}
                    />
                  </div>
                  <div className="mt-2 flex justify-between text-xs text-text-3">
                    <span>Agent {p.agent_id || "unknown"}</span>
                    <span>
                      {p.last_active_at
                        ? `Last active ${formatTimestamp(p.last_active_at)}`
                        : `Registered ${formatTimestamp(p.registered_at)}`}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Recent Job Activity">
          {!ops.recent_jobs?.length ? (
            <EmptyState
              label="Recent Job Activity"
              title="No jobs recorded"
              description="Recent execution state will appear here once the runtime accepts and processes work."
            />
          ) : (
            <div className="space-y-3">
              {ops.recent_jobs.map((job, i) => (
                <div
                  key={i}
                  className="rounded-lg border p-3 transition-shadow hover:shadow-subtle"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-text">
                        {job.capability}
                      </div>
                      <div className="mt-0.5 text-xs text-text-3">
                        {job.payment_protocol || "unassigned"} /{" "}
                        {formatMoney(
                          job.payment_amount || 0,
                          job.payment_currency || "USDC",
                        )}
                      </div>
                    </div>
                    <Badge status={job.status || "pending"} />
                  </div>
                  <div className="mt-2 flex justify-between text-xs text-text-3">
                    <span>{job.platform || "local runtime"}</span>
                    <span>
                      {formatTimestamp(job.updated_at || job.created_at)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
