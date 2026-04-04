import { useCallback, useState } from "react";
import {
  getStatus,
  getDecisions,
  pauseAgent,
  resumeAgent,
  type RuntimeStatus,
  type Decision,
} from "@/lib/api";
import { useApi } from "@/hooks/use-api";
import { PageHero } from "@/components/layout/PageHero";
import { Panel } from "@/components/ui/Panel";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Spinner";
import { formatTimestamp, clipText } from "@/lib/utils";

export default function Agent() {
  const statusFetcher = useCallback(() => getStatus(), []);
  const decisionsFetcher = useCallback(
    () => getDecisions(25).then((r) => r.decisions),
    [],
  );
  const { data: status, loading: statusLoading, refetch: refetchStatus } =
    useApi<RuntimeStatus>(statusFetcher);
  const { data: decisions, loading: decisionsLoading } =
    useApi<Decision[]>(decisionsFetcher);

  const [acting, setActing] = useState(false);

  async function handlePause() {
    setActing(true);
    try {
      await pauseAgent();
      refetchStatus();
    } finally {
      setActing(false);
    }
  }

  async function handleResume() {
    setActing(true);
    try {
      await resumeAgent();
      refetchStatus();
    } finally {
      setActing(false);
    }
  }

  if (statusLoading || !status) return <Spinner />;

  return (
    <>
      <PageHero
        eyebrow="Autonomous Operation"
        title="Agent"
        description="Inspect recent decisions, tool invocations, and operational state before you let the agent run wider."
        compact
        actions={
          <>
            <button
              onClick={handlePause}
              disabled={acting}
              className="rounded-[10px] bg-text px-4 py-2 text-sm font-semibold text-white shadow-button transition-all hover:-translate-y-px hover:opacity-85 disabled:opacity-50"
            >
              Pause
            </button>
            <button
              onClick={handleResume}
              disabled={acting}
              className="rounded-[10px] border bg-white px-4 py-2 text-sm font-semibold text-text shadow-elevated transition-all hover:-translate-y-px hover:shadow-hover-elevated disabled:opacity-50"
            >
              Resume
            </button>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(270px,360px)_1fr]">
        <Panel title="Status">
          <Card
            label="Status"
            value={status.agent_status}
            foot={`${status.active_jobs} active jobs and ${status.jobs_completed_today ?? 0} completed today. The runtime remains the source of truth for payment, job state, and tool execution.`}
            className="shadow-none border-0 p-0"
          />
        </Panel>

        <Panel title="Decision Log">
          {decisionsLoading ? (
            <Spinner />
          ) : !decisions?.length ? (
            <EmptyState
              label="Decision Log"
              title="No recent decisions"
              description="Once the embedded agent plans or invokes tools, the recent trace will appear here."
            />
          ) : (
            <div className="space-y-0">
              {decisions.map((entry, i) => (
                <div
                  key={i}
                  className="relative border-b py-4 pl-6 last:border-b-0"
                >
                  {/* Timeline dot */}
                  <div className="absolute left-0 top-5 h-2.5 w-2.5 rounded-full bg-rose-accent shadow-[0_0_8px_rgba(217,112,89,0.5)]" />
                  <div className="flex items-baseline justify-between gap-3">
                    <strong className="text-sm font-semibold text-text">
                      {entry.action}
                    </strong>
                    <span className="shrink-0 text-xs text-text-4">
                      {formatTimestamp(entry.created_at)}
                    </span>
                  </div>
                  <pre className="mt-2 overflow-auto rounded-lg border bg-black/[0.02] p-3 font-mono text-xs leading-relaxed text-text-2">
                    {clipText(entry.detail, 400)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
