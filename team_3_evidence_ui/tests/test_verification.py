"""Unit tests for VerificationService evidence retrieval and adjudication."""
import copy
import json
from pathlib import Path
import pytest

from althea_evidence_ui.verification import VerificationService
from althea_evidence_ui.grounding import SimpleBudget
from althea_evidence_ui.errors import ContractError, BudgetLimitError, ProviderError

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def fixtures():
    with open(FIXTURES_DIR / "transcript.json", "r", encoding="utf-8") as f:
        tr = json.load(f)
    with open(FIXTURES_DIR / "analysis.json", "r", encoding="utf-8") as f:
        an = json.load(f)
    with open(FIXTURES_DIR / "verification.json", "r", encoding="utf-8") as f:
        ve = json.load(f)
    return tr, an, ve


def test_zero_network_fixture_verification(fixtures):
    tr, an, ve = fixtures
    service = VerificationService({"mode": "fixture"})
    result = service.verify(tr, an, ["pair_0001"])

    assert result["verification_id"] == ve["verification_id"]
    assert len(result["results"]) == 1
    assert result["results"][0]["verdicts"][0]["status"] == "refuted"
    assert result["results"][0]["verdicts"][1]["status"] == "refuted"
    # External request counts stay 0
    for u in result["usage"]:
        assert u["request_count"] == 0
        assert u["provider"] == "fixture"


def test_exceeding_max_verify_pairs_rejected(fixtures):
    tr, an, _ = fixtures
    service = VerificationService({"mode": "fixture", "max_verify_pairs": 1})
    # Attempt requesting 2 pairs
    with pytest.raises(ContractError, match="exceeds max_verify_pairs"):
        service.verify(tr, an, ["pair_0001", "pair_0001"])  # or 2 distinct


def test_duplicate_pair_ids_rejected(fixtures):
    tr, an, _ = fixtures
    service = VerificationService({"mode": "fixture", "max_verify_pairs": 4})
    with pytest.raises(ContractError, match="Duplicate pair IDs"):
        service.verify(tr, an, ["pair_0001", "pair_0001"])


def test_empty_eligible_pairs_returns_empty_valid_verification(fixtures):
    tr, an, _ = fixtures
    an_empty = copy.deepcopy(an)
    # Remove eligible pairs
    an_empty["pairs"] = [p for p in an_empty["pairs"] if p["relation"] not in ("direct_conflict", "numeric_discrepancy")]

    service = VerificationService({"mode": "fixture"})
    result = service.verify(tr, an_empty, [])

    assert result["results"] == []
    assert result["unverified"] == []
    assert result["evidence"] == []
    assert result["schema_version"] == "1.0.0"


def test_failure_isolation_by_pair(fixtures):
    tr, an, _ = fixtures
    # Add a second eligible pair to analysis
    an_two = copy.deepcopy(an)
    an_two["pairs"].append({
        "pair_id": "pair_0004",
        "claim_a_id": "cl_0001",
        "claim_b_id": "cl_0005",
        "relation": "direct_conflict",
        "explanation": "Test conflict pair.",
        "numeric_difference": None,
        "numeric_difference_unit": None,
        "priority": 1,
        "method": "fixture",
    })

    class FailingRetriever:
        def retrieve(self, *, transcript, claims, pair, budget):
            if pair["pair_id"] == "pair_0004":
                raise ProviderError("Search provider connection failed", code="PROVIDER_UNAVAILABLE")
            # pair_0001 succeeds
            return [
                {
                    "evidence_id": "ev_pair_0001_0001",
                    "pair_id": "pair_0001",
                    "claim_ids": ["cl_0001", "cl_0002"],
                    "url": "https://example.com/record",
                    "title": "Evidence Title",
                    "publisher": None,
                    "published_date": None,
                    "retrieved_at": "2026-10-16T00:00:00Z",
                    "content": "USD 11000000",
                    "content_origin": "retrieved_excerpt",
                    "queries": ["query"],
                }
            ], [], None

    class MockJudge:
        def judge(self, *, claims, pair, evidence, budget):
            return {
                "pair_id": pair["pair_id"],
                "verdicts": [
                    {"claim_id": pair["claim_a_id"], "status": "refuted", "rationale": "Differs", "evidence_refs": [{"evidence_id": "ev_pair_0001_0001", "stance": "refutes"}]},
                    {"claim_id": pair["claim_b_id"], "status": "refuted", "rationale": "Differs", "evidence_refs": [{"evidence_id": "ev_pair_0001_0001", "stance": "refutes"}]},
                ],
                "summary": "Both refuted",
            }, []

    service = VerificationService({"mode": "fixture"}, retriever=FailingRetriever(), judge=MockJudge())
    result = service.verify(tr, an_two, ["pair_0001", "pair_0004"])

    # pair_0001 succeeded and is preserved in results
    assert len(result["results"]) == 1
    assert result["results"][0]["pair_id"] == "pair_0001"

    # pair_0004 failed and is in unverified with provider_error
    assert len(result["unverified"]) == 1
    assert result["unverified"][0]["pair_id"] == "pair_0004"
    assert result["unverified"][0]["reason"] == "provider_error"

    # Issue recorded
    assert len(result["issues"]) == 1
    assert result["issues"][0]["code"] == "PROVIDER_UNAVAILABLE"


def test_budget_exhaustion_handling(fixtures):
    tr, an, _ = fixtures
    budget = SimpleBudget(max_attempts=1)
    budget.consume("pre_existing_call")  # Exhaust the budget

    class LiveSimulatingRetriever:
        def retrieve(self, *, transcript, claims, pair, budget):
            budget.consume("retrieval")  # Will raise BudgetLimitError
            return [], [], None

    service = VerificationService({"mode": "live"}, retriever=LiveSimulatingRetriever())
    result = service.verify(tr, an, ["pair_0001"], budget=budget)

    # Handled cleanly without crash, pair marked budget_limit
    assert len(result["unverified"]) == 1
    assert result["unverified"][0]["pair_id"] == "pair_0001"
    assert result["unverified"][0]["reason"] == "budget_limit"
    assert any(i["code"] == "BUDGET_LIMIT" for i in result["issues"])
