"""Verification service implementing the evidence pipeline for Althea AI."""
from __future__ import annotations
from typing import Any, Callable

from althea_evidence_ui._contract import (
    Verification,
    PairVerdict,
    Unverified,
    Evidence,
    GroundingAttribution,
    Issue,
    Usage,
)
from althea_evidence_ui.errors import (
    AltheaError,
    BudgetLimitError,
    ProviderError,
    ContractError,
)
from althea_evidence_ui.grounding import (
    BaseRetriever,
    FixtureRetriever,
    GeminiGroundingRetriever,
    SimpleBudget,
)
from althea_evidence_ui.adjudication import (
    BaseJudge,
    FixtureJudge,
    GeminiJudge,
)
from althea_evidence_ui.validation import (
    validate_verification,
    compute_verification_id,
)

Progress = Callable[[str], None]


class VerificationService:
    """Service orchestrating evidence retrieval and claim adjudication."""

    def __init__(
        self,
        settings: dict,
        *,
        retriever: BaseRetriever | None = None,
        judge: BaseJudge | None = None,
    ):
        self.settings = settings
        mode = settings.get("mode", "fixture")

        if retriever is not None:
            self.retriever = retriever
        elif mode == "live":
            self.retriever = GeminiGroundingRetriever(settings)
        else:
            self.retriever = FixtureRetriever(settings)

        if judge is not None:
            self.judge = judge
        elif mode == "live":
            self.judge = GeminiJudge(settings)
        else:
            self.judge = FixtureJudge(settings)

    def verify(
        self,
        transcript: dict,
        analysis: dict,
        pair_ids: list[str],
        *,
        budget: Any = None,
        progress: Progress | None = None,
    ) -> dict:
        """
        Verify selected conflict pairs against web evidence.

        Enforces four-pair cap, input validation, failure isolation,
        and contract compliance.
        """
        if budget is None:
            max_attempts = self.settings.get("max_provider_attempts", 20)
            budget = SimpleBudget(max_attempts=max_attempts)

        # 1. Validate upstream IDs/references
        analysis_id = analysis.get("analysis_id")
        if not analysis_id:
            raise ContractError("Analysis object is missing analysis_id")

        max_verify_pairs = self.settings.get("max_verify_pairs", 4)
        if len(pair_ids) > max_verify_pairs:
            raise ContractError(
                f"Requested pair count {len(pair_ids)} exceeds max_verify_pairs limit of {max_verify_pairs}"
            )

        # Check for duplicates in requested pair_ids
        if len(pair_ids) != len(set(pair_ids)):
            raise ContractError("Duplicate pair IDs requested in verification")

        analysis_pairs_map = {p["pair_id"]: p for p in analysis.get("pairs", [])}
        eligible_pairs_map = {
            p["pair_id"]: p
            for p in analysis.get("pairs", [])
            if p.get("relation") in ("direct_conflict", "numeric_discrepancy")
        }

        for pid in pair_ids:
            if pid not in analysis_pairs_map:
                raise ContractError(f"Requested pair_id {pid!r} not found in analysis pairs")
            if pid not in eligible_pairs_map:
                raise ContractError(
                    f"Requested pair_id {pid!r} has relation {analysis_pairs_map[pid].get('relation')!r}; "
                    f"only direct_conflict and numeric_discrepancy are eligible for verification"
                )

        # Universe of eligible pairs sorted deterministically
        eligible_pair_ids_sorted = sorted(eligible_pairs_map.keys())

        # If no eligible pairs in analysis: return empty valid Verification immediately
        if not eligible_pair_ids_sorted:
            payload = {
                "schema_version": "1.0.0",
                "verification_id": compute_verification_id(analysis_id, [], [], [], []),
                "analysis_id": analysis_id,
                "evidence": [],
                "results": [],
                "unverified": [],
                "grounding_attributions": [],
                "issues": [],
                "usage": [],
            }
            return validate_verification(payload, analysis)

        all_evidence: list[dict] = []
        all_results: list[dict] = []
        all_unverified: list[dict] = []
        all_attributions: list[dict] = []
        all_issues: list[dict] = []
        all_usage: list[dict] = []

        requested_set = set(pair_ids)

        for pid in eligible_pair_ids_sorted:
            pair = eligible_pairs_map[pid]

            if pid not in requested_set:
                all_unverified.append({
                    "pair_id": pid,
                    "reason": "not_selected",
                })
                continue

            if progress:
                progress(f"Checking evidence for pair {pid}...")

            # Isolated verification for this pair
            pair_evidence: list[dict] = []
            pair_usage: list[dict] = []
            pair_attribution: dict | None = None

            # Stage 1: Retrieval
            try:
                pair_evidence, pair_usage, pair_attribution = self.retriever.retrieve(
                    transcript=transcript,
                    claims=analysis.get("claims", []),
                    pair=pair,
                    budget=budget,
                )
                all_usage.extend(pair_usage)
            except AltheaError as e:
                reason = "budget_limit" if e.code == "BUDGET_LIMIT" else "provider_error"
                all_unverified.append({"pair_id": pid, "reason": reason})
                all_issues.append(e.to_issue())
                continue
            except Exception as e:
                all_unverified.append({"pair_id": pid, "reason": "provider_error"})
                all_issues.append({
                    "stage": "verification",
                    "code": "PROVIDER_UNAVAILABLE",
                    "message": f"Unexpected retrieval error for pair {pid}: {e}",
                    "retryable": False,
                    "related_ids": [pid],
                })
                continue

            # Stage 2: Adjudication
            try:
                pair_verdict, judge_usage = self.judge.judge(
                    claims=analysis.get("claims", []),
                    pair=pair,
                    evidence=pair_evidence,
                    budget=budget,
                )
                all_usage.extend(judge_usage)
            except AltheaError as e:
                reason = "budget_limit" if e.code == "BUDGET_LIMIT" else "provider_error"
                all_unverified.append({"pair_id": pid, "reason": reason})
                all_issues.append(e.to_issue())
                continue
            except Exception as e:
                all_unverified.append({"pair_id": pid, "reason": "provider_error"})
                all_issues.append({
                    "stage": "verification",
                    "code": "PROVIDER_UNAVAILABLE",
                    "message": f"Unexpected adjudication error for pair {pid}: {e}",
                    "retryable": False,
                    "related_ids": [pid],
                })
                continue

            # Adjudication successful
            all_evidence.extend(pair_evidence)
            all_results.append(pair_verdict)
            if pair_attribution:
                all_attributions.append(pair_attribution)

        # Sort results and unverified by pair_id
        all_results.sort(key=lambda x: x["pair_id"])
        all_unverified.sort(key=lambda x: x["pair_id"])

        verification_id = compute_verification_id(
            analysis_id=analysis_id,
            evidence=all_evidence,
            results=all_results,
            unverified=all_unverified,
            grounding_attributions=all_attributions,
        )

        payload = {
            "schema_version": "1.0.0",
            "verification_id": verification_id,
            "analysis_id": analysis_id,
            "evidence": all_evidence,
            "results": all_results,
            "unverified": all_unverified,
            "grounding_attributions": all_attributions,
            "issues": all_issues,
            "usage": all_usage,
        }

        return validate_verification(payload, analysis)
