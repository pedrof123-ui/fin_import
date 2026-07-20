"use client";

import { Fragment } from "react";
import type { HistoricalRow, YearRowState } from "@/lib/dcf-types";
import { useGridArrowNav } from "@/lib/useArrowNav";
import { blurFormat, focusStrip } from "@/lib/formatField";

// Sub-row kinds — derived ones are read-only; "sga"/"rd" are editable $; "revGrowth"/"grossMargin"/"capexPct"/"ebitMargin" are editable %.
type SubRowKind =
  | "revGrowth"        // editable % (revenue growth)
  | "grossMargin"      // editable % (gross margin → sets cogs_pct)
  | "sga"              // editable $ (SG&A absolute) — standard mode only
  | "rd"               // editable $ (R&D absolute) — standard mode only
  | "ebitMargin"       // editable % (EBIT margin direct) — AV mode only
  | "opMargin"         // derived %
  | "ebitdaMargin"     // derived %
  | "effectiveTaxRate" // derived %
  | "netIncomeMargin"  // derived %
  | "capexPct"         // editable % (capex % of revenue)
  | "daRev";           // derived % (D&A % of revenue)

interface RowDef {
  key: keyof HistoricalRow;
  label: string;
  isKey?: boolean;
  subRows?: SubRowKind[];
  // When set, proforma cells for this row become editable dollar inputs.
  editableProformaField?: keyof YearRowState;
}

// Standard mode rows (existing SEC DCF)
const ROWS_STANDARD: RowDef[] = [
  { key: "revenue",                   label: "Revenue",      isKey: true,  subRows: ["revGrowth"]              },
  { key: "cost_of_revenue",           label: "COGS",                       subRows: ["grossMargin"]            },
  { key: "gross_profit",              label: "Gross Profit", isKey: true                                       },
  { key: "operating_income",          label: "EBIT",         isKey: true,  subRows: ["sga", "rd", "opMargin"]  },
  { key: "ebitda",                    label: "EBITDA",       isKey: true,  subRows: ["ebitdaMargin"]           },
  { key: "income_tax_expense",        label: "Income Tax",                 subRows: ["effectiveTaxRate"]       },
  { key: "noncontrolling_interest",   label: "Noncontrolling Interest"                                      },
  { key: "net_income",                label: "Net Income",   isKey: true,  subRows: ["netIncomeMargin"]        },
  { key: "depreciation_amortization", label: "D&A",          editableProformaField: "da", subRows: ["daRev"]  },
  { key: "capital_expenditures",      label: "CapEx",                      subRows: ["capexPct"]               },
  { key: "total_assets",              label: "Total Assets" },
  { key: "total_debt",                label: "Total Debt" },
  { key: "cash_and_equivalents",      label: "Cash & Equivalents" },
  { key: "diluted_eps",               label: "Diluted EPS" },
];

// AV mode rows — EBIT margin replaces SGA/R&D editable inputs
const ROWS_AV: RowDef[] = [
  { key: "revenue",                   label: "Revenue",      isKey: true,  subRows: ["revGrowth"]          },
  { key: "cost_of_revenue",           label: "COGS",                       subRows: ["grossMargin"]        },
  { key: "gross_profit",              label: "Gross Profit", isKey: true                                   },
  { key: "operating_income",          label: "EBIT",         isKey: true,  subRows: ["ebitMargin"]         },
  { key: "ebitda",                    label: "EBITDA",       isKey: true,  subRows: ["ebitdaMargin"]       },
  { key: "income_tax_expense",        label: "Income Tax",                 subRows: ["effectiveTaxRate"]   },
  { key: "noncontrolling_interest",   label: "Noncontrolling Interest"                                     },
  { key: "net_income",                label: "Net Income",   isKey: true,  subRows: ["netIncomeMargin"]    },
  { key: "depreciation_amortization", label: "D&A",          editableProformaField: "da", subRows: ["daRev"] },
  { key: "capital_expenditures",      label: "CapEx",                      subRows: ["capexPct"]           },
  { key: "total_assets",              label: "Total Assets" },
  { key: "total_debt",                label: "Total Debt" },
  { key: "cash_and_equivalents",      label: "Cash & Equivalents" },
  { key: "diluted_eps",               label: "Diluted EPS" },
];

const SUB_LABEL: Record<SubRowKind, string> = {
  revGrowth:        "Rev Growth %",
  grossMargin:      "Gross Margin %",
  sga:              "SG&A",
  rd:               "R&D",
  ebitMargin:       "EBIT Margin %",
  opMargin:         "EBIT Margin %",
  ebitdaMargin:     "EBITDA Margin %",
  effectiveTaxRate: "Effective Tax Rate",
  netIncomeMargin:  "Net Income Margin %",
  capexPct:         "CapEx % Rev",
  daRev:            "D&A % Rev",
};

// Sub-rows that show editable dollar inputs in the proforma columns.
const DOLLAR_SUB_ROWS = new Set<SubRowKind>(["sga", "rd"]);

// Sub-rows that show editable % inputs in the proforma columns (read-only in historical).
const PCT_SUB_ROWS = new Set<SubRowKind>(["revGrowth", "grossMargin", "capexPct", "ebitMargin"]);

// Sub-rows that are always read-only derived ratios.
const DERIVED_SUB_ROWS = new Set<SubRowKind>([
  "opMargin", "ebitdaMargin", "effectiveTaxRate", "netIncomeMargin", "daRev",
]);

// Grid rows for keyboard navigation — standard mode:
// 0=RevGrowth, 1=GrossMargin, 2=SGA, 3=RD, 4=DA, 5=CapEx
const GRID_ROWS_STANDARD = 6;
const MAIN_ROW_GRID_STANDARD: Partial<Record<keyof HistoricalRow, number>> = {
  depreciation_amortization: 4,
};
const SUB_ROW_GRID_STANDARD: Partial<Record<SubRowKind, number>> = {
  revGrowth:   0,
  grossMargin: 1,
  sga:         2,
  rd:          3,
  capexPct:    5,
};

// Grid rows — AV mode:
// 0=RevGrowth, 1=GrossMargin, 2=EbitMargin, 3=DA, 4=CapEx
const GRID_ROWS_AV = 5;
const MAIN_ROW_GRID_AV: Partial<Record<keyof HistoricalRow, number>> = {
  depreciation_amortization: 3,
};
const SUB_ROW_GRID_AV: Partial<Record<SubRowKind, number>> = {
  revGrowth:   0,
  grossMargin: 1,
  ebitMargin:  2,
  capexPct:    4,
};

function computeHistSubRow(kind: SubRowKind, col: HistoricalRow, prevCol: HistoricalRow | null): number | null {
  const rev = col.revenue;
  if (!rev) return null;
  switch (kind) {
    case "revGrowth":
      return prevCol?.revenue ? col.revenue! / prevCol.revenue! - 1 : null;
    case "grossMargin":
      return col.gross_profit != null ? col.gross_profit / rev : null;
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
    case "ebitMargin":
      return col.operating_income != null ? col.operating_income / rev : null;
    case "daRev":
      return col.depreciation_amortization != null ? col.depreciation_amortization / rev : null;
    case "sga":
    case "rd":
      return null;
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
    case "capexPct":         return col.capital_expenditures != null ? Math.abs(col.capital_expenditures) / rev : null;
    case "ebitMargin":       return col.operating_income != null ? col.operating_income / rev : null;
    case "daRev":            return col.depreciation_amortization != null ? col.depreciation_amortization / rev : null;
    case "sga":
    case "rd":               return null;
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
  onCommit?: () => void;
  variant?: "av"; // AV DCF mode: EBIT Margin % replaces SGA/R&D inputs
}

export default function DcfStatements({
  historical,
  proforma,
  yearRows,
  onYearRowChange,
  onCommit,
  variant,
}: Props) {
  const isAv = variant === "av";

  const inputCls =
    "w-full bg-transparent text-right tabular-nums text-[11px] text-violet-300 outline-none " +
    "border-b border-transparent focus:border-violet-500/50 transition-colors px-1";

  const lastHistorical = historical[historical.length - 1] ?? null;
  const GRID_COLS = proforma.length;

  const ROWS        = isAv ? ROWS_AV          : ROWS_STANDARD;
  const GRID_ROWS   = isAv ? GRID_ROWS_AV     : GRID_ROWS_STANDARD;
  const MAIN_ROW_GRID = isAv ? MAIN_ROW_GRID_AV : MAIN_ROW_GRID_STANDARD;
  const SUB_ROW_GRID  = isAv ? SUB_ROW_GRID_AV  : SUB_ROW_GRID_STANDARD;

  const { refs: gridRefs, handleKeyDown: gridKeyDown } = useGridArrowNav(GRID_ROWS, GRID_COLS);

  // Dollar sub-row historical value lookup
  const histDollarField: Partial<Record<SubRowKind, keyof HistoricalRow>> = {
    sga: "selling_general_admin",
    rd:  "research_development",
  };
  // Dollar sub-row YearRowState field
  const dollarStateField: Partial<Record<SubRowKind, keyof YearRowState>> = {
    sga: "sga",
    rd:  "rd",
  };
  // Pct sub-row YearRowState field
  const pctStateField: Partial<Record<SubRowKind, keyof YearRowState>> = {
    revGrowth:   "rev_growth",
    grossMargin: "gross_margin",
    capexPct:    "capex_pct",
    ebitMargin:  "ebit_margin",
  };

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
            {ROWS.map(({ key, label, isKey, subRows, editableProformaField }, rowIdx) => {
              const rowBg = isKey ? "oklch(0.14 0.03 275)" : rowIdx % 2 === 1 ? "oklch(0.105 0.008 265)" : "oklch(0.09 0.006 265)";
              const subBg = isKey ? "oklch(0.115 0.022 275)" : rowIdx % 2 === 1 ? "oklch(0.095 0.007 265)" : "oklch(0.082 0.005 265)";
              const gridRowIdx = MAIN_ROW_GRID[key];

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

                    {/* Historical columns — always read-only */}
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

                    {/* Proforma columns — editable when editableProformaField is set (D&A only now) */}
                    {proforma.map((col, pi) => {
                      if (editableProformaField) {
                        const fieldVal = yearRows[pi + 1]?.[editableProformaField] ?? "";
                        return (
                          <td key={col.period_label} className="px-3 py-0.5">
                            <input
                              className={inputCls}
                              value={fieldVal}
                              ref={(el) => {
                                if (gridRowIdx !== undefined) gridRefs.current[gridRowIdx][pi] = el;
                              }}
                              onChange={(e) => onYearRowChange(pi + 1, editableProformaField, e.target.value)}
                              onFocus={(e) => onYearRowChange(pi + 1, editableProformaField, focusStrip(e.target.value))}
                              onBlur={(e) => { onYearRowChange(pi + 1, editableProformaField, blurFormat(e.target.value, "bn")); onCommit?.(); }}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                                else if (gridRowIdx !== undefined) gridKeyDown(gridRowIdx, pi, e);
                              }}
                            />
                          </td>
                        );
                      }

                      // Read-only proforma cell
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
                    const isDerived   = DERIVED_SUB_ROWS.has(kind);
                    const isDollar    = DOLLAR_SUB_ROWS.has(kind);
                    const isPct       = PCT_SUB_ROWS.has(kind);
                    const gridRow     = SUB_ROW_GRID[kind];
                    const stateField  = dollarStateField[kind];
                    const pctField    = pctStateField[kind];
                    const histField   = histDollarField[kind];

                    return (
                      <tr key={kind} className="border-b border-white/[0.03]" style={{ background: subBg }}>
                        <td
                          className="sticky left-0 z-10 px-4 py-1 text-zinc-600 text-[10px] whitespace-nowrap pl-8"
                          style={{ background: subBg }}
                        >
                          {SUB_LABEL[kind]}
                        </td>

                        {/* Historical sub-row cells — always read-only */}
                        {historical.map((col, ci) => {
                          if (isDollar && histField) {
                            const { text, negative } = fmtNum(col[histField] as number | null);
                            return (
                              <td key={col.period_label} className={`px-4 py-1 text-right tabular-nums text-[10px] ${
                                text === "—" ? "text-zinc-700"
                                : negative ? "text-rose-500/60"
                                : "text-zinc-500"
                              }`}>
                                {text}
                              </td>
                            );
                          }
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

                        {/* Proforma sub-row cells */}
                        {proforma.map((col, pi) => {
                          const prevProforma = pi === 0 ? lastHistorical : proforma[pi - 1];

                          // Editable % sub-row (Rev Growth, Gross Margin, CapEx %)
                          if (isPct && pctField) {
                            // Suppress Gross Margin input for service companies with no COGS
                            if (kind === "grossMargin" && col.cost_of_revenue == null) {
                              return (
                                <td key={col.period_label} className="px-4 py-1 text-right tabular-nums text-[10px] text-zinc-700">
                                  —
                                </td>
                              );
                            }
                            const fieldVal = yearRows[pi + 1]?.[pctField] ?? "";
                            return (
                              <td key={col.period_label} className="px-3 py-0.5">
                                <input
                                  className={inputCls}
                                  value={fieldVal}
                                  ref={(el) => {
                                    if (gridRow !== undefined) gridRefs.current[gridRow][pi] = el;
                                  }}
                                  onChange={(e) => onYearRowChange(pi + 1, pctField, e.target.value)}
                                  onFocus={(e) => onYearRowChange(pi + 1, pctField, focusStrip(e.target.value))}
                                  onBlur={(e) => {
                                    const formatted = blurFormat(e.target.value, "pct");
                                    for (let y = pi + 1; y <= proforma.length; y++) {
                                      onYearRowChange(y, pctField, formatted);
                                    }
                                    onCommit?.();
                                  }}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                                    else if (gridRow !== undefined) gridKeyDown(gridRow, pi, e);
                                  }}
                                />
                              </td>
                            );
                          }

                          // Editable dollar sub-row (SGA, R&D)
                          if (isDollar && stateField) {
                            // Suppress R&D input when company has no R&D
                            if (kind === "rd" && col.research_development == null) {
                              return (
                                <td key={col.period_label} className="px-4 py-1 text-right tabular-nums text-[10px] text-zinc-700">
                                  —
                                </td>
                              );
                            }
                            const fieldVal = yearRows[pi + 1]?.[stateField] ?? "";
                            return (
                              <td key={col.period_label} className="px-3 py-0.5">
                                <input
                                  className={inputCls}
                                  value={fieldVal}
                                  placeholder={kind === "rd" ? "—" : undefined}
                                  ref={(el) => {
                                    if (gridRow !== undefined) gridRefs.current[gridRow][pi] = el;
                                  }}
                                  onChange={(e) => onYearRowChange(pi + 1, stateField, e.target.value)}
                                  onFocus={(e) => onYearRowChange(pi + 1, stateField, focusStrip(e.target.value))}
                                  onBlur={(e) => { onYearRowChange(pi + 1, stateField, blurFormat(e.target.value, "bn")); onCommit?.(); }}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                                    else if (gridRow !== undefined) gridKeyDown(gridRow, pi, e);
                                  }}
                                />
                              </td>
                            );
                          }

                          // Read-only derived ratio sub-row
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

                          return <td key={col.period_label} className="px-4 py-1 text-zinc-700 text-right text-[10px]">—</td>;
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
