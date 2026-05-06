"use client";

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

interface Props {
  terminalFcff: number;
  terminalValue: number;
  pvTerminalValue: number;
  tvPctEnterpriseValue: number;
  terminalGrowthRate: number;
  wacc: number;
}

export default function DcfTerminalValue({
  terminalFcff,
  terminalValue,
  pvTerminalValue,
  tvPctEnterpriseValue,
  terminalGrowthRate,
  wacc,
}: Props) {
  return (
    <div className="mb-6">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">
        Terminal Value
      </p>
      <div
        className="rounded border border-white/[0.07] p-5"
        style={{ background: "oklch(0.11 0.008 265)" }}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-10 gap-y-3 text-xs font-mono">
          <div className="text-zinc-500">Year 5 FCFF</div>
          <div className="text-zinc-300 text-right sm:text-left">{fmtUSD(terminalFcff)}</div>

          <div className="text-zinc-500">Terminal Growth (g)</div>
          <div className="text-zinc-300 text-right sm:text-left">{fmtPct(terminalGrowthRate)}</div>

          <div className="text-zinc-500">WACC (w)</div>
          <div className="text-zinc-300 text-right sm:text-left">{fmtPct(wacc)}</div>

          <div className="text-zinc-600 text-[10px] col-span-full pt-1 border-t border-white/[0.05]">
            TV = FCFF₅ × (1 + g) / (w − g)
          </div>

          <div className="text-zinc-500">Terminal Value (TV)</div>
          <div className="text-violet-300 font-medium text-right sm:text-left">{fmtUSD(terminalValue)}</div>

          <div className="text-zinc-500">PV of Terminal Value</div>
          <div className="text-violet-300 font-medium text-right sm:text-left">{fmtUSD(pvTerminalValue)}</div>

          <div className="text-zinc-500">TV as % of Enterprise Value</div>
          <div className="text-violet-300 font-medium text-right sm:text-left">{fmtPct(tvPctEnterpriseValue)}</div>
        </div>
      </div>
    </div>
  );
}
