"use client";

import DcfViewer from "./DcfViewer";

export default function AvDcfViewer({ ticker }: { ticker: string }) {
  return <DcfViewer ticker={ticker} apiPath="/av-dcf" variant="av" />;
}
