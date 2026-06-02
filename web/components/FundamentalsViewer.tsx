"use client";

import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from "recharts";
import type { FundamentalsData } from "@/lib/dcf-types";
import { API } from "@/lib/config";

// ── Chart style constants (matches DcfIncomeChart) ───────────────────────────

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
};

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtPct(v: number | null | undefined, d = 1): string {
  if (v == null) return "—";
  return `${((v as number) * 100).toFixed(d)}%`;
}

function fmtPctAxis(v: number) { return `${(v * 100).toFixed(0)}%`; }
function fmtXAxis(v: number)   { return `${v.toFixed(0)}x`; }

function fmtX(v: number | null | undefined, d = 1): string {
  if (v == null) return "—";
  return `${(v as number).toFixed(d)}x`;
}

function fmtDollar(v: number | null | undefined): string {
  if (v == null) return "—";
  return `$${(v as number).toFixed(2)}`;
}

function fmtBn(v: number | null | undefined): string {
  if (v == null) return "—";
  const n = v as number;
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}T`;
  return `$${n.toFixed(1)}B`;
}

function fmtUpside(target: number | null | undefined, current: number | null | undefined): string {
  if (target == null || current == null) return "—";
  const pct = ((target as number) / (current as number) - 1) * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

function upsideColor(target: number | null | undefined, current: number | null | undefined): string {
  if (target == null || current == null) return "text-zinc-500";
  return (target as number) >= (current as number) ? "text-emerald-400" : "text-rose-400";
}

function revFmt(v: number | null | undefined): string {
  if (v == null) return "—";
  const n = Math.abs(v as number);
  if (n >= 1e12) return `$${((v as number) / 1e12).toFixed(2)}T`;
  if (n >= 1e9)  return `$${((v as number) / 1e9).toFixed(1)}B`;
  if (n >= 1e6)  return `$${((v as number) / 1e6).toFixed(1)}M`;
  return `$${(v as number).toFixed(0)}`;
}

// ── Signal helpers ────────────────────────────────────────────────────────────

// For valuation multiples: lower = cheaper = green
function valSig(cur: number | null | undefined, med5: number | null | undefined) {
  if (cur == null || med5 == null) return "neutral";
  if (cur < med5 * 0.92) return "cheap";
  if (cur > med5 * 1.08) return "expensive";
  return "fair";
}

// For quality metrics: higher = better = green
function qualSig(cur: number | null | undefined, med5: number | null | undefined) {
  if (cur == null || med5 == null) return "neutral";
  if (cur > med5 * 1.05) return "good";
  if (cur < med5 * 0.95) return "weak";
  return "fair";
}

type Signal = "cheap" | "good" | "fair" | "neutral" | "expensive" | "weak";

const DOT_COLOR: Record<Signal, string> = {
  cheap:     "bg-emerald-500",
  good:      "bg-emerald-500",
  fair:      "bg-amber-500",
  neutral:   "bg-zinc-600",
  expensive: "bg-rose-500",
  weak:      "bg-rose-500",
};

const SIG_LABEL: Record<Signal, string> = {
  cheap:     "Cheap vs hist",
  good:      "Above 5yr avg",
  fair:      "Near 5yr avg",
  neutral:   "—",
  expensive: "Pricey vs hist",
  weak:      "Below 5yr avg",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function KpiCard({
  label, primary, secondary, tertiary, signal,
}: {
  label: string;
  primary: string;
  secondary?: string;
  tertiary?: string;
  signal?: Signal;
}) {
  const s: Signal = signal ?? "neutral";
  return (
    <div
      className="rounded border border-white/[0.07] px-4 py-3 flex flex-col gap-1"
      style={{ background: "oklch(0.10 0.008 265)" }}
    >
      <div className="flex items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-zinc-500">{label}</span>
        {signal && signal !== "neutral" && (
          <span className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${DOT_COLOR[s]}`} />
        )}
      </div>
      <div className="font-mono text-lg font-semibold text-zinc-100 tabular-nums">{primary}</div>
      {secondary && <div className="font-mono text-[10px] text-zinc-500">{secondary}</div>}
      {tertiary  && <div className="font-mono text-[10px] text-zinc-600">{tertiary}</div>}
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">
      {children}
    </p>
  );
}

function TableHeader({ cols }: { cols: string[] }) {
  return (
    <thead>
      <tr className="border-b border-white/[0.07]">
        {cols.map((h, i) => (
          <th
            key={h}
            className={`px-4 py-2.5 font-normal text-[10px] uppercase tracking-[0.15em] text-zinc-500 ${
              i === 0 ? "sticky left-0 z-10 text-left" : "text-right min-w-[90px]"
            }`}
            style={i === 0 ? { background: "oklch(0.10 0.008 265)" } : undefined}
          >
            {h}
          </th>
        ))}
      </tr>
    </thead>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function FundamentalsViewer({ ticker }: { ticker: string }) {
  const [data, setData] = useState<FundamentalsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    setData(null);
    fetch(`${API}/av-fundamentals/${ticker}`)
      .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
      .then(({ ok, j }) => {
        if (!ok) throw new Error((j as { detail?: string }).detail ?? "HTTP error");
        setData(j as FundamentalsData);
      })
      .catch((e: unknown) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [ticker]);

  if (error) {
    return (
      <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20 text-rose-400">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-rose-500 shrink-0" />
        {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center h-64">
        <span className="font-mono text-sm text-zinc-600 animate-pulse">
          {loading ? "Loading fundamentals…" : "No data"}
        </span>
      </div>
    );
  }

  const price = data.current_price;
  const series = data.monthly_series;

  // X-axis: with interval=11 (~every 12th of 120 points) each tick lands in a unique year
  const xTickFormatter = (dateStr: string) => dateStr.slice(0, 4);

  // Analyst ratings bar totals
  const totalRatings =
    (data.analyst_strong_buy ?? 0) +
    (data.analyst_buy ?? 0) +
    (data.analyst_hold ?? 0) +
    (data.analyst_sell ?? 0) +
    (data.analyst_strong_sell ?? 0);

  const rPct = (v: number | null | undefined) =>
    totalRatings > 0 ? `${(((v ?? 0) / totalRatings) * 100).toFixed(0)}%` : "0%";

  return (
    <div
      className="space-y-6 transition-opacity duration-150"
      style={{ opacity: loading ? 0.5 : 1 }}
    >
      {/* ── 1. Header ──────────────────────────────────────────────────────── */}
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-2">
          <span className="font-mono text-sm font-semibold text-zinc-100 tracking-widest">{ticker}</span>
          {data.company_name && (
            <span className="font-mono text-sm text-zinc-400">{data.company_name}</span>
          )}
          {data.sector && (
            <>
              <span className="text-zinc-700 select-none">·</span>
              <span className="font-mono text-xs text-zinc-500">{data.sector}</span>
            </>
          )}
          {data.industry && (
            <>
              <span className="text-zinc-700 select-none">·</span>
              <span className="font-mono text-xs text-zinc-600">{data.industry}</span>
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 mb-3 font-mono text-xs">
          {price != null && (
            <span className="text-zinc-200 font-semibold tabular-nums text-sm">{fmtDollar(price)}</span>
          )}
          {data.market_cap_b != null && (
            <span className="text-zinc-500">Mkt Cap {fmtBn(data.market_cap_b)}</span>
          )}
          {data.analyst_target_price != null && (
            <>
              <span className="text-zinc-700 select-none">·</span>
              <span className="text-zinc-400">
                Analyst target{" "}
                <span className="text-zinc-200">{fmtDollar(data.analyst_target_price)}</span>
                {"  "}
                <span className={upsideColor(data.analyst_target_price, price)}>
                  {fmtUpside(data.analyst_target_price, price)}
                </span>
              </span>
            </>
          )}
          {data.stats_updated_at && (
            <span className="text-zinc-700 text-[10px]">
              Updated {data.stats_updated_at.slice(0, 10)}
            </span>
          )}
        </div>

        {totalRatings > 0 && (
          <div className="flex items-center gap-3">
            <div className="flex h-1.5 rounded overflow-hidden w-40 shrink-0">
              {(data.analyst_strong_buy ?? 0) > 0 && (
                <div style={{ width: rPct(data.analyst_strong_buy) }} className="bg-emerald-500" />
              )}
              {(data.analyst_buy ?? 0) > 0 && (
                <div style={{ width: rPct(data.analyst_buy) }} className="bg-emerald-400/60" />
              )}
              {(data.analyst_hold ?? 0) > 0 && (
                <div style={{ width: rPct(data.analyst_hold) }} className="bg-zinc-500" />
              )}
              {(data.analyst_sell ?? 0) > 0 && (
                <div style={{ width: rPct(data.analyst_sell) }} className="bg-rose-400/60" />
              )}
              {(data.analyst_strong_sell ?? 0) > 0 && (
                <div style={{ width: rPct(data.analyst_strong_sell) }} className="bg-rose-500" />
              )}
            </div>
            <span className="font-mono text-[10px] text-zinc-500">
              {data.analyst_strong_buy ?? 0} Strong Buy · {data.analyst_buy ?? 0} Buy ·{" "}
              {data.analyst_hold ?? 0} Hold · {data.analyst_sell ?? 0} Sell ·{" "}
              {data.analyst_strong_sell ?? 0} Strong Sell
            </span>
          </div>
        )}
      </div>

      {/* ── 2. KPI Snapshot grid ───────────────────────────────────────────── */}
      <div>
        <SectionHeading>Snapshot</SectionHeading>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard
            label="P/E"
            primary={fmtX(data.current_pe)}
            secondary={`Fwd ${fmtX(data.forward_pe)}  ·  5yr med ${fmtX(data.pe_rolling_5yr_median)}`}
            tertiary={`LT med ${fmtX(data.pe_lt_median)}`}
            signal={valSig(data.current_pe, data.pe_rolling_5yr_median)}
          />
          <KpiCard
            label="EV / EBITDA"
            primary={fmtX(data.current_evebitda)}
            secondary={`Fwd ${fmtX(data.forward_evebitda)}  ·  5yr med ${fmtX(data.evebitda_rolling_5yr_median)}`}
            tertiary={`LT med ${fmtX(data.evebitda_lt_median)}`}
            signal={valSig(data.current_evebitda, data.evebitda_rolling_5yr_median)}
          />
          <KpiCard
            label="P / FCF"
            primary={fmtX(data.current_pfcf)}
            secondary={`Fwd ${fmtX(data.forward_pfcf)}  ·  5yr med ${fmtX(data.pfcf_rolling_5yr_median)}`}
            tertiary={`LT med ${fmtX(data.pfcf_lt_median)}`}
            signal={valSig(data.current_pfcf, data.pfcf_rolling_5yr_median)}
          />
          <KpiCard
            label="P / Sales"
            primary={fmtX(data.current_ps)}
            secondary={`Fwd ${fmtX(data.forward_ps)}  ·  5yr med ${fmtX(data.ps_rolling_5yr_median)}`}
            tertiary={`LT med ${fmtX(data.ps_lt_median)}`}
            signal={valSig(data.current_ps, data.ps_rolling_5yr_median)}
          />
          <KpiCard
            label="Revenue Growth"
            primary={fmtPct(data.rev_growth_1yr)}
            secondary={`3yr CAGR ${fmtPct(data.rev_cagr_3yr)}  ·  5yr ${fmtPct(data.rev_cagr_5yr)}`}
            tertiary={`NTM est ${fmtPct(data.rev_ntm_growth_est)}`}
          />
          <KpiCard
            label="Op Margin"
            primary={fmtPct(data.current_operating_margin)}
            secondary={`5yr med ${fmtPct(data.operating_margin_5y_median)}`}
            tertiary={`3yr chg ${fmtPct(data.operating_margin_change_3y)}`}
            signal={qualSig(data.current_operating_margin, data.operating_margin_5y_median)}
          />
          <KpiCard
            label="FCF Margin"
            primary={fmtPct(data.current_fcf_margin)}
            secondary={`5yr med ${fmtPct(data.fcf_margin_5y_median)}`}
            tertiary={`3yr chg ${fmtPct(data.fcf_margin_change_3y)}`}
            signal={qualSig(data.current_fcf_margin, data.fcf_margin_5y_median)}
          />
          <KpiCard
            label="ROE"
            primary={fmtPct(data.current_roe)}
            secondary={`ROIC ${fmtPct(data.current_roic)}  ·  ROA ${fmtPct(data.current_roa)}`}
            tertiary={`5yr ROE med ${fmtPct(data.roe_rolling_5yr_median)}`}
            signal={qualSig(data.current_roe, data.roe_rolling_5yr_median)}
          />
        </div>
      </div>

      {/* ── 3. Valuation history charts ────────────────────────────────────── */}
      {series.length > 0 && (
        <div>
          <SectionHeading>Valuation History</SectionHeading>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2" style={CHART_BG}>
              <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1 pl-1">P/E Ratio</p>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={series} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                  <XAxis dataKey="date" tickFormatter={xTickFormatter} tick={TICK_STYLE} tickLine={false} axisLine={AXIS_LINE} interval={11} />
                  <YAxis tickFormatter={fmtXAxis} tick={TICK_STYLE} tickLine={false} axisLine={false} width={40} />
                  <Tooltip
                    {...TIP_STYLE}
                    labelFormatter={(l) => String(l).slice(0, 10)}
                    formatter={(v, name) => [typeof v === "number" ? fmtX(v) : "—", name]}
                  />
                  <Legend wrapperStyle={{ fontFamily: "monospace", fontSize: 10, color: "#71717a", paddingTop: 8 }} />
                  <Line type="monotone" dataKey="pe_ratio" name="P/E" stroke="#818cf8" strokeWidth={1.5} dot={false} connectNulls />
                  <Line type="monotone" dataKey="pe_rolling_5yr_median" name="5yr Median" stroke="#818cf8" strokeWidth={1} dot={false} strokeDasharray="4 2" connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2" style={CHART_BG}>
              <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1 pl-1">EV/EBITDA & P/FCF</p>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={series} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                  <XAxis dataKey="date" tickFormatter={xTickFormatter} tick={TICK_STYLE} tickLine={false} axisLine={AXIS_LINE} interval={11} />
                  <YAxis tickFormatter={fmtXAxis} tick={TICK_STYLE} tickLine={false} axisLine={false} width={40} />
                  <Tooltip
                    {...TIP_STYLE}
                    labelFormatter={(l) => String(l).slice(0, 10)}
                    formatter={(v, name) => [typeof v === "number" ? fmtX(v) : "—", name]}
                  />
                  <Legend wrapperStyle={{ fontFamily: "monospace", fontSize: 10, color: "#71717a", paddingTop: 8 }} />
                  <Line type="monotone" dataKey="ev_ebitda" name="EV/EBITDA" stroke="#34d399" strokeWidth={1.5} dot={false} connectNulls />
                  <Line type="monotone" dataKey="ev_ebitda_rolling_5yr_median" name="EV/EBITDA 5yr" stroke="#34d399" strokeWidth={1} dot={false} strokeDasharray="4 2" connectNulls />
                  <Line type="monotone" dataKey="pfcf_ratio" name="P/FCF" stroke="#fb923c" strokeWidth={1.5} dot={false} connectNulls />
                  <Line type="monotone" dataKey="pfcf_rolling_5yr_median" name="P/FCF 5yr" stroke="#fb923c" strokeWidth={1} dot={false} strokeDasharray="4 2" connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {/* ── 4. Margins & Returns charts ────────────────────────────────────── */}
      {series.length > 0 && (
        <div>
          <SectionHeading>Margins & Returns History</SectionHeading>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2" style={CHART_BG}>
              <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1 pl-1">Profit Margins</p>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={series} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                  <XAxis dataKey="date" tickFormatter={xTickFormatter} tick={TICK_STYLE} tickLine={false} axisLine={AXIS_LINE} interval={11} />
                  <YAxis tickFormatter={fmtPctAxis} tick={TICK_STYLE} tickLine={false} axisLine={false} width={44} />
                  <Tooltip
                    {...TIP_STYLE}
                    labelFormatter={(l) => String(l).slice(0, 10)}
                    formatter={(v, name) => [typeof v === "number" ? fmtPct(v) : "—", name]}
                  />
                  <Legend wrapperStyle={{ fontFamily: "monospace", fontSize: 10, color: "#71717a", paddingTop: 8 }} />
                  <Line type="monotone" dataKey="ttm_gross_margin"     name="Gross Margin" stroke="#34d399" strokeWidth={1.5} dot={false} connectNulls />
                  <Line type="monotone" dataKey="ttm_operating_margin" name="Op Margin"    stroke="#fb923c" strokeWidth={1.5} dot={false} connectNulls />
                  <Line type="monotone" dataKey="ttm_fcf_margin"       name="FCF Margin"   stroke="#a78bfa" strokeWidth={1.5} dot={false} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2" style={CHART_BG}>
              <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1 pl-1">Capital Returns</p>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={series} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                  <XAxis dataKey="date" tickFormatter={xTickFormatter} tick={TICK_STYLE} tickLine={false} axisLine={AXIS_LINE} interval={11} />
                  <YAxis tickFormatter={fmtPctAxis} tick={TICK_STYLE} tickLine={false} axisLine={false} width={44} />
                  <Tooltip
                    {...TIP_STYLE}
                    labelFormatter={(l) => String(l).slice(0, 10)}
                    formatter={(v, name) => [typeof v === "number" ? fmtPct(v) : "—", name]}
                  />
                  <Legend wrapperStyle={{ fontFamily: "monospace", fontSize: 10, color: "#71717a", paddingTop: 8 }} />
                  <Line type="monotone" dataKey="roa"  name="ROA"  stroke="#34d399" strokeWidth={1.5} dot={false} connectNulls />
                  <Line type="monotone" dataKey="roe"  name="ROE"  stroke="#818cf8" strokeWidth={1.5} dot={false} connectNulls />
                  <Line type="monotone" dataKey="roic" name="ROIC" stroke="#fb923c" strokeWidth={1.5} dot={false} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {/* ── 5. Price targets ────────────────────────────────────────────────── */}
      <div>
        <SectionHeading>Price Targets</SectionHeading>
        <div className="overflow-x-auto rounded border border-white/[0.07]">
          <table className="w-full text-xs font-mono border-collapse">
            <TableHeader cols={["Method", "Target", "Upside vs Current"]} />
            <tbody>
              {[
                { label: "5yr Median P/E",    target: data.goal_pe  },
                { label: "5yr Median P/FCF",  target: data.goal_pcf },
                { label: "PEG Implied",        target: data.goal_peg },
                { label: "Book Value",         target: data.goal_bv  },
                { label: "Analyst Consensus",  target: data.analyst_target_price },
              ]
                .filter((r) => r.target != null)
                .map((r, i) => {
                  const bg = i % 2 === 0 ? "oklch(0.09 0.006 265)" : "oklch(0.105 0.008 265)";
                  return (
                    <tr key={r.label} style={{ background: bg }}>
                      <td className="sticky left-0 z-10 px-4 py-2 text-zinc-400" style={{ background: bg }}>{r.label}</td>
                      <td className="px-4 py-2 text-right tabular-nums text-zinc-100">{fmtDollar(r.target)}</td>
                      <td className={`px-4 py-2 text-right tabular-nums ${upsideColor(r.target, price)}`}>
                        {fmtUpside(r.target, price)}
                      </td>
                    </tr>
                  );
                })}
              {(data.goal_low != null || data.goal_high != null) && (() => {
                const bg = "oklch(0.09 0.006 265)";
                return (
                  <tr style={{ background: bg }}>
                    <td className="sticky left-0 z-10 px-4 py-2 text-zinc-600 text-[10px]" style={{ background: bg }}>Range (Low – High)</td>
                    <td className="px-4 py-2 text-right tabular-nums text-zinc-600 text-[10px]">
                      {data.goal_low != null ? fmtDollar(data.goal_low) : "—"} – {data.goal_high != null ? fmtDollar(data.goal_high) : "—"}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-zinc-600 text-[10px]">
                      {fmtUpside(data.goal_low, price)} – {fmtUpside(data.goal_high, price)}
                    </td>
                  </tr>
                );
              })()}
            </tbody>
          </table>
        </div>
        <p className="font-mono text-[10px] text-zinc-700 mt-1.5">
          Current: {fmtDollar(price)} · For full DCF model see AV DCF tab
        </p>
      </div>

      {/* ── 6. Valuation multiples detail ───────────────────────────────────── */}
      <div>
        <SectionHeading>Valuation Multiples</SectionHeading>
        <div className="overflow-x-auto rounded border border-white/[0.07]">
          <table className="w-full text-xs font-mono border-collapse">
            <TableHeader cols={["Multiple", "Current", "Forward", "5yr Median", "LT Median", "Range P25–P75", "Signal"]} />
            <tbody>
              {[
                { label: "P/E",       cur: data.current_pe,       fwd: data.forward_pe,       med5: data.pe_rolling_5yr_median,       medLt: data.pe_lt_median,       p25: data.pe_p25,       p75: data.pe_p75       },
                { label: "EV/EBITDA", cur: data.current_evebitda, fwd: data.forward_evebitda, med5: data.evebitda_rolling_5yr_median, medLt: data.evebitda_lt_median, p25: data.evebitda_p25, p75: data.evebitda_p75 },
                { label: "P/FCF",     cur: data.current_pfcf,     fwd: data.forward_pfcf,     med5: data.pfcf_rolling_5yr_median,     medLt: data.pfcf_lt_median,     p25: data.pfcf_p25,     p75: data.pfcf_p75     },
                { label: "P/Sales",   cur: data.current_ps,       fwd: data.forward_ps,       med5: data.ps_rolling_5yr_median,       medLt: data.ps_lt_median,       p25: data.ps_p25,       p75: data.ps_p75       },
                { label: "P/BV",      cur: data.current_pbv,      fwd: null,                  med5: data.pbv_rolling_5yr_median,      medLt: data.pbv_lt_median,      p25: null,              p75: null              },
              ].map((r, i) => {
                const sig = valSig(r.cur, r.med5);
                const bg  = i % 2 === 0 ? "oklch(0.09 0.006 265)" : "oklch(0.105 0.008 265)";
                return (
                  <tr key={r.label} style={{ background: bg }}>
                    <td className="sticky left-0 z-10 px-4 py-2 text-zinc-300 font-medium" style={{ background: bg }}>{r.label}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-zinc-100">{fmtX(r.cur)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-zinc-400">{fmtX(r.fwd)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-zinc-400">{fmtX(r.med5)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-zinc-500">{fmtX(r.medLt)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-zinc-600 text-[10px]">
                      {r.p25 != null && r.p75 != null ? `${fmtX(r.p25, 0)} – ${fmtX(r.p75, 0)}` : "—"}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <span className={`inline-block w-1.5 h-1.5 rounded-full ${DOT_COLOR[sig as Signal]}`} />
                        <span className="text-zinc-500 text-[10px]">{SIG_LABEL[sig as Signal]}</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── 7. Growth & Profitability ───────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div>
          <SectionHeading>Growth Rates</SectionHeading>
          <div className="overflow-x-auto rounded border border-white/[0.07]">
            <table className="w-full text-xs font-mono border-collapse">
              <thead>
                <tr className="border-b border-white/[0.07]">
                  <th className="text-left px-4 py-2 font-normal text-[10px] uppercase tracking-[0.15em] text-zinc-500">Metric</th>
                  {["1yr", "3yr CAGR", "5yr CAGR", "NTM Est"].map((h) => (
                    <th key={h} className="text-right px-3 py-2 font-normal text-[10px] text-zinc-500 min-w-[64px]">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { label: "Revenue",  g1: data.rev_growth_1yr,  g3: data.rev_cagr_3yr,  g5: data.rev_cagr_5yr,  ntm: data.rev_ntm_growth_est  },
                  { label: "Earnings", g1: data.earn_growth_1yr, g3: data.earn_cagr_3yr, g5: data.earn_cagr_5yr, ntm: data.earn_ntm_growth_est },
                ].map((r, i) => {
                  const bg = i % 2 === 0 ? "oklch(0.09 0.006 265)" : "oklch(0.105 0.008 265)";
                  const gc = (v: number | null | undefined) =>
                    v != null && v < 0 ? "text-rose-400" : "text-zinc-200";
                  return (
                    <tr key={r.label} style={{ background: bg }}>
                      <td className="px-4 py-2 text-zinc-300">{r.label}</td>
                      <td className={`px-3 py-2 text-right tabular-nums ${gc(r.g1)}`}>{fmtPct(r.g1)}</td>
                      <td className={`px-3 py-2 text-right tabular-nums ${gc(r.g3)}`}>{fmtPct(r.g3)}</td>
                      <td className={`px-3 py-2 text-right tabular-nums ${gc(r.g5)}`}>{fmtPct(r.g5)}</td>
                      <td className={`px-3 py-2 text-right tabular-nums ${gc(r.ntm)}`}>{fmtPct(r.ntm)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <SectionHeading>Profitability</SectionHeading>
          <div className="overflow-x-auto rounded border border-white/[0.07]">
            <table className="w-full text-xs font-mono border-collapse">
              <thead>
                <tr className="border-b border-white/[0.07]">
                  <th className="text-left px-4 py-2 font-normal text-[10px] uppercase tracking-[0.15em] text-zinc-500">Metric</th>
                  {["Current", "5yr Med", "3yr Chg"].map((h) => (
                    <th key={h} className="text-right px-3 py-2 font-normal text-[10px] text-zinc-500 min-w-[72px]">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { label: "Gross Margin", cur: data.current_gross_margin,     med: data.gross_margin_5y_median,     chg: null                           },
                  { label: "EBIT Margin",  cur: data.current_operating_margin, med: data.operating_margin_5y_median, chg: data.operating_margin_change_3y },
                  { label: "FCF Margin",   cur: data.current_fcf_margin,       med: data.fcf_margin_5y_median,       chg: data.fcf_margin_change_3y       },
                  { label: "ROA",          cur: data.current_roa,              med: data.roa_rolling_5yr_median,     chg: null                           },
                  { label: "ROE",          cur: data.current_roe,              med: data.roe_rolling_5yr_median,     chg: null                           },
                  { label: "ROIC",         cur: data.current_roic,             med: data.roic_rolling_5yr_median,    chg: null                           },
                ].map((r, i) => {
                  const bg  = i % 2 === 0 ? "oklch(0.09 0.006 265)" : "oklch(0.105 0.008 265)";
                  const qc  = (c: typeof r.cur, m: typeof r.med) =>
                    c != null && m != null ? (c >= m ? "text-emerald-400" : "text-rose-400") : "text-zinc-300";
                  const chgColor = (v: typeof r.chg) =>
                    v == null ? "text-zinc-600" : v >= 0 ? "text-emerald-400" : "text-rose-400";
                  return (
                    <tr key={r.label} style={{ background: bg }}>
                      <td className="px-4 py-2 text-zinc-300">{r.label}</td>
                      <td className={`px-3 py-2 text-right tabular-nums ${qc(r.cur, r.med)}`}>{fmtPct(r.cur)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-zinc-500">{fmtPct(r.med)}</td>
                      <td className={`px-3 py-2 text-right tabular-nums ${chgColor(r.chg)}`}>{r.chg != null ? fmtPct(r.chg) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ── 8. Analyst Estimates ────────────────────────────────────────────── */}
      {data.analyst_estimates.length > 0 && (
        <div>
          <SectionHeading>Analyst Estimates</SectionHeading>
          <div className="overflow-x-auto rounded border border-white/[0.07]">
            <table className="w-full text-xs font-mono border-collapse">
              <thead>
                <tr className="border-b border-white/[0.07]">
                  {["Period", "Type", "EPS (avg)", "EPS Range", "Revenue (avg)", "Rev Range", "Analysts"].map((h, i) => (
                    <th key={h} className={`px-4 py-2.5 font-normal text-[10px] uppercase tracking-[0.15em] text-zinc-500 ${i === 0 ? "text-left" : "text-right min-w-[100px]"}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.analyst_estimates.map((e, i) => {
                  const bg  = i % 2 === 0 ? "oklch(0.09 0.006 265)" : "oklch(0.105 0.008 265)";
                  const eps = (v: number | null | undefined) => v == null ? "—" : `$${v.toFixed(2)}`;
                  return (
                    <tr key={i} style={{ background: bg }}>
                      <td className="px-4 py-2 text-zinc-200">{e.date.slice(0, 10)}</td>
                      <td className="px-4 py-2 text-right text-zinc-500 text-[10px]">{e.horizon}</td>
                      <td className="px-4 py-2 text-right tabular-nums text-zinc-200">{eps(e.eps_avg)}</td>
                      <td className="px-4 py-2 text-right tabular-nums text-zinc-500 text-[10px]">
                        {e.eps_low != null && e.eps_high != null ? `${eps(e.eps_low)} – ${eps(e.eps_high)}` : "—"}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-zinc-200">{revFmt(e.rev_avg)}</td>
                      <td className="px-4 py-2 text-right tabular-nums text-zinc-500 text-[10px]">
                        {e.rev_low != null && e.rev_high != null ? `${revFmt(e.rev_low)} – ${revFmt(e.rev_high)}` : "—"}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-zinc-600">{e.eps_count ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Leverage & Dividends ─────────────────────────────────────────────── */}
      {(data.debt_to_ebitda != null || data.interest_coverage != null || (data.dividend_yield != null && data.dividend_yield > 0)) && (
        <div>
          <SectionHeading>Leverage & Dividends</SectionHeading>
          <div className="grid grid-cols-3 gap-3 max-w-lg">
            {data.debt_to_ebitda != null && (
              <KpiCard
                label="Debt / EBITDA"
                primary={fmtX(data.debt_to_ebitda)}
                signal={data.debt_to_ebitda < 2 ? "good" : data.debt_to_ebitda > 4 ? "weak" : "fair"}
              />
            )}
            {data.interest_coverage != null && (
              <KpiCard
                label="Interest Coverage"
                primary={fmtX(data.interest_coverage)}
                signal={data.interest_coverage > 5 ? "good" : data.interest_coverage < 2 ? "weak" : "fair"}
              />
            )}
            {data.dividend_yield != null && data.dividend_yield > 0 && (
              <KpiCard label="Dividend Yield" primary={fmtPct(data.dividend_yield)} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
