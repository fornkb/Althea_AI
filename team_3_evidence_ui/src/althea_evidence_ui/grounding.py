"""Grounding and web evidence retrieval seam for Althea Evidence UI."""
from __future__ import annotations
import datetime
import random
import time
from typing import Any, Protocol

from althea_evidence_ui.errors import (
    AltheaError,
    BudgetLimitError,
    ProviderError,
    ContractError,
)
from althea_evidence_ui.validation import is_valid_http_url, normalize_url


class Budget(Protocol):
    def consume(self, stage: str) -> None:
        ...


class SimpleBudget:
    """In-memory budget tracker enforcing provider attempt limit."""

    def __init__(self, max_attempts: int = 20):
        self.max_attempts = max_attempts
        self.attempts = 0

    def consume(self, stage: str) -> None:
        if self.attempts >= self.max_attempts:
            raise BudgetLimitError(f"Budget limit of {self.max_attempts} attempts reached in stage {stage}")
        self.attempts += 1


class BaseRetriever(Protocol):
    def retrieve(
        self,
        *,
        transcript: dict,
        claims: list[dict],
        pair: dict,
        budget: Any,
    ) -> tuple[list[dict], list[dict], dict | None]:
        ...


class FixtureRetriever:
    """Offline reference fixture retriever producing deterministic synthetic evidence."""

    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}

    def retrieve(
        self,
        *,
        transcript: dict,
        claims: list[dict],
        pair: dict,
        budget: Any,
    ) -> tuple[list[dict], list[dict], dict | None]:
        pair_id = pair["pair_id"]

        # Only pair_0001 in reference sample has synthetic evidence
        if pair_id == "pair_0001":
            evidence = [
                {
                    "evidence_id": f"ev_{pair_id}_0001",
                    "pair_id": pair_id,
                    "claim_ids": [pair["claim_a_id"], pair["claim_b_id"]],
                    "url": "https://example.com/althea-fixtures/riverton-budget-2024",
                    "title": "Fictional Riverton budget record",
                    "publisher": "Synthetic demo fixture",
                    "published_date": "2024-12-31",
                    "retrieved_at": "2026-10-16T00:00:00Z",
                    "content": "Riverton's adopted transport budget for calendar year 2024 was USD 11000000.",
                    "content_origin": "retrieved_excerpt",
                    "queries": ["fictional fixture; no live search"],
                }
            ]
        else:
            evidence = []

        usage = [
            {
                "stage": "retrieval",
                "provider": "fixture",
                "model": "fixture-v1",
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        ]
        return evidence, usage, None


class GeminiGroundingRetriever:
    """Live Google Search Grounding retriever via google-genai SDK."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.model_name = settings.get("grounding_model", "gemini-2.5-flash")
        self.request_timeout_s = settings.get("request_timeout_s", 90)
        self.client = None

    def _get_client(self):
        if self.client is None:
            try:
                from google import genai
                # Respect Application Default Credentials or explicit project_id/location
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

    def retrieve(
        self,
        *,
        transcript: dict,
        claims: list[dict],
        pair: dict,
        budget: Any,
    ) -> tuple[list[dict], list[dict], dict | None]:
        pair_id = pair["pair_id"]
        claims_map = {c["claim_id"]: c for c in claims}
        claim_a = claims_map.get(pair["claim_a_id"], {})
        claim_b = claims_map.get(pair["claim_b_id"], {})

        # Formulate neutral search query
        query_prompt = (
            f"Fact check question between two conflicting claims:\n"
            f"Claim 1: {claim_a.get('proposition', '')} (period: {claim_a.get('period')}, geo: {claim_a.get('geography')})\n"
            f"Claim 2: {claim_b.get('proposition', '')} (period: {claim_b.get('period')}, geo: {claim_b.get('geography')})\n"
            f"Search authoritative sources for the official figure and status."
        )

        client = self._get_client()
        from google.genai import types

        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            max_output_tokens=self.settings.get("max_output_tokens_retrieval", 2048),
        )

        attempts = 0
        max_attempts = 3
        last_error = None
        response = None

        while attempts < max_attempts:
            # Consume budget attempt immediately before external call
            budget.consume("retrieval")
            attempts += 1

            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=query_prompt,
                    config=config,
                )
                break
            except AltheaError:
                raise
            except Exception as e:
                err_str = str(e).lower()
                is_transient = "429" in err_str or "503" in err_str or "500" in err_str or "deadline" in err_str or "timeout" in err_str
                if is_transient and attempts < max_attempts:
                    last_error = e
                    # Exponential backoff with jitter
                    sleep_time = (2 ** attempts) * 0.5 + random.uniform(0.1, 0.5)
                    time.sleep(sleep_time)
                    continue
                code = "RATE_LIMIT" if "429" in err_str else "PROVIDER_UNAVAILABLE"
                raise ProviderError(
                    f"Gemini search retrieval failed after {attempts} attempts: {e}",
                    code=code,
                    retryable=is_transient,
                    related_ids=[pair_id],
                ) from e

        if response is None:
            raise ProviderError(
                f"Gemini search retrieval produced no response: {last_error}",
                code="PROVIDER_RESPONSE_INVALID",
                retryable=False,
                related_ids=[pair_id],
            )

        # Parse native grounding metadata
        evidence_list: list[dict] = []
        queries: list[str] = [query_prompt]
        search_entry_point_html: str | None = None

        raw_chunks: list[dict] = []
        grounding_supports: list[Any] = []

        now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        candidates = getattr(response, "candidates", None) or []
        if candidates:
            cand = candidates[0]
            metadata = getattr(cand, "grounding_metadata", None)
            if metadata:
                # Queries
                if getattr(metadata, "web_search_queries", None):
                    queries = list(metadata.web_search_queries)

                # Search entry point HTML
                sep = getattr(metadata, "search_entry_point", None)
                if sep and getattr(sep, "rendered_content", None):
                    search_entry_point_html = sep.rendered_content

                # Grounding chunks
                chunks = getattr(metadata, "grounding_chunks", None) or []
                for chunk in chunks:
                    web = getattr(chunk, "web", None)
                    if web:
                        uri = getattr(web, "uri", None)
                        title = getattr(web, "title", None) or uri or "Web source"
                        if uri and is_valid_http_url(uri):
                            raw_chunks.append({"uri": uri, "title": title})

                # Grounding supports (mapping segments to chunk indices)
                grounding_supports = getattr(metadata, "grounding_supports", None) or []

        # Map supporting text per chunk index
        chunk_texts: dict[int, list[str]] = {}
        for supp in grounding_supports:
            segment = getattr(supp, "segment", None)
            seg_text = getattr(segment, "text", "") if segment else ""
            indices = getattr(supp, "grounding_chunk_indices", None) or []
            for idx in indices:
                if isinstance(idx, int) and 0 <= idx < len(raw_chunks):
                    if seg_text:
                        chunk_texts.setdefault(idx, []).append(seg_text.strip())

        # Build evidence items with normalized URLs and deduplication
        seen_normalized_urls: set[str] = set()
        deduped_evidence_candidates: list[dict] = []

        for idx, chunk in enumerate(raw_chunks):
            uri = chunk["uri"]
            try:
                norm_url = normalize_url(uri)
            except Exception:
                continue

            if norm_url in seen_normalized_urls:
                continue
            seen_normalized_urls.add(norm_url)

            texts = chunk_texts.get(idx, [])
            if texts:
                content = " ".join(texts)
                content_origin = "grounded_summary"
            else:
                content = None
                content_origin = "metadata_only"

            deduped_evidence_candidates.append({
                "norm_url": norm_url,
                "url": uri,
                "title": chunk["title"],
                "content": content,
                "content_origin": content_origin,
            })

        # Sort candidate evidence records by normalized URL order per spec
        deduped_evidence_candidates.sort(key=lambda x: x["norm_url"])

        for ev_idx, cand_ev in enumerate(deduped_evidence_candidates, start=1):
            evidence_id = f"ev_{pair_id}_{ev_idx:04d}"
            evidence_list.append({
                "evidence_id": evidence_id,
                "pair_id": pair_id,
                "claim_ids": [pair["claim_a_id"], pair["claim_b_id"]],
                "url": cand_ev["url"],
                "title": cand_ev["title"],
                "publisher": None,
                "published_date": None,
                "retrieved_at": now_utc,
                "content": cand_ev["content"],
                "content_origin": cand_ev["content_origin"],
                "queries": queries,
            })

        # Usage
        usage_metadata = getattr(response, "usage_metadata", None)
        in_tokens = getattr(usage_metadata, "prompt_token_count", None) if usage_metadata else None
        out_tokens = getattr(usage_metadata, "candidates_token_count", None) if usage_metadata else None

        usage = [
            {
                "stage": "retrieval",
                "provider": "vertex",
                "model": self.model_name,
                "request_count": attempts,
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
            }
        ]

        attribution = None
        if search_entry_point_html:
            attribution = {
                "pair_id": pair_id,
                "search_entry_point_html": search_entry_point_html,
            }

        return evidence_list, usage, attribution
