"use client";

import { Fragment } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type StmtType = "income" | "balance" | "cashflow";
type PeriodType = "FY" | "Q";

interface Props {
  data: Record<string, unknown>[];
  ticker: string;
  stmtType: StmtType;
  periodType: PeriodType;
  onStmtChange: (t: StmtType) => void;
  onPeriodTypeChange: (t: PeriodType) => void;
  loading: boolean;
}

const SKIP_COLS = new Set([
  "ticker",
  "period_end_date",
  "fiscal_year",
  "period_type",
]);

// Rows to highlight — key summary lines
const KEY_METRICS = new Set([
  "revenue",
  "gross_profit",
  "operating_income",
  "net_income",
  "total_assets",
  "total_equity",
  "net_cash_operating_activities",
  "diluted_eps",
]);

// Section separators — render a thin rule above these rows
const SECTION_STARTS = new Set([
  "research_development",
  "interest_income",
  "pretax_income",
  "net_income_continuing_ops",
  "basic_eps",
  "ppe_gross",
  "accounts_payable",
  "long_term_debt",
  "common_stock",
  "depreciation_amortization",
  "capital_expenditures",
  "debt_issuance",
  "effect_of_exchange_rate",
  "cash_paid_for_interest",
]);

function formatPeriod(record: Record<string, unknown>): string {
  if (record.period_type === "Annual") return `FY ${record.fiscal_year}`;
  const d = new Date(record.period_end_date as string);
  const q = Math.ceil((d.getUTCMonth() + 1) / 3);
  return `Q${q} ${record.fiscal_year}`;
}

function isSharesField(key: string): boolean {
  return key.includes("shares") || key.includes("share_count");
}

function formatNumber(val: unknown, key = ""): { text: string; negative: boolean } {
  if (val === null || val === undefined) return { text: "—", negative: false };
  const n = val as number;
  const abs = Math.abs(n);
  const neg = n < 0;
  const sign = neg ? "-" : "";
  let text: string;
  if (isSharesField(key)) {
    // Shares: show as plain number without $ prefix
    if (abs >= 1e9)      text = `${sign}${(abs / 1e9).toFixed(3)}B`;
    else if (abs >= 1e6) text = `${sign}${(abs / 1e6).toFixed(1)}M`;
    else                 text = `${sign}${abs.toFixed(0)}`;
  } else {
    if (abs >= 1e9)      text = `${sign}$${(abs / 1e9).toFixed(2)}B`;
    else if (abs >= 1e6) text = `${sign}$${(abs / 1e6).toFixed(2)}M`;
    else if (abs >= 1e3) text = `${sign}$${(abs / 1e3).toFixed(1)}K`;
    else                 text = `${sign}$${abs.toFixed(2)}`;
  }
  return { text, negative: neg };
}

function formatLabel(key: string): string {
  return key
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function fmtRatio(val: number | null): { text: string; negative: boolean } {
  if (val === null || val === undefined) return { text: "—", negative: false };
  return { text: `${(val * 100).toFixed(1)}%`, negative: val < 0 };
}

type SubRowDef = {
  label: string;
  compute: (col: Record<string, unknown>, prevCol: Record<string, unknown> | null) => number | null;
};

const INCOME_SUB_ROWS: Record<string, SubRowDef[]> = {
  revenue: [{
    label: "Rev Growth %",
    compute: (col, prev) => {
      const r = col.revenue as number | null;
      const p = prev?.revenue as number | null;
      return r && p ? r / p - 1 : null;
    },
  }],
  gross_profit: [{
    label: "Gross Margin %",
    compute: (col) => {
      const r = col.revenue as number | null;
      const gp = col.gross_profit as number | null;
      return r && gp != null ? gp / r : null;
    },
  }],
  operating_income: [{
    label: "EBIT Margin %",
    compute: (col) => {
      const r = col.revenue as number | null;
      const oi = col.operating_income as number | null;
      return r && oi != null ? oi / r : null;
    },
  }],
  income_tax_expense: [{
    label: "Tax Rate %",
    compute: (col) => {
      const pretax = col.pretax_income as number | null;
      const tax = col.income_tax_expense as number | null;
      return pretax && tax != null ? tax / pretax : null;
    },
  }],
  net_income: [{
    label: "Net Income Margin %",
    compute: (col) => {
      const r = col.revenue as number | null;
      const ni = col.net_income as number | null;
      return r && ni != null ? ni / r : null;
    },
  }],
};

const STMT_LABELS: Record<StmtType, string> = {
  income: "Income Statement",
  balance: "Balance Sheet",
  cashflow: "Cash Flow",
};

export default function StatementViewer({
  data,
  ticker,
  stmtType,
  periodType,
  onStmtChange,
  onPeriodTypeChange,
  loading,
}: Props) {
  if (!data.length) return null;

  const metricKeys = Object.keys(data[0]).filter(
    (k) =>
      !SKIP_COLS.has(k) &&
      data.some((r) => r[k] !== null && r[k] !== undefined)
  );

  const periodLabels = data.map(formatPeriod);

  return (
    <div
      className="transition-opacity duration-150"
      style={{ opacity: loading ? 0.45 : 1 }}
    >
      {/* Controls */}
      <div className="flex items-center gap-3 mb-4">
        <span className="font-mono text-sm font-semibold text-zinc-100 tracking-widest">
          {ticker}
        </span>
        <span className="text-zinc-700 select-none">·</span>
        <Select
          value={stmtType}
          onValueChange={(v) => onStmtChange(v as StmtType)}
          disabled={loading}
        >
          <SelectTrigger className="w-48 font-mono text-xs h-8">
            <SelectValue>{STMT_LABELS[stmtType]}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="income" className="font-mono text-xs">
              Income Statement
            </SelectItem>
            <SelectItem value="balance" className="font-mono text-xs">
              Balance Sheet
            </SelectItem>
            <SelectItem value="cashflow" className="font-mono text-xs">
              Cash Flow
            </SelectItem>
          </SelectContent>
        </Select>
        <div className="flex items-center gap-1 ml-auto">
          {(["FY", "Q"] as const).map((pt) => (
            <button
              key={pt}
              onClick={() => !loading && onPeriodTypeChange(pt)}
              disabled={loading}
              className={`px-2.5 py-1 text-[10px] font-mono rounded border transition-colors ${
                periodType === pt
                  ? "border-violet-500/50 bg-violet-950/30 text-violet-300"
                  : "border-white/[0.07] text-zinc-500 hover:text-zinc-300 hover:border-white/[0.12]"
              }`}
            >
              {pt}
            </button>
          ))}
          <span className="text-zinc-700 font-mono text-[10px] ml-2">
            {data.length} period{data.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded border border-white/[0.07]">
        <table className="w-full text-xs font-mono border-collapse">
          <thead>
            <tr className="border-b border-white/[0.07]">
              <th
                className="sticky left-0 z-10 text-left px-4 py-2.5 font-normal text-[10px] uppercase tracking-[0.15em] text-zinc-500"
                style={{ background: "oklch(0.10 0.008 265)" }}
              >
                Metric
              </th>
              {data.map((record, i) => {
                const ped = typeof record.period_end_date === "string" ? record.period_end_date.slice(0, 10) : null;
                return (
                  <th
                    key={i}
                    className="text-right px-4 py-2.5 font-medium text-zinc-300 min-w-[120px] whitespace-nowrap"
                  >
                    <div>{periodLabels[i]}</div>
                    {ped && <div className="text-[9px] font-normal text-zinc-600 mt-0.5">{ped}</div>}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {metricKeys.map((key, rowIdx) => {
              const isKey = KEY_METRICS.has(key);
              const isSectionStart = SECTION_STARTS.has(key);
              const rowBg = isKey
                ? "oklch(0.14 0.03 275)"
                : rowIdx % 2 === 1
                ? "oklch(0.105 0.008 265)"
                : "oklch(0.09 0.006 265)";
              const subRows = stmtType === "income" ? (INCOME_SUB_ROWS[key] ?? []) : [];

              return (
                <Fragment key={key}>
                  <tr
                    className={`
                      ${isSectionStart ? "border-t border-white/[0.06]" : "border-b border-white/[0.04]"}
                      hover:brightness-125 transition-[filter] duration-75
                    `}
                    style={{ background: rowBg }}
                  >
                    {/* Metric label — sticky */}
                    <td
                      className={`sticky left-0 z-10 px-4 py-2 whitespace-nowrap ${
                        isKey
                          ? "text-zinc-100 font-medium"
                          : "text-zinc-400 font-normal"
                      }`}
                      style={{ background: rowBg }}
                    >
                      {isKey && (
                        <span className="inline-block w-1 h-1 rounded-full bg-violet-500 mr-2 mb-[1px]" />
                      )}
                      {formatLabel(key)}
                    </td>

                    {/* Values per period */}
                    {data.map((record, colIdx) => {
                      const val = record[key];
                      const isNull = val === null || val === undefined;
                      const { text, negative } = formatNumber(val, key);
                      return (
                        <td
                          key={colIdx}
                          className={`px-4 py-2 text-right tabular-nums ${
                            isNull
                              ? "text-zinc-700"
                              : negative
                              ? isKey
                                ? "text-rose-300"
                                : "text-rose-400/80"
                              : isKey
                              ? "text-zinc-100"
                              : "text-zinc-300"
                          }`}
                        >
                          {text}
                        </td>
                      );
                    })}
                  </tr>

                  {/* Derived sub-rows (income statement only) */}
                  {subRows.map((sub) => (
                    <tr key={sub.label} style={{ background: rowBg }}>
                      <td
                        className="sticky left-0 z-10 pl-8 pr-4 py-1 text-[10px] text-zinc-500 whitespace-nowrap"
                        style={{ background: rowBg }}
                      >
                        {sub.label}
                      </td>
                      {data.map((record, colIdx) => {
                        const val = sub.compute(record, data[colIdx + 1] ?? null);
                        const { text, negative } = fmtRatio(val);
                        return (
                          <td
                            key={colIdx}
                            className={`px-4 py-1 text-right tabular-nums text-[10px] ${
                              negative ? "text-rose-400/70" : "text-zinc-400"
                            }`}
                          >
                            {text}
                          </td>
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
