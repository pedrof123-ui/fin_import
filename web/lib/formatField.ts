/**
 * Format a field value on blur.
 * - "pct": "4.5" → "4.5%"   (1 decimal)
 * - "decimal": "0.661" → "0.66"  (2 decimals)
 * - "days": "45.2" → "45.2"  (1 decimal)
 */
export function blurFormat(value: string, type: "pct" | "decimal" | "days"): string {
  const num = parseFloat(value.replace(/%/g, "").trim());
  if (isNaN(num)) return value;
  switch (type) {
    case "pct":     return `${num.toFixed(1)}%`;
    case "decimal": return num.toFixed(2);
    case "days":    return num.toFixed(1);
  }
}

/** Strip trailing % and whitespace before the user starts editing. */
export function focusStrip(value: string): string {
  return value.replace(/%/g, "").trim();
}

/** Parse a string that may have a trailing % sign; returns the decimal fraction. */
export function parsePct(value: string): number {
  return parseFloat(value.replace(/%/g, "").trim()) / 100;
}
