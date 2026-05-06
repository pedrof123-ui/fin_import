"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type PeriodType = "FY" | "Q";

interface Props {
  onSubmit: (ticker: string, periods: number, periodType: PeriodType) => void;
  loading: boolean;
}

export default function ImportForm({ onSubmit, loading }: Props) {
  const [ticker, setTicker] = useState("");
  const [periods, setPeriods] = useState(10);
  const [periodType, setPeriodType] = useState<PeriodType>("FY");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ticker.trim() || loading) return;
    onSubmit(ticker.trim(), periods, periodType);
  };

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2 flex-1">
      <Input
        placeholder="AAPL"
        value={ticker}
        onChange={(e) => setTicker(e.target.value.toUpperCase())}
        className="w-24 font-mono text-sm uppercase tracking-widest placeholder:text-zinc-600 placeholder:tracking-widest h-8"
        maxLength={10}
        disabled={loading}
        aria-label="Ticker symbol"
      />
      <Input
        type="number"
        min={1}
        max={20}
        value={periods}
        onChange={(e) =>
          setPeriods(Math.max(1, Math.min(20, parseInt(e.target.value) || 5)))
        }
        className="w-14 font-mono text-sm text-center h-8"
        disabled={loading}
        aria-label="Number of periods"
      />
      <Select
        value={periodType}
        onValueChange={(v) => setPeriodType(v as PeriodType)}
        disabled={loading}
      >
        <SelectTrigger className="w-36 font-mono text-xs h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="FY" className="font-mono text-xs">
            FY (Annual)
          </SelectItem>
          <SelectItem value="Q" className="font-mono text-xs">
            Q (Quarterly)
          </SelectItem>
        </SelectContent>
      </Select>
      <Button
        type="submit"
        disabled={!ticker.trim() || loading}
        className="font-mono text-xs tracking-widest uppercase h-8 bg-violet-700 hover:bg-violet-600 text-white px-4 cursor-pointer"
      >
        {loading ? "Importing..." : "Import ▶"}
      </Button>
    </form>
  );
}
