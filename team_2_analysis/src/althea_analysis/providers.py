"""Offline fakes and the explicitly Vertex-only hosted text adapter."""
import copy
import json
import random
import time
from importlib.resources import files
from .errors import AnalysisError, invalid


def fixture_usage(operation):
    return dict(stage=operation, provider="fixture", model="fixture-v1",
                request_count=0, input_tokens=0, output_tokens=0)


class FixtureTextProvider:
    """Exact saved Riverton extraction, followed by the normal Python pipeline."""
    mode = "fixture"

    def generate_json(self, *, operation, system, payload, response_schema, max_output_tokens, budget):
        data = files("althea_analysis").joinpath("data")
        if operation == "extraction":
            transcript = json.loads(data.joinpath("transcript.json").read_text(encoding="utf-8"))
            if payload["transcript"] != {k: transcript[k] for k in ("transcript_id", "language", "duration_s", "segments")}:
                raise AnalysisError("INVALID_INPUT", "Fixture mode supports the supplied Riverton transcript only; inject a fake for other offline cases.")
            reference = json.loads(data.joinpath("expected_analysis.json").read_text(encoding="utf-8"))
            claims = []
            for claim in reference["claims"]:
                c = copy.deepcopy(claim)
                c.pop("claim_id")
                c["quantity_raw"] = c.pop("quantity")["raw_text"]
                c["currency_context"] = None
                claims.append(c)
            return {"claims": claims}, fixture_usage(operation)
        raise invalid("Fixture unexpectedly requested a hosted comparison.")


class ScriptedTextProvider:
    """Deterministic integration fake; one budgeted simulated attempt per event.

    Events are JSON dictionaries, exceptions, or (JSON, Usage) tuples. Fixture
    mode accepts it because it never calls the network. Token counts are unknown
    for simulated live requests. No data is downloaded or inferred here.
    """
    mode = "fixture"

    def __init__(self, events, *, consume=True):
        self.events = list(events)
        self.calls = []
        self.consume = consume

    def generate_json(self, *, operation, system, payload, response_schema, max_output_tokens, budget):
        if self.consume:
            budget.consume(operation)
        self.calls.append(dict(operation=operation, system=system, payload=copy.deepcopy(payload),
                               response_schema=response_schema, max_output_tokens=max_output_tokens))
        if not self.events:
            raise invalid("Scripted provider has no remaining event.")
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        if isinstance(event, tuple):
            return copy.deepcopy(event)
        return copy.deepcopy(event), fixture_usage(operation)


class VertexTextProvider:
    mode = "live"

    def __init__(self, settings, *, client=None, sleeper=time.sleep, jitter=random.random):
        self.settings = dict(settings)
        self._client = client
        self._sleep, self._jitter = sleeper, jitter
        self._attempts = {}

    def _get_client(self):
        if self._client is None:
            from google import genai
            from google.genai import types
            from google.auth.exceptions import DefaultCredentialsError, GoogleAuthError
            gemini=self.settings.get('provider')=='gemini'
            if gemini and not self.settings.get('api_key'):
                raise AnalysisError('PROVIDER_AUTH','Add your Gemini API key.')
            if not gemini and not self.settings.get("project_id"):
                raise AnalysisError("PROVIDER_AUTH", "Live mode requires a Google Cloud project and Application Default Credentials.")
            try:
                options=types.HttpOptions(api_version=None if gemini else 'v1',timeout=int(self.settings.get('request_timeout_s',90)*1000),retry_options=types.HttpRetryOptions(attempts=1))
                self._client=genai.Client(vertexai=False,api_key=self.settings['api_key'],http_options=options) if gemini else genai.Client(vertexai=True,project=self.settings['project_id'],location=self.settings.get('location','global'),http_options=options)
            except (DefaultCredentialsError, GoogleAuthError) as exc:
                raise AnalysisError("PROVIDER_AUTH", "Google Cloud Application Default Credentials are unavailable.") from exc
            except (TypeError, ValueError) as exc:
                raise AnalysisError("PROVIDER_UNAVAILABLE", "The Google Cloud client configuration is unsupported.") from exc
        return self._client

    def generate_json(self, *, operation, system, payload, response_schema, max_output_tokens, budget):
        from google.genai import types
        from google.auth.exceptions import GoogleAuthError
        import httpx
        if not payload.get("_repair"):
            self._attempts[operation] = 0
        self._attempts.setdefault(operation, 0)
        if self._attempts[operation] >= 3:
            raise invalid("The three-attempt ceiling for this operation has been reached.")
        client = self._get_client()
        count, input_tokens, output_tokens = 0, 0, 0
        token_counts_known = True

        def usage():
            return dict(stage=operation, provider="gemini" if self.settings.get('provider')=='gemini' else "vertex", model=self.settings.get("text_model", "gemini-2.5-flash"),
                        request_count=count, input_tokens=input_tokens if token_counts_known else None,
                        output_tokens=output_tokens if token_counts_known else None)

        while self._attempts[operation] < 3:
            try:
                budget.consume(operation)
            except Exception as exc:
                if getattr(exc, "code", None) == "BUDGET_LIMIT":
                    raise AnalysisError("BUDGET_LIMIT", "The shared job attempt budget is exhausted.", stage=operation) from exc
                raise
            self._attempts[operation] += 1
            count += 1
            try:
                response = client.models.generate_content(
                    model=self.settings.get("text_model", "gemini-2.5-flash"),
                    contents=json.dumps(payload, ensure_ascii=False, allow_nan=False),
                    config=types.GenerateContentConfig(
                        system_instruction=system, response_mime_type="application/json",
                        response_schema=response_schema, temperature=0,
                        max_output_tokens=max_output_tokens))
                metadata = response.usage_metadata
                if metadata is None or metadata.prompt_token_count is None or metadata.candidates_token_count is None:
                    token_counts_known = False
                else:
                    input_tokens += metadata.prompt_token_count
                    output_tokens += metadata.candidates_token_count
                try:
                    parsed = json.loads(response.text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
                    if not isinstance(parsed, dict):
                        raise ValueError("Expected object")
                except (ValueError, TypeError):
                    error = invalid("The model did not return a valid JSON object.")
                    error.usage = usage()
                    raise error
                return parsed, usage()
            except AnalysisError:
                raise
            except Exception as exc:
                code = getattr(exc, "code", None)
                token_counts_known = False
                auth = code in (401, 403) or isinstance(exc, GoogleAuthError)
                transient = code == 429 or isinstance(code, int) and 500 <= code <= 599 or isinstance(exc, (httpx.TransportError, TimeoutError, ConnectionError))
                if transient and self._attempts[operation] < 3:
                    self._sleep(min(4, .5 * 2 ** (self._attempts[operation] - 1)) + .25 * self._jitter())
                    continue
                safe_code = "PROVIDER_AUTH" if auth else "RATE_LIMIT" if code == 429 else "PROVIDER_UNAVAILABLE"
                error = AnalysisError(safe_code, "Selected text provider request failed; check credentials, model access, quota and connectivity.",
                                      retryable=bool(transient), stage=operation)
                error.usage = usage()
                raise error from exc
