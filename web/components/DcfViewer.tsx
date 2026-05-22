"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import type { DcfData, RunRequest, YearOverrideBody, YearRowState } from "@/lib/dcf-types";
import { parseBn, parsePct } from "@/lib/formatField";
import { API } from "@/lib/config";
import DcfSummary from "./DcfSummary";
import DcfFcffTable from "./DcfFcffTable";
import DcfStatements from "./DcfStatements";
import DcfSensitivity from "./DcfSensitivity";
import DcfNwcCapex from "./DcfNwcCapex";
import DcfTerminalValue from "./DcfTerminalValue";
import DcfQuarterly from "./DcfQuarterly";
import EarningsEstimates from "./EarningsEstimates";

function fmtBn(v: number | null | undefined): string {
  if (v == null) return "";
  return (Math.abs(v) / 1e9).toFixed(2) + "B";
}

function buildYearRows(
  year_forecasts: DcfData["year_forecasts"],
  proforma: DcfData["proforma"],
): Record<number, YearRowState> {
  const r: Record<number, YearRowState> = {};
  for (let i = 0; i < year_forecasts.length; i++) {
    const yf = year_forecasts[i];
    const pf = proforma[i];
    r[yf.year] = {
      revenue:      fmtBn(pf?.revenue),
      gross_profit: fmtBn(pf?.gross_profit),
      sga:          fmtBn(pf?.selling_general_admin),
      rd:           fmtBn(pf?.research_development),
      da:           fmtBn(pf?.depreciation_amortization),
      capex:        fmtBn(pf?.capital_expenditures),
    };
  }
  return r;
}

type ModelDefaults = {
  yearRows: Record<number, YearRowState>;
  quarterRevenues: Record<number, string>;
  terminalGrowth: string;
  rf: string;
  mrp: string;
  beta: string;
  cod: string;
  taxRate: string;
  dso: string;
  dpo: string;
  dio: string;
};

export default function DcfViewer({ ticker }: { ticker: string }) {
  const [data, setData] = useState<DcfData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [yearRows, setYearRows] = useState<Record<number, YearRowState>>({});
  // Quarterly revenue overrides: stored as string in billions (e.g. "143.76")
  const [quarterRevenues, setQuarterRevenues] = useState<Record<number, string>>({});
  const [terminalGrowth, setTerminalGrowth] = useState("");
  const [rf, setRf] = useState("");
  const [mrp, setMrp] = useState("");
  const [beta, setBeta] = useState("");
  const [cod, setCod] = useState("");
  const [taxRate, setTaxRate] = useState("");
  const [dso, setDso] = useState("");
  const [dpo, setDpo] = useState("");
  const [dio, setDio] = useState("");

  const modelDefaultsRef = useRef<ModelDefaults | null>(null);
  const initialDataRef = useRef<DcfData | null>(null);

  const fetchDcf = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/dcf/${ticker}`);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? `HTTP ${res.status}`);
      const d = json as DcfData;
      setData(d);

      const r = buildYearRows(d.year_forecasts, d.proforma);

      // Start empty: only user-edited quarters are sent as overrides.
      // DcfQuarterly falls back to y1_quarters API data for display.
      const qr: Record<number, string> = {};

      const defaults: ModelDefaults = {
        yearRows:      r,
        quarterRevenues: qr,
        terminalGrowth: (d.terminal_growth_rate            * 100).toFixed(1),
        rf:             (d.wacc_detail.risk_free_rate       * 100).toFixed(1),
        mrp:            (d.wacc_detail.market_risk_premium  * 100).toFixed(1),
        beta:            d.wacc_detail.beta_raw.toFixed(2),
        cod:            (d.wacc_detail.cost_of_debt         * 100).toFixed(1),
        taxRate:        (d.wacc_detail.tax_rate             * 100).toFixed(1),
        dso:             d.nwc_assumptions.dso.toFixed(1),
        dpo:             d.nwc_assumptions.dpo.toFixed(1),
        dio:             d.nwc_assumptions.dio.toFixed(1),
      };

      initialDataRef.current = d;
      modelDefaultsRef.current = defaults;
      setYearRows(defaults.yearRows);
      setQuarterRevenues(defaults.quarterRevenues);
      setTerminalGrowth(defaults.terminalGrowth);
      setRf(defaults.rf);
      setMrp(defaults.mrp);
      setBeta(defaults.beta);
      setCod(defaults.cod);
      setTaxRate(defaults.taxRate);
      setDso(defaults.dso);
      setDpo(defaults.dpo);
      setDio(defaults.dio);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [ticker]);

  useEffect(() => {
    if (ticker) fetchDcf();
  }, [ticker, fetchDcf]);

  function handleReset() {
    const d = modelDefaultsRef.current;
    const initData = initialDataRef.current;
    if (!d || !initData) return;
    const initRows = buildYearRows(initData.year_forecasts, initData.proforma);
    setYearRows(initRows);
    // Reset baseline so next Update compares against original values
    modelDefaultsRef.current = { ...d, yearRows: initRows };
    setQuarterRevenues(d.quarterRevenues);
    setTerminalGrowth(d.terminalGrowth);
    setRf(d.rf);
    setMrp(d.mrp);
    setBeta(d.beta);
    setCod(d.cod);
    setTaxRate(d.taxRate);
    setDso(d.dso);
    setDpo(d.dpo);
    setDio(d.dio);
    setData(initData);
  }

  async function handleUpdate() {
    if (!ticker || !data) return;
    setLoading(true);
    setError(null);
    try {
      const years: Record<string, YearOverrideBody> = {};

      // data.historical is sorted newest-to-oldest (DESC from API), so [0] is the most recent year.
      // That is the correct base for the Y1 revenue growth calculation.
      const histRevenue = data.historical[0]?.revenue ?? 0;

      for (const [yearStr, row] of Object.entries(yearRows)) {
        const yearNum = parseInt(yearStr);
        const defaultRow = modelDefaultsRef.current?.yearRows[yearNum];

        const revChanged   = row.revenue      !== defaultRow?.revenue;
        const gpChanged    = row.gross_profit !== defaultRow?.gross_profit;
        const sgaChanged   = row.sga          !== defaultRow?.sga;
        const rdChanged    = row.rd           !== defaultRow?.rd;
        const daChanged    = row.da           !== defaultRow?.da;
        const capexChanged = row.capex        !== defaultRow?.capex;

        if (!revChanged && !gpChanged && !sgaChanged && !rdChanged && !daChanged && !capexChanged) continue;

        const thisRevenue = parseBn(row.revenue);
        const thisGP      = parseBn(row.gross_profit);

        // Previous year revenue: use Y(n-1) from current yearRows state (which was initialised
        // from the model proforma and reflects any user edits to prior years).
        const prevRevenue = yearNum === 1
          ? histRevenue
          : parseBn(yearRows[yearNum - 1]?.revenue ?? "0");

        const override: YearOverrideBody = {};

        // Only send revenue_growth when revenue itself changed (otherwise fade_growth_years
        // would treat this as a user override and skip its blending logic).
        if (revChanged && prevRevenue && isFinite(thisRevenue / prevRevenue)) {
          override.revenue_growth = thisRevenue / prevRevenue - 1;
        }
        if (thisRevenue > 0) {
          // Guard cogs_pct: when company doesn't report a COGS breakdown, gross_profit is null
          // and gross_profit row state is "". Sending cogs_pct = 1.0 in that case would break EBIT.
          if (row.gross_profit !== "") {
            override.cogs_pct = (thisRevenue - thisGP) / thisRevenue;
          }
          override.sga_pct           = parseBn(row.sga) / thisRevenue;
          override.capex_pct_revenue = parseBn(row.capex) / thisRevenue;
          override.da_pct            = parseBn(row.da) / thisRevenue;
          if (row.rd) {
            override.rd_pct = parseBn(row.rd) / thisRevenue;
          }
        }

        years[yearStr] = override;
      }

      const qRevRaw: Record<string, number> = {};
      for (const [k, v] of Object.entries(quarterRevenues)) {
        const n = parseFloat(v) * 1e9;
        if (isFinite(n)) qRevRaw[k] = n;
      }
      const req: RunRequest = {
        years,
        terminal_growth_rate: parsePct(terminalGrowth),
        risk_free_rate:       parsePct(rf),
        market_risk_premium:  parsePct(mrp),
        beta:                 parseFloat(beta),
        cost_of_debt:         parsePct(cod),
        tax_rate:             parsePct(taxRate),
        dso:                  parseFloat(dso),
        dpo:                  parseFloat(dpo),
        dio:                  parseFloat(dio),
        ...(Object.keys(qRevRaw).length > 0 && { y1_quarter_revenues: qRevRaw }),
      };
      const res = await fetch(`${API}/dcf/${ticker}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? `HTTP ${res.status}`);
      const d = json as DcfData;
      setData(d);

      // Re-sync yearRows and modelDefaults from the response.
      const updatedRows = buildYearRows(d.year_forecasts, d.proforma);
      setYearRows(updatedRows);
      if (modelDefaultsRef.current) {
        modelDefaultsRef.current = { ...modelDefaultsRef.current, yearRows: updatedRows };
      }
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-64">
        <span className="font-mono text-sm text-zinc-600 animate-pulse">
          Running DCF model...
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20 text-rose-400">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-rose-500 shrink-0" />
        {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="font-mono text-xs text-zinc-600">No DCF data</p>
      </div>
    );
  }

  const historical = [...data.historical].reverse();

  return (
    <div className="transition-opacity duration-150" style={{ opacity: loading ? 0.6 : 1 }}>
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold text-zinc-100 tracking-widest">
            {data.ticker}
          </span>
          <span className="text-zinc-700">·</span>
          <span className="font-mono text-xs text-zinc-500">DCF Valuation</span>
          {data.historical[0]?.period_end_date && (
            <>
              <span className="text-zinc-700">·</span>
              <span className="font-mono text-[10px] text-zinc-600">
                as of {data.historical[0].period_end_date}
              </span>
            </>
          )}
          {loading && (
            <span className="font-mono text-xs text-violet-500 animate-pulse ml-2">
              Recalculating...
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleReset}
            disabled={loading}
            className="font-mono text-xs px-3 py-1.5 rounded border border-zinc-700/50 bg-zinc-900/30 text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Reset
          </button>
          <button
            onClick={handleUpdate}
            disabled={loading}
            className="font-mono text-xs px-3 py-1.5 rounded border border-violet-700/50 bg-violet-950/30 text-violet-300 hover:bg-violet-900/40 hover:text-violet-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Update
          </button>
        </div>
      </div>

      {data.warnings?.length > 0 && (
        <div className="mb-5 space-y-1.5">
          {data.warnings.map((w, i) => (
            <div
              key={i}
              className="flex items-start gap-2 text-xs font-mono px-3 py-2 rounded border border-amber-800/50 bg-amber-950/20 text-amber-400"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 shrink-0 mt-1" />
              {w}
            </div>
          ))}
        </div>
      )}

      <DcfSummary
        data={data}
        terminalGrowth={terminalGrowth}
        rf={rf}
        mrp={mrp}
        beta={beta}
        cod={cod}
        taxRate={taxRate}
        onTerminalGrowthChange={setTerminalGrowth}
        onRfChange={setRf}
        onMrpChange={setMrp}
        onBetaChange={setBeta}
        onCodChange={setCod}
        onTaxRateChange={setTaxRate}
      />

      <DcfStatements
        historical={historical}
        proforma={data.proforma}
        yearRows={yearRows}
        onYearRowChange={(year, field, value) =>
          setYearRows((prev) => ({ ...prev, [year]: { ...prev[year], [field]: value } }))
        }
      />

      <DcfNwcCapex
        nwcAssumptions={data.nwc_assumptions}
        fcffSeries={data.fcff_series}
        yearForecasts={data.year_forecasts}
        dso={dso}
        dpo={dpo}
        dio={dio}
        onDsoChange={setDso}
        onDpoChange={setDpo}
        onDioChange={setDio}
      />

      <DcfFcffTable
        fcffSeries={data.fcff_series}
        taxRate={data.wacc_detail.tax_rate}
        pvTerminalValue={data.pv_terminal_value}
        terminalValue={data.terminal_value}
        terminalGrowthRate={data.terminal_growth_rate}
        wacc={data.wacc_detail.wacc}
        enterpriseValue={data.enterprise_value}
        netDebt={data.net_debt}
        equityValue={data.equity_value}
        dilutedShares={data.diluted_shares}
        intrinsicValue={data.intrinsic_value_per_share}
      />

      <DcfTerminalValue
        terminalFcff={data.terminal_fcff}
        terminalValue={data.terminal_value}
        pvTerminalValue={data.pv_terminal_value}
        tvPctEnterpriseValue={data.tv_pct_enterprise_value}
        terminalGrowthRate={data.terminal_growth_rate}
        wacc={data.wacc_detail.wacc}
      />

      <DcfSensitivity
        cells={data.sensitivity}
        currentPrice={data.current_price}
        baseWacc={data.wacc_detail.wacc}
        baseTerminalGrowth={data.terminal_growth_rate}
      />

      <DcfQuarterly
        y1Quarters={data.y1_quarters ?? []}
        lastHistorical={historical[historical.length - 1] ?? null}
        quarterRevenues={quarterRevenues}
        onQuarterRevenueChange={(qNum, value) =>
          setQuarterRevenues((prev) => ({ ...prev, [qNum]: value }))
        }
      />

      <EarningsEstimates estimates={data.analyst_estimates ?? []} />
    </div>
  );
}
