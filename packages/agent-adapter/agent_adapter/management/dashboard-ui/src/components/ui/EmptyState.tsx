interface EmptyStateProps {
  label: string;
  title: string;
  description: string;
}

export function EmptyState({ label, title, description }: EmptyStateProps) {
  return (
    <div className="rounded-xl border bg-white p-5 shadow-card">
      <span className="eyebrow">{label}</span>
      <strong className="mt-2 block text-base font-bold text-text">
        {title}
      </strong>
      <p className="mt-2 text-[0.8125rem] leading-relaxed text-text-3">
        {description}
      </p>
    </div>
  );
}
