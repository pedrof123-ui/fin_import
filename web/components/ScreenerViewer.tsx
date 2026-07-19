"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { API } from "@/lib/config";

// ── Extensibility guide ───────────────────────────────────────────────────────
// Adding a new metric:
//   1. Add entry to RANGE_FIELD_META (key = backend field prefix, matches screener_router.py)
//   2. Add the key to the appropriate section in FILTER_SECTIONS
//   3. Optionally add to RESULT_COLS for display in the results table
//   4. In api/screener_router.py: add RANGE_FIELDS entry + two ScreenRequest fields

type FmtType = "x" | "pct" | "bn" | "str";

const RANGE_FIELD_META: Record<string, { label: string; fmt: FmtType }> = {
  market_cap_b:      { label: "Mkt Cap ($B)",    fmt: "bn"  },
  pe:                { label: "P/E",              fmt: "x"   },
  fwd_pe:            { label: "Fwd P/E",          fmt: "x"   },
  ev_ebitda:         { label: "EV/EBITDA",        fmt: "x"   },
  pfcf:              { label: "P/FCF",            fmt: "x"   },
  ps_ratio:          { label: "P/Sales",          fmt: "x"   },
  pbv:               { label: "P/BV",             fmt: "x"   },
  rev_growth_1yr:    { label: "Rev Growth 1yr (TTM)", fmt: "pct" },
  rev_cagr_3yr:      { label: "Rev CAGR 3yr",     fmt: "pct" },
  earn_growth_1yr:   { label: "Earn Growth 1yr",  fmt: "pct" },
  gross_margin:      { label: "Gross Margin",     fmt: "pct" },
  ebit_margin:       { label: "EBIT Margin",      fmt: "pct" },
  fcf_margin:        { label: "FCF Margin",       fmt: "pct" },
  roe:               { label: "ROE",              fmt: "pct" },
  roic:              { label: "ROIC",             fmt: "pct" },
  debt_to_ebitda:    { label: "Debt/EBITDA",      fmt: "x"   },
  interest_coverage: { label: "Int Coverage",     fmt: "x"   },
  dividend_yield:    { label: "Div Yield",        fmt: "pct" },
  momentum_12_1:     { label: "Momentum 12-1",    fmt: "pct" },
  goal_low_upside:   { label: "PT Low Upside",    fmt: "pct" },
  goal_high_upside:  { label: "PT High Upside",   fmt: "pct" },
  goal_pe_upside:    { label: "PT P/E Upside",    fmt: "pct" },
  goal_pcf_upside:   { label: "PT P/FCF Upside",  fmt: "pct" },
  goal_peg_upside:   { label: "PT PEG Upside",    fmt: "pct" },
  goal_bv_upside:    { label: "PT P/BV Upside",   fmt: "pct" },
  dcf_upside:        { label: "DCF Upside",       fmt: "pct" },
};

const FILTER_SECTIONS: { label: string; fields: string[] }[] = [
  { label: "Universe",          fields: ["market_cap_b"] },
  { label: "Valuation",         fields: ["pe", "fwd_pe", "ev_ebitda", "pfcf", "ps_ratio", "pbv"] },
  { label: "Growth",            fields: ["rev_growth_1yr", "rev_cagr_3yr", "earn_growth_1yr"] },
  { label: "Quality",           fields: ["gross_margin", "ebit_margin", "fcf_margin", "roe", "roic"] },
  { label: "Leverage",          fields: ["debt_to_ebitda", "interest_coverage"] },
  { label: "Income & Momentum", fields: ["dividend_yield", "momentum_12_1"] },
  { label: "Price Targets",    fields: ["goal_low_upside", "goal_high_upside", "goal_pe_upside", "goal_pcf_upside", "goal_peg_upside", "goal_bv_upside", "dcf_upside"] },
];

const RESULT_COLS: { key: string; label: string; fmt: FmtType }[] = [
  { key: "ticker",                   label: "Ticker",    fmt: "str" },
  { key: "company_name",             label: "Company",   fmt: "str" },
  { key: "sector",                   label: "Sector",    fmt: "str" },
  { key: "market_cap_b",             label: "Mkt Cap",   fmt: "bn"  },
  { key: "current_pe",               label: "P/E",       fmt: "x"   },
  { key: "current_evebitda",         label: "EV/EBITDA", fmt: "x"   },
  { key: "current_pfcf",             label: "P/FCF",     fmt: "x"   },
  { key: "current_ps",               label: "P/S",       fmt: "x"   },
  { key: "current_pbv",              label: "P/BV",      fmt: "x"   },
  { key: "rev_growth_1yr",           label: "Rev Gr (TTM)", fmt: "pct" },
  { key: "current_gross_margin",     label: "Gross Mgn", fmt: "pct" },
  { key: "current_operating_margin", label: "EBIT Mgn",  fmt: "pct" },
  { key: "current_roic",             label: "ROIC",      fmt: "pct" },
  { key: "debt_to_ebitda",           label: "D/EBITDA",  fmt: "x"   },
  { key: "dividend_yield",           label: "Div Yield", fmt: "pct" },
  { key: "momentum_12_1",            label: "Mom 12-1",  fmt: "pct" },
  { key: "goal_low_upside",          label: "PT Low Up", fmt: "pct" },
  { key: "goal_high_upside",         label: "PT Hi Up",  fmt: "pct" },
  { key: "dcf_upside",               label: "DCF Upside", fmt: "pct" },
];

type Preset = {
  label: string;
  filters: Record<string, string>;
  tooltip: [string, string][];
};

const PRESETS: Record<string, Preset> = {
  undervalued_quality: {
    label: "Undervalued Quality",
    filters: {
      market_cap_b_min: "0.5",
      pe_min: "5",
      pe_max: "30",
      ev_ebitda_max: "15",
      rev_growth_1yr_min: "5",
      ebit_margin_min: "10",
      roic_min: "10",
      debt_to_ebitda_max: "3",
      interest_coverage_min: "3",
    },
    tooltip: [
      ["Mkt Cap",      "> $0.5B"],
      ["P/E",          "5 – 30x"],
      ["EV/EBITDA",    "< 15x"],
      ["Rev Growth",   "> 5%"],
      ["EBIT Margin",  "> 10%"],
      ["ROIC",         "> 10%"],
      ["Debt/EBITDA",  "< 3x"],
      ["Int Coverage", "> 3x"],
    ],
  },
  fundamental_upside: {
    label: "Fundamental Upside",
    filters: {
      goal_low_upside_min: "0",
    },
    tooltip: [
      ["PT Low Upside", "> 0%"],
      ["", "All fundamental price targets"],
      ["", "(P/E, P/FCF, PEG, P/BV)"],
      ["", "above current price"],
    ],
  },
  dcf_undervalued: {
    label: "DCF Undervalued",
    filters: {
      dcf_upside_min: "20",
    },
    tooltip: [
      ["DCF Upside", "> 20%"],
      ["", "Intrinsic value (DCF model)"],
      ["", "exceeds current price by 20%+"],
    ],
  },
};

const DISPLAY_LIMIT = 500;

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtCell(v: unknown, fmt: FmtType): string {
  if (v == null) return "—";
  if (fmt === "str") return String(v);
  const n = v as number;
  if (!isFinite(n)) return "—";
  if (fmt === "x")   return `${n.toFixed(1)}x`;
  if (fmt === "pct") return `${(n * 100).toFixed(1)}%`;
  if (fmt === "bn") {
    if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}T`;
    return `$${n.toFixed(1)}B`;
  }
  return String(v);
}

function makeEmptyFilters(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const key of Object.keys(RANGE_FIELD_META)) {
    out[`${key}_min`] = "";
    out[`${key}_max`] = "";
  }
  return out;
}

function buildBody(
  filters: Record<string, string>,
  sectors: string[],
  industries: string[],
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (sectors.length > 0)   body.sectors   = sectors;
  if (industries.length > 0) body.industries = industries;
  for (const [key, meta] of Object.entries(RANGE_FIELD_META)) {
    const divisor = meta.fmt === "pct" ? 100 : 1;
    const minStr = filters[`${key}_min`];
    const maxStr = filters[`${key}_max`];
    if (minStr !== "") {
      const v = parseFloat(minStr);
      if (!isNaN(v)) body[`${key}_min`] = v / divisor;
    }
    if (maxStr !== "") {
      const v = parseFloat(maxStr);
      if (!isNaN(v)) body[`${key}_max`] = v / divisor;
    }
  }
  return body;
}

// ── MultiSelectDropdown ───────────────────────────────────────────────────────

function MultiSelectDropdown({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: string[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const allChecked = options.length > 0 && selected.length === options.length;

  const allLabel = label === "Industry" ? "All Industries" : `All ${label}s`;
  const buttonLabel =
    selected.length === 0 ? allLabel :
    selected.length === 1 ? selected[0] :
    `${selected[0]} +${selected.length - 1}`;

  const toggle = (opt: string) =>
    onChange(selected.includes(opt) ? selected.filter(s => s !== opt) : [...selected, opt]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className={`h-7 px-2.5 rounded border font-mono text-[11px] flex items-center gap-1.5 transition-colors whitespace-nowrap ${
          selected.length > 0
            ? "border-violet-500/50 bg-violet-950/20 text-violet-300"
            : "border-white/[0.07] text-zinc-400 hover:text-zinc-200 hover:border-white/[0.2]"
        }`}
      >
        <span className="max-w-[200px] truncate">{buttonLabel}</span>
        <span className="text-zinc-600 text-[9px] shrink-0">▾</span>
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 z-50 w-64 rounded border border-white/[0.1] shadow-xl"
             style={{ background: "oklch(0.12 0.008 265)" }}>
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-white/[0.07]">
            <button
              onClick={() => onChange(allChecked ? [] : [...options])}
              className="font-mono text-[10px] text-zinc-500 hover:text-zinc-200 transition-colors"
            >
              {allChecked ? "Deselect all" : "Select all"}
            </button>
            {selected.length > 0 && (
              <button
                onClick={() => onChange([])}
                className="font-mono text-[10px] text-zinc-600 hover:text-rose-400 transition-colors"
              >
                Clear ({selected.length})
              </button>
            )}
          </div>
          {/* Options */}
          <div className="max-h-56 overflow-y-auto py-1">
            {options.map(opt => (
              <label
                key={opt}
                className="flex items-center gap-2.5 px-3 py-1.5 hover:bg-white/[0.04] cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(opt)}
                  onChange={() => toggle(opt)}
                  className="accent-violet-500 shrink-0"
                />
                <span className="font-mono text-[11px] text-zinc-300 truncate">{opt}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── PresetDropdown ────────────────────────────────────────────────────────────

function PresetDropdown({ onSelect }: { onSelect: (key: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="h-8 px-3 rounded border border-white/[0.07] font-mono text-xs text-zinc-400 hover:text-zinc-200 hover:border-white/[0.2] transition-colors flex items-center gap-1.5"
      >
        Presets
        <span className="text-zinc-600 text-[9px]">▾</span>
      </button>

      {open && (
        <div
          className="absolute top-full left-0 mt-1 z-50 w-56 rounded border border-white/[0.1] shadow-xl py-1"
          style={{ background: "oklch(0.12 0.008 265)" }}
        >
          {Object.entries(PRESETS).map(([key, preset]) => (
            <button
              key={key}
              onClick={() => { onSelect(key); setOpen(false); }}
              className="w-full text-left px-3 py-2 font-mono text-[11px] text-zinc-300 hover:bg-white/[0.05] hover:text-zinc-100 transition-colors"
            >
              <div className="font-medium">{preset.label}</div>
              <div className="text-zinc-600 text-[10px] mt-0.5">
                {preset.tooltip.filter(([l]) => l).map(([l, v]) => `${l} ${v}`).slice(0, 2).join(" · ")}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500 mb-2">
      {children}
    </p>
  );
}

function RangeRow({
  fieldKey,
  filters,
  onChange,
}: {
  fieldKey: string;
  filters: Record<string, string>;
  onChange: (key: string, val: string) => void;
}) {
  const meta = RANGE_FIELD_META[fieldKey];
  const hint = meta.fmt === "pct" ? "%" : meta.fmt === "bn" ? "$B" : "x";
  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-[11px] text-zinc-400 w-32 shrink-0">{meta.label}</span>
      <input
        type="number"
        placeholder={`min ${hint}`}
        value={filters[`${fieldKey}_min`]}
        onChange={(e) => onChange(`${fieldKey}_min`, e.target.value)}
        className="w-20 h-7 px-2 rounded border border-white/[0.07] bg-transparent font-mono text-[11px] text-zinc-200 placeholder:text-zinc-700 focus:outline-none focus:border-violet-500/50"
      />
      <span className="font-mono text-[10px] text-zinc-700">–</span>
      <input
        type="number"
        placeholder={`max ${hint}`}
        value={filters[`${fieldKey}_max`]}
        onChange={(e) => onChange(`${fieldKey}_max`, e.target.value)}
        className="w-20 h-7 px-2 rounded border border-white/[0.07] bg-transparent font-mono text-[11px] text-zinc-200 placeholder:text-zinc-700 focus:outline-none focus:border-violet-500/50"
      />
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface ScreenerViewerProps {
  onSelectTicker: (ticker: string) => void;
}

export default function ScreenerViewer({ onSelectTicker }: ScreenerViewerProps) {
  const [allSectors, setAllSectors] = useState<string[]>([]);
  const [sectorIndustries, setSectorIndustries] = useState<Record<string, string[]>>({});
  const [selectedSectors, setSelectedSectors] = useState<string[]>([]);
  const [selectedIndustries, setSelectedIndustries] = useState<string[]>([]);
  const [filters, setFilters] = useState<Record<string, string>>(makeEmptyFilters);
  const [results, setResults] = useState<Record<string, unknown>[] | null>(null);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState("market_cap_b");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    fetch(`${API}/screen/metadata`)
      .then((r) => r.json())
      .then((j) => {
        setAllSectors(j.sectors ?? []);
        setSectorIndustries(j.sector_industries ?? {});
      })
      .catch(() => {});
  }, []);

  // Industries available given current sector selection
  const availableIndustries = useMemo(() => {
    const set =
      selectedSectors.length === 0
        ? new Set(Object.values(sectorIndustries).flat())
        : new Set(selectedSectors.flatMap(s => sectorIndustries[s] ?? []));
    return [...set].sort();
  }, [selectedSectors, sectorIndustries]);

  // Drop any selected industries that are no longer available after a sector change
  useEffect(() => {
    const allowed = new Set(availableIndustries);
    setSelectedIndustries(prev => prev.filter(i => allowed.has(i)));
  }, [availableIndustries]);

  const setFilter = useCallback((key: string, val: string) => {
    setFilters((prev) => ({ ...prev, [key]: val }));
  }, []);

  const handleReset = () => {
    setFilters(makeEmptyFilters());
    setSelectedSectors([]);
    setSelectedIndustries([]);
    setResults(null);
    setError(null);
  };

  const applyPreset = (key: string) => {
    const preset = PRESETS[key];
    if (!preset) return;
    setFilters({ ...makeEmptyFilters(), ...preset.filters });
    setSelectedSectors([]);
    setSelectedIndustries([]);
    setResults(null);
  };

  const handleSort = (key: string) => {
    if (key === sortKey) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/screen`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildBody(filters, selectedSectors, selectedIndustries)),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? `HTTP ${res.status}`);
      const rows: Record<string, unknown>[] = json.results ?? [];
      setResults(rows);
      setCount(json.count ?? 0);
      setSortKey("market_cap_b");
      setSortDir("desc");
      // Sync sector dropdown to sectors present in results so the user can
      // deselect unwanted sectors and re-run without starting from scratch.
      const resultSectors = [...new Set(rows.map(r => r.sector as string).filter(Boolean))].sort();
      setSelectedSectors(resultSectors);
    } catch (e: unknown) {
      const msg = (e as Error).message;
      setError(msg === "Failed to fetch" ? "Backend not reachable — is the API server running on port 8000?" : msg);
      setResults(null);
    } finally {
      setLoading(false);
    }
  };

  const sortedResults = useMemo(() => {
    if (!results) return [];
    return [...results].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp =
        typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [results, sortKey, sortDir]);

  const displayRows = sortedResults.slice(0, DISPLAY_LIMIT);

  const exportCsv = () => {
    const header = RESULT_COLS.map((c) => c.label).join(",");
    const rows = sortedResults.map((row) =>
      RESULT_COLS.map((c) => {
        const v = row[c.key];
        const s = c.fmt === "str" ? String(v ?? "") : fmtCell(v, c.fmt);
        return s.includes(",") ? `"${s}"` : s;
      }).join(",")
    );
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `screen_results_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      {/* ── Filter panel ──────────────────────────────────────────────────── */}
      <div
        className="rounded border border-white/[0.07] p-5 space-y-5"
        style={{ background: "oklch(0.09 0.006 265)" }}
      >
        {/* Universe: sector, industry, market cap */}
        <div>
          <SectionLabel>Universe</SectionLabel>
          <div className="flex flex-wrap gap-x-6 gap-y-3 items-center">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] text-zinc-400 w-20 shrink-0">Sector</span>
              <MultiSelectDropdown
                label="Sector"
                options={allSectors}
                selected={selectedSectors}
                onChange={setSelectedSectors}
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] text-zinc-400 w-20 shrink-0">Industry</span>
              <MultiSelectDropdown
                label="Industry"
                options={availableIndustries}
                selected={selectedIndustries}
                onChange={setSelectedIndustries}
              />
            </div>
            <RangeRow fieldKey="market_cap_b" filters={filters} onChange={setFilter} />
          </div>
        </div>

        {/* Remaining metric sections */}
        {FILTER_SECTIONS.filter((s) => s.label !== "Universe").map((section) => (
          <div key={section.label}>
            <SectionLabel>{section.label}</SectionLabel>
            <div className="flex flex-wrap gap-x-6 gap-y-3">
              {section.fields.map((fieldKey) => (
                <RangeRow key={fieldKey} fieldKey={fieldKey} filters={filters} onChange={setFilter} />
              ))}
            </div>
          </div>
        ))}

        {/* Action bar */}
        <div className="flex items-center gap-3 pt-1 border-t border-white/[0.05]">
          <button
            onClick={handleSubmit}
            disabled={loading}
            className="h-8 px-4 rounded border border-violet-500/50 bg-violet-950/30 font-mono text-xs text-violet-300 hover:bg-violet-950/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? "Running…" : "Run Screen"}
          </button>
          <PresetDropdown onSelect={applyPreset} />
          <button
            onClick={handleReset}
            className="h-8 px-3 rounded border border-white/[0.07] font-mono text-xs text-zinc-500 hover:text-zinc-300 hover:border-white/[0.15] transition-colors"
          >
            Reset
          </button>
          {results !== null && !loading && (
            <>
              <span className="font-mono text-xs text-zinc-600 ml-1">
                {count} match{count !== 1 ? "es" : ""}
                {count > DISPLAY_LIMIT ? ` · showing first ${DISPLAY_LIMIT}` : ""}
              </span>
              {count > 0 && (
                <button
                  onClick={exportCsv}
                  className="ml-auto h-8 px-3 rounded border border-white/[0.07] font-mono text-xs text-zinc-500 hover:text-zinc-300 hover:border-white/[0.15] transition-colors"
                >
                  Export CSV
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Error ─────────────────────────────────────────────────────────── */}
      {error && (
        <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20 text-rose-400">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-rose-500 shrink-0" />
          {error}
        </div>
      )}

      {/* ── Hint when no results yet ──────────────────────────────────────── */}
      {results === null && !loading && !error && (
        <div className="flex flex-col items-center justify-center h-40 gap-2">
          <p className="font-mono text-xs text-zinc-600">Set filters above and click Run Screen</p>
          <p className="font-mono text-[10px] text-zinc-700">
            Or use Presets to get started
          </p>
        </div>
      )}

      {/* ── Results table ─────────────────────────────────────────────────── */}
      {results !== null && count === 0 && !loading && (
        <p className="font-mono text-xs text-zinc-600 text-center py-10">No stocks match the current filters.</p>
      )}

      {displayRows.length > 0 && (
        <div className="overflow-x-auto rounded border border-white/[0.07]">
          <table className="w-full text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-white/[0.07]" style={{ background: "oklch(0.10 0.008 265)" }}>
                {RESULT_COLS.map((col) => (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col.key)}
                    className={`px-3 py-2.5 font-normal text-[10px] uppercase tracking-[0.12em] cursor-pointer select-none transition-colors
                      ${col.fmt === "str" && col.key !== "ticker" ? "text-left" : "text-right"}
                      ${sortKey === col.key ? "text-violet-400" : "text-zinc-500 hover:text-zinc-300"}
                    `}
                  >
                    {col.label}
                    {sortKey === col.key && (
                      <span className="ml-1 text-violet-500">{sortDir === "asc" ? "↑" : "↓"}</span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayRows.map((row, i) => {
                const bg = i % 2 === 0 ? "oklch(0.09 0.006 265)" : "oklch(0.105 0.008 265)";
                return (
                  <tr key={row.ticker as string} style={{ background: bg }} className="hover:brightness-110">
                    {RESULT_COLS.map((col) => {
                      const v = row[col.key];
                      const isGrowthOrQuality = col.fmt === "pct" && col.key !== "dividend_yield";
                      const numericColor =
                        isGrowthOrQuality
                          ? typeof v === "number" && v < 0 ? "text-rose-400" : "text-emerald-400"
                          : "text-zinc-200";
                      if (col.key === "ticker") {
                        return (
                          <td key={col.key} className="px-3 py-2 text-right">
                            <button
                              onClick={() => onSelectTicker(v as string)}
                              className="font-mono text-[11px] font-semibold text-violet-400 hover:text-violet-300 tracking-widest transition-colors"
                            >
                              {v as string}
                            </button>
                          </td>
                        );
                      }
                      if (col.key === "company_name" || col.key === "sector") {
                        return (
                          <td key={col.key} className="px-3 py-2 text-left text-zinc-400 max-w-[160px] truncate">
                            {v != null ? String(v) : "—"}
                          </td>
                        );
                      }
                      return (
                        <td
                          key={col.key}
                          className={`px-3 py-2 text-right tabular-nums ${
                            col.fmt === "pct" ? numericColor : "text-zinc-200"
                          }`}
                        >
                          {fmtCell(v, col.fmt)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
