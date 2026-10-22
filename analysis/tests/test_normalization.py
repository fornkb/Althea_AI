from decimal import Decimal
import pytest
from althea_analysis import normalize_quantity
from althea_analysis.validation import validate_quantity


@pytest.mark.parametrize("raw,value,unit,currency", [
    ("2.5 million", "2500000", "count", None), ("2500000", "2500000", "count", None),
    ("2.5M USD", "2500000", "currency", "USD"),
    ("2,500,000 US dollars", "2500000", "currency", "USD"),
    ("5 percent", "5", "percent", None), ("5%", "5", "percent", None),
    ("1 percentage point", "1", "percentage_point", None),
    ("25 lakh", "2500000", "count", None), ("0.25 crore", "2500000", "count", None),
    ("1 km", "1000", "m", None), ("1000 m", "1000", "m", None),
    ("1 kg", "1", "kg", None), ("1000 g", "1", "kg", None),
    ("five percent", "5", "percent", None), ("negative five", "-5", "count", None),
    ("-2.50 million USD", "-2500000", "currency", "USD"),
    ("0.000001", "0.000001", "count", None), ("10k", "10000", "count", None),
    ("twenty-five", "25", "count", None), ("one hundred", "100", "count", None),
    ("₹10", "10", "currency", "INR"), ("€10", "10", "currency", "EUR"),
])
def test_canonical_numbers(raw, value, unit, currency):
    q = normalize_quantity(raw, context={"unit": "count"})
    assert (q["value"], q["unit"], q["currency"]) == (value, unit, currency)
    assert q["raw_text"] == raw
    assert validate_quantity(q) == q


@pytest.mark.parametrize("raw,operator", [("at least 10", "ge"), ("over 10", "gt"),
    ("about 10", "approx"), ("at most 10", "le"), ("under 10", "lt")])
def test_operators(raw, operator):
    assert normalize_quantity(raw, context={"unit": "count"})["operator"] == operator


def test_range():
    q = normalize_quantity("between 10 and 12", context={"unit": "count"})
    assert (q["operator"], q["value"], q["lower"], q["upper"]) == ("range", None, "10", "12")


@pytest.mark.parametrize("raw", ["NaN", "infinity", "-inf", "2e6", "10 XYZ", "$10", "10 dollars", "ten-ish", "12,34", "between 12 and 10"])
def test_unsupported_is_not_invented(raw):
    assert normalize_quantity(raw, context={"unit": "count"}) is None


def test_currency_and_year_context():
    assert normalize_quantity("$10", context={"currency": "CAD"})["currency"] == "CAD"
    assert normalize_quantity("10 XYZ", context={"currency": "USD"}) is None
    assert normalize_quantity("2024", context={"period": "2024", "unit": "count"}) is None
    assert normalize_quantity("25 lakh", context={}) is None
    assert normalize_quantity("10 m", context={})["value"] == "10"
    assert normalize_quantity("10M", context={"unit": "count"})["value"] == "10000000"
    assert normalize_quantity("25 lakh", context={"metric": "population"})["value"] == "2500000"
    assert normalize_quantity("10", context={"metric": "transport budget"}) is None


def test_quantity_rejects_broken_semantics():
    q = normalize_quantity("10", context={"unit": "count"})
    q.update(operator="range", value=None, lower="12", upper="10")
    with pytest.raises(ValueError):
        validate_quantity(q)
