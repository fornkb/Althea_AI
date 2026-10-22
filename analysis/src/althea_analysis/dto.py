"""Small provider-only DTOs. No model may assign public IDs or arithmetic."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SpanProposal(DTO):
    segment_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    start_char: int | None
    end_char: int | None


class ClaimProposal(DTO):
    speaker_id: str = Field(min_length=1)
    proposition: str = Field(min_length=1)
    subject: str | None
    metric: str | None
    period: str | None
    geography: str | None
    population: str | None
    measurement_basis: str | None
    qualifiers: list[str]
    checkability: Literal["checkable", "needs_context"]
    missing_context: list[str]
    source_spans: list[SpanProposal] = Field(min_length=1)
    quantity_raw: str | None
    currency_context: str | None


class ExtractionDTO(DTO):
    # Validate individual entries independently so unusable proposals can be reported.
    claims: list[dict]


class PairProposal(DTO):
    claim_a_id: str
    claim_b_id: str
    relation: Literal["direct_conflict", "numeric_discrepancy", "compatible",
                      "different_scope", "insufficient_context"]
    explanation: str = Field(min_length=1)


class ComparisonDTO(DTO):
    pairs: list[PairProposal]


def provider_schema(model):
    """Inline refs; translate nullable unions to Vertex's supported Schema subset.

    The wire validators still forbid extra fields and enforce all constraints.
    Only the provider DTO is adapted; provider responses are never filtered.
    """
    root = model.model_json_schema()
    if model is ExtractionDTO:
        claim = ClaimProposal.model_json_schema()
        root["properties"]["claims"]["items"] = claim
        root.setdefault("$defs", {}).update(claim.get("$defs", {}))
    defs = root.get("$defs", {})

    def convert(node):
        if "$ref" in node:
            return convert(defs[node["$ref"].split("/")[-1]])
        if "anyOf" in node:
            nonnull = [x for x in node["anyOf"] if x.get("type") != "null"]
            if len(nonnull) == 1:
                return {**convert(nonnull[0]), "nullable": True}
        return {k: ({p: convert(s) for p, s in v.items()} if k == "properties"
                    else [convert(x) for x in v] if k == "anyOf"
                    else convert(v) if k == "items" else v)
                for k, v in node.items() if k in
                {"type", "properties", "items", "required", "enum", "nullable", "anyOf"}}
    return convert(root)
