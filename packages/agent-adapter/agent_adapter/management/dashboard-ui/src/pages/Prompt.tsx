import { FormEvent, useCallback, useState } from "react";
import { getPrompt, updatePrompt, type PromptSettings } from "@/lib/api";
import { useApi } from "@/hooks/use-api";
import { PageHero } from "@/components/layout/PageHero";
import { Panel } from "@/components/ui/Panel";
import { Spinner } from "@/components/ui/Spinner";

export default function Prompt() {
  const fetcher = useCallback(() => getPrompt(), []);
  const { data: prompt, loading, refetch } = useApi<PromptSettings>(fetcher);

  if (loading || !prompt) return <Spinner />;

  return (
    <>
      <PageHero
        eyebrow="Provider Policy Surface"
        title="Prompt"
        description="Adjust the provider strategy layer live. Changes are persisted locally and hot-reloaded into the cached agent loop before the next run."
        compact
        callout={{
          label: "Reload Model",
          text: "File-backed prompt editing with append or replace control.",
        }}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <PromptEditor prompt={prompt} onSaved={refetch} />

        <Panel title="Effective Prompt">
          <div className="space-y-3">
            <div>
              <div className="eyebrow">Path</div>
              <div className="mt-1 break-all text-sm text-text-3">
                {prompt.path || ""}
              </div>
            </div>
            <pre className="max-h-[500px] overflow-auto rounded-lg border bg-input/50 p-4 font-mono text-xs leading-relaxed text-text-2">
              {prompt.effective_prompt || ""}
            </pre>
          </div>
        </Panel>
      </div>
    </>
  );
}

function PromptEditor({
  prompt,
  onSaved,
}: {
  prompt: PromptSettings;
  onSaved: () => void;
}) {
  const [customPrompt, setCustomPrompt] = useState(
    prompt.custom_prompt || "",
  );
  const [mode, setMode] = useState<"append" | "replace">(
    prompt.append_to_default ? "append" : "replace",
  );
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await updatePrompt({
        custom_prompt: customPrompt,
        append_to_default: mode === "append",
      });
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Panel title="Prompt Controls">
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Mode selector */}
        <div className="flex flex-wrap gap-2">
          <label
            className={`inline-flex cursor-pointer items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
              mode === "append"
                ? "border-text bg-text text-white"
                : "text-text-2 hover:bg-black/[0.04]"
            }`}
          >
            <input
              type="radio"
              name="mode"
              value="append"
              checked={mode === "append"}
              onChange={() => setMode("append")}
              className="sr-only"
            />
            Append to default
          </label>
          <label
            className={`inline-flex cursor-pointer items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
              mode === "replace"
                ? "border-text bg-text text-white"
                : "text-text-2 hover:bg-black/[0.04]"
            }`}
          >
            <input
              type="radio"
              name="mode"
              value="replace"
              checked={mode === "replace"}
              onChange={() => setMode("replace")}
              className="sr-only"
            />
            Replace default
          </label>
        </div>

        {/* Textarea */}
        <label className="block">
          <span className="eyebrow">Custom Prompt</span>
          <textarea
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
            rows={16}
            className="mt-2 w-full resize-y rounded-[10px] border bg-input px-4 py-3 font-mono text-sm leading-relaxed text-text placeholder:text-text-4 focus:border-strong focus:outline-none"
          />
        </label>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-[10px] bg-text px-4 py-2 text-sm font-semibold text-white shadow-button transition-all hover:-translate-y-px hover:opacity-85 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save prompt"}
          </button>
          <span className="text-xs text-text-3">
            Changes hot-reload before the next agent loop run.
          </span>
        </div>
      </form>
    </Panel>
  );
}
