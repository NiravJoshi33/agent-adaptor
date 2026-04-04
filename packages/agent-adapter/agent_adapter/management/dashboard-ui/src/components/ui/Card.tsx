import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface CardProps {
  label: string;
  value: ReactNode;
  foot?: string;
  className?: string;
}

export function Card({ label, value, foot, className }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-white p-5 shadow-card transition-shadow hover:shadow-hover-elevated",
        className,
      )}
    >
      <span className="eyebrow">{label}</span>
      <strong className="mt-2 block text-xl font-bold leading-snug text-text">
        {value}
      </strong>
      {foot && (
        <p className="mt-2 text-[0.8125rem] leading-relaxed text-text-3">
          {foot}
        </p>
      )}
    </div>
  );
}
