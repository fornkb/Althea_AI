import os
from types import SimpleNamespace
import pytest
from althea_analysis import AnalysisService, AttemptBudget, AnalysisError
from althea_analysis.providers import VertexTextProvider
from althea_analysis.dto import ExtractionDTO, provider_schema


class HTTPError(Exception):
    def __init__(self, code):
        self.code = code


def response(text='{"claims": []}', *, tokens=True):
    metadata = SimpleNamespace(prompt_token_count=11, candidates_token_count=3) if tokens else None
    return SimpleNamespace(text=text, usage_metadata=metadata)


class Client:
    def __init__(self, events):
        self.events, self.calls = list(events), []
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        event = self.events.pop(0)
        if isinstance(event, Exception): raise event
        return event


def generate(provider, budget, *, repair=False):
    return provider.generate_json(operation="extraction", system="test", payload={"_repair": True} if repair else {},
        response_schema=provider_schema(ExtractionDTO), max_output_tokens=100, budget=budget)


def test_transient_retries_count_every_attempt_and_preserve_unknown_usage():
    client, sleeps = Client([HTTPError(429), HTTPError(503), response()]), []
    p = VertexTextProvider({}, client=client, sleeper=sleeps.append, jitter=lambda: 0)
    budget = AttemptBudget(3)
    data, usage = generate(p, budget)
    assert data == {"claims": []}
    assert budget.used == usage["request_count"] == len(client.calls) == 3
    assert usage["input_tokens"] is None and usage["output_tokens"] is None
    assert sleeps == [.5, 1]
    config = client.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.max_output_tokens == 100


@pytest.mark.parametrize("code,expected", [(401, "PROVIDER_AUTH"), (403, "PROVIDER_AUTH"), (400, "PROVIDER_UNAVAILABLE"), (404, "PROVIDER_UNAVAILABLE")])
def test_permanent_failures_not_retried(code, expected):
    client = Client([HTTPError(code)])
    p = VertexTextProvider({}, client=client)
    with pytest.raises(AnalysisError) as caught: generate(p, AttemptBudget())
    assert caught.value.code == expected
    assert len(client.calls) == 1


def test_budget_prevents_additional_network_call():
    client = Client([HTTPError(503), response()])
    p = VertexTextProvider({}, client=client, sleeper=lambda _: None)
    with pytest.raises(AnalysisError) as caught: generate(p, AttemptBudget(1))
    assert caught.value.code == "BUDGET_LIMIT"
    assert len(client.calls) == 1


def test_invalid_json_repair_within_same_three_attempt_ceiling(transcript):
    client = Client([HTTPError(503), response("invalid json"), response()])
    p = VertexTextProvider({}, client=client, sleeper=lambda _: None)
    budget = AttemptBudget()
    a = AnalysisService({"mode": "live"}, text_provider=p).analyze(transcript, budget=budget)
    assert a["claims"] == [] and len(client.calls) == budget.used == 3
    assert sum(x["request_count"] for x in a["usage"]) == 3


def test_no_hidden_fourth_attempt(transcript):
    client = Client([HTTPError(429), HTTPError(503), response("bad JSON"), response()])
    p = VertexTextProvider({}, client=client, sleeper=lambda _: None)
    budget = AttemptBudget()
    with pytest.raises(AnalysisError) as caught:
        AnalysisService({"mode": "live"}, text_provider=p).analyze(transcript, budget=budget)
    assert caught.value.code == "PROVIDER_RESPONSE_INVALID"
    assert len(client.calls) == budget.used == 3


def test_second_invalid_response_is_failure(transcript):
    client = Client([response("bad"), response("bad"), response()])
    p = VertexTextProvider({}, client=client)
    with pytest.raises(AnalysisError) as caught:
        AnalysisService({"mode": "live"}, text_provider=p).analyze(transcript, budget=AttemptBudget())
    assert caught.value.code == "PROVIDER_RESPONSE_INVALID"
    assert len(client.calls) == 2


def test_success_tokens_and_missing_metadata():
    p = VertexTextProvider({}, client=Client([response(), response(tokens=False)]))
    _, usage = generate(p, AttemptBudget())
    assert (usage["request_count"], usage["input_tokens"], usage["output_tokens"]) == (1, 11, 3)
    _, usage = generate(p, AttemptBudget())
    assert usage["input_tokens"] is None


def test_sdk_retries_disabled_and_client_lazy(monkeypatch):
    from google import genai
    seen = []
    monkeypatch.setattr(genai, "Client", lambda **kwargs: seen.append(kwargs) or Client([response()]))
    p = VertexTextProvider({"project_id": "synthetic-project"})
    assert not seen
    generate(p, AttemptBudget())
    assert seen[0]["vertexai"] is True
    assert seen[0]["http_options"].retry_options.attempts == 1
    assert seen[0]["http_options"].timeout == 90000
    assert "api_key" not in seen[0]


@pytest.mark.live
def test_live_smoke(transcript):
    if os.environ.get("ALTHEA_RUN_LIVE") != "1" or not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        pytest.skip("Set ALTHEA_RUN_LIVE=1 and an authorized Google Cloud project with ADC to opt in.")
    result = AnalysisService(dict(mode="live", project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        text_model=os.environ.get("ALTHEA_TEXT_MODEL", "gemini-2.5-flash"))).analyze(transcript, budget=AttemptBudget())
    assert result["transcript_id"] == transcript["transcript_id"]
