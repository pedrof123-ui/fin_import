"use client";

interface Props {
  label: string;
  low: number | null | undefined;
  mid: number | null | undefined;
  high: number | null | undefined;
  current: number | null | undefined;
  unit?: "$" | "x";
}

function fmt(v: number, unit: "$" | "x"): string {
  return unit === "$" ? `$${v.toFixed(2)}` : `${v.toFixed(1)}x`;
}

// Reuses the emerald/rose upside-badge convention from DcfSummary.tsx: current
// price below the band -> undervalued (emerald), above -> overvalued (rose),
// inside the band -> neutral.
export default function ValuationRangeBand({ label, low, mid, high, current, unit = "$" }: Props) {
  if (low == null || mid == null || high == null || high <= low) return null;

  const clamp = (v: number) => Math.min(100, Math.max(0, ((v - low) / (high - low)) * 100));
  const midPct = clamp(mid);
  const currentPct = current != null ? clamp(current) : null;

  const state =
    current == null ? "unknown"
    : current < low ? "under"
    : current > high ? "over"
    : current < mid ? "under-mid"
    : current > mid ? "over-mid"
    : "at-mid";
  const trackColor =
    state === "under" ? "bg-emerald-900/40" : state === "over" ? "bg-rose-900/40" : "bg-zinc-800/60";
  const markerColor =
    state === "under" ? "bg-emerald-400"
    : state === "under-mid" ? "bg-emerald-400/50"
    : state === "over" ? "bg-rose-400"
    : state === "over-mid" ? "bg-rose-400/50"
    : "bg-zinc-300";

  return (
    <div className="mb-3">
      <div className="flex items-baseline justify-between mb-1">
        <span className="font-mono text-[10px] text-zinc-500">{label}</span>
        <span className="font-mono text-[10px] text-zinc-300">
          {fmt(low, unit)} &ndash; {fmt(high, unit)} (mid {fmt(mid, unit)})
        </span>
      </div>
      <div className={`relative h-2 rounded ${trackColor}`}>
        <div
          className="absolute top-0 bottom-0 w-2 flex items-center justify-center cursor-default"
          style={{ left: `${midPct}%`, transform: "translateX(-50%)" }}
          title={`Model estimate (mid): ${fmt(mid, unit)}`}
        >
          <div className="w-0.5 h-full bg-indigo-400" />
        </div>
        {currentPct != null && (
          <div
            className={`absolute -top-0.5 -bottom-0.5 w-1 rounded ${markerColor} cursor-default`}
            style={{ left: `calc(${currentPct}% - 2px)` }}
            title={`Current: ${fmt(current as number, unit)}`}
          />
        )}
      </div>
    </div>
  );
}
