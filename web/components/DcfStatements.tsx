"use client";

import { Fragment } from "react";
import type { HistoricalRow, YearRowState } from "@/lib/dcf-types";
import { useGridArrowNav } from "@/lib/useArrowNav";
import { blurFormat, focusStrip } from "@/lib/formatField";

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

const EDITABLE_FIELD: Partial<Record<SubRowKind, keyof YearRowState>> = {
  revGrowth:  "revenue_growth",
  cogsMargin: "cogs_pct",
  sgaPct:     "sga_pct",
  rdPct:      "rd_pct",
  capexPct:   "capex_pct_revenue",
};

const GRID_ROW_INDEX: Partial<Record<SubRowKind, number>> = {
  revGrowth:  0,
  cogsMargin: 1,
  sgaPct:     2,
  rdPct:      3,
  capexPct:   4,
};
const GRID_ROWS = 5;

const DERIVED_SUB_ROWS = new Set<SubRowKind>(["grossMargin", "opMargin", "ebitdaMargin", "effectiveTaxRate", "netIncomeMargin"]);

function computeHistSubRow(kind: SubRowKind, col: HistoricalRow, prevCol: HistoricalRow | null): number | null {
  const rev = col.revenue;
  if (!rev) return null;
  switch (kind) {
    case "revGrowth":
      return prevCol?.revenue ? col.revenue! / prevCol.revenue! - 1 : null;
    case "cogsMargin":
      if (col.cost_of_revenue != null) return col.cost_of_revenue / rev;
      if (col.gross_profit != null) return (rev - col.gross_profit) / rev;
      return null;
    case "grossMargin":
      return col.gross_profit != null ? col.gross_profit / rev : null;
    case "sgaPct":
      return col.selling_general_admin != null ? col.selling_general_admin / rev : null;
    case "rdPct":
      return col.research_development != null ? col.research_development / rev : null;
    case "opMargin":
      return col.operating_income != null ? col.operating_income / rev : null;
    case "ebitdaMargin":
      return col.ebitda != null ? col.ebitda / rev : null;
    case "effectiveTaxRate":
      return col.pretax_income && col.income_tax_expense != null
        ? col.income_tax_expense / col.pretax_income
        : null;
    case "netIncomeMargin":
      return col.net_income != null ? col.net_income / rev : null;
    case "capexPct":
      return col.capital_expenditures != null ? Math.abs(col.capital_expenditures) / rev : null;
  }
}

function computeProformaSubRow(kind: SubRowKind, col: HistoricalRow, prevCol: HistoricalRow | null): number | null {
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
  historical: HistoricalRow[];
  proforma: HistoricalRow[];
  yearRows: Record<number, YearRowState>;
  onYearRowChange: (year: number, field: keyof YearRowState, value: string) => void;
}

export default function DcfStatements({
  historical,
  proforma,
  yearRows,
  onYearRowChange,
}: Props) {
  const inputCls =
    "w-full bg-transparent text-right tabular-nums text-[11px] text-violet-300 outline-none " +
    "border-b border-transparent focus:border-violet-500/50 transition-colors px-1";

  const lastHistorical = historical[historical.length - 1] ?? null;
  const GRID_COLS = proforma.length;

  const { refs: gridRefs, handleKeyDown: gridKeyDown } = useGridArrowNav(GRID_ROWS, GRID_COLS);

  return (
    <div className="mb-6">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">
        Historical &amp; Proforma
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

              {historical.map((col) => (
                <th key={col.period_label} className="text-right px-4 py-2.5 font-medium text-zinc-400 min-w-[110px] whitespace-nowrap">
                  <div>{col.period_label}</div>
                  {col.period_end_date && (
                    <div className="text-[9px] font-normal text-zinc-600 mt-0.5">{col.period_end_date}</div>
                  )}
                </th>
              ))}

              <th className="w-px bg-violet-900/20" />

              {proforma.map((col) => (
                <th key={col.period_label} className="text-right px-4 py-2.5 font-medium text-violet-400/70 min-w-[110px] whitespace-nowrap">
                  {col.period_label}
                </th>
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

                    {historical.map((col) => {
                      const { text, negative } = fmtNum(col[key] as number | null);
                      return (
                        <td key={col.period_label} className={`px-4 py-2 text-right tabular-nums ${
                          text === "—" ? "text-zinc-700"
                          : negative ? isKey ? "text-rose-300" : "text-rose-400/80"
                          : isKey ? "text-zinc-100" : "text-zinc-300"
                        }`}>
                          {text}
                        </td>
                      );
                    })}

                    <td className="w-px bg-violet-900/20 p-0" />

                    {proforma.map((col) => {
                      const { text, negative } = fmtNum(col[key] as number | null);
                      return (
                        <td key={col.period_label} className={`px-4 py-2 text-right tabular-nums ${
                          text === "—" ? "text-zinc-700"
                          : negative ? "text-rose-400/60"
                          : isKey ? "text-violet-300" : "text-violet-400/70"
                        }`}>
                          {text}
                        </td>
                      );
                    })}
                  </tr>

                  {subRows?.map((kind) => {
                    const editField = EDITABLE_FIELD[kind];
                    const isDerived = DERIVED_SUB_ROWS.has(kind);
                    const gridRow = GRID_ROW_INDEX[kind];

                    return (
                      <tr key={kind} className="border-b border-white/[0.03]" style={{ background: subBg }}>
                        <td
                          className="sticky left-0 z-10 px-4 py-1 text-zinc-600 text-[10px] whitespace-nowrap pl-8"
                          style={{ background: subBg }}
                        >
                          {SUB_LABEL[kind]}
                        </td>

                        {historical.map((col, ci) => {
                          const { text, negative } = fmtRatio(
                            computeHistSubRow(kind, col, ci > 0 ? historical[ci - 1] : null),
                          );
                          return (
                            <td key={col.period_label} className={`px-4 py-1 text-right tabular-nums text-[10px] ${
                              text === "—" ? "text-zinc-700"
                              : negative ? "text-rose-500/60"
                              : "text-zinc-500"
                            }`}>
                              {text}
                            </td>
                          );
                        })}

                        <td className="w-px bg-violet-900/20 p-0" />

                        {proforma.map((col, pi) => {
                          const prevProforma = pi === 0 ? lastHistorical : proforma[pi - 1];

                          if (isDerived) {
                            const { text, negative } = fmtRatio(computeProformaSubRow(kind, col, prevProforma));
                            return (
                              <td key={col.period_label} className={`px-4 py-1 text-right tabular-nums text-[10px] ${
                                text === "—" ? "text-zinc-700"
                                : negative ? "text-rose-400/50"
                                : "text-violet-400/50"
                              }`}>
                                {text}
                              </td>
                            );
                          }

                          const fieldVal = editField ? (yearRows[pi + 1]?.[editField] ?? "") : "";
                          return (
                            <td key={col.period_label} className="px-3 py-0.5">
                              <input
                                className={inputCls}
                                value={fieldVal}
                                placeholder={kind === "rdPct" ? "—" : undefined}
                                ref={(el) => {
                                  if (gridRow !== undefined) gridRefs.current[gridRow][pi] = el;
                                }}
                                onChange={(e) => editField && onYearRowChange(pi + 1, editField, e.target.value)}
                                onFocus={(e) => editField && onYearRowChange(pi + 1, editField, focusStrip(e.target.value))}
                                onBlur={(e) => editField && onYearRowChange(pi + 1, editField, blurFormat(e.target.value, "pct"))}
                                onKeyDown={(e) => {
                                  if (gridRow !== undefined) gridKeyDown(gridRow, pi, e);
                                }}
                              />
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
