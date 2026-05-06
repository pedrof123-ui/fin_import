"use client";

import type { FcffYear } from "@/lib/dcf-types";

function fmtUSD(n: number | null): { text: string; negative: boolean } {
  if (n === null || n === undefined) return { text: "—", negative: false };
  const abs = Math.abs(n);
  const neg = n < 0;
  const sign = neg ? "-" : "";
  let text: string;
  if (abs >= 1e9)      text = `${sign}$${(abs / 1e9).toFixed(2)}B`;
  else if (abs >= 1e6) text = `${sign}$${(abs / 1e6).toFixed(2)}M`;
  else                 text = `${sign}$${abs.toFixed(2)}`;
  return { text, negative: neg };
}

function fmtPct(n: number): string {
  return `${(n * 100).toFixed(2)}%`;
}

interface RowDef {
  label: string;
  getValue: (f: FcffYear) => number | null;
  tv?: number | null;
  isKey?: boolean;
  prefix?: "+" | "−" | "=";
  negativeIsGood?: boolean; // ΔNWC: positive means cash out (bad for FCF)
}

interface Props {
  fcffSeries: FcffYear[];
  taxRate: number;
  pvTerminalValue: number;
  terminalValue: number;
  terminalGrowthRate: number;
  wacc: number;
  enterpriseValue: number;
  netDebt: number;
  equityValue: number;
  dilutedShares: number;
  intrinsicValue: number;
}

export default function DcfFcffTable({
  fcffSeries,
  taxRate,
  pvTerminalValue,
  terminalValue,
  terminalGrowthRate,
  wacc,
  enterpriseValue,
  netDebt,
  equityValue,
  dilutedShares,
  intrinsicValue,
}: Props) {
  const n = fcffSeries.length;
  const tvDiscountFactor = n > 0 ? 1 / (1 + wacc) ** n : 1;

  const rows: RowDef[] = [
    { label: "Revenue",                    getValue: (f) => f.revenue,    isKey: true },
    { label: "EBIT",                        getValue: (f) => f.ebit,       isKey: true },
    { label: `NOPAT  ×(1−${(taxRate * 100).toFixed(1)}%)`, getValue: (f) => f.nopat },
    { label: "+ D&A",                       getValue: (f) => f.da,         prefix: "+" },
    { label: "− CapEx",                     getValue: (f) => f.capex,      prefix: "−" },
    { label: "− ΔNWC",                      getValue: (f) => f.delta_nwc,  prefix: "−" },
    { label: "= FCFF",                      getValue: (f) => f.fcff,       isKey: true, prefix: "=", tv: terminalValue },
    { label: "Discount Factor",             getValue: (f) => f.discount_factor, tv: tvDiscountFactor },
    { label: "PV",                          getValue: (f) => f.pv_fcff,    isKey: true, tv: pvTerminalValue },
  ];

  const pvFcffSum = fcffSeries.reduce((s, f) => s + f.pv_fcff, 0);
  const bgCard = "oklch(0.11 0.008 265)";
  const bgKey  = "oklch(0.14 0.03 275)";
  const bgSub  = "oklch(0.09 0.006 265)";

  return (
    <div className="mb-6">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">
        Enterprise Value Calculation — FCFF
      </p>
      <div className="overflow-x-auto rounded border border-white/[0.07]">
        <table className="w-full text-xs font-mono border-collapse">
          <thead>
            <tr className="border-b border-white/[0.07]" style={{ background: "oklch(0.10 0.008 265)" }}>
              <th className="sticky left-0 z-10 text-left px-4 py-2.5 font-normal text-[10px] uppercase tracking-[0.15em] text-zinc-500 whitespace-nowrap"
                  style={{ background: "oklch(0.10 0.008 265)" }}>
                Metric
              </th>
              {fcffSeries.map((f) => (
                <th key={f.year} className="text-right px-4 py-2.5 font-medium text-violet-400/70 min-w-[110px] whitespace-nowrap">
                  Y+{f.year}
                </th>
              ))}
              <th className="text-right px-4 py-2.5 font-medium text-violet-300/60 min-w-[110px] whitespace-nowrap">
                Terminal
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => {
              const isDiscountRow = row.label === "Discount Factor";
              const rowBg = row.isKey ? bgKey : ri % 2 === 0 ? bgSub : bgCard;

              return (
                <tr
                  key={row.label}
                  className="border-b border-white/[0.04] hover:brightness-125 transition-[filter] duration-75"
                  style={{ background: rowBg }}
                >
                  <td
                    className={`sticky left-0 z-10 px-4 py-2 whitespace-nowrap ${
                      row.isKey ? "text-zinc-100 font-medium" : "text-zinc-400"
                    }`}
                    style={{ background: rowBg }}
                  >
                    {row.isKey && (
                      <span className="inline-block w-1 h-1 rounded-full bg-violet-500 mr-2 mb-[1px]" />
                    )}
                    {!row.isKey && row.prefix && (
                      <span className="text-zinc-600 mr-1.5 pl-4">{row.prefix}</span>
                    )}
                    {row.isKey ? row.label : row.prefix ? row.label.replace(/^[+−=]\s*/, "") : row.label}
                  </td>

                  {fcffSeries.map((f) => {
                    const val = row.getValue(f);
                    if (isDiscountRow) {
                      return (
                        <td key={f.year} className="px-4 py-2 text-right tabular-nums text-zinc-500">
                          {val !== null ? val.toFixed(4) : "—"}
                        </td>
                      );
                    }
                    const { text, negative } = fmtUSD(val);
                    const colorCls = text === "—"
                      ? "text-zinc-700"
                      : negative
                      ? row.isKey ? "text-rose-300" : "text-rose-400/70"
                      : row.isKey ? "text-violet-300" : "text-zinc-300";
                    return (
                      <td key={f.year} className={`px-4 py-2 text-right tabular-nums ${colorCls}`}>
                        {text}
                      </td>
                    );
                  })}

                  {/* Terminal value column */}
                  <td className="px-4 py-2 text-right tabular-nums">
                    {row.tv !== undefined ? (
                      isDiscountRow ? (
                        <span className="text-zinc-500">{(row.tv as number).toFixed(4)}</span>
                      ) : (() => {
                        const { text, negative } = fmtUSD(row.tv as number);
                        return (
                          <span className={
                            text === "—" ? "text-zinc-700"
                            : negative ? "text-rose-300"
                            : "text-violet-300 font-medium"
                          }>{text}</span>
                        );
                      })()
                    ) : (
                      <span className="text-zinc-700">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* EV bridge */}
      <div
        className="mt-3 rounded border border-white/[0.07] p-4"
        style={{ background: bgCard }}
      >
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-8 gap-y-2 text-xs font-mono">
          <div className="text-zinc-500">∑ PV FCFFs</div>
          <div className="text-zinc-300 text-right sm:text-left">{fmtUSD(pvFcffSum).text}</div>
          <div className="text-zinc-500">+ PV Terminal</div>
          <div className="text-zinc-300 text-right sm:text-left">{fmtUSD(pvTerminalValue).text}</div>
          <div className="text-zinc-400 font-medium">= Enterprise Value</div>
          <div className="text-violet-300 font-semibold text-right sm:text-left">{fmtUSD(enterpriseValue).text}</div>
          <div className="text-zinc-500">− Net Debt</div>
          <div className="text-zinc-300 text-right sm:text-left">{fmtUSD(netDebt).text}</div>
          <div className="text-zinc-400 font-medium">= Equity Value</div>
          <div className="text-violet-300 font-semibold text-right sm:text-left">{fmtUSD(equityValue).text}</div>
          <div className="text-zinc-500">÷ Diluted Shares</div>
          <div className="text-zinc-300 text-right sm:text-left">
            {dilutedShares >= 1e9
              ? `${(dilutedShares / 1e9).toFixed(3)}B`
              : `${(dilutedShares / 1e6).toFixed(1)}M`}
          </div>
          <div className="text-zinc-400 font-medium">= Intrinsic Value / Share</div>
          <div className="text-violet-200 font-semibold text-right sm:text-left">${intrinsicValue.toFixed(2)}</div>
          <div className="text-zinc-600 text-[10px] col-span-2 sm:col-span-4 pt-1">
            FCFF = NOPAT + D&amp;A − CapEx − ΔNWC &nbsp;·&nbsp; NOPAT = EBIT × (1 − {fmtPct(taxRate)})
          </div>
        </div>
      </div>
    </div>
  );
}
