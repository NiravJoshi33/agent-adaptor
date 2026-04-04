import { cn } from "@/lib/utils";

const STATUS_COLORS: Record<string, string> = {
  active: "text-emerald-600 bg-emerald-50 border-emerald-200",
  healthy: "text-emerald-600 bg-emerald-50 border-emerald-200",
  delivered: "text-emerald-600 bg-emerald-50 border-emerald-200",
  completed: "text-emerald-600 bg-emerald-50 border-emerald-200",
  running: "text-emerald-600 bg-emerald-50 border-emerald-200",
  registered: "text-emerald-600 bg-emerald-50 border-emerald-200",
  needs_pricing: "text-amber-600 bg-amber-50 border-amber-200",
  new: "text-amber-600 bg-amber-50 border-amber-200",
  pending: "text-amber-600 bg-amber-50 border-amber-200",
  disabled: "text-red-500 bg-red-50 border-red-200",
  stale: "text-red-500 bg-red-50 border-red-200",
  schema_changed: "text-red-500 bg-red-50 border-red-200",
  degraded: "text-red-500 bg-red-50 border-red-200",
  failed: "text-red-500 bg-red-50 border-red-200",
  error: "text-red-500 bg-red-50 border-red-200",
  paused: "text-red-500 bg-red-50 border-red-200",
};

export function Badge({ status }: { status: string }) {
  const colors = STATUS_COLORS[status] || "text-text-3 bg-black/[0.04] border-[rgba(0,0,0,0.1)]";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-[0.6875rem] font-semibold capitalize tracking-wide",
        colors,
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
