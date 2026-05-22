"use client";

import { Fragment } from "react";
import type { HistoricalRow } from "@/lib/dcf-types";
import { focusStrip } from "@/lib/formatField";

type SubRowKind =
  | "revGrowth"
  | "cogsMargin"
  | "grossMargin"
  | "sgaPct"
  | "rdPct"
  | "opMargin"
  | "ebitdaMargin"
  | "effectiveTaxRate"
  | "netIncomeMargin"
  | "capexPct";

interface RowDef {
  key: keyof HistoricalRow;
  label: string;
  isKey?: boolean;
  subRows?: SubRowKind[];
}

const ROWS: RowDef[] = [
  { key: "revenue",                   label: "Revenue",            isKey: true, subRows: ["revGrowth"]                    },
  { key: "gross_profit",              label: "Gross Profit",       isKey: true, subRows: ["cogsMargin", "grossMargin"]    },
  { key: "operating_income",          label: "EBIT",               isKey: true, subRows: ["sgaPct", "rdPct", "opMargin"] },
  { key: "ebitda",                    label: "EBITDA",             isKey: true, subRows: ["ebitdaMargin"]                },
  { key: "income_tax_expense",        label: "Income Tax",                      subRows: ["effectiveTaxRate"]            },
  { key: "net_income",                label: "Net Income",         isKey: true, subRows: ["netIncomeMargin"]             },
  { key: "depreciation_amortization", label: "D&A" },
  { key: "capital_expenditures",      label: "CapEx",                           subRows: ["capexPct"]                   },
  { key: "total_assets",              label: "Total Assets" },
  { key: "total_debt",                label: "Total Debt" },
  { key: "cash_and_equivalents",      label: "Cash & Equivalents" },
  { key: "diluted_eps",               label: "Diluted EPS" },
];

const QUARTERLY_EST_HIDDEN: Set<keyof HistoricalRow> = new Set([
  "total_assets", "total_debt", "cash_and_equivalents",
]);

const SUB_LABEL: Record<SubRowKind, string> = {
  revGrowth:        "Rev Growth %",
  cogsMargin:       "COGS %",
  grossMargin:      "Gross Margin %",
  sgaPct:           "SG&A %",
  rdPct:            "R&D %",
  opMargin:         "EBIT Margin %",
  ebitdaMargin:     "EBITDA Margin %",
  effectiveTaxRate: "Effective Tax Rate",
  netIncomeMargin:  "Net Income Margin %",
  capexPct:         "CapEx % Rev",
};

const DERIVED_SUB_ROWS = new Set<SubRowKind>(["grossMargin", "opMargin", "ebitdaMargin", "effectiveTaxRate", "netIncomeMargin"]);

function computeActualSubRow(kind: SubRowKind, col: HistoricalRow, prevCol: HistoricalRow | null): number | null {
  const rev = col.revenue;
  if (!rev) return null;
  switch (kind) {
    case "revGrowth":
      return prevCol?.revenue ? col.revenue! / prevCol.revenue! - 1 : null;
    case "cogsMargin":
      if (col.cost_of_revenue != null) return col.cost_of_revenue / rev;
      if (col.gross_profit != null) return (rev - col.gross_profit) / rev;
      return null;
    case "grossMargin":      return col.gross_profit != null ? col.gross_profit / rev : null;
    case "sgaPct":           return col.selling_general_admin != null ? col.selling_general_admin / rev : null;
    case "rdPct":            return col.research_development != null ? col.research_development / rev : null;
    case "opMargin":         return col.operating_income != null ? col.operating_income / rev : null;
    case "ebitdaMargin":     return col.ebitda != null ? col.ebitda / rev : null;
    case "effectiveTaxRate": return col.pretax_income && col.income_tax_expense != null
                               ? col.income_tax_expense / col.pretax_income
                               : null;
    case "netIncomeMargin":  return col.net_income != null ? col.net_income / rev : null;
    case "capexPct":         return col.capital_expenditures != null ? Math.abs(col.capital_expenditures) / rev : null;
  }
}

function computeEstSubRow(kind: SubRowKind, col: HistoricalRow, prevCol: HistoricalRow | null): number | null {
  const rev = col.revenue;
  if (!rev) return null;
  switch (kind) {
    case "revGrowth":        return prevCol?.revenue ? col.revenue! / prevCol.revenue! - 1 : null;
    case "grossMargin":      return col.gross_profit != null ? col.gross_profit / rev : null;
    case "opMargin":         return col.operating_income != null ? col.operating_income / rev : null;
    case "ebitdaMargin":     return col.ebitda != null ? col.ebitda / rev : null;
    case "effectiveTaxRate": return col.pretax_income && col.income_tax_expense != null
                               ? col.income_tax_expense / col.pretax_income
                               : null;
    case "netIncomeMargin":  return col.net_income != null ? col.net_income / rev : null;
    default:                 return null;
  }
}

function fmtNum(val: number | null): { text: string; negative: boolean } {
  if (val === null || val === undefined) return { text: "—", negative: false };
  const abs = Math.abs(val);
  const neg = val < 0;
  const sign = neg ? "-" : "";
  let text: string;
  if (abs >= 1e9)      text = `${sign}$${(abs / 1e9).toFixed(2)}B`;
  else if (abs >= 1e6) text = `${sign}$${(abs / 1e6).toFixed(2)}M`;
  else if (abs >= 1e3) text = `${sign}$${(abs / 1e3).toFixed(1)}K`;
  else                 text = `${sign}$${abs.toFixed(2)}`;
  return { text, negative: neg };
}

function fmtRatio(val: number | null): { text: string; negative: boolean } {
  if (val === null) return { text: "—", negative: false };
  return { text: `${(val * 100).toFixed(1)}%`, negative: val < 0 };
}

interface Props {
  y1Quarters: HistoricalRow[];
  lastHistorical: HistoricalRow | null;
  quarterRevenues: Record<number, string>;
  onQuarterRevenueChange: (qNum: number, value: string) => void;
  onCommit?: () => void;
}

export default function DcfQuarterly({
  y1Quarters,
  lastHistorical,
  quarterRevenues,
  onQuarterRevenueChange,
  onCommit,
}: Props) {
  if (!y1Quarters.length) return null;

  const qInputCls =
    "w-full bg-transparent text-right tabular-nums text-[11px] text-amber-300 outline-none " +
    "border-b border-transparent focus:border-amber-500/50 transition-colors px-1";

  const nActuals = y1Quarters.filter((q) => q.is_actual).length;
  const hasEstimates = nActuals < y1Quarters.length;

  return (
    <div className="mb-6">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">
        Quarterly Detail
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
              {y1Quarters.map((col, qi) => (
                <Fragment key={col.period_label}>
                  {qi === nActuals && nActuals > 0 && hasEstimates && (
                    <th className="w-px bg-violet-900/20" />
                  )}
                  <th
                    className={`text-right px-4 py-2.5 font-medium min-w-[100px] whitespace-nowrap ${
                      col.is_actual ? "text-zinc-400" : "text-amber-500/70"
                    }`}
                  >
                    <div className="flex items-center justify-end gap-1">
                      {col.period_label}
                      {!col.is_actual && (
                        <span className="text-[8px] text-amber-600/70 font-normal">E</span>
                      )}
                    </div>
                    {col.period_end_date && (
                      <div className={`text-[9px] font-normal mt-0.5 ${col.is_actual ? "text-zinc-600" : "text-amber-800/60"}`}>
                        {col.period_end_date}
                      </div>
                    )}
                  </th>
                </Fragment>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map(({ key, label, isKey, subRows }, rowIdx) => {
              const rowBg = isKey ? "oklch(0.14 0.03 275)" : rowIdx % 2 === 1 ? "oklch(0.105 0.008 265)" : "oklch(0.09 0.006 265)";
              const subBg = isKey ? "oklch(0.115 0.022 275)" : rowIdx % 2 === 1 ? "oklch(0.095 0.007 265)" : "oklch(0.082 0.005 265)";

              return (
                <Fragment key={key}>
                  <tr
                    className="border-b border-white/[0.04] hover:brightness-125 transition-[filter] duration-75"
                    style={{ background: rowBg }}
                  >
                    <td
                      className={`sticky left-0 z-10 px-4 py-2 whitespace-nowrap ${isKey ? "text-zinc-100 font-medium" : "text-zinc-400"}`}
                      style={{ background: rowBg }}
                    >
                      {isKey && <span className="inline-block w-1 h-1 rounded-full bg-violet-500 mr-2 mb-[1px]" />}
                      {label}
                    </td>
                    {y1Quarters.map((col, qi) => {
                      const isHidden = !col.is_actual && QUARTERLY_EST_HIDDEN.has(key);
                      const { text, negative } = isHidden
                        ? { text: "—", negative: false }
                        : fmtNum(col[key] as number | null);
                      return (
                        <Fragment key={col.period_label}>
                          {qi === nActuals && nActuals > 0 && hasEstimates && (
                            <td className="w-px bg-violet-900/20 p-0" />
                          )}
                          <td className={`px-4 py-2 text-right tabular-nums ${
                            text === "—" ? "text-zinc-700"
                            : negative
                              ? col.is_actual
                                ? isKey ? "text-rose-300" : "text-rose-400/80"
                                : "text-rose-400/60"
                              : col.is_actual
                                ? isKey ? "text-zinc-100" : "text-zinc-300"
                                : isKey ? "text-amber-300" : "text-amber-400/70"
                          }`}>
                            {text}
                          </td>
                        </Fragment>
                      );
                    })}
                  </tr>

                  {subRows?.map((kind) => (
                    <tr key={kind} className="border-b border-white/[0.03]" style={{ background: subBg }}>
                      <td
                        className="sticky left-0 z-10 px-4 py-1 text-zinc-600 text-[10px] whitespace-nowrap pl-8"
                        style={{ background: subBg }}
                      >
                        {SUB_LABEL[kind]}
                      </td>
                      {y1Quarters.map((col, qi) => {
                        const prevCol = qi === 0 ? lastHistorical : y1Quarters[qi - 1];
                        const isDerived = DERIVED_SUB_ROWS.has(kind);

                        let cell: React.ReactNode;
                        if (col.is_actual) {
                          const { text, negative } = fmtRatio(computeActualSubRow(kind, col, prevCol));
                          cell = (
                            <td className={`px-4 py-1 text-right tabular-nums text-[10px] ${
                              text === "—" ? "text-zinc-700"
                              : negative ? "text-rose-500/60"
                              : "text-zinc-500"
                            }`}>
                              {text}
                            </td>
                          );
                        } else if (kind === "revGrowth") {
                          const qNum = qi + 1;
                          const strVal = quarterRevenues[qNum] ?? ((col.revenue ?? 0) / 1e9).toFixed(2);
                          const displayVal = strVal.endsWith("B") ? strVal : strVal + "B";
                          cell = (
                            <td className="px-3 py-0.5">
                              <input
                                className={qInputCls}
                                value={displayVal}
                                placeholder="$B"
                                onFocus={(e) =>
                                  onQuarterRevenueChange(qNum, focusStrip(e.target.value).replace(/B$/i, "").trim())
                                }
                                onChange={(e) => onQuarterRevenueChange(qNum, e.target.value)}
                                onBlur={(e) => {
                                  const n = parseFloat(e.target.value.replace(/[^0-9.-]/g, ""));
                                  onQuarterRevenueChange(qNum, isNaN(n) ? strVal : n.toFixed(2) + "B");
                                  onCommit?.();
                                }}
                                onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                              />
                            </td>
                          );
                        } else {
                          const { text, negative } = fmtRatio(
                            isDerived ? computeEstSubRow(kind, col, prevCol) : null,
                          );
                          cell = (
                            <td className={`px-4 py-1 text-right tabular-nums text-[10px] ${
                              text === "—" ? "text-zinc-700"
                              : negative ? "text-rose-400/50"
                              : "text-amber-500/50"
                            }`}>
                              {text}
                            </td>
                          );
                        }

                        return (
                          <Fragment key={col.period_label}>
                            {qi === nActuals && nActuals > 0 && hasEstimates && (
                              <td className="w-px bg-violet-900/20 p-0" />
                            )}
                            {cell}
                          </Fragment>
                        );
                      })}
                    </tr>
                  ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
