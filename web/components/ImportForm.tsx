"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  onSubmit: (ticker: string) => void;
  loading: boolean;
}

export default function ImportForm({ onSubmit, loading }: Props) {
  const [ticker, setTicker] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ticker.trim() || loading) return;
    onSubmit(ticker.trim());
  };

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2">
      <Input
        placeholder="AAPL"
        value={ticker}
        onChange={(e) => setTicker(e.target.value.toUpperCase())}
        className="w-24 font-mono text-sm uppercase tracking-widest placeholder:text-zinc-600 placeholder:tracking-widest h-8"
        maxLength={10}
        disabled={loading}
        aria-label="Ticker symbol"
      />
      <Button
        type="submit"
        disabled={!ticker.trim() || loading}
        className="font-mono text-xs tracking-widest uppercase h-8 bg-violet-700 hover:bg-violet-600 text-white px-4 cursor-pointer"
      >
        Load ▶
      </Button>
    </form>
  );
}
