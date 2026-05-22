/**
 * Format a field value on blur.
 * - "pct": "4.5" → "4.5%"   (1 decimal)
 * - "decimal": "0.661" → "0.66"  (2 decimals)
 * - "days": "45.2" → "45.2"  (1 decimal)
 * - "bn": "450.23" → "450.23B"  (billions, 2 decimals)
 */
export function blurFormat(value: string, type: "pct" | "decimal" | "days" | "bn"): string {
  const num = parseFloat(value.replace(/[%B]/g, "").trim());
  if (isNaN(num)) return value;
  switch (type) {
    case "pct":     return `${num.toFixed(1)}%`;
    case "decimal": return num.toFixed(2);
    case "days":    return num.toFixed(1);
    case "bn":      return `${Math.abs(num).toFixed(2)}B`;
  }
}

/** Strip trailing %, B and whitespace before the user starts editing. */
export function focusStrip(value: string): string {
  return value.replace(/[%B]/g, "").trim();
}

/** Parse a string that may have a trailing % sign; returns the decimal fraction. */
export function parsePct(value: string): number {
  return parseFloat(value.replace(/%/g, "").trim()) / 100;
}

/** Parse a billions string (e.g. "450.23B" or "450.23") → raw dollars. */
export function parseBn(value: string): number {
  const n = parseFloat(value.replace(/[%B]/g, "").trim());
  return isFinite(n) ? n * 1e9 : 0;
}
