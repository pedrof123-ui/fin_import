"use client";

import { Fragment } from "react";
import type { EarningsEstimate } from "@/lib/dcf-types";

interface Props {
  estimates: EarningsEstimate[];
}

function fmtRev(val: number | null): string {
  if (val === null || val === undefined) return "—";
  const abs = Math.abs(val);
  if (abs >= 1e9) return `$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(abs / 1e6).toFixed(2)}M`;
  return `$${abs.toFixed(0)}`;
}

function fmtEps(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return `$${val.toFixed(2)}`;
}

function fmtCount(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return String(Math.round(val));
}

function periodLabel(e: EarningsEstimate): string {
  const d = new Date(e.date + "T00:00:00");
  const yr = d.getFullYear();
  if (e.horizon === "fiscal year") return `FY${yr}`;
  // Derive quarter label from month
  const mo = d.getMonth() + 1; // 1-12
  const q = Math.ceil(mo / 3);
  return `Q${q} FY${yr}`;
}

export default function EarningsEstimates({ estimates }: Props) {
  if (!estimates || estimates.length === 0) return null;

  const quarterly = estimates
    .filter((e) => e.horizon === "fiscal quarter")
    .sort((a, b) => a.date.localeCompare(b.date));

  const annual = estimates
    .filter((e) => e.horizon === "fiscal year")
    .sort((a, b) => a.date.localeCompare(b.date));

  const renderTable = (cols: EarningsEstimate[], title: string) => {
    if (cols.length === 0) return null;
    return (
      <div className="mb-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-zinc-500 mb-2">
          {title}
        </p>
        <div className="overflow-x-auto rounded border border-white/[0.07]">
          <table className="w-full text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-white/[0.07]">
                <th
                  className="sticky left-0 z-10 text-left px-4 py-2.5 font-normal text-[10px] uppercase tracking-[0.15em] text-zinc-500 whitespace-nowrap"
                  style={{ background: "oklch(0.10 0.008 265)" }}
                >
                  Metric
                </th>
                {cols.map((e) => (
                  <th
                    key={e.date}
                    className="text-right px-4 py-2.5 font-medium min-w-[110px] whitespace-nowrap text-sky-400/80"
                  >
                    {periodLabel(e)}
                    <div className="text-[9px] font-normal text-zinc-600 mt-0.5">{e.date}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                {
                  label: "Revenue Est.",
                  isKey: true,
                  render: (e: EarningsEstimate) => fmtRev(e.revenue_estimate_avg),
                },
                {
                  label: "Revenue Range",
                  isKey: false,
                  render: (e: EarningsEstimate) =>
                    e.revenue_estimate_low != null && e.revenue_estimate_high != null
                      ? `${fmtRev(e.revenue_estimate_low)} – ${fmtRev(e.revenue_estimate_high)}`
                      : "—",
                },
                {
                  label: "Revenue Analysts",
                  isKey: false,
                  render: (e: EarningsEstimate) => fmtCount(e.revenue_analyst_count),
                },
                {
                  label: "EPS Est.",
                  isKey: true,
                  render: (e: EarningsEstimate) => fmtEps(e.eps_estimate_avg),
                },
                {
                  label: "EPS Range",
                  isKey: false,
                  render: (e: EarningsEstimate) =>
                    e.eps_estimate_low != null && e.eps_estimate_high != null
                      ? `${fmtEps(e.eps_estimate_low)} – ${fmtEps(e.eps_estimate_high)}`
                      : "—",
                },
                {
                  label: "EPS Analysts",
                  isKey: false,
                  render: (e: EarningsEstimate) => fmtCount(e.eps_analyst_count),
                },
              ].map(({ label, isKey, render }, rowIdx) => {
                const bg = isKey
                  ? "oklch(0.14 0.03 275)"
                  : rowIdx % 2 === 1
                  ? "oklch(0.105 0.008 265)"
                  : "oklch(0.09 0.006 265)";
                return (
                  <tr
                    key={label}
                    className="border-b border-white/[0.04] hover:brightness-125 transition-[filter] duration-75"
                    style={{ background: bg }}
                  >
                    <td
                      className={`sticky left-0 z-10 px-4 py-2 whitespace-nowrap ${
                        isKey ? "text-zinc-100 font-medium" : "text-zinc-400"
                      }`}
                      style={{ background: bg }}
                    >
                      {isKey && (
                        <span className="inline-block w-1 h-1 rounded-full bg-sky-500 mr-2 mb-[1px]" />
                      )}
                      {label}
                    </td>
                    {cols.map((e) => (
                      <td
                        key={e.date}
                        className={`px-4 py-2 text-right tabular-nums ${
                          isKey ? "text-sky-300" : "text-zinc-500"
                        }`}
                      >
                        {render(e)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  return (
    <div className="mb-6">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">
        Analyst Estimates
      </p>
      {renderTable(quarterly, "Quarterly")}
      {renderTable(annual, "Annual")}
    </div>
  );
}
