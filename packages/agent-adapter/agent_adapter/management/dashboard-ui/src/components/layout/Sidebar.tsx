import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useState } from "react";

const NAV_ITEMS = [
  { to: "/dashboard/", idx: "01", label: "Overview", sub: "Wallet and revenue pulse" },
  { to: "/dashboard/capabilities", idx: "02", label: "Capabilities", sub: "Pricing, drift, availability" },
  { to: "/dashboard/agent", idx: "03", label: "Agent", sub: "Decisions and execution" },
  { to: "/dashboard/operations", idx: "04", label: "Operations", sub: "Wallet, heartbeats, events" },
  { to: "/dashboard/metrics", idx: "05", label: "Metrics", sub: "Revenue, cost, performance" },
  { to: "/dashboard/prompt", idx: "06", label: "Prompt", sub: "Provider instructions, live policy" },
  { to: "/dashboard/wallet", idx: "07", label: "Wallet", sub: "Keys, balances, payment history" },
];

export function Sidebar() {
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* Mobile top bar */}
      <div className="flex items-center justify-between border-b px-4 py-3 lg:hidden">
        <Brand />
        <button
          onClick={() => setOpen(!open)}
          className="rounded-[10px] border p-2 text-text-3 transition-colors hover:text-text"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
            {open ? (
              <path d="M5 5l10 10M15 5L5 15" />
            ) : (
              <path d="M3 6h14M3 10h14M3 14h14" />
            )}
          </svg>
        </button>
      </div>

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-[280px] flex-col gap-6 border-r bg-white/80 px-5 py-6 backdrop-blur-xl transition-transform lg:static lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="hidden lg:block">
          <Brand />
        </div>

        <nav className="flex flex-col gap-1.5">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/dashboard/"}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                cn(
                  "group flex items-center gap-3 rounded-[10px] px-3 py-2.5 transition-all",
                  isActive
                    ? "bg-text text-white shadow-button"
                    : "text-text-2 hover:bg-black/[0.04]",
                )
              }
            >
              <span className="font-mono text-[0.625rem] tracking-[0.14em] opacity-50">
                {item.idx}
              </span>
              <span className="min-w-0">
                <span className="block text-[0.9375rem] font-semibold leading-tight">
                  {item.label}
                </span>
                <span className="block text-xs opacity-60">{item.sub}</span>
              </span>
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto rounded-[10px] border p-4">
          <div className="eyebrow">Local-First Control</div>
          <p className="mt-2 text-[0.8125rem] leading-relaxed text-text-3">
            Self-hosted runtime for monetized APIs, wallet-backed execution, and
            autonomous agent operations.
          </p>
        </div>
      </aside>

      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/20 backdrop-blur-sm lg:hidden"
          onClick={() => setOpen(false)}
        />
      )}
    </>
  );
}

function Brand() {
  return (
    <NavLink to="/dashboard/" className="flex items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-[10px] bg-text text-sm font-extrabold text-white shadow-button">
        A
      </div>
      <div>
        <div className="eyebrow">Agent Adapter</div>
        <div className="text-lg font-bold leading-tight tracking-tight">
          Runtime
        </div>
      </div>
    </NavLink>
  );
}
