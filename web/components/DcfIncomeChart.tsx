"use client";

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ReferenceArea, ResponsiveContainer,
} from "recharts";
import type { HistoricalRow } from "@/lib/dcf-types";

interface Props {
  historical: HistoricalRow[];  // oldest-first (already reversed in DcfViewer)
  proforma: HistoricalRow[];    // Y1-Y10
}

function fmtBnAxis(v: number) {
  return `$${(v / 1e9).toFixed(0)}B`;
}

function fmtBnTip(v: number) {
  return `$${(v / 1e9).toFixed(1)}B`;
}

// Shorten "FY 2024" → "2024" for a cleaner X-axis
function shortLabel(label: string) {
  return label.replace(/^FY\s*/, "");
}

export default function DcfIncomeChart({ historical, proforma }: Props) {
  const data = [
    ...historical.slice(-5).map((h) => ({
      label: shortLabel(h.period_label),
      revenue:      h.revenue,
      gross_profit: h.gross_profit,
      ebit:         h.operating_income,
      net_income:   h.net_income,
      isProforma:   false,
    })),
    ...proforma.map((p) => ({
      label: shortLabel(p.period_label),
      revenue:      p.revenue,
      gross_profit: p.gross_profit,
      ebit:         p.operating_income,
      net_income:   p.net_income,
      isProforma:   true,
    })),
  ];

  const firstProforma = proforma[0] ? shortLabel(proforma[0].period_label) : undefined;
  const lastProforma  = proforma[proforma.length - 1] ? shortLabel(proforma[proforma.length - 1].period_label) : undefined;

  return (
    <div className="mb-6">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">
        Income Statement
      </p>
      <div
        className="rounded border border-white/[0.07] px-2 pt-4 pb-2"
        style={{ background: "oklch(0.09 0.006 265)" }}
      >
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data} margin={{ top: 4, right: 16, left: 16, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />

            {firstProforma && lastProforma && (
              <ReferenceArea
                x1={firstProforma}
                x2={lastProforma}
                fill="rgba(139,92,246,0.06)"
                label={{
                  value: "Forecast",
                  position: "insideTopLeft",
                  fill: "rgba(139,92,246,0.4)",
                  fontSize: 9,
                  fontFamily: "monospace",
                }}
              />
            )}

            <XAxis
              dataKey="label"
              tick={{ fill: "#71717a", fontSize: 10, fontFamily: "monospace" }}
              tickLine={false}
              axisLine={{ stroke: "rgba(255,255,255,0.07)" }}
            />
            <YAxis
              tickFormatter={fmtBnAxis}
              tick={{ fill: "#71717a", fontSize: 10, fontFamily: "monospace" }}
              tickLine={false}
              axisLine={false}
              width={52}
            />
            <Tooltip
              contentStyle={{
                background: "#18181b",
                border: "1px solid rgba(255,255,255,0.1)",
                fontFamily: "monospace",
                fontSize: 11,
                borderRadius: 4,
              }}
              labelStyle={{ color: "#a1a1aa", marginBottom: 4 }}
              formatter={(value, name) => {
                const v = typeof value === "number" ? value : null;
                return [v != null ? fmtBnTip(v) : "—", name];
              }}
            />
            <Legend
              wrapperStyle={{ fontFamily: "monospace", fontSize: 10, color: "#71717a", paddingTop: 8 }}
            />

            <Line type="monotone" dataKey="revenue"      name="Revenue"      stroke="#818cf8" strokeWidth={2}   dot={false} connectNulls />
            <Line type="monotone" dataKey="gross_profit" name="Gross Profit"  stroke="#34d399" strokeWidth={1.5} dot={false} connectNulls />
            <Line type="monotone" dataKey="ebit"         name="EBIT"          stroke="#fb923c" strokeWidth={1.5} dot={false} connectNulls />
            <Line type="monotone" dataKey="net_income"   name="Net Income"    stroke="#a78bfa" strokeWidth={1.5} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
