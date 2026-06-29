"use client";

import {
  ComposedChart, LineChart, Line, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ReferenceArea, ResponsiveContainer,
} from "recharts";
import type { HistoricalRow } from "@/lib/dcf-types";

interface Props {
  historical: HistoricalRow[];
  proforma: HistoricalRow[];
}

function fmtBnAxis(v: number) { return `$${(v / 1e9).toFixed(0)}B`; }
function fmtBnTip(v: number)  { return `$${(v / 1e9).toFixed(1)}B`; }
function fmtPctAxis(v: number) { return `${v.toFixed(0)}%`; }
function fmtPctTip(v: number)  { return `${v.toFixed(1)}%`; }
function shortLabel(l: string) { return l.replace(/^FY\s*/, ""); }

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

export default function DcfIncomeChart({ historical, proforma }: Props) {
  const absData = [
    ...historical.map((h) => ({
      label:        shortLabel(h.period_label),
      revenue:      h.revenue,
      gross_profit: h.gross_profit,
      ebit:         h.operating_income,
      net_income:   h.net_income,
    })),
    ...proforma.map((p) => ({
      label:        shortLabel(p.period_label),
      revenue:      p.revenue,
      gross_profit: p.gross_profit,
      ebit:         p.operating_income,
      net_income:   p.net_income,
    })),
  ];

  const growthData = absData.map((d, i) => {
    const cur  = d.revenue;
    const prev = i === 0 ? null : absData[i - 1].revenue;
    const growth = cur != null && prev != null && prev !== 0
      ? ((cur - prev) / prev) * 100
      : null;
    const base3 = i >= 3 ? absData[i - 3].revenue : null;
    const cagr3 = cur != null && base3 != null && base3 > 0
      ? (Math.pow(cur / base3, 1 / 3) - 1) * 100
      : null;
    return { label: d.label, growth, cagr3 };
  });

  const marginData = absData.map((d) => ({
    label:         d.label,
    gross_margin:  d.revenue && d.gross_profit != null ? (d.gross_profit / d.revenue) * 100 : null,
    ebit_margin:   d.revenue && d.ebit         != null ? (d.ebit         / d.revenue) * 100 : null,
    net_margin:    d.revenue && d.net_income   != null ? (d.net_income   / d.revenue) * 100 : null,
  }));

  const firstProforma = proforma[0]     ? shortLabel(proforma[0].period_label)     : undefined;
  const lastProforma  = proforma.at(-1) ? shortLabel(proforma.at(-1)!.period_label) : undefined;

  const forecastArea = firstProforma && lastProforma ? (
    <ReferenceArea
      x1={firstProforma}
      x2={lastProforma}
      fill="rgba(139,92,246,0.06)"
      label={{ value: "Forecast", position: "insideTopLeft", fill: "rgba(139,92,246,0.4)", fontSize: 9, fontFamily: "monospace" }}
    />
  ) : null;

  return (
    <div className="mb-6">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">
        Income Statement
      </p>

      {/* Absolute chart — Revenue & Gross Profit */}
      <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2 mb-2" style={CHART_BG}>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={absData} margin={{ top: 4, right: 16, left: 16, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
            {forecastArea}
            <XAxis dataKey="label" tick={TICK_STYLE} tickLine={false} axisLine={AXIS_LINE} />
            <YAxis tickFormatter={fmtBnAxis} tick={TICK_STYLE} tickLine={false} axisLine={false} width={52} />
            <Tooltip
              {...TIP_STYLE}
              formatter={(v, name) => [typeof v === "number" ? fmtBnTip(v) : "—", name]}
              itemSorter={(item) => ["revenue", "gross_profit"].indexOf(item.dataKey as string)}
            />
            <Legend wrapperStyle={{ fontFamily: "monospace", fontSize: 10, color: "#71717a", paddingTop: 8 }} />
            <Line type="monotone" dataKey="revenue"      name="Revenue"      stroke="#818cf8" strokeWidth={2}   dot={false} connectNulls />
            <Line type="monotone" dataKey="gross_profit" name="Gross Profit"  stroke="#34d399" strokeWidth={1.5} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Revenue Growth chart */}
      <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2 mb-2" style={CHART_BG}>
        <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1 pl-1">
          Revenue Growth
        </p>
        <ResponsiveContainer width="100%" height={160}>
          <ComposedChart data={growthData} margin={{ top: 4, right: 16, left: 16, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
            {forecastArea}
            <XAxis dataKey="label" tick={TICK_STYLE} tickLine={false} axisLine={AXIS_LINE} />
            <YAxis tickFormatter={fmtPctAxis} tick={TICK_STYLE} tickLine={false} axisLine={false} width={40} />
            <Tooltip
              {...TIP_STYLE}
              formatter={(v, _name) => [typeof v === "number" ? fmtPctTip(v) : "—", "Rev Growth"]}
            />
            <Bar dataKey="growth" name="Rev Growth" isAnimationActive={false}>
              {growthData.map((d, i) => (
                <Cell key={i} fill={d.growth != null && d.growth < 0 ? "#f87171" : "#34d399"} />
              ))}
            </Bar>
            <Line type="monotone" dataKey="cagr3" name="3yr CAGR" stroke="#f59e0b" strokeWidth={1.5} dot={false} connectNulls />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Margin chart — EBIT % and Net % */}
      <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2" style={CHART_BG}>
        <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1 pl-1">
          Margins
        </p>
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={marginData} margin={{ top: 4, right: 16, left: 16, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
            {forecastArea}
            <XAxis dataKey="label" tick={TICK_STYLE} tickLine={false} axisLine={AXIS_LINE} />
            <YAxis tickFormatter={fmtPctAxis} tick={TICK_STYLE} tickLine={false} axisLine={false} width={40} />
            <Tooltip
              {...TIP_STYLE}
              formatter={(v, name) => [typeof v === "number" ? fmtPctTip(v) : "—", name]}
            />
            <Legend wrapperStyle={{ fontFamily: "monospace", fontSize: 10, color: "#71717a", paddingTop: 8 }} />
            <Line type="monotone" dataKey="gross_margin" name="Gross Margin" stroke="#34d399" strokeWidth={1.5} dot={false} connectNulls />
            <Line type="monotone" dataKey="ebit_margin"  name="EBIT Margin"  stroke="#fb923c" strokeWidth={1.5} dot={false} connectNulls />
            <Line type="monotone" dataKey="net_margin"   name="Net Margin"   stroke="#a78bfa" strokeWidth={1.5} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
