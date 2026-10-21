"""Conservative explicit quantity parsing. No float arithmetic or external models."""
import re
from decimal import Decimal, InvalidOperation, localcontext
from ._contract import Quantity

NORMALIZATION_VERSION = "decimal-v1.0.0"
_SMALL = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(), range(20)))
_SMALL.update(dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10))))
_SCALES = {"k": 1000, "thousand": 1000, "million": 1000000, "M": 1000000,
           "billion": 1000000000, "lakh": 100000, "lakhs": 100000,
           "crore": 10000000, "crores": 10000000}
_CURRENCIES = {"USD": r"US dollars?|U\.S\. dollars?|USD|US\$",
               "INR": r"INR|Indian rupees?|rupees?|₹",
               "EUR": r"EUR|euros?|€", "GBP": r"GBP|pounds? sterling|£",
               "CAD": r"CAD|Canadian dollars?|CA\$", "AUD": r"AUD|Australian dollars?|AU\$",
               "JPY": r"JPY|Japanese yen", "CHF": r"CHF|Swiss francs?",
               "CNY": r"CNY|Chinese yuan", "NZD": r"NZD|New Zealand dollars?"}


def count_context(context):
    if context.get("unit") == "count" or context.get("quantity_kind") == "count":
        return True
    metric = (context.get("metric") or "").casefold()
    if re.search(r"\b(rate|budget|allocation|cost|price|distance|length|weight|mass|change)\b", metric):
        return False
    return bool(re.search(r"\b(count|number|population|residents|people|passengers|commuters|vehicles|buildings|books|libraries|jobs|deaths|votes|visitors|attendees|stations)\b", metric))


def decimal_text(value):
    if not value.is_finite():
        raise ValueError("Non-finite quantity")
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _number(text):
    text = text.strip()
    scale = 1
    for token, factor in _SCALES.items():
        match = re.search(r"\s*" + re.escape(token) + r"$", text,
                          flags=0 if token == "M" else re.I)
        if match:
            text, scale = text[:match.start()].strip(), factor
            break
    negative = text.startswith("minus ") or text.startswith("negative ")
    text = re.sub(r"^(minus|negative)\s+", "", text)
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", text):
        number = Decimal(text)
    elif re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
        number = Decimal(text.replace(",", ""))
    else:
        words = text.casefold().replace("-", " ").split()
        if not words:
            raise ValueError("No quantity")
        # Small English values; deliberately reject unsupported compound grammars.
        if len(words) == 1 and words[0] in _SMALL:
            number = Decimal(_SMALL[words[0]])
        elif len(words) == 2 and words[0] in _SMALL and _SMALL[words[0]] >= 20 and words[1] in _SMALL and 0 < _SMALL[words[1]] < 10:
            number = Decimal(_SMALL[words[0]] + _SMALL[words[1]])
        elif len(words) == 2 and words[0] in _SMALL and words[1] == "hundred":
            number = Decimal(_SMALL[words[0]] * 100)
        else:
            raise ValueError("Unsupported number")
    return (-number if negative else number) * scale


def normalize_quantity(raw: str, *, context: dict) -> dict | None:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 256:
        return None
    text = raw.strip().replace("−", "-")
    if re.search(r"\b(nan|inf|infinity)\b", text, re.I):
        return None
    if re.fullmatch(r"(?:19|20|21)\d{2}", text) and (context.get("period") == text or context.get("is_year")):
        return None
    operator = "eq"
    prefixes = [(r"at least\s+", "ge"), (r"(?:over|more than|greater than)\s+", "gt"),
                (r"(?:at most|no more than)\s+", "le"), (r"(?:under|less than)\s+", "lt"),
                (r"(?:about|approximately|around)\s+", "approx")]
    for pattern, op in prefixes:
        match = re.match(pattern, text, re.I)
        if match:
            operator, text = op, text[match.end():]
            break
    currency = None
    for code, pattern in _CURRENCIES.items():
        # Unit markers can be before or after the number, never inside words.
        cleaned, n = re.subn(r"(?<![a-z])(?:" + pattern + r")(?![a-z])", "", text, flags=re.I)
        if n:
            if currency and currency != code:
                return None
            currency, text = code, cleaned.strip()
    if "$" in text or re.search(r"\bdollars?\b", text, re.I):
        supplied = context.get("currency")
        if supplied not in _CURRENCIES or currency and currency != supplied:
            return None
        currency = supplied
        text = re.sub(r"\$|\bdollars?\b", "", text, flags=re.I).strip()
    unit, multiplier = ("currency", Decimal(1)) if currency else ("count", Decimal(1))
    explicit_unit = False
    units = [(r"percentage points?|pp", "percentage_point", "1"),
             (r"percent|%", "percent", "1"), (r"kilomet(?:er|re)s?|km", "m", "1000"),
             (r"met(?:er|re)s?|(?-i:m)", "m", "1"), (r"kilograms?|kg", "kg", "1"),
             (r"grams?|g", "kg", "0.001")]
    for pattern, name, factor in ([] if currency else units):
        match = re.search(r"\s*(?:" + pattern + r")$", text, re.I)
        if match:
            if currency:
                return None
            text, unit, multiplier = text[:match.start()].strip(), name, Decimal(factor)
            explicit_unit = True
            break
    # bare magnitude is a count only when the extracted context identifies one
    if not currency and not explicit_unit and not count_context(context):
        return None
    try:
        with localcontext() as decimal_context:
            decimal_context.prec = 600
            range_match = re.fullmatch(r"between (.+) and (.+)", text, re.I)
            if range_match:
                lo, hi = (_number(x) * multiplier for x in range_match.groups())
                if lo > hi or operator != "eq":
                    return None
                quantity = dict(value=None, lower=decimal_text(lo), upper=decimal_text(hi), operator="range")
            else:
                quantity = dict(value=decimal_text(_number(text) * multiplier), lower=None, upper=None, operator=operator)
        return Quantity.model_validate(dict(raw_text=raw, **quantity, unit=unit, currency=currency,
                                           basis=context.get("measurement_basis", context.get("basis"))), strict=True).model_dump(mode="json")
    except (ValueError, InvalidOperation):
        return None
