"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import type { DcfData, RunRequest, YearOverrideBody, YearRowState } from "@/lib/dcf-types";
import { parsePct } from "@/lib/formatField";
import DcfSummary from "./DcfSummary";
import DcfFcffTable from "./DcfFcffTable";
import DcfStatements from "./DcfStatements";
import DcfSensitivity from "./DcfSensitivity";
import DcfNwcCapex from "./DcfNwcCapex";
import DcfTerminalValue from "./DcfTerminalValue";
import DcfQuarterly from "./DcfQuarterly";
import EarningsEstimates from "./EarningsEstimates";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

      const r: Record<number, YearRowState> = {};
      for (const yf of d.year_forecasts) {
        r[yf.year] = {
          revenue_growth:    (yf.revenue_growth    * 100).toFixed(1),
          cogs_pct:          (yf.cogs_pct           * 100).toFixed(1),
          sga_pct:           (yf.sga_pct            * 100).toFixed(1),
          rd_pct:            yf.rd_pct !== null ? (yf.rd_pct * 100).toFixed(1) : "",
          interest_pct:      (yf.interest_pct       * 100).toFixed(1),
          other_pct:         (yf.other_pct          * 100).toFixed(1),
          capex_pct_revenue: (yf.capex_pct_revenue  * 100).toFixed(1),
        };
      }

      // Initialize quarter revenues (non-actuals) as billions strings
      const qr: Record<number, string> = {};
      (d.y1_quarters ?? []).forEach((q, i) => {
        if (!q.is_actual && q.revenue != null) qr[i + 1] = (q.revenue / 1e9).toFixed(2);
      });

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
    if (!d) return;
    setYearRows(d.yearRows);
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
    if (initialDataRef.current) setData(initialDataRef.current);
  }

  async function handleUpdate() {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    try {
      const years: Record<string, YearOverrideBody> = {};
      for (const [year, row] of Object.entries(yearRows)) {
        const defaultRow = modelDefaultsRef.current?.yearRows[parseInt(year)];
        const revGrowthChanged = !defaultRow || row.revenue_growth !== defaultRow.revenue_growth;
        years[year] = {
          revenue_growth:    revGrowthChanged ? parsePct(row.revenue_growth) : undefined,
          cogs_pct:          parsePct(row.cogs_pct),
          sga_pct:           parsePct(row.sga_pct),
          rd_pct:            row.rd_pct !== "" ? parsePct(row.rd_pct) : undefined,
          interest_pct:      parsePct(row.interest_pct),
          other_pct:         parsePct(row.other_pct),
          capex_pct_revenue: parsePct(row.capex_pct_revenue),
        };
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

      // Re-sync yearRows and modelDefaults from the response so that
      // analyst-estimated growth rates (and any other model-computed fields)
      // are reflected in the editable inputs, not just in the proforma revenues.
      const updatedRows: Record<number, YearRowState> = {};
      for (const yf of d.year_forecasts) {
        updatedRows[yf.year] = {
          revenue_growth:    (yf.revenue_growth    * 100).toFixed(1),
          cogs_pct:          (yf.cogs_pct           * 100).toFixed(1),
          sga_pct:           (yf.sga_pct            * 100).toFixed(1),
          rd_pct:            yf.rd_pct !== null ? (yf.rd_pct * 100).toFixed(1) : "",
          interest_pct:      (yf.interest_pct       * 100).toFixed(1),
          other_pct:         (yf.other_pct          * 100).toFixed(1),
          capex_pct_revenue: (yf.capex_pct_revenue  * 100).toFixed(1),
        };
      }
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
