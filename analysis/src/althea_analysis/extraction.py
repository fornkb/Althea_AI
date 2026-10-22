"""Validate source proposals, normalize quantities, deduplicate and assign stable IDs."""
from pydantic import ValidationError
from .dto import ExtractionDTO, ClaimProposal
from .normalization import normalize_quantity
from .utils import canonical, normalized, issue

EXTRACTION_VERSION = "atomic-extract-v1.1.0"


def parse_extraction(payload, transcript, max_claims=30):
    dto = ExtractionDTO.model_validate(payload)
    segments = {s["segment_id"]: s for s in transcript["segments"]}
    positions = {s["segment_id"]: i for i, s in enumerate(transcript["segments"])}
    valid, rejected, issues = [], [], []
    for index, raw in enumerate(dto.claims):
        try:
            c = ClaimProposal.model_validate(raw).model_dump()
            spans = []
            for proposed in c["source_spans"]:
                segment = segments.get(proposed["segment_id"])
                if segment is None or segment["speaker_id"] != c["speaker_id"]:
                    raise ValueError("Nonexistent or wrong-speaker source segment")
                text, quote = segment["text"], proposed["quote"]
                occurrences, start = [], 0
                while (offset := text.find(quote, start)) != -1:
                    occurrences.append(offset)
                    start = offset + 1
                if len(occurrences) == 1:
                    start = occurrences[0]
                elif len(occurrences) > 1:
                    start = proposed["start_char"]
                    if start not in occurrences or proposed["end_char"] != start + len(quote):
                        raise ValueError("Repeated quote lacks unique valid offsets")
                else:
                    raise ValueError("Quote does not occur exactly in source")
                spans.append(dict(segment_id=segment["segment_id"], start_char=start,
                                  end_char=start + len(quote), quote=quote))
            unique = {canonical(s): s for s in spans}
            c["source_spans"] = sorted(unique.values(), key=lambda s: (positions[s["segment_id"]], s["start_char"]))
            currency_context = c.pop("currency_context")
            quantity_raw = c.pop("quantity_raw")
            if quantity_raw and not any(quantity_raw in s["quote"] for s in c["source_spans"]):
                raise ValueError("Numeric wording is not present in the supporting quotations")
            # Currency supplied for an ambiguous symbol must also be evidenced in
            # this speaker's transcript, rather than invented by the extractor.
            if currency_context:
                from .normalization import _CURRENCIES
                import re
                pattern = _CURRENCIES.get(currency_context)
                if not pattern or not any(re.search(r"(?<!\w)(?:" + pattern + r")(?!\w)",
                          s["text"], re.I) for s in transcript["segments"] if s["speaker_id"] == c["speaker_id"]):
                    raise ValueError("Currency context is not evidenced by this speaker")
            context = {**c, "currency": currency_context}
            c["quantity"] = normalize_quantity(quantity_raw, context=context) if quantity_raw else None
            if quantity_raw and c["quantity"] is None:
                c["missing_context"].append("quantity could not be normalized: explicit unit/currency or supported wording required")
                c["checkability"] = "needs_context"
            if c["quantity"] and c["quantity"]["operator"] != "eq":
                prefix = quantity_raw.casefold()
                if prefix not in {x.casefold() for x in c["qualifiers"]}:
                    c["qualifiers"].append(quantity_raw)
            for field in ("subject", "metric", "period", "geography", "population", "measurement_basis"):
                if c[field] is not None and not c[field].strip():
                    raise ValueError("Blank scope string")
                aliases = {"period": ("period", "date", "time", "year"),
                           "population": ("population",),
                           "measurement_basis": ("measurement_basis", "measurement definition", "basis")}.get(field, (field,))
                documented = any(alias in note.casefold() for alias in aliases for note in c["missing_context"])
                if c[field] is None and not documented and (
                        field in ("subject", "metric", "period", "geography") or not c["missing_context"]):
                    c["missing_context"].append(field)
            if not c["subject"] or not c["metric"] or not c["period"]:
                c["checkability"] = "needs_context"
            c["missing_context"] = list(dict.fromkeys(c["missing_context"]))
            valid.append(c)
        except (ValueError, TypeError, KeyError):
            rejected.append(index)
    valid.sort(key=lambda c: (positions[c["source_spans"][0]["segment_id"]], c["source_spans"][0]["start_char"], c["proposition"]))
    ledger, seen = [], {}
    for c in valid:
        # Every semantic field and speaker participates; cross-speaker merging is impossible.
        signature = canonical({k: normalized(v) if isinstance(v, str) else v
                               for k, v in c.items() if k != "source_spans"})
        if signature in seen:
            old = seen[signature]
            unique = {canonical(s): s for s in old["source_spans"] + c["source_spans"]}
            old["source_spans"] = sorted(unique.values(), key=lambda s: (positions[s["segment_id"]], s["start_char"]))
        else:
            ledger.append(c)
            seen[signature] = c
    if rejected:
        issues.append(issue("CLAIMS_DROPPED", f"Dropped {len(rejected)} unusable provider proposals after source/schema checks."))
    if len(ledger) > max_claims:
        issues.append(issue("CLAIMS_TRUNCATED", f"Kept the first {max_claims} of {len(ledger)} validated claims in source order."))
    claims = [dict(claim_id=f"cl_{i:04d}", **c) for i, c in enumerate(ledger[:max_claims], 1)]
    return claims, issues, rejected, len(dto.claims)
