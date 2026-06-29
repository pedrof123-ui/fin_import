"use client";

import type { DcfData } from "@/lib/dcf-types";
import { useLinearArrowNav } from "@/lib/useArrowNav";
import { blurFormat, focusStrip } from "@/lib/formatField";

function fmtUSD(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  return `${sign}$${abs.toFixed(2)}`;
}

function fmtPct(n: number): string {
  return `${(n * 100).toFixed(2)}%`;
}

const inputCls =
  "bg-transparent font-mono text-xs text-zinc-200 outline-none border-b border-white/[0.07] " +
  "focus:border-violet-500/50 transition-colors pb-0.5 w-16 text-right tabular-nums";

interface Props {
  data: DcfData;
  terminalGrowth: string;
  rf: string;
  mrp: string;
  beta: string;
  cod: string;
  taxRate: string;
  onTerminalGrowthChange: (v: string) => void;
  onRfChange: (v: string) => void;
  onMrpChange: (v: string) => void;
  onBetaChange: (v: string) => void;
  onCodChange: (v: string) => void;
  onTaxRateChange: (v: string) => void;
  onCommit?: () => void;
}

// WACC card editable fields in navigation order: rf, mrp, beta, cod, taxRate
const WACC_NAV_COUNT = 5;

export default function DcfSummary({
  data,
  terminalGrowth, rf, mrp, beta, cod, taxRate,
  onTerminalGrowthChange, onRfChange, onMrpChange, onBetaChange, onCodChange, onTaxRateChange,
  onCommit,
}: Props) {
  const { intrinsic_value_per_share: iv, current_price: price, upside_pct: upside, wacc_detail: w } = data;
  const isUnder = price !== null && iv < price;

  const { refs: waccRefs, handleKeyDown: waccKeyDown } = useLinearArrowNav(WACC_NAV_COUNT);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
      {/* Valuation card */}
      <div
        className="rounded border border-white/[0.07] p-5"
        style={{ background: "oklch(0.11 0.008 265)" }}
      >
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-4">
          Valuation
        </p>
        <div className="flex items-end gap-4 mb-4">
          <div>
            <p className="font-mono text-[10px] text-zinc-500 mb-1">Intrinsic Value</p>
            <p className="font-mono text-2xl font-semibold text-zinc-100">
              ${iv.toFixed(2)}
            </p>
          </div>
          {price !== null && (
            <>
              <div className="text-zinc-700 text-lg mb-1">vs</div>
              <div>
                <p className="font-mono text-[10px] text-zinc-500 mb-1">Market Price</p>
                <p className="font-mono text-2xl font-semibold text-zinc-300">
                  ${price.toFixed(2)}
                </p>
              </div>
            </>
          )}
        </div>
        {upside !== null && (
          <div
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-mono font-medium border ${
              isUnder
                ? "border-rose-800/50 bg-rose-950/30 text-rose-400"
                : "border-emerald-800/50 bg-emerald-950/30 text-emerald-400"
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${isUnder ? "bg-rose-500" : "bg-emerald-500"}`}
            />
            {upside >= 0 ? "+" : ""}{(upside * 100).toFixed(1)}% {isUnder ? "downside" : "upside"}
          </div>
        )}
        <div className="mt-4 pt-4 border-t border-white/[0.06] grid grid-cols-2 gap-x-6 gap-y-2 text-xs font-mono">
          <div className="text-zinc-500">Enterprise Value</div>
          <div className="text-zinc-300 text-right">{fmtUSD(data.enterprise_value)}</div>
          <div className="text-zinc-500">Net Debt</div>
          <div className="text-zinc-300 text-right">{fmtUSD(data.net_debt)}</div>
          <div className="text-zinc-500">Equity Value</div>
          <div className="text-zinc-300 text-right">{fmtUSD(data.equity_value)}</div>
          <div className="text-zinc-500">PV Terminal</div>
          <div className="text-zinc-300 text-right">{fmtUSD(data.pv_terminal_value)}</div>
          <div className="text-zinc-500">Terminal Growth %</div>
          <div className="text-right">
            <input
              className={inputCls}
              value={terminalGrowth}
              onChange={(e) => onTerminalGrowthChange(e.target.value)}
              onFocus={(e) => onTerminalGrowthChange(focusStrip(e.target.value))}
              onBlur={(e) => { onTerminalGrowthChange(blurFormat(e.target.value, "pct")); onCommit?.(); }}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
            />
          </div>
        </div>
      </div>

      {/* WACC card */}
      <div
        className="rounded border border-white/[0.07] p-5"
        style={{ background: "oklch(0.11 0.008 265)" }}
      >
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-4">
          WACC
        </p>
        <p className="font-mono text-2xl font-semibold text-violet-400 mb-4">
          {fmtPct(w.wacc)}
        </p>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs font-mono">
          <div className="text-zinc-500">Risk-Free Rate %</div>
          <div className="text-right">
            <input
              className={inputCls}
              value={rf}
              ref={(el) => { waccRefs.current[0] = el; }}
              onChange={(e) => onRfChange(e.target.value)}
              onFocus={(e) => onRfChange(focusStrip(e.target.value))}
              onBlur={(e) => { onRfChange(blurFormat(e.target.value, "pct")); onCommit?.(); }}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); else waccKeyDown(0, e); }}
            />
          </div>
          <div className="text-zinc-500">Mkt Risk Premium %</div>
          <div className="text-right">
            <input
              className={inputCls}
              value={mrp}
              ref={(el) => { waccRefs.current[1] = el; }}
              onChange={(e) => onMrpChange(e.target.value)}
              onFocus={(e) => onMrpChange(focusStrip(e.target.value))}
              onBlur={(e) => { onMrpChange(blurFormat(e.target.value, "pct")); onCommit?.(); }}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); else waccKeyDown(1, e); }}
            />
          </div>
          <div className="text-zinc-500">Beta 5yr (raw / re-lev)</div>
          <div className="text-zinc-300 text-right flex items-center justify-end gap-1.5">
            <input
              className={`${inputCls} w-10`}
              value={beta}
              ref={(el) => { waccRefs.current[2] = el; }}
              onChange={(e) => onBetaChange(e.target.value)}
              onBlur={(e) => { onBetaChange(blurFormat(e.target.value, "decimal")); onCommit?.(); }}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); else waccKeyDown(2, e); }}
            />
            <span className="text-zinc-600">/ {w.beta_relevered.toFixed(2)}</span>
          </div>
          <div className="text-zinc-500">Beta 2yr (ref)</div>
          <div className="text-zinc-400 text-right font-mono text-xs tabular-nums">
            {w.beta_2yr != null ? w.beta_2yr.toFixed(2) : "—"}
          </div>
          <div className="text-zinc-500">Cost of Equity</div>
          <div className="text-zinc-300 text-right">{fmtPct(w.cost_of_equity)}</div>
          <div className="text-zinc-500">Cost of Debt %</div>
          <div className="text-right">
            <input
              className={inputCls}
              value={cod}
              ref={(el) => { waccRefs.current[3] = el; }}
              onChange={(e) => onCodChange(e.target.value)}
              onFocus={(e) => onCodChange(focusStrip(e.target.value))}
              onBlur={(e) => { onCodChange(blurFormat(e.target.value, "pct")); onCommit?.(); }}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); else waccKeyDown(3, e); }}
            />
          </div>
          <div className="text-zinc-500">Tax Rate %</div>
          <div className="text-right">
            <input
              className={inputCls}
              value={taxRate}
              ref={(el) => { waccRefs.current[4] = el; }}
              onChange={(e) => onTaxRateChange(e.target.value)}
              onFocus={(e) => onTaxRateChange(focusStrip(e.target.value))}
              onBlur={(e) => { onTaxRateChange(blurFormat(e.target.value, "pct")); onCommit?.(); }}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); else waccKeyDown(4, e); }}
            />
          </div>
          <div className="text-zinc-500">Debt / Equity Weight</div>
          <div className="text-zinc-300 text-right">
            {fmtPct(w.debt_weight)} / {fmtPct(w.equity_weight)}
          </div>
        </div>
      </div>
    </div>
  );
}
