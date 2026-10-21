"""Strict wire and cross-reference checks beyond the frozen base models."""
import re
from decimal import Decimal
from pydantic import ValidationError
from ._contract import Analysis, Transcript, Quantity, Usage
from .errors import AnalysisError
from .utils import transcript_identity, analysis_identity


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_quantity(payload):
    q = Quantity.model_validate(payload, strict=True).model_dump(mode="json")
    if q["operator"] == "range":
        _require(q["value"] is None and q["lower"] is not None and q["upper"] is not None,
                 "Range quantities require bounds and null value.")
        _require(Decimal(q["lower"]) <= Decimal(q["upper"]), "Quantity bounds are reversed.")
    else:
        _require(q["value"] is not None and q["lower"] is None and q["upper"] is None,
                 "Non-range quantities require a value and null bounds.")
    _require(bool(re.fullmatch(r"[A-Z]{3}", q["currency"] or "")) if q["unit"] == "currency"
             else q["currency"] is None, "Currency and unit disagree.")
    return q


def validate_transcript(payload):
    try:
        t = Transcript.model_validate(payload, strict=True).model_dump(mode="json")
        _require(1 <= len(t["speakers"]) <= 4, "Transcript requires one to four speakers.")
        speakers = [s["speaker_id"] for s in t["speakers"]]
        _require(speakers == [f"speaker_{i:02d}" for i in range(1, len(speakers) + 1)],
                 "Speaker IDs must be unique and sequential.")
        previous = -1
        for i, segment in enumerate(t["segments"], 1):
            _require(segment["segment_id"] == f"seg_{i:04d}", "Segment IDs must follow source order.")
            _require(segment["speaker_id"] in speakers, "Segment speaker does not exist.")
            _require(0 <= segment["start_s"] < segment["end_s"] <= t["duration_s"] + .25,
                     "Invalid segment interval.")
            _require(segment["start_s"] >= previous, "Segments are not chronological.")
            _require(all(round(segment[k], 3) == segment[k] for k in ("start_s", "end_s")),
                     "Segment times must be rounded to three decimal places.")
            previous = segment["start_s"]
        _require(t["transcript_id"] == transcript_identity(t), "Transcript content identity does not match.")
        return t
    except (ValueError, TypeError, KeyError) as exc:
        code = "AUDIO_TOO_LONG" if isinstance(payload, dict) and isinstance(payload.get("duration_s"), (int, float)) and payload["duration_s"] > 300 else "INVALID_INPUT"
        raise AnalysisError(code, "Invalid transcript: English, stable references, valid timing and content identity are required.") from exc


def validate_usage(payload, operation):
    usage = Usage.model_validate(payload, strict=True).model_dump(mode="json")
    _require(usage["stage"] == operation, "Usage stage does not match the operation.")
    return usage


def validate_analysis(payload: dict, transcript: dict) -> dict:
    t = validate_transcript(transcript)
    try:
        a = Analysis.model_validate(payload, strict=True).model_dump(mode="json")
        _require(a["transcript_id"] == t["transcript_id"], "Analysis transcript reference does not match.")
        _require(len(a["claims"]) <= 30 and len(a["pairs"]) <= 60, "Analysis exceeds demo limits.")
        segments = {s["segment_id"]: s for s in t["segments"]}
        positions = {s["segment_id"]: i for i, s in enumerate(t["segments"])}
        previous = (-1, -1)
        for i, claim in enumerate(a["claims"], 1):
            _require(claim["claim_id"] == f"cl_{i:04d}", "Claim IDs must be unique and sequential.")
            _require(bool(claim["source_spans"]), "Claim has no source spans.")
            span_positions = []
            for span in claim["source_spans"]:
                segment = segments.get(span["segment_id"])
                _require(segment is not None, "Source segment does not exist.")
                _require(segment["speaker_id"] == claim["speaker_id"], "Source span belongs to a different speaker.")
                start, end = span["start_char"], span["end_char"]
                _require(0 <= start < end <= len(segment["text"]), "Source offsets are invalid.")
                _require(segment["text"][start:end] == span["quote"], "Source quote is not exact.")
                span_positions.append((positions[span["segment_id"]], start))
            _require(span_positions == sorted(set(span_positions)), "Source spans must be unique and ordered.")
            _require(min(span_positions) >= previous, "Claims are not in source order.")
            previous = min(span_positions)
            for field in ("subject", "metric", "period", "geography", "population", "measurement_basis"):
                _require(claim[field] is None or bool(claim[field].strip()), "Scope strings cannot be blank.")
            unknown = [k for k in ("subject", "metric", "period", "geography", "population", "measurement_basis") if claim[k] is None]
            _require(not unknown or bool(claim["missing_context"]), "Unknown scope must be recorded as missing context.")
            if claim["checkability"] == "checkable":
                _require(bool(claim["subject"]) and bool(claim["metric"]) and bool(claim["period"]), "Checkable claims need subject, metric and a time scope or explicit non-applicability.")
            else:
                _require(bool(claim["missing_context"]), "Needs-context claim lacks missing context.")
            if claim["quantity"]:
                q = validate_quantity(claim["quantity"])
                _require(claim["quantity"]["basis"] == claim["measurement_basis"], "Quantity basis does not match claim.")
                _require(any(q["raw_text"] in s["quote"] for s in claim["source_spans"]),
                         "Quantity wording is absent from supporting quotes.")
                from .normalization import normalize_quantity, _CURRENCIES
                code = q["currency"]
                pattern = _CURRENCIES.get(code)
                explicit_currency = code if pattern and any(
                    re.search(r"(?<!\w)(?:" + pattern + r")(?!\w)", s["text"], re.I)
                    for s in t["segments"] if s["speaker_id"] == claim["speaker_id"]) else None
                canonical_quantity = normalize_quantity(q["raw_text"], context={**claim,
                    "currency": explicit_currency})
                _require(q == canonical_quantity, "Quantity does not follow explicit source wording and normalization.")
        claims = {c["claim_id"]: c for c in a["claims"]}
        tuples = []
        for i, pair in enumerate(a["pairs"], 1):
            key = (pair["claim_a_id"], pair["claim_b_id"])
            _require(pair["pair_id"] == f"pair_{i:04d}", "Pair IDs must be sequential.")
            _require(key[0] < key[1] and all(k in claims for k in key), "Invalid pair reference or order.")
            left, right = (claims[k] for k in key)
            _require(left["speaker_id"] != right["speaker_id"], "Same-speaker pair is forbidden.")
            tuples.append(key)
            expected_priority = {"numeric_discrepancy": 1, "direct_conflict": 2}.get(pair["relation"], 3)
            _require(pair["priority"] == expected_priority, "Incorrect pair priority.")
            difference = pair["numeric_difference"]
            _require((difference is None) == (pair["numeric_difference_unit"] is None), "Difference unit must match difference presence.")
            from .comparison import compare_deterministic
            deterministic = compare_deterministic(left, right)
            if deterministic is not None:
                _require(pair["relation"] == deterministic["relation"], "Assessment contradicts safe deterministic scope/arithmetic.")
                _require(difference == deterministic["numeric_difference"] and pair["numeric_difference_unit"] == deterministic["numeric_difference_unit"], "Missing or incorrect safe arithmetic.")
            elif difference is not None:
                raise ValueError("Subtraction is not justified for this pair.")
            _require(pair["relation"] != "numeric_discrepancy" or (
                left["quantity"] is not None and right["quantity"] is not None), "Numeric discrepancy requires quantities.")
        _require(tuples == sorted(set(tuples)), "Pairs must be unique and sorted.")
        _require(a["analysis_id"] == analysis_identity(a), "Analysis content identity does not match.")
        return a
    except (ValueError, TypeError, KeyError) as exc:
        raise AnalysisError("CONTRACT_INVALID", "Analysis violates the frozen wire contract or source/scope semantics.") from exc
