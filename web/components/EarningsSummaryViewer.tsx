"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API } from "@/lib/config";

const MODEL_OPTIONS = [
  { label: "Qwen3 235B",          value: "qwen/qwen3-235b-a22b-2507" },
  { label: "Gemini 3.5 Flash",    value: "google/gemini-3.5-flash" },
  { label: "GLM 5.2",              value: "z-ai/glm-5.2" },
  { label: "Qwen3.7 Max",         value: "qwen/qwen3.7-max" },
  { label: "MiniMax M3",          value: "minimax/minimax-m3" },
];

const DEFAULT_MODEL = MODEL_OPTIONS[0].value;

type ChatRole = "user" | "assistant";
interface ChatMessage { role: ChatRole; content: string }

const TOOL_LABELS: Record<string, string> = {
  screen_stocks:   "Screening stocks...",
  get_ticker_data: "Fetching ticker data...",
  get_sector_data: "Fetching sector data...",
};

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

  // Chat state
  const [chatReport, setChatReport] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, toolStatus]);

  useEffect(() => {
    setReport(null);
    setGenerating(false);
    setError(null);
    setImportInfo(null);
    setAudioFile("");
    setAudioQuarter("");
    setTranscribing(false);
    setAudioInfo(null);
    setChatReport(null);
    setMessages([]);
    setChatInput("");
    setChatLoading(false);
    setChatError(null);
    setToolStatus(null);
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
      setChatReport(text);
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
      setChatReport(json as string);
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
      setChatReport(json as string);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setTranscribing(false);
    }
  };

  const busy = generating || importing || transcribing;

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
      const res = await fetch(`${API}/earnings/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, quarter, model, messages: history, report: chatReport }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body!.getReader();
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
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
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

      {/* Chat section */}
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

            {toolStatus && (
              <div className="flex justify-start">
                <span className="font-mono text-xs text-violet-400 animate-pulse">{toolStatus}</span>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>
        )}

        {chatError && (
          <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20 text-rose-400 mb-3">
            <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0 bg-rose-500" />
            {chatError}
          </div>
        )}

        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={chatLoading}
            placeholder={
              report
                ? "Ask a follow-up about the earnings call..."
                : "Ask a question about the earnings call or any finance question..."
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
