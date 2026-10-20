"""Unit tests for semantic evidence validation and contract enforcement."""
import copy
import json
from pathlib import Path
import pytest

from althea_evidence_ui.validation import (
    validate_verification,
    normalize_url,
    is_valid_http_url,
    canonical_json,
    sha256_digest,
    compute_verification_id,
)
from althea_evidence_ui.errors import ContractError

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def reference_analysis():
    with open(FIXTURES_DIR / "analysis.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def reference_verification():
    with open(FIXTURES_DIR / "verification.json", "r", encoding="utf-8") as f:
        return json.load(f)


def test_reference_verification_passes(reference_verification, reference_analysis):
    validated = validate_verification(reference_verification, reference_analysis)
    assert validated["verification_id"] == reference_verification["verification_id"]
    assert validated["schema_version"] == "1.0.0"


def test_url_validation_and_normalization():
    # Valid HTTP(S) URLs
    assert is_valid_http_url("https://example.com/data?query=1")
    assert is_valid_http_url("http://riverton.gov/budget")

    # Invalid URLs (javascript, data, file, missing scheme/host)
    assert not is_valid_http_url("javascript:alert(1)")
    assert not is_valid_http_url("data:text/html,<b>hello</b>")
    assert not is_valid_http_url("file:///etc/passwd")
    assert not is_valid_http_url("not-a-url")

    # Normalization: lowercases, strips fragments, strips tracking parameters
    raw_url = "HTTPS://EXAMPLE.COM:443/Budget?utm_source=twitter&ref=123&year=2024#section1"
    normalized = normalize_url(raw_url)
    assert normalized == "https://example.com/Budget?year=2024"


def test_reject_javascript_url_in_evidence(reference_verification, reference_analysis):
    payload = copy.deepcopy(reference_verification)
    payload["evidence"][0]["url"] = "javascript:steal()"

    with pytest.raises(ContractError, match="has invalid URL"):
        validate_verification(payload, reference_analysis)


def test_metadata_only_cannot_support_or_refute(reference_verification, reference_analysis):
    payload = copy.deepcopy(reference_verification)
    # Set evidence to metadata_only
    payload["evidence"][0]["content_origin"] = "metadata_only"
    payload["evidence"][0]["content"] = None

    # Recompute verification_id so digest passes, but semantic validation fails
    payload["verification_id"] = compute_verification_id(
        payload["analysis_id"],
        payload["evidence"],
        payload["results"],
        payload["unverified"],
        payload["grounding_attributions"],
    )

    with pytest.raises(ContractError, match="cannot support/refute"):
        validate_verification(payload, reference_analysis)


def test_both_claims_refuted_allowed(reference_verification, reference_analysis):
    # Reference fixture has both claims refuted; ensure it is valid
    validated = validate_verification(reference_verification, reference_analysis)
    verdicts = validated["results"][0]["verdicts"]
    assert verdicts[0]["status"] == "refuted"
    assert verdicts[1]["status"] == "refuted"


def test_one_supported_one_insufficient_allowed(reference_verification, reference_analysis):
    payload = copy.deepcopy(reference_verification)
    # Change verdicts: claim_a supported, claim_b insufficient_evidence
    payload["results"][0]["verdicts"][0]["status"] = "supported"
    payload["results"][0]["verdicts"][0]["evidence_refs"][0]["stance"] = "supports"
    payload["results"][0]["verdicts"][1]["status"] = "insufficient_evidence"
    payload["results"][0]["verdicts"][1]["evidence_refs"] = []

    payload["verification_id"] = compute_verification_id(
        payload["analysis_id"],
        payload["evidence"],
        payload["results"],
        payload["unverified"],
        payload["grounding_attributions"],
    )

    validated = validate_verification(payload, reference_analysis)
    assert validated["results"][0]["verdicts"][0]["status"] == "supported"
    assert validated["results"][0]["verdicts"][1]["status"] == "insufficient_evidence"


def test_wrong_pair_or_claim_reference_rejected(reference_verification, reference_analysis):
    payload = copy.deepcopy(reference_verification)
    # Assign evidence to wrong pair
    payload["evidence"][0]["pair_id"] = "pair_0002"
    payload["evidence"][0]["evidence_id"] = "ev_pair_0002_0001"

    payload["verification_id"] = compute_verification_id(
        payload["analysis_id"],
        payload["evidence"],
        payload["results"],
        payload["unverified"],
        payload["grounding_attributions"],
    )

    with pytest.raises(ContractError):
        validate_verification(payload, reference_analysis)


def test_invalid_evidence_id_sequence_rejected(reference_verification, reference_analysis):
    payload = copy.deepcopy(reference_verification)
    # Non-sequential or wrong format ID
    payload["evidence"][0]["evidence_id"] = "ev_pair_0001_0002"

    payload["verification_id"] = compute_verification_id(
        payload["analysis_id"],
        payload["evidence"],
        payload["results"],
        payload["unverified"],
        payload["grounding_attributions"],
    )

    with pytest.raises(ContractError, match="must be strictly sequential"):
        validate_verification(payload, reference_analysis)


def test_ineligible_pair_in_results_rejected(reference_verification, reference_analysis):
    payload = copy.deepcopy(reference_verification)
    # pair_0002 has relation different_scope (ineligible)
    payload["results"].append({
        "pair_id": "pair_0002",
        "verdicts": [
            {"claim_id": "cl_0003", "status": "insufficient_evidence", "rationale": "N/A", "evidence_refs": []},
            {"claim_id": "cl_0004", "status": "insufficient_evidence", "rationale": "N/A", "evidence_refs": []},
        ],
        "summary": "N/A",
    })
    payload["verification_id"] = compute_verification_id(
        payload["analysis_id"],
        payload["evidence"],
        payload["results"],
        payload["unverified"],
        payload["grounding_attributions"],
    )

    with pytest.raises(ContractError, match="ineligible or unknown pair IDs"):
        validate_verification(payload, reference_analysis)


def test_verification_id_digest_mismatch_rejected(reference_verification, reference_analysis):
    payload = copy.deepcopy(reference_verification)
    payload["verification_id"] = "ve_0000000000000000000000000000000000000000000000000000000000000000"

    with pytest.raises(ContractError, match="Verification ID mismatch"):
        validate_verification(payload, reference_analysis)
