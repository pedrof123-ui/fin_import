"use client";

import { useState, useCallback, useEffect } from "react";
import ImportForm from "@/components/ImportForm";
import StatementViewer from "@/components/StatementViewer";
import AvFinancialsViewer from "@/components/AvFinancialsViewer";
import AvDcfViewer from "@/components/AvDcfViewer";
import FundamentalsViewer from "@/components/FundamentalsViewer";
import EquityResearchViewer from "@/components/EquityResearchViewer";
import EarningsSummaryViewer from "@/components/EarningsSummaryViewer";
import EarningsCalendarViewer from "@/components/EarningsCalendarViewer";
import ScreenerViewer from "@/components/ScreenerViewer";
import SectorViewer from "@/components/SectorViewer";
import EstimatesViewer from "@/components/EstimatesViewer";
import NewsViewer from "@/components/NewsViewer";
import { API } from "@/lib/config";

type PeriodType = "FY" | "Q";
type StmtType = "income" | "balance" | "cashflow";
type Tab = "screener" | "sector" | "calendar" | "av_financials" | "av_dcf" | "fundamentals" | "financials" | "research" | "earnings" | "estimates" | "news";

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
  const [activeTab, setActiveTab] = useState<Tab>("screener");
  const [stmtType, setStmtType] = useState<StmtType>("income");
  const [xbrlData, setXbrlData] = useState<Record<string, unknown>[] | null>(null);
  const [loadedTicker, setLoadedTicker] = useState("");
  const [displayPeriodType, setDisplayPeriodType] = useState<PeriodType>("FY");
  const [xbrlLoaded, setXbrlLoaded] = useState(false);
  const [importing, setImporting] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [quartersStatus, setQuartersStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchXbrlStatement = useCallback(
    async (ticker: string, periodType: PeriodType, stmt: StmtType, periods: number) => {
      setFetching(true);
      setError(null);
      try {
        const res = await fetch(
          `${API}/statements/${ticker}/${stmt}?period_type=${periodType}&periods=${periods}`
        );
        const json = await res.json();
        if (!res.ok) throw new Error(json.detail ?? `HTTP ${res.status}`);
        setXbrlData(json);
      } catch (e: unknown) {
        setError((e as Error).message);
        setXbrlData(null);
      } finally {
        setFetching(false);
      }
    },
    []
  );

  const handleLoad = (ticker: string) => {
    setLoadedTicker(ticker.toUpperCase());
    setActiveTab("av_financials");
    setXbrlData(null);
    setXbrlLoaded(false);
    setError(null);
    setStatus(null);
    setQuartersStatus(null);
  };

  const handleScreenerSelectTicker = (ticker: string) => {
    handleLoad(ticker);
  };

  const handleXbrlDownload = async () => {
    const ticker = loadedTicker;
    if (!ticker) return;
    setImporting(true);
    setError(null);
    setQuartersStatus(null);
    setStatus(`Downloading 20 years of annual filings for ${ticker}…`);

    try {
      const res = await fetch(`${API}/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, periods: 20, period_type: "FY" }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? `HTTP ${res.status}`);

      const n = json.filings_processed as number;
      setDisplayPeriodType("FY");
      await fetchXbrlStatement(ticker, "FY", stmtType, FY_DISPLAY_PERIODS);

      setStatus(
        n > 0
          ? `${n} new filing${n !== 1 ? "s" : ""} imported for ${ticker}`
          : `${ticker} already up to date`
      );
      setXbrlLoaded(true);
      setActiveTab("financials");

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
    if (loadedTicker && xbrlLoaded) {
      const periods = displayPeriodType === "Q" ? Q_DISPLAY_PERIODS : FY_DISPLAY_PERIODS;
      fetchXbrlStatement(loadedTicker, displayPeriodType, stmt, periods);
    }
  };

  const handlePeriodTypeChange = (pt: PeriodType) => {
    setDisplayPeriodType(pt);
    if (loadedTicker && xbrlLoaded) {
      const periods = pt === "Q" ? Q_DISPLAY_PERIODS : FY_DISPLAY_PERIODS;
      fetchXbrlStatement(loadedTicker, pt, stmtType, periods);
    }
  };

  const showSpinner = importing || !!quartersStatus;
  const displayStatus = quartersStatus ?? status;

  const tabs: Tab[] = [
    "screener",
    "sector",
    "calendar",
    "av_financials",
    "av_dcf",
    "fundamentals",
    "estimates",
    "research",
    "earnings",
    "news",
    ...(xbrlLoaded ? (["financials"] as Tab[]) : []),
  ];
  const TAB_LABELS: Record<Tab, string> = {
    screener: "Screener",
    sector: "Sector",
    calendar: "Calendar",
    av_financials: "AV Data",
    av_dcf: "AV DCF",
    fundamentals: "Fundamentals",
    estimates: "Estimates",
    research: "AI Research",
    earnings: "Earnings",
    news: "News",
    financials: "XBRL",
  };

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
          <ImportForm onSubmit={handleLoad} loading={importing} />
          {loadedTicker && !xbrlLoaded && (
            <>
              <div className="w-px h-4 bg-white/10 shrink-0" />
              <button
                onClick={handleXbrlDownload}
                disabled={importing}
                className="font-mono text-xs tracking-widest uppercase h-8 px-3 rounded border border-white/[0.07] text-zinc-400 hover:text-zinc-200 hover:border-white/[0.2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {importing ? "Downloading…" : "Download XBRL"}
              </button>
            </>
          )}
          {displayStatus && !error && (
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

      {/* Tab bar — sticky below header */}
      <div
        className="sticky top-[57px] z-10 border-b border-white/[0.07] backdrop-blur-md"
        style={{ background: "oklch(0.08 0.008 265 / 85%)" }}
      >
        <div className="max-w-[1600px] mx-auto px-6 py-2 flex items-center gap-1">
          {tabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-1.5 text-xs font-mono rounded border transition-colors ${
                activeTab === tab
                  ? "border-violet-500/50 bg-violet-950/30 text-violet-300"
                  : "border-white/[0.07] text-zinc-500 hover:text-zinc-300 hover:border-white/[0.12]"
              }`}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <main className="flex-1 max-w-[1600px] mx-auto w-full px-6 py-5">
        {/* Error bar */}
        {error && (
          <div className="mb-3 flex items-center gap-2 text-xs font-mono px-3 py-2 rounded border border-rose-900/50 bg-rose-950/20 text-rose-400">
            <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0 bg-rose-500" />
            {error}
          </div>
        )}

        {/* Screener tab — always rendered */}
        <div className={activeTab === "screener" ? undefined : "hidden"}>
          <ScreenerViewer onSelectTicker={handleScreenerSelectTicker} />
        </div>

        {/* Sector dashboard — always rendered */}
        <div className={activeTab === "sector" ? undefined : "hidden"}>
          <SectorViewer onSelectTicker={handleScreenerSelectTicker} />
        </div>

        {/* Earnings calendar — always rendered */}
        <div className={activeTab === "calendar" ? undefined : "hidden"}>
          <EarningsCalendarViewer onSelectTicker={handleScreenerSelectTicker} />
        </div>

        {/* All ticker-specific tab panels */}
        {loadedTicker && (
          <>
            <div className={activeTab === "av_financials" ? undefined : "hidden"}>
              <AvFinancialsViewer ticker={loadedTicker} />
            </div>
            <div className={activeTab === "av_dcf" ? undefined : "hidden"}>
              <AvDcfViewer ticker={loadedTicker} />
            </div>
            <div className={activeTab === "fundamentals" ? undefined : "hidden"}>
              <FundamentalsViewer ticker={loadedTicker} />
            </div>
            <div className={activeTab === "estimates" ? undefined : "hidden"}>
              <EstimatesViewer ticker={loadedTicker} />
            </div>
            <div className={activeTab === "research" ? undefined : "hidden"}>
              <EquityResearchViewer ticker={loadedTicker} />
            </div>
            <div className={activeTab === "earnings" ? undefined : "hidden"}>
              <EarningsSummaryViewer ticker={loadedTicker} />
            </div>
            <div className={activeTab === "news" ? undefined : "hidden"}>
              <NewsViewer ticker={loadedTicker} />
            </div>
            {xbrlLoaded && (
              <div className={activeTab === "financials" ? undefined : "hidden"}>
                {xbrlData && (
                  <StatementViewer
                    data={xbrlData}
                    ticker={loadedTicker}
                    stmtType={stmtType}
                    periodType={displayPeriodType}
                    onStmtChange={handleStmtChange}
                    onPeriodTypeChange={handlePeriodTypeChange}
                    loading={fetching}
                  />
                )}
              </div>
            )}
          </>
        )}

        {/* Empty state — only when no ticker and not on screener/sector */}
        {!loadedTicker && !error && activeTab !== "screener" && activeTab !== "sector" && activeTab !== "calendar" && activeTab !== "news" && (
          <div className="flex flex-col items-center justify-center h-64 gap-3">
            <p className="font-mono text-xs text-zinc-600 tracking-widest uppercase">
              No data loaded
            </p>
            <p className="font-mono text-xs text-zinc-700">
              Enter a ticker above to view financials
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
