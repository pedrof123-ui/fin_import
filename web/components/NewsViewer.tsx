"use client";

import { useEffect, useState } from "react";
import { API } from "@/lib/config";

interface Article {
  title: string;
  summary: string;
  publisher: string;
  link: string;
  pub_date: string | null;
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export default function NewsViewer({ ticker }: { ticker: string }) {
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);

  const load = async (t: string, d: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/news/${t}?days=${d}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: Article[] = await res.json();
      setArticles(data);
    } catch (e: unknown) {
      setError((e as Error).message);
      setArticles([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setArticles([]);
    setError(null);
    load(ticker, days);
  }, [ticker]);

  const handleRefresh = () => load(ticker, days);

  const handleDaysChange = (d: number) => {
    setDays(d);
    load(ticker, d);
  };

  return (
    <div>
      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-4">
        <span className="font-mono text-xs text-zinc-500">Period</span>
        {[7, 14, 30, 60, 90].map((d) => (
          <button
            key={d}
            onClick={() => handleDaysChange(d)}
            disabled={loading}
            className={`font-mono text-xs h-7 px-3 rounded border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
              days === d
                ? "border-violet-500/50 bg-violet-950/30 text-violet-300"
                : "border-white/[0.07] text-zinc-500 hover:text-zinc-300 hover:border-white/[0.12]"
            }`}
          >
            {d}d
          </button>
        ))}
        <button
          onClick={handleRefresh}
          disabled={loading}
          className="font-mono text-xs h-7 px-3 rounded border border-white/[0.07] text-zinc-500 hover:text-zinc-300 hover:border-white/[0.12] transition-colors disabled:opacity-40 disabled:cursor-not-allowed ml-1"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
        {!loading && articles.length > 0 && (
          <span className="font-mono text-xs text-zinc-600">{articles.length} articles</span>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20 text-rose-400 mb-4">
          <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0 bg-rose-500" />
          {error}
        </div>
      )}

      {loading && articles.length === 0 && (
        <div className="flex items-center justify-center h-48">
          <span className="font-mono text-xs text-zinc-600">Loading news…</span>
        </div>
      )}

      {!loading && !error && articles.length === 0 && (
        <div className="flex flex-col items-center justify-center h-48 gap-2">
          <p className="font-mono text-xs text-zinc-600 tracking-widest uppercase">No news found</p>
          <p className="font-mono text-xs text-zinc-700">No articles for {ticker} in the last {days} days</p>
        </div>
      )}

      <div className="space-y-3">
        {articles.map((art, i) => (
          <div
            key={i}
            className="rounded border border-white/[0.06] bg-white/[0.02] px-4 py-3 hover:border-white/[0.1] transition-colors"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                {art.link ? (
                  <a
                    href={art.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono text-xs text-zinc-200 hover:text-violet-300 transition-colors leading-snug block mb-1"
                  >
                    {art.title}
                  </a>
                ) : (
                  <p className="font-mono text-xs text-zinc-200 leading-snug mb-1">{art.title}</p>
                )}
                {art.summary && (
                  <p className="font-mono text-xs text-zinc-500 leading-relaxed line-clamp-2">{art.summary}</p>
                )}
              </div>
              <div className="text-right shrink-0">
                {art.pub_date && (
                  <p className="font-mono text-xs text-zinc-600">{formatDate(art.pub_date)}</p>
                )}
                {art.publisher && (
                  <p className="font-mono text-xs text-zinc-700 mt-0.5">{art.publisher}</p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
