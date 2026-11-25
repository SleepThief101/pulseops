from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

UNKNOWN_CURRENCY = "UNKNOWN"


class InvalidCurrencyError(ValueError):
    """Raised when a currency code or monetary precision value is invalid."""


# ISO-4217 minor unit exponents (0, 2, 3, 4 decimal places)
ISO4217_EXPONENTS: dict[str, int] = {
    # 0-decimal currencies
    "BIF": 0,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "ISK": 0,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "PYG": 0,
    "RWF": 0,
    "UGX": 0,
    "UYI": 0,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
    # 3-decimal currencies
    "BHD": 3,
    "IQD": 3,
    "JOD": 3,
    "KWD": 3,
    "LYD": 3,
    "OMR": 3,
    "TND": 3,
    # 4-decimal currencies
    "CLF": 4,
    "UYW": 4,
    # Standard 2-decimal currencies
    "AED": 2,
    "AFN": 2,
    "ALL": 2,
    "AMD": 2,
    "ANG": 2,
    "AOA": 2,
    "ARS": 2,
    "AUD": 2,
    "AWG": 2,
    "AZN": 2,
    "BAM": 2,
    "BBD": 2,
    "BDT": 2,
    "BGN": 2,
    "BMD": 2,
    "BND": 2,
    "BOB": 2,
    "BRL": 2,
    "BSD": 2,
    "BTN": 2,
    "BWP": 2,
    "BYN": 2,
    "BZD": 2,
    "CAD": 2,
    "CDF": 2,
    "CHF": 2,
    "CNY": 2,
    "COP": 2,
    "CRC": 2,
    "CUP": 2,
    "CVE": 2,
    "CZK": 2,
    "DKK": 2,
    "DOP": 2,
    "DZD": 2,
    "EGP": 2,
    "ERN": 2,
    "ETB": 2,
    "EUR": 2,
    "FJD": 2,
    "FKP": 2,
    "GBP": 2,
    "GEL": 2,
    "GHS": 2,
    "GIP": 2,
    "GMD": 2,
    "GTQ": 2,
    "GYD": 2,
    "HKD": 2,
    "HNL": 2,
    "HTG": 2,
    "HUF": 2,
    "IDR": 2,
    "ILS": 2,
    "INR": 2,
    "IRR": 2,
    "JMD": 2,
    "KES": 2,
    "KGS": 2,
    "KHR": 2,
    "KYD": 2,
    "KZT": 2,
    "LAK": 2,
    "LBP": 2,
    "LKR": 2,
    "LRD": 2,
    "LSL": 2,
    "MAD": 2,
    "MDL": 2,
    "MGA": 2,
    "MKD": 2,
    "MMK": 2,
    "MNT": 2,
    "MOP": 2,
    "MRU": 2,
    "MUR": 2,
    "MVR": 2,
    "MWK": 2,
    "MXN": 2,
    "MYR": 2,
    "MZN": 2,
    "NAD": 2,
    "NGN": 2,
    "NIO": 2,
    "NOK": 2,
    "NPR": 2,
    "NZD": 2,
    "PAB": 2,
    "PEN": 2,
    "PGK": 2,
    "PHP": 2,
    "PKR": 2,
    "PLN": 2,
    "QAR": 2,
    "RON": 2,
    "RSD": 2,
    "RUB": 2,
    "SAR": 2,
    "SBD": 2,
    "SCR": 2,
    "SDG": 2,
    "SEK": 2,
    "SGD": 2,
    "SHP": 2,
    "SLE": 2,
    "SOS": 2,
    "SRD": 2,
    "SSP": 2,
    "STN": 2,
    "SYP": 2,
    "SZL": 2,
    "THB": 2,
    "TJS": 2,
    "TMT": 2,
    "TOP": 2,
    "TRY": 2,
    "TTD": 2,
    "TWD": 2,
    "TZS": 2,
    "UAH": 2,
    "USD": 2,
    "UYU": 2,
    "UZS": 2,
    "VES": 2,
    "WST": 2,
    "XCD": 2,
    "YER": 2,
    "ZAR": 2,
    "ZMW": 2,
    "ZWL": 2,
}

MINOR_UNIT_NAMES: dict[str, str] = {
    "INR": "paise",
    "PKR": "paisa",
    "NPR": "paisa",
    "BDT": "poisha",
    "LKR": "cents",
    "USD": "cents",
    "CAD": "cents",
    "AUD": "cents",
    "SGD": "cents",
    "NZD": "cents",
    "HKD": "cents",
    "EUR": "cents",
    "ZAR": "cents",
    "GBP": "pence",
    "CHF": "rappen",
    "JPY": "yen",
    "KRW": "won",
    "VND": "dong",
    "KWD": "fils",
    "BHD": "fils",
    "JOD": "fils",
    "IQD": "fils",
    "AED": "fils",
    "OMR": "baisa",
    "TND": "millimes",
    "LYD": "dirhams",
    "SAR": "halalas",
    "QAR": "dirhams",
    "MXN": "centavos",
    "BRL": "centavos",
    "CNY": "fen",
}

CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "INR": "₹",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "KRW": "₩",
}


def normalize_currency(
    currency: str | None,
    *,
    allow_none: bool = True,
) -> str | None:
    """Validate and uppercase an ISO-4217 3-letter currency code."""
    if currency is None:
        if allow_none:
            return None
        raise InvalidCurrencyError("Currency is required.")

    cleaned = str(currency).strip().upper()
    if not cleaned:
        if allow_none:
            return None
        raise InvalidCurrencyError("Currency cannot be empty.")

    if len(cleaned) != 3 or not cleaned.isalpha() or cleaned not in ISO4217_EXPONENTS:
        raise InvalidCurrencyError(f"Unsupported or invalid ISO-4217 currency code: {currency!r}")

    return cleaned


def get_minor_unit_exponent(
    currency: str | None,
    *,
    override_exponent: int | None = None,
) -> int:
    """Return the ISO-4217 minor unit exponent (0, 2, 3, or 4) for a currency."""
    if override_exponent is not None:
        if override_exponent < 0 or override_exponent > 4:
            raise InvalidCurrencyError(
                f"Invalid minor unit exponent: {override_exponent!r}"
            )
        return int(override_exponent)

    normalized = normalize_currency(currency, allow_none=True)
    if normalized is None:
        raise InvalidCurrencyError("Cannot determine minor-unit exponent without a currency.")
    return ISO4217_EXPONENTS[normalized]


def get_minor_unit_name(currency: str | None) -> str:
    """Return the human-readable minor-unit name (e.g. 'paise', 'cents', 'fils', 'yen')."""
    if currency is None:
        return "minor units"
    code = str(currency).strip().upper()
    if code == UNKNOWN_CURRENCY or not code:
        return "minor units"
    return MINOR_UNIT_NAMES.get(code, "minor units")


def minor_to_major_decimal(
    amount_minor: int,
    currency: str | None,
    *,
    exponent: int | None = None,
) -> Decimal:
    """Convert integer minor units into an exact Decimal major-unit value."""
    exp = get_minor_unit_exponent(currency, override_exponent=exponent)
    scaled = Decimal(int(amount_minor)).scaleb(-exp)
    if exp == 0:
        return scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    quant = Decimal("1").scaleb(-exp)
    return scaled.quantize(quant, rounding=ROUND_HALF_UP)


def major_to_minor_int(
    amount_major: Decimal | str | int,
    currency: str,
    *,
    exponent: int | None = None,
) -> int:
    """
    Convert a Decimal, string, or integer major-unit value into exact integer minor units.
    Rejects binary floats to avoid IEEE-754 representation drift.
    """
    if isinstance(amount_major, float):
        raise TypeError("Float values are forbidden for monetary conversions; pass Decimal, str, or int.")

    normalized = normalize_currency(currency, allow_none=False)
    exp = get_minor_unit_exponent(normalized, override_exponent=exponent)

    try:
        dec = Decimal(str(amount_major).strip())
    except (InvalidOperation, ValueError) as exc:
        raise InvalidCurrencyError(f"Invalid monetary amount: {amount_major!r}") from exc

    if not dec.is_finite():
        raise InvalidCurrencyError(f"Non-finite monetary amount: {amount_major!r}")

    scaled = dec * (Decimal(10) ** exp)
    if scaled != scaled.to_integral_value():
        raise InvalidCurrencyError(
            f"Amount {amount_major!r} has more than {exp} decimal places for {normalized}."
        )
    return int(scaled)


def format_minor_amount(
    amount_minor: int,
    currency: str | None,
    *,
    exponent: int | None = None,
) -> str:
    """
    Format integer minor units deterministically using Decimal and currency precision.

    Examples:
    - (100000, "INR") -> "₹1,000.00"
    - (10000, "USD")  -> "$100.00"
    - (1000, "JPY")   -> "¥1,000"
    - (1500, "KWD")   -> "KWD 1.500"
    """
    if currency is None or str(currency).strip().upper() in ("", UNKNOWN_CURRENCY):
        return f"{int(amount_minor):,} (unknown currency minor units)"

    code = str(currency).strip().upper()
    if code not in ISO4217_EXPONENTS and exponent is None:
        return f"{code} {int(amount_minor):,} (minor units)"

    major = minor_to_major_decimal(amount_minor, code, exponent=exponent)
    exp = get_minor_unit_exponent(code, override_exponent=exponent)

    sign = "-" if major < 0 else ""
    abs_major = abs(major)
    num_str = f"{abs_major:,.{exp}f}"

    symbol = CURRENCY_SYMBOLS.get(code)
    if symbol is not None:
        return f"{sign}{symbol}{num_str}"
    return f"{sign}{code} {num_str}"
