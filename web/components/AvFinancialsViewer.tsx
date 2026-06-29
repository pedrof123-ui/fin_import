"use client";

import { Fragment, useEffect, useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { API } from "@/lib/config";

type StmtType = "income" | "balance" | "cashflow";
type PeriodType = "annual" | "quarterly";

const AV_SKIP_COLS = new Set([
  "ticker",
  "fiscal_date_ending",
  "period_type",
  "reported_currency",
  "fetched_at",
  // AV always duplicates cost_of_revenue here — identical values, adds noise
  "cost_of_goods_and_services_sold",
  // AV's pre-computed ebit sometimes differs from operating_income due to their
  // own methodology; showing both confuses readers — operating_income is canonical
  "ebit",
]);

// Explicit GAAP-order column lists for each statement.
// Only columns present AND non-null in the fetched data are rendered;
// any column not listed here is silently omitted.
const AV_COL_ORDER: Record<StmtType, string[]> = {
  income: [
    "total_revenue",
    "cost_of_revenue",
    "gross_profit",
    "selling_general_and_administrative",
    "research_and_development",
    "operating_expenses",
    "operating_income",
    "ebitda",
    "depreciation_and_amortization",
    "depreciation",
    "investment_income_net",
    "net_interest_income",
    "interest_income",
    "interest_expense",
    "non_interest_income",
    "other_non_operating_income",
    "interest_and_debt_expense",
    "income_before_tax",
    "income_tax_expense",
    "net_income_from_continuing_ops",
    "comprehensive_income_net_of_tax",
    "net_income",
  ],
  balance: [
    "total_current_assets",
    "cash_and_cash_equivalents",
    "cash_and_short_term_investments",
    "short_term_investments",
    "current_net_receivables",
    "inventory",
    "other_current_assets",
    "total_non_current_assets",
    "property_plant_equipment",
    "accumulated_depreciation_amortization_ppe",
    "intangible_assets",
    "intangible_assets_excl_goodwill",
    "goodwill",
    "investments",
    "long_term_investments",
    "other_non_current_assets",
    "total_assets",
    "total_current_liabilities",
    "current_accounts_payable",
    "current_debt",
    "short_term_debt",
    "deferred_revenue",
    "other_current_liabilities",
    "total_non_current_liabilities",
    "long_term_debt",
    "long_term_debt_noncurrent",
    "capital_lease_obligations",
    "other_non_current_liabilities",
    "total_liabilities",
    "total_shareholder_equity",
    "common_stock",
    "retained_earnings",
    "treasury_stock",
    "common_stock_shares_outstanding",
  ],
  cashflow: [
    "operating_cashflow",
    "profit_loss",
    "depreciation_depletion_and_amortization",
    "stock_based_compensation",
    "change_in_receivables",
    "change_in_inventory",
    "change_in_operating_assets",
    "change_in_operating_liabilities",
    "payments_for_operating_activities",
    "proceeds_from_operating_activities",
    "cashflow_from_investment",
    "capital_expenditures",
    "cashflow_from_financing",
    "dividend_payout",
    "dividend_payout_common_stock",
    "dividend_payout_preferred_stock",
    "payments_for_repurchase_common_stock",
    "payments_for_repurchase_equity",
    "payments_for_repurchase_preferred_stock",
    "proceeds_from_issuance_common_stock",
    "proceeds_from_issuance_long_term_debt",
    "proceeds_from_issuance_preferred_stock",
    "proceeds_from_repurchase_equity",
    "proceeds_from_sale_treasury_stock",
    "proceeds_from_repayments_short_term_debt",
    "change_in_cash_and_cash_equivalents",
    "change_in_exchange_rate",
    "net_income",
  ],
};

const AV_KEY_METRICS: Record<StmtType, Set<string>> = {
  income: new Set([
    "total_revenue",
    "gross_profit",
    "ebitda",
    "operating_income",
    "net_income",
  ]),
  balance: new Set([
    "total_assets",
    "total_current_assets",
    "total_liabilities",
    "total_current_liabilities",
    "total_shareholder_equity",
  ]),
  cashflow: new Set([
    "operating_cashflow",
    "capital_expenditures",
    "cashflow_from_investment",
    "cashflow_from_financing",
  ]),
};

const AV_SECTION_STARTS: Record<StmtType, Set<string>> = {
  income: new Set([
    "selling_general_and_administrative", // operating expense section
    "investment_income_net",              // non-operating section
    "income_before_tax",                  // pre-tax section
    "net_income_from_continuing_ops",     // bottom-line section
  ]),
  balance: new Set([
    "total_non_current_assets",   // non-current assets section
    "total_assets",               // assets subtotal / liabilities header
    "total_current_liabilities",  // current liabilities section
    "total_non_current_liabilities",
    "total_liabilities",          // liabilities subtotal / equity header
    "total_shareholder_equity",   // equity section
  ]),
  cashflow: new Set([
    "cashflow_from_investment",   // investing section
    "cashflow_from_financing",    // financing section
    "change_in_cash_and_cash_equivalents", // net change
  ]),
};

const STMT_LABELS: Record<StmtType, string> = {
  income: "Income Statement",
  balance: "Balance Sheet",
  cashflow: "Cash Flow",
};

type SubRowDef = {
  label: string;
  compute: (col: Record<string, unknown>, prev: Record<string, unknown> | null) => number | null;
};

const AV_INCOME_SUB_ROWS: Record<string, SubRowDef[]> = {
  total_revenue: [{
    label: "Rev Growth %",
    compute: (col, prev) => {
      const r = col.total_revenue as number | null;
      const p = prev?.total_revenue as number | null;
      return r && p ? r / p - 1 : null;
    },
  }],
  gross_profit: [{
    label: "Gross Margin %",
    compute: (col) => {
      const r = col.total_revenue as number | null;
      const gp = col.gross_profit as number | null;
      return r && gp != null ? gp / r : null;
    },
  }],
  operating_income: [{
    label: "EBIT Margin %",
    compute: (col) => {
      const r = col.total_revenue as number | null;
      const oi = col.operating_income as number | null;
      return r && oi != null ? oi / r : null;
    },
  }],
  net_income: [{
    label: "Net Margin %",
    compute: (col) => {
      const r = col.total_revenue as number | null;
      const ni = col.net_income as number | null;
      return r && ni != null ? ni / r : null;
    },
  }],
};

function formatAvPeriod(record: Record<string, unknown>, periodType: PeriodType): string {
  if (periodType === "quarterly" && record.period_label) {
    return record.period_label as string;
  }
  const date = record.fiscal_date_ending as string | null;
  if (!date) return "";
  const year = date.slice(0, 4);
  if (periodType === "annual") return `FY ${year}`;
  const month = parseInt(date.slice(5, 7));
  const quarter = Math.ceil(month / 3);
  return `Q${quarter} ${year}`;
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

export default function AvFinancialsViewer({ ticker }: { ticker: string }) {
  const [stmtType, setStmtType] = useState<StmtType>("income");
  const [periodType, setPeriodType] = useState<PeriodType>("annual");
  const [data, setData] = useState<Record<string, unknown>[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    fetch(
      `${API}/av-financials/${ticker}/${stmtType}?period_type=${periodType}`
    )
      .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
      .then(({ ok, j }) => {
        if (!ok) throw new Error((j as { detail?: string }).detail ?? "HTTP error");
        setData(j as Record<string, unknown>[]);
      })
      .catch((e: unknown) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [ticker, stmtType, periodType]);

  if (error) {
    return (
      <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20 text-rose-400">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-rose-500 shrink-0" />
        {error}
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-64 transition-opacity duration-150"
        style={{ opacity: loading ? 0.45 : 1 }}
      >
        <span className="font-mono text-sm text-zinc-600 animate-pulse">
          {loading ? "Loading AV data…" : "No data"}
        </span>
      </div>
    );
  }

  const keyMetrics = AV_KEY_METRICS[stmtType];
  const sectionStarts = AV_SECTION_STARTS[stmtType];

  // Use explicit GAAP-ordered list; only show columns present and non-null in data
  const metricKeys = AV_COL_ORDER[stmtType].filter(
    (k) =>
      !AV_SKIP_COLS.has(k) &&
      data.some((r) => r[k] !== null && r[k] !== undefined)
  );

  const periodLabels = data.map((r) => formatAvPeriod(r, periodType));

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
        <span className="font-mono text-[10px] text-zinc-500 uppercase tracking-widest">
          Alpha Vantage
        </span>
        <span className="text-zinc-700 select-none">·</span>
        <Select
          value={stmtType}
          onValueChange={(v) => setStmtType(v as StmtType)}
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
          {(["annual", "quarterly"] as PeriodType[]).map((pt) => (
            <button
              key={pt}
              onClick={() => !loading && setPeriodType(pt)}
              disabled={loading}
              className={`px-2.5 py-1 text-[10px] font-mono rounded border transition-colors ${
                periodType === pt
                  ? "border-violet-500/50 bg-violet-950/30 text-violet-300"
                  : "border-white/[0.07] text-zinc-500 hover:text-zinc-300 hover:border-white/[0.12]"
              }`}
            >
              {pt === "annual" ? "FY" : "Q"}
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
                const ped = record.fiscal_date_ending as string | null;
                const dateStr = ped ? String(ped).slice(0, 10) : null;
                return (
                  <th
                    key={i}
                    className="text-right px-4 py-2.5 font-medium text-zinc-300 min-w-[120px] whitespace-nowrap"
                  >
                    <div>{periodLabels[i]}</div>
                    {dateStr && (
                      <div className="text-[9px] font-normal text-zinc-600 mt-0.5">
                        {dateStr}
                      </div>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {metricKeys.map((key, rowIdx) => {
              const isKey = keyMetrics.has(key);
              const isSectionStart = sectionStarts.has(key);
              const rowBg = isKey
                ? "oklch(0.14 0.03 275)"
                : rowIdx % 2 === 1
                ? "oklch(0.105 0.008 265)"
                : "oklch(0.09 0.006 265)";
              const subRows =
                stmtType === "income" ? (AV_INCOME_SUB_ROWS[key] ?? []) : [];

              return (
                <Fragment key={key}>
                  <tr
                    className={`
                      ${isSectionStart ? "border-t border-white/[0.06]" : "border-b border-white/[0.04]"}
                      hover:brightness-125 transition-[filter] duration-75
                    `}
                    style={{ background: rowBg }}
                  >
                    <td
                      className={`sticky left-0 z-10 px-4 py-2 whitespace-nowrap ${
                        isKey ? "text-zinc-100 font-medium" : "text-zinc-400 font-normal"
                      }`}
                      style={{ background: rowBg }}
                    >
                      {isKey && (
                        <span className="inline-block w-1 h-1 rounded-full bg-violet-500 mr-2 mb-[1px]" />
                      )}
                      {formatLabel(key)}
                    </td>
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
