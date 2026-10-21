"""Read-only, zero-credit checks; the text smoke is separately explicit."""
import importlib.metadata
import importlib.util
import os
import shutil
from pathlib import Path
from .settings import validate_settings


def preflight(settings):
    s=validate_settings(settings)
    checks=[]
    for package,module in [('pydantic','pydantic'),('google-genai','google.genai'),('streamlit','streamlit'),('althea-ingestion','althea_ingestion'),('althea-analysis','althea_analysis'),('althea-evidence-ui','althea_evidence_ui')]:
        try:
            found=importlib.util.find_spec(module) is not None
            version=importlib.metadata.version(package) if found else None
        except (ImportError,importlib.metadata.PackageNotFoundError):
            found=False;version=None
        checks.append(dict(name=package,ok=found,detail=version or 'Install requirements-dev.txt'))
    for binary in ('ffmpeg','ffprobe'):
        checks.append(dict(name=binary,ok=shutil.which(binary) is not None,detail='Available on PATH' if shutil.which(binary) else 'Required for live audio; transcript import/sample still work'))
    if s['provider']=='gemini':
        checks.append(dict(name='Gemini API key',ok=bool(s.get('api_key')),detail='Configured; key not displayed or checked' if s.get('api_key') else 'Set GEMINI_API_KEY or enter a key in the app'))
    else:
        checks.append(dict(name='Google Cloud project',ok=bool(s['project_id']),detail='Configured' if s['project_id'] else 'Set GOOGLE_CLOUD_PROJECT for live calls'))
    adc=os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    known=Path(os.environ.get('APPDATA',str(Path.home()/'.config')))/'gcloud'/'application_default_credentials.json'
    adc_exists=Path(adc).is_file() if adc else known.is_file()
    if s['provider']!='gemini':checks.append(dict(name='Local ADC configuration',ok=adc_exists,detail='A local credential configuration exists; validity/access not checked' if adc_exists else 'Configure gcloud auth application-default login or authorized GOOGLE_APPLICATION_CREDENTIALS'))
    from google.genai import types
    supported=hasattr(types,'AudioTranscriptionConfig') and 'audio_transcription_config' in types.GenerateContentConfig.model_fields
    checks.append(dict(name='Transcription SDK fields',ok=supported,detail='Verbatim/diarization/timestamp schema available' if supported else 'Install a compatible google-genai SDK'))
    return dict(mode=s['mode'],provider=s['provider'],external_requests=0,checks=checks,data_dir=s['data_dir'],
        models={key:s[key] for key in ('transcribe_model','text_model','grounding_model')},
        model_access='Not checked: zero-credit preflight does not contact Google',
        credit_eligibility='Not checked; no billing configuration was changed')


def live_smoke(settings):
    """One accounted text request only; does not establish audio/grounding access."""
    from althea_ingestion.runtime import VertexAdapter,AttemptBudget,usage
    from google.genai import types
    s=validate_settings({**settings,'mode':'live'})
    budget=AttemptBudget(1)
    try:
        response,attempts=VertexAdapter(s).request('extraction',budget,model=s['text_model'],contents='Reply with OK.',config=types.GenerateContentConfig(max_output_tokens=8,temperature=0))
        return dict(status='passed',provider_attempts=budget.used,model=s['text_model'],usage=usage(response,'extraction',s['text_model'],attempts,provider=s['provider']),limitation='Text endpoint only; transcription, grounding, credits and accuracy are not established.')
    except Exception as exc:
        return dict(status='failed',provider_attempts=budget.used,code=getattr(exc,'code','PROVIDER_UNAVAILABLE'),message='Live text smoke did not finish; check project, ADC, model access and connectivity.')
