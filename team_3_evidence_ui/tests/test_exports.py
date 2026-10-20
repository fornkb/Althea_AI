"""Unit tests for snapshot and claims exports."""
import copy
import json
from pathlib import Path
import pytest

from althea_evidence_ui.exports import claims_csv, snapshot_json, neutralize_csv_formula

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def reference_snapshot():
    with open(FIXTURES_DIR / "reference_snapshot.json", "r", encoding="utf-8") as f:
        return json.load(f)


def test_neutralize_csv_formula():
    # Dangerous formula triggers escaped with leading '
    assert neutralize_csv_formula("=SUM(A1:A10)") == "'=SUM(A1:A10)"
    assert neutralize_csv_formula("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert neutralize_csv_formula("-some_expression") == "'-some_expression"
    assert neutralize_csv_formula("@SUM(B2)") == "'@SUM(B2)"

    # Genuine numeric values are NOT escaped
    assert neutralize_csv_formula("-10") == "-10"
    assert neutralize_csv_formula("-10.5") == "-10.5"
    assert neutralize_csv_formula("123") == "123"
    assert neutralize_csv_formula(None) == ""


def test_claims_csv_excel_bom_and_escaping(reference_snapshot):
    snap = copy.deepcopy(reference_snapshot)
    # Inject formula in a claim proposition
    snap["analysis"]["claims"][0]["proposition"] = "=1+1 is two"

    csv_bytes = claims_csv(snap)
    # Verify UTF-8 BOM
    assert csv_bytes.startswith(b"\xef\xbb\xbf")

    decoded = csv_bytes.decode("utf-8-sig")
    lines = decoded.splitlines()
    # Check headers
    assert "claim_id,speaker_id,speaker_display_name,proposition" in lines[0]
    # Check that injected formula was escaped
    assert "'=1+1 is two" in lines[1]


def test_snapshot_json_preserves_unmodified_data(reference_snapshot):
    json_bytes = snapshot_json(reference_snapshot)
    decoded = json_bytes.decode("utf-8")
    reloaded = json.loads(decoded)

    assert reloaded["job_id"] == reference_snapshot["job_id"]
    assert reloaded["status"] == reference_snapshot["status"]
    assert len(reloaded["analysis"]["claims"]) == len(reference_snapshot["analysis"]["claims"])
