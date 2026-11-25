const ZERO_DECIMAL_CURRENCIES = new Set([
  "BIF",
  "CLP",
  "DJF",
  "GNF",
  "ISK",
  "JPY",
  "KMF",
  "KRW",
  "PYG",
  "RWF",
  "UGX",
  "UYI",
  "VND",
  "VUV",
  "XAF",
  "XOF",
  "XPF",
]);

const THREE_DECIMAL_CURRENCIES = new Set([
  "BHD",
  "IQD",
  "JOD",
  "KWD",
  "LYD",
  "OMR",
  "TND",
]);

const FOUR_DECIMAL_CURRENCIES = new Set(["CLF", "UYW"]);

const UNAMBIGUOUS_SYMBOLS: Record<string, string> = {
  USD: "$",
  INR: "₹",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  KRW: "₩",
};

export function getMinorUnitExponent(currency?: string | null): number {
  const code = (currency || "").trim().toUpperCase();
  if (!code || code === "UNKNOWN") return 2;
  if (ZERO_DECIMAL_CURRENCIES.has(code)) return 0;
  if (THREE_DECIMAL_CURRENCIES.has(code)) return 3;
  if (FOUR_DECIMAL_CURRENCIES.has(code)) return 4;
  try {
    const resolved = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
    }).resolvedOptions();
    if (typeof resolved.maximumFractionDigits === "number") {
      return resolved.maximumFractionDigits;
    }
  } catch {
    // fallback below
  }
  return 2;
}

export function minorToMajorNumber(
  amountMinor: number,
  currency?: string | null,
  exponentOverride?: number | null
): number {
  const exp =
    typeof exponentOverride === "number"
      ? exponentOverride
      : getMinorUnitExponent(currency);
  return amountMinor / 10 ** exp;
}

export function formatMoneyMinor(
  amountMinor: number,
  currency?: string | null,
  exponentOverride?: number | null
): string {
  const code = (currency || "").trim().toUpperCase();
  if (!code || code === "UNKNOWN") {
    return `${new Intl.NumberFormat("en-US").format(amountMinor)} (currency unknown)`;
  }

  const exp =
    typeof exponentOverride === "number"
      ? exponentOverride
      : getMinorUnitExponent(code);
  const major = amountMinor / 10 ** exp;

  const symbol = UNAMBIGUOUS_SYMBOLS[code];
  if (symbol) {
    const sign = major < 0 ? "-" : "";
    const formattedNum = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: exp,
      maximumFractionDigits: exp,
    }).format(Math.abs(major));
    return `${sign}${symbol}${formattedNum}`;
  }

  try {
    const formatted = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
      currencyDisplay: "code",
      minimumFractionDigits: exp,
      maximumFractionDigits: exp,
    }).format(major);
    return formatted.replace(/\u00a0/g, " ");
  } catch {
    return `${code} ${major.toFixed(exp)}`;
  }
}

export function formatCurrencyCents(
  cents: number,
  currency?: string | null
): string {
  return formatMoneyMinor(cents, currency);
}

export function formatShortDate(isoDate: string): string {
  const d = new Date(isoDate);
  if (Number.isNaN(d.getTime())) {
    return isoDate;
  }
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
