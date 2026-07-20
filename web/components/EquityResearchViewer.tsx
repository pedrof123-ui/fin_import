"use client";

import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API } from "@/lib/config";

const STATUS_POLL_MS = 2500;
const DEFAULT_MODEL = "google/gemini-3.5-flash";

type Phase = "idle" | "gathering_data" | "running_specialists" | "synthesizing" | "done" | "error" | "cancelled";

const PHASE_LABELS: Record<Phase, string> = {
  idle: "Starting...",
  gathering_data: "Gathering financials, filings & market data...",
  running_specialists: "Running specialist analysts (competitive, earnings, technical, valuation)...",
  synthesizing: "Chief Analyst synthesizing the report...",
  done: "Report ready.",
  error: "Generation failed.",
  cancelled: "Cancelled.",
};
const MODEL_OPTIONS = [
  { label: "Claude Sonnet 4.6",           value: "anthropic/claude-sonnet-4-6" },
  { label: "Qwen3 235B",                  value: "qwen/qwen3-235b-a22b-2507" },
  { label: "Gemini 3.5 Flash (Default)",  value: "google/gemini-3.5-flash" },
  { label: "GLM 5.2",                     value: "z-ai/glm-5.2" },
  { label: "Qwen3.7 Max",                 value: "qwen/qwen3.7-max" },
  { label: "Grok 4.5",                    value: "x-ai/grok-4.5" },
];

type ChatRole = "user" | "assistant";
interface ChatMessage { role: ChatRole; content: string }

const TOOL_LABELS: Record<string, string> = {
  screen_stocks:    "Screening stocks...",
  get_ticker_data:  "Fetching ticker data...",
  get_sector_data:  "Fetching sector data...",
};

export default function EquityResearchViewer({ ticker }: { ticker: string }) {
  // Report state
  const [model, setModel]         = useState(DEFAULT_MODEL);
  const [report, setReport]       = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [phase, setPhase]         = useState<Phase>("idle");
  const [statusMessage, setStatusMessage] = useState("");
  const [elapsedSec, setElapsedSec] = useState(0);
  const statusIntervalRef  = useRef<ReturnType<typeof setInterval> | null>(null);
  const elapsedIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const genStartRef = useRef(0);

  // Chat state
  const [messages, setMessages]     = useState<ChatMessage[]>([]);
  const [chatReport, setChatReport] = useState<string | null>(null);
  const [chatInput, setChatInput]   = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError]   = useState<string | null>(null);
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const chatEndRef  = useRef<HTMLDivElement>(null);
  const inputRef    = useRef<HTMLTextAreaElement>(null);

  const stopPolling = () => {
    if (statusIntervalRef.current) { clearInterval(statusIntervalRef.current); statusIntervalRef.current = null; }
    if (elapsedIntervalRef.current) { clearInterval(elapsedIntervalRef.current); elapsedIntervalRef.current = null; }
  };

  useEffect(() => () => stopPolling(), []);

  useEffect(() => {
    setReport(null);
    setGenerating(false);
    setError(null);
    setPhase("idle");
    setStatusMessage("");
    setElapsedSec(0);
    setMessages([]);
    setChatReport(null);
    setChatError(null);
    stopPolling();
  }, [ticker]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, toolStatus]);

  // Report generation
  interface StatusResponse { phase: Phase; message: string; error: string | null }

  const fetchStatus = async (selectedModel: string): Promise<StatusResponse> => {
    const res = await fetch(`${API}/research/status?ticker=${ticker}&model=${encodeURIComponent(selectedModel)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };

  const fetchReport = async (selectedModel: string, retry = false): Promise<string> => {
    const qs = retry ? "&retry=true" : "";
    const res = await fetch(`${API}/research/report?ticker=${ticker}&model=${encodeURIComponent(selectedModel)}${qs}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };

  const finishGeneration = (text: string) => {
    stopPolling();
    setReport(text);
    setGenerating(false);
    setChatReport(text);
  };

  const handleGo = async () => {
    stopPolling();
    setError(null);
    setReport(null);
    setGenerating(true);
    setPhase("idle");
    setStatusMessage("");
    setElapsedSec(0);

    try {
      const status = await fetchStatus(model);
      if (status.phase === "done") {
        finishGeneration(await fetchReport(model));
        return;
      }

      // Kick off (or re-kick-off) generation; retry=true clears any stale error/cancelled state
      // server-side so a fresh click always actually retries instead of replaying the old error.
      await fetchReport(model, true);

      genStartRef.current = Date.now();
      setPhase("gathering_data");
      setStatusMessage(PHASE_LABELS.gathering_data);
      elapsedIntervalRef.current = setInterval(() => {
        setElapsedSec(Math.floor((Date.now() - genStartRef.current) / 1000));
      }, 1000);

      statusIntervalRef.current = setInterval(async () => {
        try {
          const s = await fetchStatus(model);
          setPhase(s.phase);
          setStatusMessage(s.message || PHASE_LABELS[s.phase] || "");

          if (s.phase === "done") {
            finishGeneration(await fetchReport(model));
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
      await fetch(`${API}/research/cancel?ticker=${ticker}&model=${encodeURIComponent(model)}`, { method: "POST" });
    } catch { /* best-effort — UI already reflects cancelled state */ }
  };

  // Save report as markdown file download
  const handleSaveReport = () => {
    if (!report) return;
    const blob = new Blob([report], { type: "text/markdown" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `${ticker}_research_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Chat send via SSE
  const handleSend = async () => {
    const content = chatInput.trim();
    if (!content || chatLoading) return;

    const userMsg: ChatMessage = { role: "user", content };
    const history = [...messages, userMsg];
    setMessages(history);
    setChatInput("");
    setChatLoading(true);
    setChatError(null);
    setToolStatus(null);

    try {
      const res = await fetch(`${API}/research/chat`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ ticker, model, messages: history, report: chatReport }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader  = res.body!.getReader();
      const decoder = new TextDecoder();
      let assistantContent = "";
      let buffer = "";

      setMessages(prev => [...prev, { role: "assistant", content: "" }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6);
          if (raw === "[DONE]") { setToolStatus(null); break; }
          try {
            const evt = JSON.parse(raw);
            if (evt.type === "text") {
              assistantContent += evt.content;
              setMessages(prev => [
                ...prev.slice(0, -1),
                { role: "assistant", content: assistantContent },
              ]);
            } else if (evt.type === "tool_start") {
              setToolStatus(TOOL_LABELS[evt.name] ?? `Running ${evt.name}...`);
            } else if (evt.type === "tool_done") {
              setToolStatus(null);
            } else if (evt.type === "error") {
              setChatError(evt.content);
            }
          } catch { /* malformed SSE chunk */ }
        }
      }
    } catch (e: unknown) {
      setChatError((e as Error).message);
      setMessages(prev => prev.filter(m => !(m.role === "assistant" && m.content === "")));
    } finally {
      setChatLoading(false);
      setToolStatus(null);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  // Shared markdown renderer components
  const mdComponents = {
    h1: ({ children }: any) => <h1 className="font-mono text-base text-zinc-100 font-semibold mb-4 mt-6">{children}</h1>,
    h2: ({ children }: any) => <h2 className="font-mono text-xs text-violet-300 font-semibold mb-2 mt-6 tracking-[0.2em] uppercase">{children}</h2>,
    h3: ({ children }: any) => <h3 className="font-mono text-xs text-zinc-300 font-semibold mb-2 mt-4">{children}</h3>,
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
    td: ({ children }: any) => <td className="text-zinc-400 border-b border-white/[0.04] px-3 py-1">{children}</td>,
    hr: () => <hr className="border-white/[0.06] my-5" />,
    blockquote: ({ children }: any) => <blockquote className="border-l-2 border-violet-500/40 pl-3 my-3">{children}</blockquote>,
    code: ({ children }: any) => <code className="font-mono text-xs text-violet-300 bg-violet-950/30 px-1 py-0.5 rounded">{children}</code>,
    pre:  ({ children }: any) => <pre className="font-mono text-xs text-zinc-400 bg-zinc-900 rounded p-3 mb-3 overflow-x-auto">{children}</pre>,
  };

  return (
    <div>
      {/* Toolbar */}
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
          {generating ? "Creating..." : "Create Equity Report"}
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
          Cancelled. Click &ldquo;Create Equity Report&rdquo; to try again.
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
          <p className="font-mono text-xs text-zinc-700">Click Go to generate the AI equity research report</p>
        </div>
      )}

      {/* Chat section — always visible once ticker is loaded */}
      <div className="mt-8 max-w-4xl">
        <div className="flex items-center justify-between mb-3 border-t border-white/[0.06] pt-6">
          <span className="font-mono text-xs text-zinc-500 tracking-widest uppercase">AI Assistant</span>
          <button
            onClick={() => { setMessages([]); setChatReport(null); setChatError(null); }}
            disabled={messages.length === 0 && chatReport === null}
            className="font-mono text-xs text-zinc-600 hover:text-zinc-400 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Clear chat
          </button>
        </div>

        {/* Message history */}
        {messages.length > 0 && (
          <div className="mb-4 space-y-4">
            {messages.map((msg, i) => (
              <div key={i} className={msg.role === "user" ? "flex justify-end" : "flex justify-start"}>
                <div
                  className={
                    msg.role === "user"
                      ? "max-w-[80%] font-mono text-xs text-zinc-300 bg-zinc-800/60 border border-white/[0.07] rounded px-3 py-2 whitespace-pre-wrap"
                      : "max-w-[95%] font-mono text-xs text-zinc-400"
                  }
                >
                  {msg.role === "assistant" ? (
                    msg.content ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                        {msg.content}
                      </ReactMarkdown>
                    ) : (
                      <span className="text-zinc-600 animate-pulse">Thinking...</span>
                    )
                  ) : (
                    msg.content
                  )}
                </div>
              </div>
            ))}

            {/* Tool status indicator */}
            {toolStatus && (
              <div className="flex justify-start">
                <span className="font-mono text-xs text-violet-400 animate-pulse">{toolStatus}</span>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>
        )}

        {/* Chat error */}
        {chatError && (
          <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20 text-rose-400 mb-3">
            <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0 bg-rose-500" />
            {chatError}
          </div>
        )}

        {/* Input */}
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={chatLoading}
            placeholder={
              report
                ? "Ask a follow-up question or any finance question..."
                : "Ask any finance or market question..."
            }
            rows={2}
            className="flex-1 font-mono text-xs text-zinc-300 bg-transparent border border-white/[0.07] rounded px-3 py-2 resize-none focus:outline-none focus:border-violet-500/50 placeholder:text-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed"
          />
          <button
            onClick={handleSend}
            disabled={chatLoading || !chatInput.trim()}
            className="font-mono text-xs tracking-widest uppercase h-8 px-4 rounded border border-white/[0.07] text-zinc-400 hover:text-zinc-200 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          >
            {chatLoading ? "..." : "Send"}
          </button>
        </div>
        <p className="font-mono text-xs text-zinc-700 mt-1.5">Enter to send · Shift+Enter for new line</p>
      </div>
    </div>
  );
}
