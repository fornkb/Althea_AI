"""Althea wire contract v1.0.0. Private copies must remain byte-identical."""
from __future__ import annotations
from typing import Annotated, Any, Callable, Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field

NonEmpty = Annotated[str, Field(min_length=1)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
DecimalText = Annotated[str, Field(pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")]

class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Issue(Wire):
    stage: Literal["input", "transcription", "analysis", "verification", "storage", "integration"]
    code: NonEmpty
    message: NonEmpty
    retryable: bool
    related_ids: list[str]

class Usage(Wire):
    stage: Literal["transcription", "extraction", "comparison", "retrieval", "adjudication"]
    provider: Literal["vertex", "fixture"]
    model: NonEmpty
    request_count: Annotated[int, Field(ge=0)]
    input_tokens: Annotated[int, Field(ge=0)] | None
    output_tokens: Annotated[int, Field(ge=0)] | None

class InputRequest(Wire):
    kind: Literal["audio", "transcript", "sample"]
    local_path: str | None
    sample_id: str | None
    title: NonEmpty

class Source(Wire):
    kind: Literal["audio", "transcript", "sample"]
    title: NonEmpty
    original_filename: str | None
    content_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    audio_relpath: str | None

class Speaker(Wire):
    speaker_id: NonEmpty
    display_name: NonEmpty

class Segment(Wire):
    segment_id: NonEmpty
    speaker_id: NonEmpty
    start_s: NonNegative
    end_s: NonNegative
    text: NonEmpty

class Transcript(Wire):
    schema_version: Literal["1.0.0"]
    transcript_id: NonEmpty
    origin: Literal["api", "imported", "human_reviewed", "fixture"]
    language: Literal["en"]
    duration_s: Annotated[float, Field(gt=0, le=300, allow_inf_nan=False)]
    source: Source
    speakers: list[Speaker]
    segments: list[Segment]
    issues: list[Issue]
    usage: list[Usage]

class SourceSpan(Wire):
    segment_id: NonEmpty
    start_char: Annotated[int, Field(ge=0)]
    end_char: Annotated[int, Field(gt=0)]
    quote: NonEmpty

class Quantity(Wire):
    raw_text: NonEmpty
    value: DecimalText | None
    lower: DecimalText | None
    upper: DecimalText | None
    operator: Literal["eq", "approx", "gt", "ge", "lt", "le", "range"]
    unit: NonEmpty
    currency: str | None
    basis: str | None

class Claim(Wire):
    claim_id: NonEmpty
    speaker_id: NonEmpty
    proposition: NonEmpty
    subject: str | None
    metric: str | None
    period: str | None
    geography: str | None
    population: str | None
    measurement_basis: str | None
    qualifiers: list[str]
    checkability: Literal["checkable", "needs_context"]
    missing_context: list[str]
    source_spans: list[SourceSpan]
    quantity: Quantity | None

class PairAssessment(Wire):
    pair_id: NonEmpty
    claim_a_id: NonEmpty
    claim_b_id: NonEmpty
    relation: Literal["direct_conflict", "numeric_discrepancy", "compatible", "different_scope", "insufficient_context"]
    explanation: NonEmpty
    numeric_difference: DecimalText | None
    numeric_difference_unit: str | None
    priority: Literal[1, 2, 3]
    method: Literal["deterministic", "llm", "hybrid", "fixture"]

class Analysis(Wire):
    schema_version: Literal["1.0.0"]
    analysis_id: NonEmpty
    transcript_id: NonEmpty
    claims: list[Claim]
    pairs: list[PairAssessment]
    issues: list[Issue]
    usage: list[Usage]

class Evidence(Wire):
    evidence_id: NonEmpty
    pair_id: NonEmpty
    claim_ids: list[str]
    url: NonEmpty
    title: NonEmpty
    publisher: str | None
    published_date: str | None
    retrieved_at: NonEmpty
    content: str | None
    content_origin: Literal["retrieved_excerpt", "grounded_summary", "metadata_only"]
    queries: list[str]

class EvidenceRef(Wire):
    evidence_id: NonEmpty
    stance: Literal["supports", "refutes", "context"]

class ClaimVerdict(Wire):
    claim_id: NonEmpty
    status: Literal["supported", "refuted", "insufficient_evidence", "needs_context"]
    rationale: NonEmpty
    evidence_refs: list[EvidenceRef]

class PairVerdict(Wire):
    pair_id: NonEmpty
    verdicts: list[ClaimVerdict]
    summary: NonEmpty

class Unverified(Wire):
    pair_id: NonEmpty
    reason: Literal["not_selected", "budget_limit", "provider_error", "no_sources", "missing_context"]

class GroundingAttribution(Wire):
    pair_id: NonEmpty
    search_entry_point_html: str | None

class Verification(Wire):
    schema_version: Literal["1.0.0"]
    verification_id: NonEmpty
    analysis_id: NonEmpty
    evidence: list[Evidence]
    results: list[PairVerdict]
    unverified: list[Unverified]
    grounding_attributions: list[GroundingAttribution]
    issues: list[Issue]
    usage: list[Usage]

class Snapshot(Wire):
    schema_version: Literal["1.0.0"]
    job_id: NonEmpty
    title: NonEmpty
    mode: Literal["fixture", "live"]
    status: Literal["ready", "running", "complete", "partial", "failed"]
    created_at: NonEmpty
    updated_at: NonEmpty
    transcript: Transcript | None
    analysis: Analysis | None
    verification: Verification | None
    issues: list[Issue]

class JobSummary(Wire):
    job_id: NonEmpty
    title: NonEmpty
    mode: Literal["fixture", "live"]
    status: Literal["ready", "running", "complete", "partial", "failed"]
    updated_at: NonEmpty

Progress = Callable[[str], None]

class DashboardBackend(Protocol):
    mode: Literal["fixture", "live"]
    def run(self, source: dict[str, Any], *, verify: bool,
            progress: Progress | None = None) -> dict[str, Any]: ...
    def load(self, job_id: str) -> dict[str, Any]: ...
    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]: ...
    def save_review(self, job_id: str, transcript: dict[str, Any]) -> dict[str, Any]: ...
    def reanalyze(self, job_id: str, *, verify: bool,
                  progress: Progress | None = None) -> dict[str, Any]: ...
    def verify_pairs(self, job_id: str, pair_ids: list[str], *,
                     progress: Progress | None = None) -> dict[str, Any]: ...
