"""Adjudication and claim verdict judge seam for Althea Evidence UI."""
from __future__ import annotations
import json
import random
import time
from typing import Any, Protocol

from althea_evidence_ui.errors import (
    AltheaError,
    BudgetLimitError,
    ProviderError,
    ContractError,
)
from althea_evidence_ui._contract import PairVerdict


class BaseJudge(Protocol):
    def judge(
        self,
        *,
        claims: list[dict],
        pair: dict,
        evidence: list[dict],
        budget: Any,
    ) -> tuple[dict, list[dict]]:
        ...


class FixtureJudge:
    """Offline deterministic fixture judge producing synthetic reference verdicts."""

    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}

    def judge(
        self,
        *,
        claims: list[dict],
        pair: dict,
        evidence: list[dict],
        budget: Any,
    ) -> tuple[dict, list[dict]]:
        pair_id = pair["pair_id"]
        claim_a_id = pair["claim_a_id"]
        claim_b_id = pair["claim_b_id"]

        # Only pair_0001 in reference sample produces the both-refuted fixture result
        if pair_id == "pair_0001" and evidence and evidence[0].get("evidence_id") == f"ev_{pair_id}_0001":
            ev_id = f"ev_{pair_id}_0001"
            verdicts = [
                {
                    "claim_id": claim_a_id,
                    "status": "refuted",
                    "rationale": "The synthetic reference record states USD 11000000; the stated amount differs.",
                    "evidence_refs": [{"evidence_id": ev_id, "stance": "refutes"}],
                },
                {
                    "claim_id": claim_b_id,
                    "status": "refuted",
                    "rationale": "The synthetic reference record states USD 11000000; the stated amount differs.",
                    "evidence_refs": [{"evidence_id": ev_id, "stance": "refutes"}],
                },
            ]
            summary = "Both amounts differ from the fictional reference. This is synthetic demonstration evidence, not a live fact check."
        else:
            # Default with no substantive evidence or other fixture pairs
            verdicts = [
                {
                    "claim_id": claim_a_id,
                    "status": "insufficient_evidence",
                    "rationale": "No substantive evidence retrieved for this claim.",
                    "evidence_refs": [],
                },
                {
                    "claim_id": claim_b_id,
                    "status": "insufficient_evidence",
                    "rationale": "No substantive evidence retrieved for this claim.",
                    "evidence_refs": [],
                },
            ]
            summary = "Insufficient evidence to verify or refute either claim in this pair."

        usage = [
            {
                "stage": "adjudication",
                "provider": "fixture",
                "model": "fixture-v1",
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        ]

        pair_verdict = {
            "pair_id": pair_id,
            "verdicts": verdicts,
            "summary": summary,
        }
        return pair_verdict, usage


class GeminiJudge:
    """Live Gemini structured judge evaluating claims against supplied evidence."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.model_name = settings.get("text_model", "gemini-2.5-flash")
        self.client = None

    def _get_client(self):
        if self.client is None:
            try:
                from google import genai
                project_id = self.settings.get("project_id") or None
                location = self.settings.get("location") or "global"
                if project_id:
                    self.client = genai.Client(vertexai=True, project=project_id, location=location)
                else:
                    self.client = genai.Client()
            except Exception as e:
                raise ProviderError(
                    f"Failed to initialize Google GenAI client: {e}",
                    code="PROVIDER_AUTH",
                    retryable=False,
                ) from e
        return self.client

    def judge(
        self,
        *,
        claims: list[dict],
        pair: dict,
        evidence: list[dict],
        budget: Any,
    ) -> tuple[dict, list[dict]]:
        pair_id = pair["pair_id"]
        claims_map = {c["claim_id"]: c for c in claims}
        claim_a = claims_map.get(pair["claim_a_id"], {})
        claim_b = claims_map.get(pair["claim_b_id"], {})

        # Substantive evidence check: if no evidence or only metadata_only, return insufficient_evidence without call
        substantive_evidence = [
            e for e in evidence
            if e.get("content_origin") in ("retrieved_excerpt", "grounded_summary") and bool(e.get("content"))
        ]
        if not substantive_evidence:
            verdicts = [
                {
                    "claim_id": pair["claim_a_id"],
                    "status": "insufficient_evidence",
                    "rationale": "Retrieved evidence contains no substantive content to verify or refute this claim.",
                    "evidence_refs": [],
                },
                {
                    "claim_id": pair["claim_b_id"],
                    "status": "insufficient_evidence",
                    "rationale": "Retrieved evidence contains no substantive content to verify or refute this claim.",
                    "evidence_refs": [],
                },
            ]
            summary = "Retrieved sources contain only metadata or empty excerpts; unable to adjudicate factual disagreement."
            usage = [
                {
                    "stage": "adjudication",
                    "provider": "vertex",
                    "model": self.model_name,
                    "request_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            ]
            return {"pair_id": pair_id, "verdicts": verdicts, "summary": summary}, usage

        # Prepare evidence listing
        ev_lines = []
        for ev in evidence:
            ev_lines.append(
                f"- Evidence ID: {ev['evidence_id']}\n"
                f"  Title: {ev['title']}\n"
                f"  URL: {ev['url']}\n"
                f"  Origin: {ev['content_origin']}\n"
                f"  Content: {ev.get('content') or '(none)'}"
            )
        evidence_text = "\n".join(ev_lines)

        prompt = (
            f"Adjudicate the factual disagreement for pair {pair_id}.\n\n"
            f"Claim A ({pair['claim_a_id']}):\n"
            f"  Proposition: {claim_a.get('proposition')}\n"
            f"  Period: {claim_a.get('period')}, Geo: {claim_a.get('geography')}, Metric: {claim_a.get('metric')}\n"
            f"  Quantity: {claim_a.get('quantity')}\n\n"
            f"Claim B ({pair['claim_b_id']}):\n"
            f"  Proposition: {claim_b.get('proposition')}\n"
            f"  Period: {claim_b.get('period')}, Geo: {claim_b.get('geography')}, Metric: {claim_b.get('metric')}\n"
            f"  Quantity: {claim_b.get('quantity')}\n\n"
            f"Disagreement Relation: {pair.get('relation')}\n"
            f"Explanation: {pair.get('explanation')}\n\n"
            f"Retrieved Evidence:\n{evidence_text}\n\n"
            f"Rules:\n"
            f"1. Judge each claim separately against ONLY the supplied evidence.\n"
            f"2. Valid statuses: supported, refuted, insufficient_evidence, needs_context.\n"
            f"3. For supported/refuted, supply at least one evidence_ref with matching stance (supports/refutes) to substantive evidence.\n"
            f"4. Both claims can be refuted.\n"
            f"5. Return JSON matching the PairVerdict schema."
        )

        client = self._get_client()
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PairVerdict,
            max_output_tokens=self.settings.get("max_output_tokens_adjudication", 2048),
        )

        attempts = 0
        max_attempts = 3
        last_error = None
        pair_verdict_dict = None
        total_in_tokens = 0
        total_out_tokens = 0

        while attempts < max_attempts:
            budget.consume("adjudication")
            attempts += 1

            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )
                um = getattr(response, "usage_metadata", None)
                if um:
                    total_in_tokens += getattr(um, "prompt_token_count", 0) or 0
                    total_out_tokens += getattr(um, "candidates_token_count", 0) or 0

                raw_text = response.text
                parsed_json = json.loads(raw_text)
                # Validate with Pydantic PairVerdict
                pv = PairVerdict.model_validate(parsed_json)
                pair_verdict_dict = pv.model_dump(mode="json")
                break
            except AltheaError:
                raise
            except Exception as e:
                err_str = str(e).lower()
                is_transient = "429" in err_str or "503" in err_str or "500" in err_str or "timeout" in err_str or "json" in err_str
                last_error = e
                if is_transient and attempts < max_attempts:
                    sleep_time = (2 ** attempts) * 0.5 + random.uniform(0.1, 0.4)
                    time.sleep(sleep_time)
                    continue
                code = "RATE_LIMIT" if "429" in err_str else "PROVIDER_UNAVAILABLE"
                raise ProviderError(
                    f"Gemini adjudication failed after {attempts} attempts: {e}",
                    code=code,
                    retryable=is_transient,
                    related_ids=[pair_id],
                ) from e

        if pair_verdict_dict is None:
            raise ProviderError(
                f"Gemini adjudication produced invalid output: {last_error}",
                code="PROVIDER_RESPONSE_INVALID",
                retryable=False,
                related_ids=[pair_id],
            )

        # Enforce that pair_id matches
        pair_verdict_dict["pair_id"] = pair_id

        usage = [
            {
                "stage": "adjudication",
                "provider": "vertex",
                "model": self.model_name,
                "request_count": attempts,
                "input_tokens": total_in_tokens or None,
                "output_tokens": total_out_tokens or None,
            }
        ]
        return pair_verdict_dict, usage
