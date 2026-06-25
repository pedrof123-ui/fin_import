"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API } from "@/lib/config";

const MODEL_OPTIONS = [
  { label: "Qwen3 235B",          value: "qwen/qwen3-235b-a22b-2507" },
  { label: "Gemini 3.5 Flash",    value: "google/gemini-3.5-flash" },
  { label: "Gemini 3.1 Pro",      value: "google/gemini-3.1-pro-preview" },
  { label: "Qwen3.7 Max",         value: "qwen/qwen3.7-max" },
  { label: "MiniMax M3",          value: "minimax/minimax-m3" },
];

const DEFAULT_MODEL = MODEL_OPTIONS[0].value;

export default function EarningsSummaryViewer({ ticker }: { ticker: string }) {
  const [quarter, setQuarter] = useState("latest");
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [report, setReport] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [urlInput, setUrlInput] = useState("");
  const [urlQuarter, setUrlQuarter] = useState("");
  const [importing, setImporting] = useState(false);
  const [importInfo, setImportInfo] = useState<string | null>(null);

  const [audioFile, setAudioFile] = useState("");
  const [audioQuarter, setAudioQuarter] = useState("");
  const [transcribing, setTranscribing] = useState(false);
  const [audioInfo, setAudioInfo] = useState<string | null>(null);

  useEffect(() => {
    setReport(null);
    setGenerating(false);
    setError(null);
    setImportInfo(null);
    setAudioFile("");
    setAudioQuarter("");
    setTranscribing(false);
    setAudioInfo(null);
  }, [ticker]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    setReport(null);
    setImportInfo(null);

    try {
      const params = new URLSearchParams({ ticker, quarter, model });
      const res = await fetch(`${API}/earnings/report?${params}`);
      if (!res.ok) {
        const json = await res.json().catch(() => ({}));
        throw new Error((json as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }
      const text: string = await res.json();
      setReport(text);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const handleImportUrl = async () => {
    if (!urlInput.trim() || !urlQuarter.trim()) return;
    setImporting(true);
    setError(null);
    setImportInfo(null);
    setReport(null);

    try {
      const params = new URLSearchParams({ ticker, quarter: urlQuarter.trim(), url: urlInput.trim(), model });
      const res = await fetch(`${API}/earnings/import-url?${params}`, { method: "POST" });
      const json = await res.json().catch(() => ({}));
      if (res.status === 409) {
        setImportInfo((json as { detail?: string }).detail ?? "Transcript already exists from Alpha Vantage.");
        return;
      }
      if (!res.ok) {
        throw new Error((json as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }
      setReport(json as string);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setImporting(false);
    }
  };

  const handleImportAudio = async () => {
    if (!audioFile.trim() || !audioQuarter.trim()) return;
    setTranscribing(true);
    setError(null);
    setAudioInfo(null);
    setReport(null);

    try {
      const params = new URLSearchParams({ ticker, quarter: audioQuarter.trim(), filename: audioFile.trim(), model });
      const res = await fetch(`${API}/earnings/import-audio?${params}`, { method: "POST" });
      const json = await res.json().catch(() => ({}));
      if (res.status === 409) {
        setAudioInfo((json as { detail?: string }).detail ?? "Transcript already exists from Alpha Vantage.");
        return;
      }
      if (!res.ok) {
        throw new Error((json as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }
      setReport(json as string);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setTranscribing(false);
    }
  };

  const busy = generating || importing || transcribing;

  return (
    <div>
      {/* AV fetch row */}
      <div className="flex items-center gap-3 mb-3">
        <input
          type="text"
          value={quarter}
          onChange={(e) => setQuarter(e.target.value)}
          placeholder="e.g. 2025Q1 or 'latest'"
          disabled={busy}
          className="font-mono text-xs h-8 px-2 rounded border border-white/[0.07] bg-transparent text-zinc-300 placeholder:text-zinc-600 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:border-violet-500/50 w-44"
        />
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          disabled={busy}
          className="font-mono text-xs h-8 px-2 rounded border border-white/[0.07] bg-transparent text-zinc-400 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:border-violet-500/50"
        >
          {MODEL_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value} className="bg-zinc-900 text-zinc-300">
              {opt.label}
            </option>
          ))}
        </select>
        <button
          onClick={handleGenerate}
          disabled={busy}
          className="font-mono text-xs tracking-widest uppercase h-8 px-4 rounded border border-white/[0.07] text-zinc-400 hover:text-zinc-200 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {generating ? "Generating..." : "Go ▶"}
        </button>
        {generating && (
          <span className="font-mono text-xs text-zinc-500">
            Processing — may take over 1 minute depending on model
          </span>
        )}
      </div>

      {/* URL import row */}
      <div className="flex items-center gap-3 mb-6">
        <span className="font-mono text-xs text-zinc-600 shrink-0">Import URL</span>
        <input
          type="text"
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          placeholder="https://... (PDF or HTML transcript)"
          disabled={busy}
          className="font-mono text-xs h-8 px-2 rounded border border-white/[0.07] bg-transparent text-zinc-300 placeholder:text-zinc-600 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:border-violet-500/50 flex-1"
        />
        <input
          type="text"
          value={urlQuarter}
          onChange={(e) => setUrlQuarter(e.target.value)}
          placeholder="2025Q3"
          disabled={busy}
          className="font-mono text-xs h-8 px-2 rounded border border-white/[0.07] bg-transparent text-zinc-300 placeholder:text-zinc-600 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:border-violet-500/50 w-24"
        />
        <button
          onClick={handleImportUrl}
          disabled={busy || !urlInput.trim() || !urlQuarter.trim()}
          className="font-mono text-xs tracking-widest uppercase h-8 px-4 rounded border border-white/[0.07] text-zinc-400 hover:text-zinc-200 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {importing ? "Importing..." : "Import"}
        </button>
        {importing && (
          <span className="font-mono text-xs text-zinc-500">
            Fetching transcript — may take over 1 minute
          </span>
        )}
      </div>

      {/* Audio import row */}
      <div className="flex items-center gap-3 mb-6">
        <span className="font-mono text-xs text-zinc-600 shrink-0">Import Audio</span>
        <input
          type="text"
          value={audioFile}
          onChange={(e) => setAudioFile(e.target.value)}
          placeholder="filename.mp4"
          disabled={busy}
          className="font-mono text-xs h-8 px-2 rounded border border-white/[0.07] bg-transparent text-zinc-300 placeholder:text-zinc-600 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:border-violet-500/50 flex-1"
        />
        <input
          type="text"
          value={audioQuarter}
          onChange={(e) => setAudioQuarter(e.target.value)}
          placeholder="2025Q3"
          disabled={busy}
          className="font-mono text-xs h-8 px-2 rounded border border-white/[0.07] bg-transparent text-zinc-300 placeholder:text-zinc-600 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:border-violet-500/50 w-24"
        />
        <button
          onClick={handleImportAudio}
          disabled={busy || !audioFile.trim() || !audioQuarter.trim()}
          className="font-mono text-xs tracking-widest uppercase h-8 px-4 rounded border border-white/[0.07] text-zinc-400 hover:text-zinc-200 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {transcribing ? "Transcribing..." : "Transcribe"}
        </button>
        {transcribing && (
          <span className="font-mono text-xs text-zinc-500">
            Transcribing — may take several minutes
          </span>
        )}
      </div>

      {audioInfo && (
        <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-sky-900/50 bg-sky-950/20 text-sky-400 mb-4">
          <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0 bg-sky-500" />
          {audioInfo}
        </div>
      )}

      {importInfo && (
        <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-sky-900/50 bg-sky-950/20 text-sky-400 mb-4">
          <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0 bg-sky-500" />
          {importInfo}
        </div>
      )}

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
              thead: ({ children }) => <thead>{children}</thead>,
              th: ({ children }) => (
                <th className="text-left text-zinc-500 border-b border-white/[0.07] px-3 py-1.5 font-medium whitespace-nowrap">{children}</th>
              ),
              td: ({ children }) => (
                <td className="text-zinc-400 border-b border-white/[0.04] px-3 py-1">{children}</td>
              ),
              hr: () => <hr className="border-white/[0.06] my-5" />,
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

      {!report && !busy && !error && !importInfo && (
        <div className="flex flex-col items-center justify-center h-48 gap-2">
          <p className="font-mono text-xs text-zinc-600 tracking-widest uppercase">No report loaded</p>
          <p className="font-mono text-xs text-zinc-700">
            Enter a quarter (or keep &apos;latest&apos;) and click Go to generate an earnings summary
          </p>
        </div>
      )}
    </div>
  );
}
