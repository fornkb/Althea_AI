"""Only the application reads environment configuration. No import-time I/O."""
import math
import os
import re
from pathlib import Path
from .errors import require

DEFAULTS = dict(mode='fixture',provider='gemini',api_key=None,project_id=None,location='global',transcribe_model='gemini-3.5-transcribe',gemini_audio_model='gemini-3.5-flash-lite',
    text_model='gemini-3.5-flash-lite',grounding_model='gemini-3.5-flash-lite',max_audio_seconds=300,
    max_upload_bytes=20*1024*1024,max_claims=30,max_candidate_pairs=60,max_display_conflicts=8,
    max_verify_pairs=4,max_provider_attempts=20,max_output_tokens_extraction=8192,
    max_output_tokens_comparison=8192,max_output_tokens_retrieval=2048,
    max_output_tokens_adjudication=2048,request_timeout_s=90)

ENV = dict(GOOGLE_CLOUD_PROJECT='project_id',GOOGLE_CLOUD_LOCATION='location',
    ALTHEA_TRANSCRIBE_MODEL='transcribe_model',ALTHEA_TEXT_MODEL='text_model',
    ALTHEA_GROUNDING_MODEL='grounding_model',ALTHEA_DATA_DIR='data_dir',ALTHEA_PROVIDER='provider',GEMINI_API_KEY='api_key',ALTHEA_GEMINI_AUDIO_MODEL='gemini_audio_model')


def project_root():
    # Works for editable source installs; callers may explicitly pass root/data_dir.
    for parent in Path(__file__).resolve().parents:
        if (parent/'reference').is_dir() and (parent/'analysis').is_dir():
            return parent
    return Path.cwd().resolve()


def read_dotenv(path):
    """Read simple KEY=value entries without executing/expanding shell expressions."""
    result = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:]
        key,sep,value = line.partition('=')
        require(bool(sep) and bool(re.fullmatch('[A-Z_][A-Z0-9_]*',key.strip())), 'Invalid .env entry.', 'INVALID_INPUT')
        value = value.strip()
        if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):
            value = value[1:-1]
        else:
            value = value.split(' #',1)[0].rstrip()
        result[key.strip()] = value
    return result


def validate_settings(settings, *, root=None):
    root = Path(root or project_root()).resolve()
    s = {**DEFAULTS,'data_dir':str(root/'data'),**settings}
    require(s['mode'] in ('fixture','live'),'Mode must be fixture or live.','INVALID_INPUT')
    require(s['provider'] in ('vertex','gemini'),'Provider must be vertex or gemini.','INVALID_INPUT')
    require(s['api_key'] is None or isinstance(s['api_key'],str) and 0<len(s['api_key'])<=512 and not any(c.isspace() for c in s['api_key']),'Invalid API key format.','INVALID_INPUT')
    s['wire_schema_version']='1.1.0' if s['provider']=='gemini' else '1.0.0'
    if s['provider']=='gemini':s['transcribe_model']=s['gemini_audio_model']
    for key,cap in [('max_claims',30),('max_candidate_pairs',60),('max_display_conflicts',8),('max_verify_pairs',4),('max_provider_attempts',20),('max_upload_bytes',20*1024*1024),('max_output_tokens_extraction',8192),('max_output_tokens_comparison',8192),('max_output_tokens_retrieval',2048),('max_output_tokens_adjudication',2048)]:
        require(type(s[key]) is int and 1<=s[key]<=cap,f'{key} must be an integer from 1 to {cap}.','INVALID_INPUT')
    for key,cap in [('max_audio_seconds',300),('request_timeout_s',90)]:
        require(type(s[key]) in (int,float) and math.isfinite(s[key]) and 0<s[key]<=cap,f'{key} must be greater than zero and at most {cap}.','INVALID_INPUT')
    for key in ('transcribe_model','gemini_audio_model','text_model','grounding_model','location'):
        require(isinstance(s[key],str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,199}',s[key])),f'Invalid {key}.','INVALID_INPUT')
    require(s['project_id'] is None or isinstance(s['project_id'],str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}',s['project_id'])),'Invalid project identifier.','INVALID_INPUT')
    path = Path(s['data_dir']).expanduser()
    s['data_dir'] = str((path if path.is_absolute() else root/path).resolve())
    return s


def load_settings(mode='fixture', *, root=None, environ=None, overrides=None):
    root = Path(root or project_root()).resolve()
    env = {**read_dotenv(root/'.env'),**(os.environ if environ is None else environ)}
    values = {key:env[name] for name,key in ENV.items() if env.get(name)}
    return validate_settings({**values,'mode':mode,**(overrides or {})},root=root)
