"use client";

import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API } from "@/lib/config";

const STATUS_POLL_MS = 2500;
const DEFAULT_MODEL = "google/gemini-3.5-flash";

type Phase =
  | "idle"
  | "gathering_data"
  | "digesting_companies"
  | "running_specialists"
  | "synthesizing"
  | "done"
  | "error"
  | "cancelled";

const PHASE_LABELS: Record<Phase, string> = {
  idle: "Starting...",
  gathering_data: "Gathering financials, transcripts & industry aggregates...",
  digesting_companies: "Summarizing earnings calls for each company...",
  running_specialists: "Running industry specialists and chief strategist...",
  synthesizing: "Assembling final report...",
  done: "Report ready.",
  error: "Generation failed.",
  cancelled: "Cancelled.",
};

interface ModelOption { label: string; value: string }
interface IndustryOption { industry: string; sector: string; member_count: number }
interface StatusResponse { phase: Phase; message: string; error: string | null }

const isTickerLike = (text: string) => /^[A-Z]{1,6}(\.[A-Z])?$/.test(text.trim());

export default function IndustryResearchViewer({
  onSelectTicker,
}: {
  onSelectTicker: (ticker: string) => void;
}) {
  const [industries, setIndustries] = useState<IndustryOption[]>([]);
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([{ label: "Gemini 3.5 Flash (Default)", value: DEFAULT_MODEL }]);
  const [selectedIndustry, setSelectedIndustry] = useState("");
  const [customTickers, setCustomTickers] = useState("");
  const [model, setModel] = useState(DEFAULT_MODEL);

  const [report, setReport] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [statusMessage, setStatusMessage] = useState("");
  const [elapsedSec, setElapsedSec] = useState(0);
  const statusIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const elapsedIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const genStartRef = useRef(0);

  const stopPolling = () => {
    if (statusIntervalRef.current) { clearInterval(statusIntervalRef.current); statusIntervalRef.current = null; }
    if (elapsedIntervalRef.current) { clearInterval(elapsedIntervalRef.current); elapsedIntervalRef.current = null; }
  };

  useEffect(() => () => stopPolling(), []);

  useEffect(() => {
    fetch(`${API}/industry-research/industries`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data: IndustryOption[]) => {
        setIndustries(data);
        if (data.length > 0) setSelectedIndustry(data[0].industry);
      })
      .catch(() => setIndustries([]));

    fetch(`${API}/industry-research/models`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data: ModelOption[] | null) => { if (data && data.length > 0) setModelOptions(data); })
      .catch(() => { /* keep default */ });
  }, []);

  const scopeParams = (extra: Record<string, string> = {}): URLSearchParams => {
    const params = new URLSearchParams({ model, ...extra });
    const custom = customTickers.trim();
    if (custom) {
      params.set("tickers", custom);
    } else if (selectedIndustry) {
      params.set("industry", selectedIndustry);
    }
    return params;
  };

  const scopeLabel = customTickers.trim()
    ? `Custom basket (${customTickers.trim()})`
    : selectedIndustry || "";

  const fetchStatus = async (): Promise<StatusResponse> => {
    const res = await fetch(`${API}/industry-research/status?${scopeParams()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };

  const fetchReport = async (retry = false): Promise<string> => {
    const params = scopeParams(retry ? { retry: "true" } : {});
    const res = await fetch(`${API}/industry-research/report?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };

  const finishGeneration = (text: string) => {
    stopPolling();
    setReport(text);
    setGenerating(false);
  };

  const handleGo = async () => {
    if (!customTickers.trim() && !selectedIndustry) return;
    stopPolling();
    setError(null);
    setReport(null);
    setGenerating(true);
    setPhase("idle");
    setStatusMessage("");
    setElapsedSec(0);

    try {
      const status = await fetchStatus();
      if (status.phase === "done") {
        finishGeneration(await fetchReport());
        return;
      }

      // Kick off (or re-kick-off) generation; retry=true clears any stale error/cancelled state
      // server-side so a fresh click always actually retries instead of replaying the old error.
      await fetchReport(true);

      genStartRef.current = Date.now();
      setPhase("gathering_data");
      setStatusMessage(PHASE_LABELS.gathering_data);
      elapsedIntervalRef.current = setInterval(() => {
        setElapsedSec(Math.floor((Date.now() - genStartRef.current) / 1000));
      }, 1000);

      statusIntervalRef.current = setInterval(async () => {
        try {
          const s = await fetchStatus();
          setPhase(s.phase);
          setStatusMessage(s.message || PHASE_LABELS[s.phase] || "");

          if (s.phase === "done") {
            finishGeneration(await fetchReport());
          } else if (s.phase === "error") {
            stopPolling();
            setError(s.error || s.message || "Report generation failed.");
            setGenerating(false);
          } else if (s.phase === "cancelled") {
            stopPolling();
            setGenerating(false);
          }
        } catch { /* ignore transient poll errors */ }
      }, STATUS_POLL_MS);
    } catch (e: unknown) {
      setError((e as Error).message);
      setGenerating(false);
    }
  };

  const handleCancel = async () => {
    stopPolling();
    setGenerating(false);
    setPhase("cancelled");
    setStatusMessage(PHASE_LABELS.cancelled);
    try {
      await fetch(`${API}/industry-research/cancel?${scopeParams()}`, { method: "POST" });
    } catch { /* best-effort — UI already reflects cancelled state */ }
  };

  const handleSaveReport = () => {
    if (!report) return;
    const blob = new Blob([report], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const slug = (customTickers.trim() || selectedIndustry || "industry").replace(/[^a-z0-9]+/gi, "_");
    a.download = `${slug}_industry_research_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Shared markdown renderer components — same visual system as EquityResearchViewer, plus
  // clickable ticker cells (any table cell whose sole content is a ticker-shaped string jumps
  // to that ticker's single-name AI Research tab).
  const mdComponents = {
    h1: ({ children }: any) => <h1 className="font-mono text-base text-zinc-100 font-semibold mb-4 mt-6">{children}</h1>,
    h2: ({ children }: any) => <h2 className="font-mono text-xs text-violet-300 font-semibold mb-2 mt-6 tracking-[0.2em] uppercase">{children}</h2>,
    h3: ({ children }: any) => <h3 className="font-mono text-xs text-zinc-300 font-semibold mb-2 mt-4">{children}</h3>,
    h4: ({ children }: any) => <h4 className="font-mono text-xs text-zinc-400 font-semibold mb-2 mt-4">{children}</h4>,
    p:  ({ children }: any) => <p className="font-mono text-xs text-zinc-400 mb-3 leading-relaxed">{children}</p>,
    ul: ({ children }: any) => <ul className="font-mono text-xs text-zinc-400 mb-3 space-y-1 pl-4">{children}</ul>,
    ol: ({ children }: any) => <ol className="font-mono text-xs text-zinc-400 mb-3 space-y-1 pl-4 list-decimal">{children}</ol>,
    li: ({ children }: any) => <li className="font-mono text-xs text-zinc-400 before:content-['–'] before:mr-2 before:text-zinc-600">{children}</li>,
    strong: ({ children }: any) => <strong className="text-zinc-200 font-semibold">{children}</strong>,
    em:     ({ children }: any) => <em className="text-zinc-500 not-italic">{children}</em>,
    table: ({ children }: any) => (
      <div className="overflow-x-auto mb-4">
        <table className="w-full text-xs font-mono border-collapse">{children}</table>
      </div>
    ),
    thead: ({ children }: any) => <thead>{children}</thead>,
    th: ({ children }: any) => <th className="text-left text-zinc-500 border-b border-white/[0.07] px-3 py-1.5 font-medium whitespace-nowrap">{children}</th>,
    td: ({ children }: any) => {
      const text = Array.isArray(children) ? children.join("") : String(children ?? "");
      if (isTickerLike(text)) {
        return (
          <td className="text-zinc-400 border-b border-white/[0.04] px-3 py-1">
            <button
              onClick={() => onSelectTicker(text.trim())}
              className="text-violet-400 hover:text-violet-300 hover:underline font-semibold"
            >
              {text.trim()}
            </button>
          </td>
        );
      }
      return <td className="text-zinc-400 border-b border-white/[0.04] px-3 py-1">{children}</td>;
    },
    hr: () => <hr className="border-white/[0.06] my-5" />,
    blockquote: ({ children }: any) => <blockquote className="border-l-2 border-violet-500/40 pl-3 my-3">{children}</blockquote>,
    code: ({ children }: any) => <code className="font-mono text-xs text-violet-300 bg-violet-950/30 px-1 py-0.5 rounded">{children}</code>,
    pre:  ({ children }: any) => <pre className="font-mono text-xs text-zinc-400 bg-zinc-900 rounded p-3 mb-3 overflow-x-auto">{children}</pre>,
  };

  return (
    <div>
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <select
          value={selectedIndustry}
          onChange={(e) => setSelectedIndustry(e.target.value)}
          disabled={generating || !!customTickers.trim()}
          className="font-mono text-xs h-8 px-2 rounded border border-white/[0.07] bg-transparent text-zinc-400 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:border-violet-500/50 max-w-[280px]"
        >
          {industries.map((opt) => (
            <option key={opt.industry} value={opt.industry} className="bg-zinc-900 text-zinc-300">
              {opt.industry} ({opt.member_count})
            </option>
          ))}
        </select>

        <input
          type="text"
          value={customTickers}
          onChange={(e) => setCustomTickers(e.target.value)}
          disabled={generating}
          placeholder="Custom tickers (comma-separated, overrides industry)"
          className="font-mono text-xs h-8 px-2 rounded border border-white/[0.07] bg-transparent text-zinc-300 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:border-violet-500/50 w-72 placeholder:text-zinc-700"
        />

        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          disabled={generating}
          className="font-mono text-xs h-8 px-2 rounded border border-white/[0.07] bg-transparent text-zinc-400 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:border-violet-500/50"
        >
          {modelOptions.map((opt) => (
            <option key={opt.value} value={opt.value} className="bg-zinc-900 text-zinc-300">
              {opt.label}
            </option>
          ))}
        </select>

        <button
          onClick={handleGo}
          disabled={generating || (!customTickers.trim() && !selectedIndustry)}
          className="font-mono text-xs tracking-widest uppercase h-8 px-4 rounded border border-white/[0.07] text-zinc-400 hover:text-zinc-200 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {generating ? "Generating..." : "Generate Industry Report"}
        </button>

        {report && (
          <button
            onClick={handleSaveReport}
            className="font-mono text-xs h-8 px-3 rounded border border-white/[0.07] text-zinc-500 hover:text-zinc-300 hover:border-white/[0.2] transition-colors"
          >
            Save .md
          </button>
        )}
      </div>

      {/* Live status bar — one line, Claude-Code style, shown only while generating */}
      {generating && (
        <div className="flex items-center gap-3 mb-4 font-mono text-xs">
          <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0 bg-violet-400 animate-pulse" />
          <span className="text-zinc-400">{statusMessage || PHASE_LABELS[phase]}</span>
          <span className="text-zinc-600">({elapsedSec}s)</span>
          <button
            onClick={handleCancel}
            className="ml-auto font-mono text-xs h-7 px-3 rounded border border-white/[0.07] text-zinc-500 hover:text-rose-400 hover:border-rose-900/50 transition-colors"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Report error */}
      {error && (
        <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20 text-rose-400 mb-4">
          <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0 bg-rose-500" />
          {error}
        </div>
      )}

      {/* Cancelled notice */}
      {!generating && phase === "cancelled" && !report && (
        <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-white/[0.07] bg-zinc-900/40 text-zinc-500 mb-4">
          Cancelled. Click &ldquo;Generate Industry Report&rdquo; to try again.
        </div>
      )}

      {/* Report */}
      {report && (
        <div className="max-w-4xl">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {report}
          </ReactMarkdown>
        </div>
      )}

      {!report && !generating && !error && phase !== "cancelled" && (
        <div className="flex flex-col items-center justify-center h-48 gap-2">
          <p className="font-mono text-xs text-zinc-600 tracking-widest uppercase">No report loaded</p>
          <p className="font-mono text-xs text-zinc-700">
            {scopeLabel
              ? `Click "Generate Industry Report" to analyze ${scopeLabel}`
              : "Pick an industry or enter a custom ticker basket to begin"}
          </p>
        </div>
      )}
    </div>
  );
}
