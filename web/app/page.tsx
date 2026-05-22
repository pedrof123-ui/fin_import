"use client";

import { useState, useCallback, useEffect } from "react";
import ImportForm from "@/components/ImportForm";
import StatementViewer from "@/components/StatementViewer";
import DcfViewer from "@/components/DcfViewer";
import { API } from "@/lib/config";

type PeriodType = "FY" | "Q";
type StmtType = "income" | "balance" | "cashflow";
type Tab = "financials" | "dcf";

const FY_DISPLAY_PERIODS = 20;
const Q_DISPLAY_PERIODS = 8;

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

function Spinner() {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setFrame((f) => (f + 1) % SPINNER_FRAMES.length), 80);
    return () => clearInterval(id);
  }, []);
  return <span className="font-mono text-violet-400 shrink-0">{SPINNER_FRAMES[frame]}</span>;
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("financials");
  const [stmtType, setStmtType] = useState<StmtType>("income");
  const [data, setData] = useState<Record<string, unknown>[] | null>(null);
  const [loadedTicker, setLoadedTicker] = useState("");
  const [displayPeriodType, setDisplayPeriodType] = useState<PeriodType>("FY");
  const [importing, setImporting] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [quartersStatus, setQuartersStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchStatement = useCallback(
    async (ticker: string, periodType: PeriodType, stmt: StmtType, periods: number) => {
      setFetching(true);
      setError(null);
      try {
        const res = await fetch(
          `${API}/statements/${ticker}/${stmt}?period_type=${periodType}&periods=${periods}`
        );
        const json = await res.json();
        if (!res.ok) throw new Error(json.detail ?? `HTTP ${res.status}`);
        setData(json);
      } catch (e: unknown) {
        setError((e as Error).message);
        setData(null);
      } finally {
        setFetching(false);
      }
    },
    []
  );

  const handleImport = async (ticker: string) => {
    setImporting(true);
    setError(null);
    setQuartersStatus(null);
    setStatus(`Downloading 20 years of annual filings for ${ticker}…`);
    setData(null);

    try {
      const res = await fetch(`${API}/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, periods: 20, period_type: "FY" }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? `HTTP ${res.status}`);

      const n = json.filings_processed as number;
      setStatus(
        n > 0
          ? `${n} new filing${n !== 1 ? "s" : ""} imported for ${ticker}`
          : `${ticker} already up to date`
      );
      setLoadedTicker(ticker);
      setDisplayPeriodType("FY");

      await fetchStatement(ticker, "FY", stmtType, FY_DISPLAY_PERIODS);

      // Automatically fetch 20 quarters in background
      setQuartersStatus("Fetching 20 quarters of data…");
      fetch(`${API}/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, periods: 20, period_type: "Q" }),
      })
        .then((r) => r.json())
        .then((qj) => {
          const qn = qj.filings_processed as number;
          setQuartersStatus(
            qn > 0
              ? `${qn} quarterly filing${qn !== 1 ? "s" : ""} added`
              : "Quarters up to date"
          );
          setTimeout(() => setQuartersStatus(null), 4000);
        })
        .catch(() => setQuartersStatus(null));
    } catch (e: unknown) {
      setError((e as Error).message);
      setStatus(null);
    } finally {
      setImporting(false);
    }
  };

  const handleStmtChange = (stmt: StmtType) => {
    setStmtType(stmt);
    if (loadedTicker) {
      const periods = displayPeriodType === "Q" ? Q_DISPLAY_PERIODS : FY_DISPLAY_PERIODS;
      fetchStatement(loadedTicker, displayPeriodType, stmt, periods);
    }
  };

  const handlePeriodTypeChange = (pt: PeriodType) => {
    setDisplayPeriodType(pt);
    if (loadedTicker) {
      const periods = pt === "Q" ? Q_DISPLAY_PERIODS : FY_DISPLAY_PERIODS;
      fetchStatement(loadedTicker, pt, stmtType, periods);
    }
  };

  const busy = importing || fetching;
  const showSpinner = importing || !!quartersStatus;
  const displayStatus = quartersStatus ?? status;

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header
        className="sticky top-0 z-20 border-b border-white/[0.07] backdrop-blur-md"
        style={{ background: "oklch(0.08 0.008 265 / 85%)" }}
      >
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center gap-4">
          <span className="font-mono text-xs tracking-[0.3em] text-violet-400 font-semibold uppercase shrink-0">
            FinView
          </span>
          <div className="w-px h-4 bg-white/10 shrink-0" />
          <ImportForm onSubmit={handleImport} loading={importing} />
          {!error && displayStatus && (
            <>
              <div className="w-px h-4 bg-white/10 shrink-0" />
              <div className="flex items-center gap-2 text-xs font-mono text-zinc-400 min-w-0">
                {showSpinner ? (
                  <Spinner />
                ) : (
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-violet-500 shrink-0" />
                )}
                <span className="truncate">{displayStatus}</span>
              </div>
            </>
          )}
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 max-w-[1600px] mx-auto w-full px-6 py-5">
        {/* Error bar */}
        {error && (
          <div className="mb-3 flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20 text-rose-400">
            <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0 bg-rose-500" />
            {error}
          </div>
        )}

        {/* Tab bar — only shown when a ticker is loaded */}
        {loadedTicker && (
          <div className="flex items-center gap-1 mb-5">
            {(["financials", "dcf"] as Tab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-1.5 text-xs font-mono rounded border transition-colors ${
                  activeTab === tab
                    ? "border-violet-500/50 bg-violet-950/30 text-violet-300"
                    : "border-white/[0.07] text-zinc-500 hover:text-zinc-300 hover:border-white/[0.12]"
                }`}
              >
                {tab === "financials" ? "Financials" : "DCF Valuation"}
              </button>
            ))}
          </div>
        )}

        {/* Loading placeholder */}
        {busy && !data && activeTab === "financials" && (
          <div className="flex items-center justify-center h-64">
            <span className="font-mono text-sm text-zinc-600 animate-pulse">
              {status ?? "Loading…"}
            </span>
          </div>
        )}

        {/* Financials tab */}
        {activeTab === "financials" && data && (
          <StatementViewer
            data={data}
            ticker={loadedTicker}
            stmtType={stmtType}
            periodType={displayPeriodType}
            onStmtChange={handleStmtChange}
            onPeriodTypeChange={handlePeriodTypeChange}
            loading={fetching}
          />
        )}

        {/* DCF tab */}
        {activeTab === "dcf" && loadedTicker && (
          <DcfViewer ticker={loadedTicker} />
        )}

        {/* Empty state */}
        {!busy && !loadedTicker && !error && (
          <div className="flex flex-col items-center justify-center h-64 gap-3">
            <p className="font-mono text-xs text-zinc-600 tracking-widest uppercase">
              No data loaded
            </p>
            <p className="font-mono text-xs text-zinc-700">
              Enter a ticker above to import SEC filings
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
