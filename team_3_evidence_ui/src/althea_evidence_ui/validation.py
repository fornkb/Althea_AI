"""Validation helpers and semantic checks for Althea Evidence UI."""
from __future__ import annotations
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from pydantic import ValidationError

from althea_evidence_ui._contract import (
    Verification,
    Analysis,
    PairVerdict,
    Unverified,
    Evidence,
    GroundingAttribution,
)
from althea_evidence_ui.errors import ContractError

TRACKING_PARAM_PATTERNS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "msclkid",
    "mc_eid",
    "_ga",
    "ref",
}


def canonical_json(data: Any) -> bytes:
    """Format data as canonical JSON bytes."""
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_digest(data: Any) -> str:
    """Compute SHA256 hex digest of canonical JSON."""
    return hashlib.sha256(canonical_json(data)).hexdigest()


def compute_verification_id(
    analysis_id: str,
    evidence: list[dict],
    results: list[dict],
    unverified: list[dict],
    grounding_attributions: list[dict],
) -> str:
    """Compute verification_id: 've_' + digest({analysis_id, evidence, results, unverified, grounding_attributions})."""
    body = {
        "analysis_id": analysis_id,
        "evidence": evidence,
        "results": results,
        "unverified": unverified,
        "grounding_attributions": grounding_attributions,
    }
    return "ve_" + sha256_digest(body)


def compute_transcript_id(
    content_sha256: str,
    language: str,
    duration_s: float,
    speakers: list[dict],
    segments: list[dict],
) -> str:
    """Compute transcript_id: 'tr_' + digest({content_sha256, language, duration_s, speakers, segments})."""
    body = {
        "content_sha256": content_sha256,
        "language": language,
        "duration_s": duration_s,
        "speakers": speakers,
        "segments": segments,
    }
    return "tr_" + sha256_digest(body)


def is_valid_http_url(url: str) -> bool:
    """Validate that url is HTTP(S) and not javascript, data, or file."""
    if not isinstance(url, str) or not url.strip():
        return False
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
    return True


def normalize_url(url: str) -> str:
    """
    Normalize URL for deduplication and canonical ordering:
    - Lowercase scheme and netloc.
    - Remove default ports (80 for http, 443 for https).
    - Remove fragment.
    - Strip tracking parameters.
    - Sort query parameters.
    """
    if not is_valid_http_url(url):
        raise ContractError(f"Invalid HTTP(S) URL: {url!r}")

    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    if (scheme == "http" and netloc.endswith(":80")) or (scheme == "https" and netloc.endswith(":443")):
        netloc = netloc.rsplit(":", 1)[0]

    # Clean path
    path = parsed.path or "/"

    # Clean query
    query_params = parse_qsl(parsed.query, keep_blank_values=True)
    filtered_params = [
        (k, v) for k, v in query_params if k.lower() not in TRACKING_PARAM_PATTERNS
    ]
    filtered_params.sort(key=lambda x: (x[0], x[1]))
    clean_query = urlencode(filtered_params)

    # Empty fragment
    return urlunparse((scheme, netloc, path, parsed.params, clean_query, ""))


def validate_verification(payload: dict, analysis: dict) -> dict:
    """
    Validate verification payload against frozen contract and upstream analysis.

    Returns the validated payload as a dict (via model_dump(mode='json')).
    Raises ContractError on any contract violation.
    """
    if not isinstance(payload, dict):
        raise ContractError("Verification payload must be a dictionary")
    if not isinstance(analysis, dict):
        raise ContractError("Analysis context must be a dictionary")

    # 1. Base Pydantic wire contract check
    try:
        verification_model = Verification.model_validate(payload)
    except ValidationError as e:
        raise ContractError(f"Verification contract validation error: {e}") from e

    # 2. Match upstream analysis_id
    if verification_model.analysis_id != analysis.get("analysis_id"):
        raise ContractError(
            f"Verification analysis_id {verification_model.analysis_id!r} does not match "
            f"analysis analysis_id {analysis.get('analysis_id')!r}"
        )

    # 3. Identify eligible pairs in analysis
    analysis_pairs = {p["pair_id"]: p for p in analysis.get("pairs", [])}
    eligible_pair_ids = {
        p_id
        for p_id, p in analysis_pairs.items()
        if p.get("relation") in ("direct_conflict", "numeric_discrepancy")
    }

    # 4. Map evidence records
    evidence_by_id: dict[str, Evidence] = {}
    evidence_by_pair: dict[str, list[Evidence]] = {}

    for ev in verification_model.evidence:
        # Check URL
        if not is_valid_http_url(ev.url):
            raise ContractError(f"Evidence {ev.evidence_id} has invalid URL: {ev.url!r}")

        # Check content origin rules
        if ev.content_origin == "metadata_only" and ev.content is not None:
            raise ContractError(
                f"Evidence {ev.evidence_id} with content_origin='metadata_only' must have null content"
            )

        # Check evidence ID format: ev_<pair_id>_0001
        ev_pattern = rf"^ev_{re.escape(ev.pair_id)}_([0-9]{{4}})$"
        m = re.match(ev_pattern, ev.evidence_id)
        if not m:
            raise ContractError(
                f"Evidence ID {ev.evidence_id!r} does not match required format 'ev_{ev.pair_id}_0001'"
            )

        evidence_by_id[ev.evidence_id] = ev
        evidence_by_pair.setdefault(ev.pair_id, []).append(ev)

    # Check evidence ID sequence order per pair
    for p_id, ev_list in evidence_by_pair.items():
        for expected_idx, ev in enumerate(ev_list, start=1):
            expected_id = f"ev_{p_id}_{expected_idx:04d}"
            if ev.evidence_id != expected_id:
                raise ContractError(
                    f"Evidence IDs for pair {p_id} must be strictly sequential starting at 0001: "
                    f"expected {expected_id}, found {ev.evidence_id}"
                )

    # 5. Check universe of eligible pairs
    results_pair_ids = [r.pair_id for r in verification_model.results]
    unverified_pair_ids = [u.pair_id for u in verification_model.unverified]

    # Check for duplicates in results and unverified
    if len(results_pair_ids) != len(set(results_pair_ids)):
        raise ContractError("Duplicate pair_id found in verification results")
    if len(unverified_pair_ids) != len(set(unverified_pair_ids)):
        raise ContractError("Duplicate pair_id found in verification unverified")

    combined_set = set(results_pair_ids) | set(unverified_pair_ids)
    overlap = set(results_pair_ids) & set(unverified_pair_ids)
    if overlap:
        raise ContractError(f"Pair IDs cannot appear in both results and unverified: {overlap}")

    # No ineligible pairs may appear
    ineligible_in_results = set(results_pair_ids) - eligible_pair_ids
    if ineligible_in_results:
        raise ContractError(
            f"Results contain ineligible or unknown pair IDs: {ineligible_in_results}"
        )
    ineligible_in_unverified = set(unverified_pair_ids) - eligible_pair_ids
    if ineligible_in_unverified:
        raise ContractError(
            f"Unverified contains ineligible or unknown pair IDs: {ineligible_in_unverified}"
        )

    # Every eligible pair must appear exactly once across results + unverified
    missing_eligible = eligible_pair_ids - combined_set
    if missing_eligible:
        raise ContractError(
            f"Every eligible pair must occur in results or unverified. Missing: {missing_eligible}"
        )

    # 6. Check each PairVerdict in results
    for pv in verification_model.results:
        pair_info = analysis_pairs[pv.pair_id]
        expected_claims = {pair_info["claim_a_id"], pair_info["claim_b_id"]}

        if len(pv.verdicts) != 2:
            raise ContractError(
                f"PairVerdict for {pv.pair_id} must contain exactly 2 claim verdicts, found {len(pv.verdicts)}"
            )

        verdict_claim_ids = {cv.claim_id for cv in pv.verdicts}
        if verdict_claim_ids != expected_claims:
            raise ContractError(
                f"PairVerdict for {pv.pair_id} claims {verdict_claim_ids} do not match "
                f"pair claims {expected_claims}"
            )

        for cv in pv.verdicts:
            # Check each evidence ref
            has_substantive_match = False
            for ref in cv.evidence_refs:
                if ref.evidence_id not in evidence_by_id:
                    raise ContractError(
                        f"Evidence reference {ref.evidence_id!r} in claim verdict {cv.claim_id} "
                        f"does not exist in verification evidence"
                    )
                ev_rec = evidence_by_id[ref.evidence_id]
                if ev_rec.pair_id != pv.pair_id:
                    raise ContractError(
                        f"Evidence reference {ref.evidence_id} belongs to pair {ev_rec.pair_id}, "
                        f"not {pv.pair_id}"
                    )
                if cv.claim_id not in ev_rec.claim_ids:
                    raise ContractError(
                        f"Evidence {ref.evidence_id} does not cite claim {cv.claim_id} in claim_ids"
                    )

                # Check if substantive
                is_substantive = ev_rec.content_origin in ("retrieved_excerpt", "grounded_summary") and bool(ev_rec.content)
                if cv.status == "supported" and ref.stance == "supports" and is_substantive:
                    has_substantive_match = True
                elif cv.status == "refuted" and ref.stance == "refutes" and is_substantive:
                    has_substantive_match = True

            if cv.status in ("supported", "refuted") and not has_substantive_match:
                raise ContractError(
                    f"Claim {cv.claim_id} has status {cv.status!r} but lacks a matching substantive "
                    f"evidence reference with stance {cv.status[:6]}s ('metadata_only' cannot support/refute)"
                )

    # 7. Check grounding attributions
    ga_pairs = set()
    for ga in verification_model.grounding_attributions:
        if ga.pair_id in ga_pairs:
            raise ContractError(f"Duplicate grounding attribution for pair {ga.pair_id}")
        ga_pairs.add(ga.pair_id)
        if ga.pair_id not in set(results_pair_ids):
            raise ContractError(
                f"Grounding attribution pair {ga.pair_id} was not checked in results"
            )

    # 8. Check verification_id digest
    raw_dict = verification_model.model_dump(mode="json")
    expected_verification_id = compute_verification_id(
        analysis_id=raw_dict["analysis_id"],
        evidence=raw_dict["evidence"],
        results=raw_dict["results"],
        unverified=raw_dict["unverified"],
        grounding_attributions=raw_dict["grounding_attributions"],
    )
    if verification_model.verification_id != expected_verification_id:
        raise ContractError(
            f"Verification ID mismatch: payload has {verification_model.verification_id!r}, "
            f"expected {expected_verification_id!r}"
        )

    return raw_dict
