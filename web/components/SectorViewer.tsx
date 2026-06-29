"use client";

import { useEffect, useState, useCallback, Fragment } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { API } from "@/lib/config";

// ── Types ─────────────────────────────────────────────────────────────────────

type GroupType = "sector" | "industry";

interface SectorRow {
  group_type: string;
  group_name: string;
  month_end_date: string;
  ticker_count: number;
  composite_score: number | null;
  pe_median: number | null;
  pe_p25: number | null;
  pe_p75: number | null;
  pfcf_median: number | null;
  evebitda_median: number | null;
  evebitda_hist_median: number | null;
  evebitda_hist_ratio: number | null;
  ps_median: number | null;
  pbv_median: number | null;
  earnings_yield_median: number | null;
  fcf_yield_median: number | null;
  dividend_yield_median: number | null;
  roa_median: number | null;
  roe_median: number | null;
  roic_median: number | null;
  rev_growth_1yr_median: number | null;
  earn_growth_1yr_median: number | null;
  operating_margin_median: number | null;
  fcf_margin_median: number | null;
  debt_to_ebitda_median: number | null;
  pe_change_3m: number | null;
  pe_change_6m: number | null;
  pe_change_12m: number | null;
  rev_growth_change_12m: number | null;
}

interface HistoryRow {
  month_end_date: string;
  pe_median: number | null;
  evebitda_median: number | null;
  pfcf_median: number | null;
  ps_median: number | null;
  roe_median: number | null;
  roic_median: number | null;
  rev_growth_1yr_median: number | null;
  operating_margin_median: number | null;
  fcf_margin_median: number | null;
  debt_to_ebitda_median: number | null;
}

interface CompanyRow {
  ticker: string;
  company_name: string;
  market_cap_b: number | null;
  current_pe: number | null;
  current_evebitda: number | null;
  rev_growth_1yr: number | null;
  current_roic: number | null;
  momentum_12_1: number | null;
}

// ── Chart config ──────────────────────────────────────────────────────────────

const CHART_METRICS: { key: keyof HistoryRow; label: string; fmt: "x" | "pct" }[] = [
  { key: "pe_median",             label: "P/E",            fmt: "x"   },
  { key: "evebitda_median",       label: "EV/EBITDA",      fmt: "x"   },
  { key: "pfcf_median",           label: "P/FCF",          fmt: "x"   },
  { key: "ps_median",             label: "P/Sales",        fmt: "x"   },
  { key: "roe_median",            label: "ROE",            fmt: "pct" },
  { key: "roic_median",           label: "ROIC",           fmt: "pct" },
  { key: "rev_growth_1yr_median", label: "Rev Growth",     fmt: "pct" },
  { key: "operating_margin_median",label: "Op Margin",     fmt: "pct" },
  { key: "fcf_margin_median",     label: "FCF Margin",     fmt: "pct" },
  { key: "debt_to_ebitda_median", label: "Debt/EBITDA",    fmt: "x"   },
];

const TIP_STYLE = {
  contentStyle: {
    background: "#18181b",
    border: "1px solid rgba(255,255,255,0.1)",
    fontFamily: "monospace",
    fontSize: 11,
    borderRadius: 4,
  },
  labelStyle: { color: "#a1a1aa", marginBottom: 4 },
};

// ── Table columns ─────────────────────────────────────────────────────────────

type ColKey = keyof SectorRow | "pe_change_12m_col";

interface Col {
  key: keyof SectorRow;
  label: string;
  fmt: "x" | "pct" | "chg" | "score" | "int";
  title?: string;
}

const COLS: Col[] = [
  { key: "composite_score",        label: "Score",      fmt: "score", title: "VMQ composite: 35% Value + 35% Momentum + 30% Quality" },
  { key: "pe_median",              label: "P/E",        fmt: "x"    },
  { key: "evebitda_median",        label: "EV/EBITDA",  fmt: "x"    },
  { key: "pfcf_median",            label: "P/FCF",      fmt: "x"    },
  { key: "ps_median",              label: "P/Sales",    fmt: "x"    },
  { key: "rev_growth_1yr_median",  label: "Rev Gr",     fmt: "pct"  },
  { key: "earn_growth_1yr_median", label: "Earn Gr",    fmt: "pct"  },
  { key: "roic_median",            label: "ROIC",       fmt: "pct"  },
  { key: "roe_median",             label: "ROE",        fmt: "pct"  },
  { key: "operating_margin_median",label: "Op Margin",  fmt: "pct"  },
  { key: "fcf_margin_median",      label: "FCF Margin", fmt: "pct"  },
  { key: "debt_to_ebitda_median",  label: "D/EBITDA",   fmt: "x"    },
  { key: "dividend_yield_median",  label: "Div Yield",  fmt: "pct"  },
  { key: "pe_change_3m",           label: "PE Δ3m",     fmt: "chg"  },
  { key: "pe_change_12m",          label: "PE Δ12m",    fmt: "chg"  },
  { key: "ticker_count",           label: "Stocks",     fmt: "int"  },
];

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtX(v: number | null, d = 1) {
  if (v == null) return "—";
  return `${v.toFixed(d)}x`;
}
function fmtPct(v: number | null, d = 1) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(d)}%`;
}
function fmtChg(v: number | null) {
  if (v == null) return "—";
  const s = `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  return s;
}
function fmtScore(v: number | null) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(3)}`;
}
function fmtCell(col: Col, v: number | null): string {
  if (col.fmt === "x")     return fmtX(v);
  if (col.fmt === "pct")   return fmtPct(v);
  if (col.fmt === "chg")   return fmtChg(v);
  if (col.fmt === "score") return fmtScore(v);
  if (col.fmt === "int")   return v != null ? String(v) : "—";
  return "—";
}
function chgColor(v: number | null) {
  if (v == null) return "text-zinc-500";
  return v > 0 ? "text-rose-400" : "text-emerald-400"; // rising PE = expensive = bad
}
function scoreColor(v: number | null) {
  if (v == null) return "text-zinc-500";
  if (v > 0.2)  return "text-emerald-400";
  if (v < -0.2) return "text-rose-400";
  return "text-zinc-300";
}
function cellColor(col: Col, v: number | null): string {
  if (col.fmt === "chg" && col.key.startsWith("pe_change")) return chgColor(v);
  if (col.fmt === "score") return scoreColor(v);
  return "text-zinc-300";
}

// ── Chart ─────────────────────────────────────────────────────────────────────

function SectorChart({ groupType, name }: { groupType: GroupType; name: string }) {
  const [data, setData] = useState<HistoryRow[]>([]);
  const [metric, setMetric] = useState<keyof HistoryRow>("pe_median");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/sector/history?group_type=${groupType}&name=${encodeURIComponent(name)}&months=60`)
      .then(r => r.json())
      .then(j => setData(j.results ?? []))
      .finally(() => setLoading(false));
  }, [groupType, name]);

  const metaCfg = CHART_METRICS.find(m => m.key === metric)!;
  const chartData = data.map(r => ({
    date: r.month_end_date?.slice(0, 7) ?? "",
    value: r[metric] as number | null,
  }));

  const yFmt = metaCfg.fmt === "pct"
    ? (v: number) => `${(v * 100).toFixed(0)}%`
    : (v: number) => `${v.toFixed(1)}x`;

  const tipFmt = metaCfg.fmt === "pct"
    ? (v: number) => fmtPct(v)
    : (v: number) => fmtX(v);

  return (
    <div>
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        {CHART_METRICS.map(m => (
          <button
            key={m.key as string}
            onClick={() => setMetric(m.key)}
            className={`px-2 py-0.5 text-xs font-mono rounded border transition-colors ${
              metric === m.key
                ? "border-violet-500/50 bg-violet-950/30 text-violet-300"
                : "border-white/[0.07] text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      {loading ? (
        <div className="h-48 flex items-center justify-center text-xs font-mono text-zinc-600">loading…</div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData} margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              dataKey="date"
              tick={{ fill: "#71717a", fontSize: 9, fontFamily: "monospace" }}
              axisLine={{ stroke: "rgba(255,255,255,0.07)" }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tickFormatter={yFmt}
              tick={{ fill: "#71717a", fontSize: 9, fontFamily: "monospace" }}
              axisLine={{ stroke: "rgba(255,255,255,0.07)" }}
              tickLine={false}
              width={44}
            />
            <Tooltip
              formatter={(v: unknown) => [tipFmt(v as number), metaCfg.label]}
              {...TIP_STYLE}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke="#8b5cf6"
              strokeWidth={1.5}
              dot={false}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── Company mini-table ────────────────────────────────────────────────────────

function CompanyTable({
  groupType, name, onSelectTicker,
}: {
  groupType: GroupType;
  name: string;
  onSelectTicker: (ticker: string) => void;
}) {
  const [data, setData] = useState<CompanyRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/sector/companies?group_type=${groupType}&name=${encodeURIComponent(name)}`)
      .then(r => r.json())
      .then(j => setData(j.results ?? []))
      .finally(() => setLoading(false));
  }, [groupType, name]);

  if (loading) return <div className="text-xs font-mono text-zinc-600 py-2">loading…</div>;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono border-collapse">
        <thead>
          <tr className="text-left text-zinc-600 border-b border-white/[0.05]">
            <th className="pb-1 pr-3">Ticker</th>
            <th className="pb-1 pr-3">Company</th>
            <th className="pb-1 pr-3 text-right">Mkt Cap</th>
            <th className="pb-1 pr-3 text-right">P/E</th>
            <th className="pb-1 pr-3 text-right">EV/EBITDA</th>
            <th className="pb-1 pr-3 text-right">Rev Gr</th>
            <th className="pb-1 pr-3 text-right">ROIC</th>
            <th className="pb-1 text-right">Mom 12-1</th>
          </tr>
        </thead>
        <tbody>
          {data.slice(0, 20).map(c => (
            <tr key={c.ticker} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
              <td className="py-0.5 pr-3">
                <button
                  onClick={() => onSelectTicker(c.ticker)}
                  className="text-violet-400 hover:text-violet-200 transition-colors"
                >
                  {c.ticker}
                </button>
              </td>
              <td className="py-0.5 pr-3 text-zinc-400 max-w-[180px] truncate">{c.company_name ?? "—"}</td>
              <td className="py-0.5 pr-3 text-right text-zinc-300">
                {c.market_cap_b != null ? `$${c.market_cap_b.toFixed(1)}B` : "—"}
              </td>
              <td className="py-0.5 pr-3 text-right text-zinc-300">{fmtX(c.current_pe)}</td>
              <td className="py-0.5 pr-3 text-right text-zinc-300">{fmtX(c.current_evebitda)}</td>
              <td className={`py-0.5 pr-3 text-right ${c.rev_growth_1yr != null && c.rev_growth_1yr > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {fmtPct(c.rev_growth_1yr)}
              </td>
              <td className="py-0.5 pr-3 text-right text-zinc-300">{fmtPct(c.current_roic)}</td>
              <td className={`py-0.5 text-right ${c.momentum_12_1 != null && c.momentum_12_1 > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {fmtPct(c.momentum_12_1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.length > 20 && (
        <p className="text-xs font-mono text-zinc-600 mt-1">Showing top 20 of {data.length} by market cap</p>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function SectorViewer({ onSelectTicker }: { onSelectTicker: (ticker: string) => void }) {
  const [groupType, setGroupType] = useState<GroupType>("sector");
  const [rows, setRows] = useState<SectorRow[]>([]);
  const [snapshotDate, setSnapshotDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<keyof SectorRow>("composite_score");
  const [sortAsc, setSortAsc] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const fetchSnapshot = useCallback((gt: GroupType) => {
    setLoading(true);
    setError(null);
    setExpanded(null);
    fetch(`${API}/sector/snapshot?group_type=${gt}`)
      .then(r => r.json())
      .then(j => {
        setRows(j.results ?? []);
        setSnapshotDate(j.snapshot_date?.slice(0, 10) ?? "");
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchSnapshot(groupType); }, [groupType, fetchSnapshot]);

  const handleSort = (key: keyof SectorRow) => {
    if (sortKey === key) {
      setSortAsc(a => !a);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const sorted = [...rows].sort((a, b) => {
    const av = a[sortKey] as number | null;
    const bv = b[sortKey] as number | null;
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return sortAsc ? av - bv : bv - av;
  });

  const toggleExpand = (name: string) => {
    setExpanded(prev => (prev === name ? null : name));
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-4">
        <div className="flex gap-1">
          {(["sector", "industry"] as GroupType[]).map(gt => (
            <button
              key={gt}
              onClick={() => setGroupType(gt)}
              className={`px-4 py-1.5 text-xs font-mono rounded border transition-colors capitalize ${
                groupType === gt
                  ? "border-violet-500/50 bg-violet-950/30 text-violet-300"
                  : "border-white/[0.07] text-zinc-500 hover:text-zinc-300 hover:border-white/[0.12]"
              }`}
            >
              {gt === "sector" ? "Sectors" : "Industries"}
            </button>
          ))}
        </div>
        {snapshotDate && (
          <span className="text-xs font-mono text-zinc-600">as of {snapshotDate}</span>
        )}
      </div>

      {error && (
        <div className="text-xs font-mono text-rose-400 px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-xs font-mono text-zinc-600 py-8 text-center">loading…</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono border-collapse min-w-[1100px]">
            <thead>
              <tr className="text-left border-b border-white/[0.07]">
                <th className="pb-2 pr-4 text-zinc-500 font-normal">
                  {groupType === "sector" ? "Sector" : "Industry"}
                </th>
                {COLS.map(col => (
                  <th
                    key={col.key}
                    className="pb-2 pr-3 text-right text-zinc-500 font-normal cursor-pointer hover:text-zinc-300 select-none whitespace-nowrap"
                    title={col.title}
                    onClick={() => handleSort(col.key)}
                  >
                    {col.label}
                    {sortKey === col.key && (
                      <span className="ml-1 text-violet-400">{sortAsc ? "↑" : "↓"}</span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map(row => {
                const isExpanded = expanded === row.group_name;
                return (
                  <Fragment key={row.group_name}>
                    <tr
                      className={`border-b border-white/[0.04] cursor-pointer transition-colors ${
                        isExpanded
                          ? "bg-violet-950/20 hover:bg-violet-950/25"
                          : "hover:bg-white/[0.02]"
                      }`}
                      onClick={() => toggleExpand(row.group_name)}
                    >
                      <td className="py-1.5 pr-4 text-zinc-200 whitespace-nowrap">
                        <span className="mr-1.5 text-zinc-600 text-[10px]">{isExpanded ? "▼" : "▶"}</span>
                        {row.group_name}
                      </td>
                      {COLS.map(col => {
                        const v = row[col.key] as number | null;
                        return (
                          <td
                            key={col.key}
                            className={`py-1.5 pr-3 text-right tabular-nums ${cellColor(col, v)}`}
                          >
                            {fmtCell(col, v)}
                          </td>
                        );
                      })}
                    </tr>
                    {isExpanded && (
                      <tr>
                        <td colSpan={COLS.length + 1} className="p-0">
                          <div className="px-4 py-4 border-b border-violet-900/30 bg-violet-950/10 grid grid-cols-1 xl:grid-cols-2 gap-6">
                            <div>
                              <p className="text-xs font-mono text-zinc-500 mb-2 uppercase tracking-widest">
                                Historical (5yr)
                              </p>
                              <SectorChart groupType={groupType} name={row.group_name} />
                            </div>
                            <div>
                              <p className="text-xs font-mono text-zinc-500 mb-2 uppercase tracking-widest">
                                Top Companies by Market Cap
                              </p>
                              <CompanyTable
                                groupType={groupType}
                                name={row.group_name}
                                onSelectTicker={onSelectTicker}
                              />
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
