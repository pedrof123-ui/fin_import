"use client";

import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { RESEARCH_API } from "@/lib/config";

const POLL_MS = 15000;
const DEFAULT_MODEL = "anthropic/claude-sonnet-4-6";
const MODEL_OPTIONS = [
  { label: "Claude Sonnet 4.6 (Default)", value: "anthropic/claude-sonnet-4-6" },
  { label: "Qwen3 235B",                  value: "qwen/qwen3-235b-a22b-2507" },
  { label: "Gemini 3.5 Flash",            value: "google/gemini-3.5-flash" },
  { label: "Gemini 3.1 Pro",              value: "google/gemini-3.1-pro-preview" },
  { label: "Qwen3.7 Max",                 value: "qwen/qwen3.7-max" },
  { label: "MiniMax M3",                  value: "minimax/minimax-m3" },
];

export default function EquityResearchViewer({ ticker }: { ticker: string }) {
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [report, setReport] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  useEffect(() => () => stopPolling(), []);

  useEffect(() => {
    setReport(null);
    setGenerating(false);
    setError(null);
    stopPolling();
  }, [ticker]);

  const fetchReport = async (selectedModel: string): Promise<string> => {
    const res = await fetch(`${RESEARCH_API}/research/report?ticker=${ticker}&model=${encodeURIComponent(selectedModel)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };

  const handleGo = async () => {
    stopPolling();
    setGenerating(true);
    setError(null);
    setReport(null);

    try {
      const text = await fetchReport(model);
      setReport(text);

      if (text.startsWith("## Generating")) {
        intervalRef.current = setInterval(async () => {
          try {
            const updated = await fetchReport(model);
            setReport(updated);
            if (!updated.startsWith("## Generating")) {
              stopPolling();
              setGenerating(false);
            }
          } catch {
            // ignore transient poll errors
          }
        }, POLL_MS);
      } else {
        setGenerating(false);
      }
    } catch (e: unknown) {
      setError((e as Error).message);
      setGenerating(false);
    }
  };

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          disabled={generating}
          className="font-mono text-xs h-8 px-2 rounded border border-white/[0.07] bg-transparent text-zinc-400 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:border-violet-500/50"
        >
          {MODEL_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value} className="bg-zinc-900 text-zinc-300">
              {opt.label}
            </option>
          ))}
        </select>
        <button
          onClick={handleGo}
          disabled={generating}
          className="font-mono text-xs tracking-widest uppercase h-8 px-4 rounded border border-white/[0.07] text-zinc-400 hover:text-zinc-200 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {generating ? "Generating..." : "Go ▶"}
        </button>
        {generating && report && (
          <span className="font-mono text-xs text-zinc-500">
            Polling every 15s for results...
          </span>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20 text-rose-400 mb-4">
          <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0 bg-rose-500" />
          {error}
        </div>
      )}

      {report && (
        <div className="max-w-4xl">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              h1: ({ children }) => (
                <h1 className="font-mono text-base text-zinc-100 font-semibold mb-4 mt-6">{children}</h1>
              ),
              h2: ({ children }) => (
                <h2 className="font-mono text-xs text-violet-300 font-semibold mb-2 mt-6 tracking-[0.2em] uppercase">{children}</h2>
              ),
              h3: ({ children }) => (
                <h3 className="font-mono text-xs text-zinc-300 font-semibold mb-2 mt-4">{children}</h3>
              ),
              p: ({ children }) => (
                <p className="font-mono text-xs text-zinc-400 mb-3 leading-relaxed">{children}</p>
              ),
              ul: ({ children }) => (
                <ul className="font-mono text-xs text-zinc-400 mb-3 space-y-1 pl-4">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="font-mono text-xs text-zinc-400 mb-3 space-y-1 pl-4 list-decimal">{children}</ol>
              ),
              li: ({ children }) => (
                <li className="font-mono text-xs text-zinc-400 before:content-['–'] before:mr-2 before:text-zinc-600">{children}</li>
              ),
              strong: ({ children }) => (
                <strong className="text-zinc-200 font-semibold">{children}</strong>
              ),
              em: ({ children }) => (
                <em className="text-zinc-500 not-italic">{children}</em>
              ),
              table: ({ children }) => (
                <div className="overflow-x-auto mb-4">
                  <table className="w-full text-xs font-mono border-collapse">{children}</table>
                </div>
              ),
              thead: ({ children }) => (
                <thead>{children}</thead>
              ),
              th: ({ children }) => (
                <th className="text-left text-zinc-500 border-b border-white/[0.07] px-3 py-1.5 font-medium whitespace-nowrap">{children}</th>
              ),
              td: ({ children }) => (
                <td className="text-zinc-400 border-b border-white/[0.04] px-3 py-1">{children}</td>
              ),
              hr: () => (
                <hr className="border-white/[0.06] my-5" />
              ),
              blockquote: ({ children }) => (
                <blockquote className="border-l-2 border-violet-500/40 pl-3 my-3">{children}</blockquote>
              ),
              code: ({ children }) => (
                <code className="font-mono text-xs text-violet-300 bg-violet-950/30 px-1 py-0.5 rounded">{children}</code>
              ),
            }}
          >
            {report}
          </ReactMarkdown>
        </div>
      )}

      {!report && !generating && !error && (
        <div className="flex flex-col items-center justify-center h-48 gap-2">
          <p className="font-mono text-xs text-zinc-600 tracking-widest uppercase">No report loaded</p>
          <p className="font-mono text-xs text-zinc-700">Click Go to generate the AI equity research report</p>
        </div>
      )}
    </div>
  );
}
