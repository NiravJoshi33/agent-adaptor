import { FormEvent, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { createSession } from "@/lib/api";

export default function Login() {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/dashboard/";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await createSession(token);
      setToken("");
      navigate(next, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-md animate-fade-up">
        <div className="mb-8 text-center">
          <div className="eyebrow">Protected Dashboard</div>
          <h2 className="mt-2 text-3xl font-extrabold tracking-tight text-text">
            Sign In
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-text-2">
            Remote management is enabled. Enter the management token to start a
            browser session.
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-xl border bg-white p-6 shadow-card"
        >
          <label className="block">
            <span className="eyebrow">Management Token</span>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoComplete="current-password"
              placeholder="adapter.managementToken"
              className="mt-2 w-full rounded-[10px] border bg-input px-4 py-3 font-mono text-sm tracking-wide text-text placeholder:text-text-4 focus:border-strong focus:outline-none focus:ring-1 focus:ring-black/10"
            />
          </label>

          <button
            type="submit"
            disabled={loading}
            className="mt-4 w-full rounded-[10px] bg-text py-3 text-[0.9375rem] font-semibold text-white shadow-button transition-all hover:opacity-85 hover:-translate-y-px disabled:cursor-not-allowed disabled:opacity-45"
          >
            {loading ? "Signing in…" : "Start session"}
          </button>

          <p className="mt-3 text-xs text-text-3">
            The token is exchanged for a short browser session cookie.
          </p>

          {error && (
            <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
              {error}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}
