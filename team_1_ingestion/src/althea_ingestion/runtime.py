"""Lazy Vertex client and bounded, explicitly accounted attempts."""
import random
import time
from .errors import ComponentError, require


class AttemptBudget:
    def __init__(self, limit=20):
        self.limit, self.used = min(limit,20), 0

    def consume(self, stage):
        require(self.used < self.limit, 'Provider-attempt limit reached.', 'BUDGET_LIMIT')
        self.used += 1


class VertexAdapter:
    def __init__(self, settings):
        self.settings, self._client = settings, None

    def client(self):
        if self._client is None:
            gemini=self.settings.get('provider')=='gemini'
            require(bool(self.settings.get('api_key')) if gemini else bool(self.settings.get('project_id')), 'Add your Gemini API key.' if gemini else 'Set GOOGLE_CLOUD_PROJECT and configure Application Default Credentials.', 'PROVIDER_AUTH' if gemini else 'PROVIDER_UNAVAILABLE')
            try:
                from google import genai
                from google.genai import types
                options=types.HttpOptions(timeout=int(self.settings.get('request_timeout_s',90)*1000),retry_options=types.HttpRetryOptions(attempts=1))
                self._client = genai.Client(vertexai=False,api_key=self.settings['api_key'],http_options=options) if gemini else genai.Client(vertexai=True,project=self.settings['project_id'],location=self.settings.get('location','global'),http_options=options)
            except Exception as exc:
                raise ComponentError('PROVIDER_UNAVAILABLE', 'Provider client unavailable; check the selected route and its credentials.', stage='transcription') from exc
        return self._client

    def request(self, stage, budget, **kwargs):
        client = self.client()
        for attempt in range(1,4):
            budget.consume(stage)
            try:
                return client.models.generate_content(**kwargs), attempt
            except Exception as exc:
                code = getattr(exc,'code',None) or getattr(exc,'status_code',None)
                import httpx
                transient = code in (429,500,502,503,504) or isinstance(exc,(TimeoutError,ConnectionError,httpx.TransportError))
                if transient and attempt < 3:
                    time.sleep(min(2**(attempt-1),4)+random.uniform(0,.2))
                    continue
                safe_code='PROVIDER_AUTH' if code in (401,403) else 'RATE_LIMIT' if code==429 else 'PROVIDER_UNAVAILABLE'
                message='Provider rate limit reached; check your quota window and retry later.' if code==429 else f'{stage.capitalize()} failed; check credentials, model access, quota and connectivity.'
                raise ComponentError(safe_code,message,stage='transcription' if stage=='transcription' else 'verification',retryable=transient) from exc


def usage(response, stage, model, count, *, provider='vertex'):
    meta = getattr(response,'usage_metadata',None)
    return dict(stage=stage,provider=provider,model=model,request_count=count,
                input_tokens=getattr(meta,'prompt_token_count',None),output_tokens=getattr(meta,'candidates_token_count',None))
