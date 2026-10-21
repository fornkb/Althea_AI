from decimal import Decimal, localcontext
from .normalization import decimal_text
from .utils import normalized
from .dto import ComparisonDTO
from .errors import invalid

COMPARISON_VERSION = "scope-compare-v1.0.0"
SCOPE_FIELDS = ("subject", "metric", "period", "geography", "population", "measurement_basis")


def assessment(left, right, relation, explanation, *, difference=None, unit=None, method="deterministic"):
    a, b = sorted((left["claim_id"], right["claim_id"]))
    return dict(claim_a_id=a, claim_b_id=b, relation=relation, explanation=explanation,
                numeric_difference=difference, numeric_difference_unit=unit,
                priority={"numeric_discrepancy": 1, "direct_conflict": 2}.get(relation, 3), method=method)


def compare_deterministic(left, right):
    # Null never acts as a wildcard, and a known mismatch precedes subtraction.
    for field in SCOPE_FIELDS[2:]:
        a, b = left.get(field), right.get(field)
        if a is not None and b is not None and normalized(a) != normalized(b):
            return assessment(left, right, "different_scope", f"Explicit {field} differs: {a} versus {b}; no contradiction established.")
    if any(left.get(k) is None or right.get(k) is None for k in SCOPE_FIELDS):
        return assessment(left, right, "insufficient_context", "Required scope is unknown; numeric values alone cannot establish a disagreement.")
    if left.get("checkability") == "needs_context" or right.get("checkability") == "needs_context":
        return assessment(left, right, "insufficient_context", "At least one claim needs context before its scope can be compared.")
    # Canonical labels may still contain paraphrases; use hosted reasoning for those.
    if any(normalized(left[k]) != normalized(right[k]) for k in SCOPE_FIELDS[:2]):
        return None
    a, b = left.get("quantity"), right.get("quantity")
    if not a or not b:
        return None
    if any(a[k] != b[k] for k in ("unit", "currency", "basis")):
        # Percent and percentage points may describe the same underlying change.
        return None
    if a["operator"] != "eq" or b["operator"] != "eq":
        return None
    # Qualifiers such as "real"/"per capita" cannot be silently ignored.
    if {normalized(x) for x in left["qualifiers"]} != {normalized(x) for x in right["qualifiers"]}:
        return None
    with localcontext() as ctx:
        ctx.prec = max(100, len(a["value"]) + len(b["value"]) + 10)
        diff = decimal_text(abs(Decimal(b["value"]) - Decimal(a["value"])))
    relation = "compatible" if Decimal(diff) == 0 else "numeric_discrepancy"
    return assessment(left, right, relation, "Same explicit measured scope and unit; exact values " +
                      ("are equal." if relation == "compatible" else f"differ by {diff} {a['unit']}."),
                      difference=diff, unit=a["unit"])


def parse_comparison(payload, selected, claims):
    dto = ComparisonDTO.model_validate(payload)
    expected, found, results = set(selected), set(), []
    for pair in dto.pairs:
        key = pair.claim_a_id, pair.claim_b_id
        if key not in expected or key in found:
            raise invalid("Comparison returned an extra, reversed or duplicate pair.")
        found.add(key)
        left, right = (claims[k] for k in key)
        if pair.relation == "numeric_discrepancy" and (not left["quantity"] or not right["quantity"]):
            raise invalid("Numeric discrepancy requires two numeric claims.")
        results.append(assessment(left, right, pair.relation, pair.explanation, method="llm"))
    if found != expected:
        raise invalid("Comparison omitted a selected candidate pair.")
    return results
