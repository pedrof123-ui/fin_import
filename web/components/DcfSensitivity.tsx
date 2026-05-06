import type { SensitivityCell } from "@/lib/dcf-types";

interface Props {
  cells: SensitivityCell[];
  currentPrice: number | null;
  baseWacc: number;
  baseTerminalGrowth: number;
}

function pct(n: number) {
  return `${(n * 100).toFixed(1)}%`;
}

export default function DcfSensitivity({ cells, currentPrice, baseWacc, baseTerminalGrowth }: Props) {
  const waccs  = [...new Set(cells.map((c) => c.wacc))].sort((a, b) => a - b);
  const tgs    = [...new Set(cells.map((c) => c.terminal_growth))].sort((a, b) => a - b);
  const lookup = new Map(cells.map((c) => [`${c.wacc.toFixed(4)}|${c.terminal_growth.toFixed(4)}`, c.intrinsic_value]));

  return (
    <div className="mb-6">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-3">
        Sensitivity — Intrinsic Value (WACC × Terminal Growth)
      </p>
      <div className="overflow-x-auto rounded border border-white/[0.07]">
        <table className="text-xs font-mono border-collapse">
          <thead>
            <tr className="border-b border-white/[0.07]">
              <th
                className="text-left px-4 py-2.5 font-normal text-[10px] text-zinc-500 whitespace-nowrap"
                style={{ background: "oklch(0.10 0.008 265)" }}
              >
                WACC \ TG
              </th>
              {tgs.map((tg) => {
                const isBase = Math.abs(tg - baseTerminalGrowth) < 0.001;
                return (
                  <th
                    key={tg}
                    className={`text-right px-4 py-2.5 min-w-[90px] whitespace-nowrap font-medium ${
                      isBase ? "text-violet-400" : "text-zinc-400"
                    }`}
                  >
                    {pct(tg)}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {waccs.map((wacc, rowIdx) => {
              const isBaseWacc = Math.abs(wacc - baseWacc) < 0.001;
              const rowBg = isBaseWacc
                ? "oklch(0.14 0.03 275)"
                : rowIdx % 2 === 0
                ? "oklch(0.09 0.006 265)"
                : "oklch(0.105 0.008 265)";

              return (
                <tr
                  key={wacc}
                  className="border-b border-white/[0.04] hover:brightness-125 transition-[filter] duration-75"
                  style={{ background: rowBg }}
                >
                  <td
                    className={`sticky left-0 z-10 px-4 py-2 whitespace-nowrap ${
                      isBaseWacc ? "text-violet-300 font-medium" : "text-zinc-400"
                    }`}
                    style={{ background: rowBg }}
                  >
                    {pct(wacc)}
                  </td>
                  {tgs.map((tg) => {
                    const iv = lookup.get(`${wacc.toFixed(4)}|${tg.toFixed(4)}`);
                    const isBase = isBaseWacc && Math.abs(tg - baseTerminalGrowth) < 0.001;
                    const isNull = iv === null || iv === undefined;
                    const above = !isNull && currentPrice !== null && iv > currentPrice;
                    const below = !isNull && currentPrice !== null && iv <= currentPrice;

                    return (
                      <td
                        key={tg}
                        className={`px-4 py-2 text-right tabular-nums ${
                          isNull
                            ? "text-zinc-700"
                            : above
                            ? "text-emerald-400"
                            : below
                            ? "text-rose-400"
                            : "text-zinc-300"
                        } ${isBase ? "font-semibold underline decoration-dotted" : ""}`}
                      >
                        {isNull ? "—" : `$${iv!.toFixed(0)}`}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {currentPrice !== null && (
        <p className="font-mono text-[10px] text-zinc-600 mt-2">
          Green = above market price (${currentPrice.toFixed(2)}) &nbsp;·&nbsp; Rose = below market price
        </p>
      )}
    </div>
  );
}
