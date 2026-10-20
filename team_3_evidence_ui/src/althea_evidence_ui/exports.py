"""Export helpers for Snapshot JSON and formula-safe Claims CSV."""
from __future__ import annotations
import csv
import io
import json
import re


def _is_numeric_string(s: str) -> bool:
    """Check if string is a plain numeric representation."""
    return bool(re.match(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$", s.strip()))


def neutralize_csv_formula(val: Any) -> str:
    """
    Neutralize spreadsheet formula injection characters (=, +, -, @) for textual columns.
    Prepends a single quote (') if the text starts with formula triggers,
    while preserving genuine numeric strings intact.
    """
    if val is None:
        return ""
    text = str(val)
    if not text:
        return ""

    if text[0] in ("=", "+", "-", "@"):
        # If it is a purely numeric string (e.g. -12.5), do not neutralize as formula
        if _is_numeric_string(text):
            return text
        return "'" + text
    return text


def claims_csv(snapshot: dict) -> bytes:
    """
    Generate UTF-8 with BOM (utf-8-sig) CSV representation of claims in a snapshot.

    Neutralizes potential formula injection characters in textual columns.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")

    headers = [
        "claim_id",
        "speaker_id",
        "speaker_display_name",
        "proposition",
        "raw_quote",
        "start_time_s",
        "end_time_s",
        "period",
        "geography",
        "population",
        "measurement_basis",
        "quantity_raw_text",
        "quantity_value",
        "quantity_unit",
        "quantity_currency",
        "quantity_operator",
        "checkability",
        "missing_context",
    ]
    writer.writerow(headers)

    transcript = snapshot.get("transcript") or {}
    speakers_map = {s["speaker_id"]: s.get("display_name", "") for s in transcript.get("speakers", [])}
    segments_map = {s["segment_id"]: s for s in transcript.get("segments", [])}

    analysis = snapshot.get("analysis") or {}
    claims = analysis.get("claims", [])

    for c in claims:
        speaker_id = c.get("speaker_id", "")
        speaker_name = speakers_map.get(speaker_id, speaker_id)

        # Source span quotes and times
        source_spans = c.get("source_spans", [])
        if source_spans:
            primary_span = source_spans[0]
            raw_quote = primary_span.get("quote", "")
            seg = segments_map.get(primary_span.get("segment_id", ""))
            start_s = seg.get("start_s", "") if seg else ""
            end_s = seg.get("end_s", "") if seg else ""
        else:
            raw_quote = ""
            start_s = ""
            end_s = ""

        # Quantity
        qty = c.get("quantity") or {}
        qty_raw = qty.get("raw_text", "")
        qty_val = qty.get("value", "")
        qty_unit = qty.get("unit", "")
        qty_curr = qty.get("currency", "")
        qty_op = qty.get("operator", "")

        # Missing context
        missing = "; ".join(c.get("missing_context", []))

        row = [
            c.get("claim_id", ""),
            speaker_id,
            neutralize_csv_formula(speaker_name),
            neutralize_csv_formula(c.get("proposition", "")),
            neutralize_csv_formula(raw_quote),
            str(start_s) if start_s != "" else "",
            str(end_s) if end_s != "" else "",
            neutralize_csv_formula(c.get("period")),
            neutralize_csv_formula(c.get("geography")),
            neutralize_csv_formula(c.get("population")),
            neutralize_csv_formula(c.get("measurement_basis")),
            neutralize_csv_formula(qty_raw),
            str(qty_val) if qty_val is not None else "",
            neutralize_csv_formula(qty_unit),
            neutralize_csv_formula(qty_curr),
            qty_op,
            c.get("checkability", ""),
            neutralize_csv_formula(missing),
        ]
        writer.writerow(row)

    return output.getvalue().encode("utf-8-sig")


def snapshot_json(snapshot: dict) -> bytes:
    """
    Generate human-readable complete JSON export of the snapshot.
    Preserves actual unmodified data.
    """
    return json.dumps(snapshot, indent=2, ensure_ascii=False).encode("utf-8")
