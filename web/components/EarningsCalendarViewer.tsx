"use client";

import { useEffect, useState, useCallback } from "react";
import { API } from "@/lib/config";

interface CalendarEntry {
  symbol: string;
  name: string | null;
  sector: string | null;
  report_date: string;
  fiscal_date_ending: string | null;
  estimate: number | null;
  currency: string | null;
  time_of_day: "pre-market" | "post-market" | null;
  status: "upcoming" | "reported";
}

function formatDate(d: string): string {
  const dt = new Date(d + "T00:00:00Z");
  return dt.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function formatFiscalPeriod(d: string | null): string {
  if (!d) return "—";
  const dt = new Date(d + "T00:00:00Z");
  const mon = dt.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const yr = String(dt.getUTCFullYear()).slice(2);
  return `${mon}'${yr}`;
}

function weekLabel(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00Z");
  const day = d.getUTCDay();
  const mon = d.getUTCDate() - (day === 0 ? 6 : day - 1);
  const weekStart = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), mon));
  const weekEnd = new Date(weekStart);
  weekEnd.setUTCDate(weekEnd.getUTCDate() + 4);
  const fmt = (dt: Date) =>
    dt.toLocaleString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  return `Week of ${fmt(weekStart)} – ${fmt(weekEnd)}`;
}

function groupByWeek(entries: CalendarEntry[]): [string, CalendarEntry[]][] {
  const map = new Map<string, CalendarEntry[]>();
  for (const e of entries) {
    const label = weekLabel(e.report_date);
    if (!map.has(label)) map.set(label, []);
    map.get(label)!.push(e);
  }
  return Array.from(map.entries());
}

export default function EarningsCalendarViewer({
  onSelectTicker,
}: {
  onSelectTicker?: (ticker: string) => void;
}) {
  const [data, setData] = useState<CalendarEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetch(`${API}/earnings-calendar`)
      .then((r) => {
        if (!r.ok) return r.json().then((j) => Promise.reject(j.detail ?? `HTTP ${r.status}`));
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <p className="font-mono text-xs text-zinc-500 py-8 text-center">
        Loading earnings calendar…
      </p>
    );
  }

  if (error) {
    return (
      <p className="font-mono text-xs text-rose-400 py-8 text-center">{error}</p>
    );
  }

  if (!data) return null;

  if (data.length === 0) {
    return (
      <div className="py-8 text-center space-y-2">
        <p className="font-mono text-xs text-zinc-600">No earnings calendar data.</p>
        <p className="font-mono text-xs text-zinc-700">
          Run{" "}
          <code className="text-zinc-500">
            uv run scripts/earnings_calendar_update.py
          </code>{" "}
          to populate.
        </p>
      </div>
    );
  }

  const upcoming = data.filter((e) => e.status === "upcoming");
  const groups = groupByWeek(data);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500">
          Earnings Calendar — next 3 months
          {upcoming.length > 0 && (
            <span className="ml-2 text-violet-400">
              {upcoming.length} upcoming
            </span>
          )}
        </p>
        <button
          onClick={load}
          className="font-mono text-[10px] uppercase tracking-widest px-2 py-1 rounded border border-white/[0.07] text-zinc-500 hover:text-zinc-300 hover:border-white/[0.15] transition-colors"
        >
          Refresh
        </button>
      </div>

      {groups.map(([weekLabel, entries]) => {
        const allReported = entries.every((e) => e.status === "reported");
        return (
          <div key={weekLabel}>
            <p
              className={`font-mono text-[9px] uppercase tracking-[0.2em] mb-1 ${
                allReported ? "text-zinc-700" : "text-zinc-500"
              }`}
            >
              {weekLabel}
            </p>
            <div className="overflow-x-auto rounded border border-white/[0.07]">
              <table className="w-full font-mono text-[11px]">
                <thead>
                  <tr className="border-b border-white/[0.07] text-zinc-500 text-[10px]">
                    <th className="text-left px-3 py-2">Ticker</th>
                    <th className="text-left px-3 py-2">Company</th>
                    <th className="text-left px-3 py-2">Sector</th>
                    <th className="text-left px-3 py-2">Report Date</th>
                    <th className="text-left px-3 py-2">Time</th>
                    <th className="text-left px-3 py-2">Fiscal Period End</th>
                    <th className="text-right px-3 py-2">EPS Est</th>
                    <th className="text-left px-3 py-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((e, i) => (
                    <tr
                      key={i}
                      className={`border-b border-white/[0.04] transition-colors ${
                        e.status === "reported"
                          ? "opacity-40"
                          : "hover:bg-white/[0.02]"
                      }`}
                    >
                      <td className="px-3 py-2">
                        {onSelectTicker ? (
                          <button
                            onClick={() => onSelectTicker(e.symbol)}
                            className="text-violet-400 hover:text-violet-300 transition-colors"
                          >
                            {e.symbol}
                          </button>
                        ) : (
                          <span className="text-violet-400">{e.symbol}</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-zinc-400 max-w-[200px] truncate">
                        {e.name ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-zinc-500">
                        {e.sector ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-zinc-300">
                        {formatDate(e.report_date)}
                      </td>
                      <td className="px-3 py-2">
                        {e.time_of_day === "pre-market" ? (
                          <span className="text-amber-400">pre</span>
                        ) : e.time_of_day === "post-market" ? (
                          <span className="text-sky-400">post</span>
                        ) : (
                          <span className="text-zinc-600">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-zinc-400">
                        {formatFiscalPeriod(e.fiscal_date_ending)}
                      </td>
                      <td className="px-3 py-2 text-right text-zinc-300">
                        {e.estimate != null
                          ? `$${e.estimate.toFixed(2)}`
                          : "—"}
                      </td>
                      <td className="px-3 py-2">
                        {e.status === "upcoming" ? (
                          <span className="text-emerald-500">upcoming</span>
                        ) : (
                          <span className="text-zinc-600">reported</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
