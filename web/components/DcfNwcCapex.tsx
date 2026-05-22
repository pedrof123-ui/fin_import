"use client";

import type { NwcAssumptions, FcffYear, YearForecast } from "@/lib/dcf-types";

function fmtUSD(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  return `${sign}$${abs.toFixed(2)}`;
}

const inputCls =
  "bg-transparent font-mono text-xs text-zinc-200 outline-none border-b border-white/[0.07] " +
  "focus:border-violet-500/50 transition-colors pb-0.5 w-16 text-right tabular-nums";

interface Props {
  nwcAssumptions: NwcAssumptions;
  fcffSeries: FcffYear[];
  yearForecasts: YearForecast[];
  dso: string;
  dpo: string;
  dio: string;
  onDsoChange: (v: string) => void;
  onDpoChange: (v: string) => void;
  onDioChange: (v: string) => void;
  onCommit?: () => void;
}

export default function DcfNwcCapex({
  fcffSeries,
  yearForecasts,
  dso, dpo, dio,
  onDsoChange, onDpoChange, onDioChange,
  onCommit,
}: Props) {
  const years = fcffSeries.map((f) => f.year);

  return (
    <div className="mb-6">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">
        NWC &amp; CapEx
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Working Capital Assumptions */}
        <div
          className="rounded border border-white/[0.07] p-5"
          style={{ background: "oklch(0.11 0.008 265)" }}
        >
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-4">
            Working Capital Days
          </p>
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-xs font-mono">
            <div className="text-zinc-500">DSO (days)</div>
            <div className="text-right">
              <input className={inputCls} value={dso} onChange={(e) => onDsoChange(e.target.value)} onBlur={() => onCommit?.()} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
            </div>
            <div className="text-zinc-500">DPO (days)</div>
            <div className="text-right">
              <input className={inputCls} value={dpo} onChange={(e) => onDpoChange(e.target.value)} onBlur={() => onCommit?.()} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
            </div>
            <div className="text-zinc-500">DIO (days)</div>
            <div className="text-right">
              <input className={inputCls} value={dio} onChange={(e) => onDioChange(e.target.value)} onBlur={() => onCommit?.()} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
            </div>
          </div>
          <p className="font-mono text-[10px] text-zinc-700 mt-4">
            NWC = Receivables + Inventory − Payables
          </p>
        </div>

        {/* Projected NWC & CapEx per year */}
        <div
          className="rounded border border-white/[0.07] p-5"
          style={{ background: "oklch(0.11 0.008 265)" }}
        >
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-4">
            Projected (model)
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono border-collapse">
              <thead>
                <tr className="border-b border-white/[0.07]">
                  <th className="text-left py-1.5 font-normal text-[10px] text-zinc-600">Metric</th>
                  {years.map((y) => (
                    <th key={y} className="text-right py-1.5 font-medium text-violet-400/70 min-w-[80px]">
                      Y+{y}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-white/[0.04]">
                  <td className="py-1.5 text-zinc-500">ΔNWC</td>
                  {fcffSeries.map((f) => (
                    <td
                      key={f.year}
                      className={`py-1.5 text-right tabular-nums ${
                        f.delta_nwc > 0 ? "text-rose-400/70" : "text-emerald-400/70"
                      }`}
                    >
                      {fmtUSD(f.delta_nwc)}
                    </td>
                  ))}
                </tr>
                <tr className="border-b border-white/[0.04]">
                  <td className="py-1.5 text-zinc-500">CapEx</td>
                  {fcffSeries.map((f) => (
                    <td key={f.year} className="py-1.5 text-right tabular-nums text-zinc-400">
                      {fmtUSD(f.capex)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="py-1.5 text-zinc-500">CapEx %</td>
                  {yearForecasts.map((yf) => (
                    <td key={yf.year} className="py-1.5 text-right tabular-nums text-zinc-500">
                      {(yf.capex_pct_revenue * 100).toFixed(1)}%
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
