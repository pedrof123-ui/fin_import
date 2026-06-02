"use client";

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ReferenceArea, ResponsiveContainer,
} from "recharts";
import type { HistoricalRow } from "@/lib/dcf-types";

interface Props {
  historical: HistoricalRow[];
  proforma: HistoricalRow[];
}

function fmtDaysAxis(v: number) { return `${v.toFixed(0)}d`; }
function fmtDaysTip(v: number)  { return `${v.toFixed(1)} days`; }
function fmtPctAxis(v: number)  { return `${v.toFixed(0)}%`; }
function fmtPctTip(v: number)   { return `${v.toFixed(1)}%`; }
function shortLabel(l: string)  { return l.replace(/^FY\s*/, ""); }

const CHART_BG   = { background: "oklch(0.09 0.006 265)" };
const GRID_STROKE = "rgba(255,255,255,0.05)";
const TICK_STYLE  = { fill: "#71717a", fontSize: 10, fontFamily: "monospace" };
const AXIS_LINE   = { stroke: "rgba(255,255,255,0.07)" };
const TIP_STYLE   = {
  contentStyle: {
    background: "#18181b",
    border: "1px solid rgba(255,255,255,0.1)",
    fontFamily: "monospace",
    fontSize: 11,
    borderRadius: 4,
  },
  labelStyle: { color: "#a1a1aa", marginBottom: 4 },
};

function dso(h: HistoricalRow): number | null {
  if (!h.accounts_receivable || !h.revenue || h.revenue === 0) return null;
  return (h.accounts_receivable / h.revenue) * 365;
}

function dpo(h: HistoricalRow): number | null {
  const cogs = h.cost_of_revenue;
  if (!h.accounts_payable || !cogs || cogs === 0) return null;
  return (h.accounts_payable / cogs) * 365;
}

function dio(h: HistoricalRow): number | null {
  const cogs = h.cost_of_revenue;
  if (!h.inventory || !cogs || cogs === 0) return null;
  return (h.inventory / cogs) * 365;
}

export default function DcfEfficiencyChart({ historical, proforma }: Props) {
  // Working capital days — historical only
  const wcData = historical.map((h) => ({
    label: shortLabel(h.period_label),
    dso:   dso(h),
    dpo:   dpo(h),
    dio:   dio(h),
  })).filter((d) => d.dso != null || d.dpo != null || d.dio != null);

  // Capex / Revenue — historical + proforma
  const capexData = [
    ...historical.map((h) => ({
      label:     shortLabel(h.period_label),
      capex_pct: h.capital_expenditures != null && h.revenue
        ? (Math.abs(h.capital_expenditures) / h.revenue) * 100
        : null,
    })),
    ...proforma.map((p) => ({
      label:     shortLabel(p.period_label),
      capex_pct: p.capital_expenditures != null && p.revenue
        ? (Math.abs(p.capital_expenditures) / p.revenue) * 100
        : null,
    })),
  ];

  // Effective tax rate — historical only; null-guard for loss years
  const taxData = historical.map((h) => ({
    label:   shortLabel(h.period_label),
    tax_pct: h.income_tax_expense != null && h.pretax_income != null && h.pretax_income > 0
      ? (h.income_tax_expense / h.pretax_income) * 100
      : null,
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

  const showWc = wcData.length > 0;
  const showCapex = capexData.some((d) => d.capex_pct != null);
  const showTax   = taxData.some((d) => d.tax_pct   != null);

  if (!showWc && !showCapex && !showTax) return null;

  return (
    <div className="mb-6">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">
        Efficiency &amp; Capital
      </p>

      {/* Working Capital Days */}
      {showWc && (
        <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2 mb-2" style={CHART_BG}>
          <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1 pl-1">
            Working Capital Days
          </p>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={wcData} margin={{ top: 4, right: 16, left: 16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
              <XAxis dataKey="label" tick={TICK_STYLE} tickLine={false} axisLine={AXIS_LINE} />
              <YAxis tickFormatter={fmtDaysAxis} tick={TICK_STYLE} tickLine={false} axisLine={false} width={40} />
              <Tooltip
                {...TIP_STYLE}
                formatter={(v, name) => [typeof v === "number" ? fmtDaysTip(v) : "—", name]}
              />
              <Legend wrapperStyle={{ fontFamily: "monospace", fontSize: 10, color: "#71717a", paddingTop: 8 }} />
              <Line type="monotone" dataKey="dso" name="DSO" stroke="#818cf8" strokeWidth={1.5} dot={false} connectNulls />
              <Line type="monotone" dataKey="dpo" name="DPO" stroke="#fb923c" strokeWidth={1.5} dot={false} connectNulls />
              <Line type="monotone" dataKey="dio" name="DIO" stroke="#34d399" strokeWidth={1.5} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Capex % and Tax Rate side by side */}
      {(showCapex || showTax) && (
        <div className="grid grid-cols-2 gap-2">
          {showCapex && (
            <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2" style={CHART_BG}>
              <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1 pl-1">
                Capex / Revenue
              </p>
              <ResponsiveContainer width="100%" height={160}>
                <LineChart data={capexData} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                  {forecastArea}
                  <XAxis dataKey="label" tick={TICK_STYLE} tickLine={false} axisLine={AXIS_LINE} />
                  <YAxis tickFormatter={fmtPctAxis} tick={TICK_STYLE} tickLine={false} axisLine={false} width={36} />
                  <Tooltip
                    {...TIP_STYLE}
                    formatter={(v, name) => [typeof v === "number" ? fmtPctTip(v) : "—", name]}
                  />
                  <Line type="monotone" dataKey="capex_pct" name="Capex %" stroke="#f472b6" strokeWidth={1.5} dot={false} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {showTax && (
            <div className="rounded border border-white/[0.07] px-2 pt-4 pb-2" style={CHART_BG}>
              <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-600 mb-1 pl-1">
                Effective Tax Rate
              </p>
              <ResponsiveContainer width="100%" height={160}>
                <LineChart data={taxData} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                  <XAxis dataKey="label" tick={TICK_STYLE} tickLine={false} axisLine={AXIS_LINE} />
                  <YAxis tickFormatter={fmtPctAxis} tick={TICK_STYLE} tickLine={false} axisLine={false} width={36} />
                  <Tooltip
                    {...TIP_STYLE}
                    formatter={(v, name) => [typeof v === "number" ? fmtPctTip(v) : "—", name]}
                  />
                  <Line type="monotone" dataKey="tax_pct" name="Eff. Tax Rate" stroke="#facc15" strokeWidth={1.5} dot={false} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
