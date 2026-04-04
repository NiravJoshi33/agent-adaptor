import type { ReactNode } from "react";

interface PageHeroProps {
  eyebrow: string;
  title: string;
  description: string;
  compact?: boolean;
  actions?: ReactNode;
  callout?: { label: string; text: string };
}

export function PageHero({
  eyebrow,
  title,
  description,
  compact,
  actions,
  callout,
}: PageHeroProps) {
  return (
    <section className="mb-8 flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between animate-fade-up">
      <div className={compact ? "max-w-2xl" : "max-w-3xl"}>
        <div className="eyebrow">{eyebrow}</div>
        <h2 className="mt-1 text-4xl font-extrabold leading-[0.95] tracking-tight text-text sm:text-5xl">
          {title}
        </h2>
        <p className="mt-3 max-w-xl text-base leading-relaxed text-text-2">
          {description}
        </p>
        {actions && <div className="mt-5 flex flex-wrap gap-3">{actions}</div>}
      </div>
      {callout && (
        <div className="shrink-0 rounded-[10px] border bg-white p-4 shadow-card sm:max-w-[280px]">
          <div className="eyebrow">{callout.label}</div>
          <p className="mt-1 text-[0.9375rem] font-semibold leading-snug text-text">
            {callout.text}
          </p>
        </div>
      )}
    </section>
  );
}
