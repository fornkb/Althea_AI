from importlib.resources import files
from pydantic import ValidationError
from .dto import ExtractionDTO, ComparisonDTO, provider_schema
from .extraction import parse_extraction
from .matching import ranked_candidates
from .comparison import compare_deterministic, parse_comparison
from .providers import FixtureTextProvider, VertexTextProvider, fixture_usage
from .validation import validate_transcript, validate_analysis, validate_usage
from .utils import analysis_identity, issue
from .errors import AnalysisError, invalid

DEFAULTS = dict(mode="fixture", location="global", text_model="gemini-2.5-flash",
                max_audio_seconds=300, max_claims=30, max_candidate_pairs=60,
                max_provider_attempts=20, max_output_tokens_extraction=8192,
                max_output_tokens_comparison=8192, request_timeout_s=90)


class AnalysisService:
    def __init__(self, settings: dict, *, text_provider=None):
        self.settings = {**DEFAULTS, **settings}
        if self.settings["mode"] not in ("fixture", "live"):
            raise AnalysisError("INVALID_INPUT", "Mode must be fixture or live.")
        for key, upper in (("max_claims", 30), ("max_candidate_pairs", 60), ("max_provider_attempts", 20)):
            value = self.settings[key]
            if type(value) is not int or not 1 <= value <= upper:
                raise AnalysisError("INVALID_INPUT", f"{key} must be an integer from 1 to {upper}.")
        for key in ("max_output_tokens_extraction", "max_output_tokens_comparison"):
            if type(self.settings[key]) is not int or not 1 <= self.settings[key] <= 8192:
                raise AnalysisError("INVALID_INPUT", f"{key} must be an integer from 1 to 8192.")
        timeout = self.settings["request_timeout_s"]
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 90:
            raise AnalysisError("INVALID_INPUT", "Request timeout must be between 0 and 90 seconds.")
        duration = self.settings["max_audio_seconds"]
        if not isinstance(duration, (int, float)) or not 0 < duration <= 300:
            raise AnalysisError("INVALID_INPUT", "Maximum transcript duration must be between 0 and 300 seconds.")
        self.provider = text_provider if text_provider is not None else (
            FixtureTextProvider() if self.settings["mode"] == "fixture" else VertexTextProvider(self.settings))
        if self.settings["mode"] == "fixture" and getattr(self.provider, "mode", None) != "fixture":
            raise AnalysisError("INVALID_INPUT", "Fixture mode requires a provider explicitly marked offline.")

    def _operation(self, operation, payload, model, parser, budget, usage):
        prompt = files("althea_analysis").joinpath("prompts", "extract_v1.txt" if operation == "extraction" else "compare_v1.txt").read_text(encoding="utf-8")
        had_proposals = False
        rejected_initially = 0
        for repair in (False, True):
            request = {**payload}
            if repair:
                request.update(_repair=True, repair_instruction="Previous response failed local schema, source-span or pair-coverage checks. Re-extract/reassess the complete supplied data; use only the supplied sources and selected pairs.")
            try:
                response, raw_usage = self.provider.generate_json(
                    operation=operation, system=prompt, payload=request,
                    response_schema=provider_schema(model),
                    max_output_tokens=self.settings[f"max_output_tokens_{operation}"], budget=budget)
                usage.append(validate_usage(raw_usage, operation))
                if operation == "extraction" and isinstance(response, dict):
                    had_proposals = had_proposals or bool(response.get("claims"))
                result = parser(response)
                if operation == "extraction" and had_proposals and not result[0] and not result[3]:
                    raise invalid("Previously invalid proposals cannot be erased into an empty extraction.")
                if operation == "extraction" and result[2]:
                    if not repair:
                        rejected_initially = len(result[2])
                        continue
                    if result[3] and not result[0]:
                        raise invalid("Every proposed claim failed source/schema validation.")
                if operation == "extraction" and repair and rejected_initially:
                    result[1].append(issue("EXTRACTION_REPAIRED", f"Initial response contained {rejected_initially} unusable proposals; one repair returned {len(result[0])} validated claims. Unusable proposals were repaired or dropped."))
                return result
            except (ValueError, TypeError, KeyError, AnalysisError) as exc:
                if isinstance(exc, AnalysisError) and exc.code != "PROVIDER_RESPONSE_INVALID":
                    raise
                if getattr(exc, "usage", None):
                    usage.append(validate_usage(exc.usage, operation))
                if repair:
                    raise invalid("The analysis provider response remained invalid after one bounded repair.") from exc
        raise invalid()

    def analyze(self, transcript: dict, *, budget, progress=None) -> dict:
        t = validate_transcript(transcript)
        if t["duration_s"] > min(300, self.settings["max_audio_seconds"]):
            raise AnalysisError("AUDIO_TOO_LONG", "Transcript exceeds the configured duration limit.")
        usage, issues = [], []
        report = progress or (lambda message: None)
        report("Extracting factual claims and checking exact source quotations.")
        claims, extraction_issues, _, _ = self._operation(
            "extraction", {"transcript": {k: t[k] for k in ("transcript_id", "language", "duration_s", "segments")}},
            ExtractionDTO, lambda response: parse_extraction(response, t, self.settings["max_claims"]), budget, usage)
        issues.extend(extraction_issues)
        if len(t["speakers"]) > 2:
            issues.append(issue("MORE_THAN_TWO_SPEAKERS", "The demo is normally evaluated with two speakers; all supplied speakers were retained."))
        ranked = ranked_candidates(claims)
        selected = ranked[:self.settings["max_candidate_pairs"]]
        if len(ranked) > len(selected):
            issues.append(issue("CANDIDATES_TRUNCATED", f"Assessed {len(selected)} of {len(ranked)} plausible candidates; this bounded shortlist is not exhaustive."))
        by_id = {c["claim_id"]: c for c in claims}
        pairs, pending = [], []
        for key in selected:
            result = compare_deterministic(*(by_id[k] for k in key))
            if result is None:
                pending.append(key)
            else:
                pairs.append(result)
        if pending:
            report(f"Assessing {len(pending)} pairs requiring contextual reasoning.")
            payload = {"claims": [by_id[k] for k in sorted({k for pair in pending for k in pair})],
                       "selected_pairs": [list(key) for key in pending]}
            pairs.extend(self._operation("comparison", payload, ComparisonDTO,
                lambda response: parse_comparison(response, pending, by_id), budget, usage))
        elif self.settings["mode"] == "fixture":
            usage.append(fixture_usage("comparison"))
        pairs.sort(key=lambda p: (p["claim_a_id"], p["claim_b_id"]))
        if { (p["claim_a_id"], p["claim_b_id"]) for p in pairs } != set(selected) or len(pairs) != len(selected):
            raise invalid("Every selected pair must have exactly one assessment.")
        result = dict(schema_version=self.settings.get('wire_schema_version','1.0.0'), analysis_id="pending", transcript_id=t["transcript_id"],
                      claims=claims, pairs=[dict(pair_id=f"pair_{i:04d}", **p) for i, p in enumerate(pairs, 1)],
                      issues=issues, usage=usage)
        result["analysis_id"] = analysis_identity(result)
        result = validate_analysis(result, t)
        report(f"Analysis complete: {len(claims)} claims and {len(pairs)} assessed pairs.")
        return result
