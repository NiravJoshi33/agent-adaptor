import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Panel({ title, action, children, className }: PanelProps) {
  return (
    <section
      className={cn(
        "rounded-xl border bg-white p-5 shadow-card sm:p-6",
        className,
      )}
    >
      <div className="mb-4 flex items-center justify-between gap-4">
        <h3 className="text-lg font-bold tracking-tight text-text">
          {title}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}
