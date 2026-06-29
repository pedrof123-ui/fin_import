"use client";

import { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from "recharts";
import { API } from "@/lib/config";

interface EstimatePeriod {
  fiscal_date: string;
  horizon: string;
  fetched_at: string;
  eps_avg: number | null;
  eps_high: number | null;
  eps_low: number | null;
  eps_count: number | null;
  eps_avg_7d: number | null;
  eps_avg_30d: number | null;
  eps_chg_7d: number | null;
  eps_chg_30d: number | null;
  eps_chg_pct_7d: number | null;
  eps_chg_pct_30d: number | null;
  eps_rev_up_7d: number | null;
  eps_rev_down_7d: number | null;
  eps_rev_up_30d: number | null;
  eps_rev_down_30d: number | null;
  rev_avg: number | null;
  rev_high: number | null;
  rev_low: number | null;
  rev_count: number | null;
  rev_chg_7d: number | null;
  rev_chg_pct_7d: number | null;
  rev_chg_30d: number | null;
  rev_chg_pct_30d: number | null;
}

interface HistoryRow {
  fetched_at: string;
  fiscal_date: string;
  horizon: string;
  eps_avg: number | null;
  rev_avg: number | null;
}

interface EstimatesData {
  ticker: string;
  periods: EstimatePeriod[];
  history: HistoryRow[];
}

const CHART_BG = { background: "oklch(0.09 0.006 265)" };
const GRID_STROKE = "rgba(255,255,255,0.05)";
const TICK_STYLE = { fill: "#71717a", fontSize: 10, fontFamily: "monospace" };
const AXIS_LINE = { stroke: "rgba(255,255,255,0.07)" };
const TIP_STYLE = {
  contentStyle: {
    background: "#18181b",
    border: "1px solid rgba(255,255,255,0.1)",
    fontFamily: "monospace",
    fontSize: 11,
    borderRadius: 4,
  },
  labelStyle: { color: "#a1a1aa", marginBottom: 4 },
  itemStyle: { color: "#d4d4d8" },
};

const LINE_COLORS = [
  "#818cf8", "#34d399", "#f59e0b", "#f472b6",
  "#38bdf8", "#fb923c", "#a78bfa", "#6ee7b7",
];

function horizonAbbr(horizon: string): string {
  return horizon.includes("quarter") ? "Q" : "FY";
}

function formatFiscalDate(d: string): string {
  const dt = new Date(d + "T00:00:00Z");
  const mon = dt.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const yr = String(dt.getUTCFullYear()).slice(2);
  return `${mon}'${yr}`;
}

function periodKey(h: HistoryRow): string {
  return `${horizonAbbr(h.horizon)} ${formatFiscalDate(h.fiscal_date)}`;
}

function fmtEps(v: number | null): string {
  if (v == null) return "—";
  return `$${v.toFixed(2)}`;
}

function fmtRev(v: number | null): string {
  if (v == null) return "—";
  return `$${(v / 1e9).toFixed(1)}B`;
}

function fmtChgPct(v: number | null): React.ReactNode {
  if (v == null) return <span className="text-zinc-600">—</span>;
  const cls = v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-zinc-400";
  return <span className={cls}>{v > 0 ? "+" : ""}{v.toFixed(1)}%</span>;
}

function toWeekStart(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00Z");
  const day = d.getUTCDay(); // 0=Sun
  d.setUTCDate(d.getUTCDate() - (day === 0 ? 6 : day - 1)); // back to Monday
  return d.toISOString().slice(0, 10);
}

function buildTrendData(
  history: HistoryRow[],
  field: "eps_avg" | "rev_avg",
): { data: Record<string, unknown>[]; keys: string[] } {
  // Collapse to weekly buckets — for each (week, period) keep the latest value
  const weekMap = new Map<string, HistoryRow>();
  for (const h of history) {
    const week = toWeekStart(h.fetched_at);
    const k = `${week}|${h.fiscal_date}|${h.horizon}`;
    const existing = weekMap.get(k);
    if (!existing || h.fetched_at > existing.fetched_at) {
      weekMap.set(k, { ...h, fetched_at: week });
    }
  }
  const weekly = Array.from(weekMap.values());

  const allDates = [...new Set(weekly.map((h) => h.fetched_at))].sort();
  const allKeys = [...new Set(history.map(periodKey))];

  // Sort by fiscal_date descending (furthest out first = highest EPS first in legend)
  const fiscalDateByKey = new Map<string, string>();
  for (const h of history) {
    fiscalDateByKey.set(periodKey(h), h.fiscal_date);
  }
  allKeys.sort((a, b) => (fiscalDateByKey.get(b) ?? "").localeCompare(fiscalDateByKey.get(a) ?? ""));

  const data = allDates.map((date) => {
    const entry: Record<string, unknown> = { date };
    weekly
      .filter((h) => h.fetched_at === date)
      .forEach((h) => {
        const v = h[field];
        if (v != null) {
          entry[periodKey(h)] = field === "rev_avg" ? v / 1e9 : v;
        }
      });
    return entry;
  });

  return { data, keys: allKeys };
}

// Custom tooltip that sorts items by value descending to match the chart's visual order
function TrendTooltip({
  active,
  payload,
  label,
  valueFormatter,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number | null; color: string }>;
  label?: string;
  valueFormatter: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  const dt = new Date((label ?? "") + "T00:00:00Z");
  const dateStr = dt.toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
  });
  const sorted = [...payload]
    .filter((p) => p.value != null)
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
  return (
    <div style={{ background: "#18181b", border: "1px solid rgba(255,255,255,0.1)", fontFamily: "monospace", fontSize: 11, borderRadius: 4, padding: "6px 10px" }}>
      <p style={{ color: "#a1a1aa", marginBottom: 4 }}>{dateStr}</p>
      {sorted.map((entry) => (
        <p key={entry.name} style={{ color: entry.color, margin: "2px 0" }}>
          {entry.name}: {valueFormatter(entry.value as number)}
        </p>
      ))}
    </div>
  );
}

export default function EstimatesViewer({ ticker }: { ticker: string }) {
  const [data, setData] = useState<EstimatesData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker) return;
    setData(null);
    setError(null);
    setLoading(true);
    fetch(`${API}/estimates/${ticker}`)
      .then((r) => {
        if (!r.ok) return r.json().then((j) => Promise.reject(j.detail ?? `HTTP ${r.status}`));
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [ticker]);

  if (loading) {
    return (
      <p className="font-mono text-xs text-zinc-500 py-8 text-center">
        Loading estimates…
      </p>
    );
  }

  if (error) {
    return (
      <p className="font-mono text-xs text-rose-400 py-8 text-center">{error}</p>
    );
  }

  if (!data) return null;

  if (data.periods.length === 0 && data.history.length === 0) {
    return (
      <p className="font-mono text-xs text-zinc-600 py-8 text-center">
        No estimates data — run{" "}
        <code className="text-zinc-400">uv run scripts/estimates_update.py</code>
      </p>
    );
  }

  const { data: epsTrend, keys: epsKeys } = buildTrendData(data.history, "eps_avg");
  const { data: revTrend, keys: revKeys } = buildTrendData(data.history, "rev_avg");

  const momentumData = data.periods.map((p) => ({
    label: `${horizonAbbr(p.horizon)} ${formatFiscalDate(p.fiscal_date)}`,
    up: p.eps_rev_up_30d ?? 0,
    down: -(p.eps_rev_down_30d ?? 0),
  }));

  const hasHistory = epsTrend.length >= 1;
  const singlePoint = epsTrend.length === 1;
  const firstTracked = singlePoint ? (epsTrend[0].date as string) : null;

  return (
    <div className="space-y-5">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500">
        Analyst Estimates — {ticker}
      </p>

      {/* EPS Trend */}
      {firstTracked && (
        <p className="font-mono text-[10px] text-zinc-600 py-1">
          First tracked{" "}
          {new Date(firstTracked + "T00:00:00Z").toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })}.
          Trend builds with weekly updates.
        </p>
      )}
      {hasHistory && (
        <div>
          <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1">
            EPS Consensus Over Time
          </p>
          <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2" style={CHART_BG}>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={epsTrend} margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                <XAxis
                  dataKey="date"
                  tick={TICK_STYLE}
                  tickLine={false}
                  axisLine={AXIS_LINE}
                  tickFormatter={(d: string) => {
                    const dt = new Date(d + "T00:00:00Z");
                    return dt.toLocaleString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
                  }}
                />
                <YAxis
                  tickFormatter={(v) => `$${v.toFixed(2)}`}
                  tick={TICK_STYLE}
                  tickLine={false}
                  axisLine={false}
                  width={52}
                />
                <Tooltip
                  content={<TrendTooltip valueFormatter={(v) => `$${v.toFixed(2)}`} />}
                />
                <Legend wrapperStyle={{ fontFamily: "monospace", fontSize: 10, color: "#71717a", paddingTop: 8 }} />
                {epsKeys.map((key, i) => (
                  <Line
                    key={key}
                    type="monotone"
                    dataKey={key}
                    stroke={LINE_COLORS[i % LINE_COLORS.length]}
                    strokeWidth={1.5}
                    dot={singlePoint ? { r: 4, fill: LINE_COLORS[i % LINE_COLORS.length] } : false}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Revenue Trend */}
      {hasHistory && (
        <div>
          <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1">
            Revenue Consensus Over Time ($B)
          </p>
          <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2" style={CHART_BG}>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={revTrend} margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                <XAxis
                  dataKey="date"
                  tick={TICK_STYLE}
                  tickLine={false}
                  axisLine={AXIS_LINE}
                  tickFormatter={(d: string) => {
                    const dt = new Date(d + "T00:00:00Z");
                    return dt.toLocaleString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
                  }}
                />
                <YAxis
                  tickFormatter={(v) => `$${v.toFixed(0)}B`}
                  tick={TICK_STYLE}
                  tickLine={false}
                  axisLine={false}
                  width={52}
                />
                <Tooltip
                  content={<TrendTooltip valueFormatter={(v) => `$${v.toFixed(1)}B`} />}
                />
                <Legend wrapperStyle={{ fontFamily: "monospace", fontSize: 10, color: "#71717a", paddingTop: 8 }} />
                {revKeys.map((key, i) => (
                  <Line
                    key={key}
                    type="monotone"
                    dataKey={key}
                    stroke={LINE_COLORS[i % LINE_COLORS.length]}
                    strokeWidth={1.5}
                    dot={singlePoint ? { r: 4, fill: LINE_COLORS[i % LINE_COLORS.length] } : false}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Revision Momentum */}
      {momentumData.some((d) => d.up !== 0 || d.down !== 0) && (
        <div>
          <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1">
            EPS Revision Momentum (30d) — Upgrades vs Downgrades
          </p>
          <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2" style={CHART_BG}>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={momentumData} margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                <XAxis dataKey="label" tick={TICK_STYLE} tickLine={false} axisLine={AXIS_LINE} />
                <YAxis tick={TICK_STYLE} tickLine={false} axisLine={false} width={28} />
                <Tooltip
                  {...TIP_STYLE}
                  cursor={{ fill: "rgba(255,255,255,0.04)" }}
                  formatter={(v: unknown, name: unknown) => [
                    Math.abs(v as number),
                    name === "up" ? "Upgrades" : "Downgrades",
                  ]}
                />
                <Bar dataKey="up" name="up" isAnimationActive={false}>
                  {momentumData.map((_, i) => (
                    <Cell key={i} fill="#34d399" />
                  ))}
                </Bar>
                <Bar dataKey="down" name="down" isAnimationActive={false}>
                  {momentumData.map((_, i) => (
                    <Cell key={i} fill="#f87171" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Summary Table */}
      <div>
        <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-2">
          Current Estimates
        </p>
        <div className="overflow-x-auto rounded border border-white/[0.07]">
          <table className="w-full font-mono text-[11px]">
            <thead>
              <tr className="border-b border-white/[0.07] text-zinc-500 text-[10px]">
                <th className="text-left px-3 py-2">Period</th>
                <th className="text-left px-3 py-2">Type</th>
                <th className="text-right px-3 py-2">EPS Est</th>
                <th className="text-right px-3 py-2">vs 7d</th>
                <th className="text-right px-3 py-2">vs 30d</th>
                <th className="text-right px-3 py-2">Analysts</th>
                <th className="text-right px-3 py-2">Rev Est</th>
                <th className="text-right px-3 py-2">Rev vs 30d</th>
                <th className="text-right px-3 py-2">Rev Analysts</th>
              </tr>
            </thead>
            <tbody>
              {data.periods.map((p, i) => (
                <tr
                  key={i}
                  className="border-b border-white/[0.04] hover:bg-white/[0.02] text-zinc-300"
                >
                  <td className="px-3 py-2 text-zinc-400">{formatFiscalDate(p.fiscal_date)}</td>
                  <td className="px-3 py-2 text-zinc-500">{horizonAbbr(p.horizon)}</td>
                  <td className="px-3 py-2 text-right">{fmtEps(p.eps_avg)}</td>
                  <td className="px-3 py-2 text-right">{fmtChgPct(p.eps_chg_pct_7d)}</td>
                  <td className="px-3 py-2 text-right">{fmtChgPct(p.eps_chg_pct_30d)}</td>
                  <td className="px-3 py-2 text-right text-zinc-400">{p.eps_count ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{fmtRev(p.rev_avg)}</td>
                  <td className="px-3 py-2 text-right">{fmtChgPct(p.rev_chg_pct_30d)}</td>
                  <td className="px-3 py-2 text-right text-zinc-400">{p.rev_count ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.periods[0]?.fetched_at && (
          <p className="font-mono text-[9px] text-zinc-600 mt-1">
            Last updated: {data.periods[0].fetched_at}
          </p>
        )}
      </div>
    </div>
  );
}
