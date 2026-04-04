import { useCallback } from "react";
import {
  getMetrics,
  getTimeseries,
  type MetricsSummary,
  type TimeseriesPoint,
} from "@/lib/api";
import { useApi } from "@/hooks/use-api";
import { PageHero } from "@/components/layout/PageHero";
import { Card } from "@/components/ui/Card";
import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Spinner";
import { formatMoney } from "@/lib/utils";

export default function Metrics() {
  const metricsFetcher = useCallback(() => getMetrics(30), []);
  const seriesFetcher = useCallback(
    () => getTimeseries(14).then((r) => r.series),
    [],
  );
  const { data: metrics, loading: metricsLoading } =
    useApi<MetricsSummary>(metricsFetcher);
  const { data: series, loading: seriesLoading } =
    useApi<TimeseriesPoint[]>(seriesFetcher);

  if (metricsLoading || !metrics) return <Spinner />;

  const revenueText = Object.entries(metrics.revenue_by_currency || {}).length
    ? Object.entries(metrics.revenue_by_currency)
        .map(([currency, value]) => formatMoney(value, currency))
        .join(" / ")
    : "0";

  return (
    <>
      <PageHero
        eyebrow="Economic Observability"
        title="Metrics"
        description="Track what the runtime is earning, what the agent is spending on inference, and which payment rails are actually pulling their weight."
        compact
        callout={{
          label: "Margin Lens",
          text: "Stable-coin revenue minus estimated LLM burn, visible in one place.",
        }}
      />

      {/* Stat cards */}
      <div className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4 animate-fade-up stagger-1">
        <Card
          label="Completed Jobs"
          value={metrics.completed_jobs || 0}
          foot="Successful runs in the selected reporting window."
        />
        <Card
          label="Revenue"
          value={revenueText}
          foot="Completed-job revenue grouped across payment currencies."
        />
        <Card
          label="LLM Cost"
          value={formatMoney(
            metrics.llm_usage?.estimated_cost || 0,
            metrics.llm_usage?.currency || "USD",
          )}
          foot="Estimated inference spend recorded from actual agent usage."
        />
        <Card
          label="Stable Margin"
          value={formatMoney(metrics.estimated_stable_margin || 0, "USD/USDC")}
          foot="Revenue in USD/USDC minus estimated LLM cost."
        />
      </div>

      {/* Charts row */}
      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <Panel title="Daily Revenue vs Cost">
          {seriesLoading || !series?.length ? (
            <div className="flex h-60 items-center justify-center text-sm text-text-3">
              {seriesLoading ? "Loading…" : "No timeseries data yet."}
            </div>
          ) : (
            <RevenueChart series={series} />
          )}
        </Panel>

        <Panel title="Payment Mix">
          {!metrics.revenue_by_payment_protocol?.length ? (
            <EmptyState
              label="Payment Mix"
              title="No paid jobs yet"
              description="Once the runtime starts completing paid work, protocol-level revenue will show up here."
            />
          ) : (
            <div className="divide-y">
              {metrics.revenue_by_payment_protocol.map((row, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                >
                  <div>
                    <div className="text-sm font-semibold text-text">
                      {row.payment_protocol || "unassigned"}
                    </div>
                    <div className="text-xs text-text-3">
                      {row.jobs} jobs
                    </div>
                  </div>
                  <div className="font-mono text-sm font-semibold tracking-tight text-text">
                    {formatMoney(row.revenue, "USDC")}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {/* Bottom row */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Job Outcomes">
          {!Object.keys(metrics.jobs_by_status || {}).length ? (
            <EmptyState
              label="Job Outcomes"
              title="No jobs recorded"
              description="Job lifecycle data will appear here as soon as the runtime starts executing work."
            />
          ) : (
            <div className="divide-y">
              {Object.entries(metrics.jobs_by_status).map(
                ([status, count]) => (
                  <div
                    key={status}
                    className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                  >
                    <Badge status={status} />
                    <div className="font-mono text-sm font-semibold text-text">
                      {count}
                    </div>
                  </div>
                ),
              )}
            </div>
          )}
        </Panel>

        <Panel title="LLM Usage">
          <LlmUsagePanel metrics={metrics} />
        </Panel>
      </div>
    </>
  );
}

function RevenueChart({ series }: { series: TimeseriesPoint[] }) {
  const maxValue = Math.max(
    1,
    ...series.map((p) =>
      Math.max(Number(p.revenue || 0), Number(p.llm_cost || 0)),
    ),
  );

  return (
    <>
      <div className="flex items-end gap-2 overflow-x-auto pb-2" style={{ minHeight: 200 }}>
        {series.map((point) => (
          <div
            key={point.day}
            className="flex flex-1 flex-col items-center gap-1"
            style={{ minWidth: 28 }}
          >
            <div className="flex w-full items-end justify-center gap-1" style={{ height: 180 }}>
              <div
                className="w-3 rounded-full bg-rose-accent/80"
                style={{
                  height: `${Math.max((Number(point.revenue || 0) / maxValue) * 100, 4)}%`,
                }}
              />
              <div
                className="w-3 rounded-full bg-text-3/50"
                style={{
                  height: `${Math.max((Number(point.llm_cost || 0) / maxValue) * 100, 4)}%`,
                }}
              />
            </div>
            <span className="font-mono text-[0.625rem] text-text-4">
              {point.day.slice(5)}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-3 flex gap-4 text-xs text-text-3">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-rose-accent/80" />
          Revenue
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-text-3/50" />
          LLM Cost
        </span>
      </div>
    </>
  );
}

function LlmUsagePanel({ metrics }: { metrics: MetricsSummary }) {
  const usage = metrics.llm_usage || {
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    estimated_cost: 0,
    currency: "USD",
    by_model: [],
  };

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-4 border-b py-3">
        <div>
          <div className="text-sm font-semibold text-text">Total Tokens</div>
          <div className="text-xs text-text-3">
            {usage.prompt_tokens || 0} prompt / {usage.completion_tokens || 0}{" "}
            completion
          </div>
        </div>
        <div className="font-mono text-sm font-semibold text-text">
          {usage.total_tokens || 0}
        </div>
      </div>
      <div className="flex items-center justify-between gap-4 border-b py-3">
        <div>
          <div className="text-sm font-semibold text-text">
            Average Completed Job
          </div>
          <div className="text-xs text-text-3">
            Completed job revenue in the reporting window
          </div>
        </div>
        <div className="font-mono text-sm font-semibold text-text">
          {formatMoney(metrics.avg_completed_job_value || 0, "USDC")}
        </div>
      </div>

      {usage.by_model?.length ? (
        <div className="pt-3">
          <div className="eyebrow mb-2">Model Breakdown</div>
          <div className="divide-y">
            {usage.by_model.map((row, i) => (
              <div
                key={i}
                className="flex items-center justify-between gap-4 py-2"
              >
                <div>
                  <div className="text-sm font-semibold text-text">
                    {row.model || "unknown"}
                  </div>
                  <div className="text-xs text-text-3">
                    {row.calls} calls / {row.total_tokens} tokens
                  </div>
                </div>
                <div className="font-mono text-sm font-semibold text-text">
                  {formatMoney(row.estimated_cost, usage.currency || "USD")}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="py-2 text-xs text-text-3">No LLM usage recorded yet.</p>
      )}
    </div>
  );
}
