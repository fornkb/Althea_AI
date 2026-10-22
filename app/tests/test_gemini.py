import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from althea_app import GeminiBackend,load_settings
from althea_app.gemini_audio import GeminiAudioTranscriber,clock_time
from althea_app.preflight import preflight
from althea_app.settings import validate_settings
from althea_app.cache_keys import analysis_key,transcription_key,verification_key
from althea_app.errors import AppError
from althea_ingestion.runtime import AttemptBudget,VertexAdapter
from althea_ingestion.common import canonical
from althea_evidence_ui import snapshot_json
from .conftest import ROOT,Providers

SECRET='TEST-KEY-FOR-OFFLINE-ASSERTIONS-ONLY'


def test_gemini_route_complete_with_actual_adapters(live_factory,reference,monkeypatch):
    from google import genai
    from google.genai import types
    _,_,source=live_factory()
    sdk_clients=[];calls=[]
    templates=Providers(reference)
    class Models:
        def generate_content(self,**kwargs):
            assert kwargs['model']=='gemini-3.5-flash-lite'
            config=kwargs['config'];contents=kwargs['contents']
            meta=SimpleNamespace(prompt_token_count=11,candidates_token_count=7)
            if isinstance(contents,list):
                calls.append('transcription')
                assert 'measured duration of this uploaded clip is 65.000 seconds' in contents[1]
                timestamps=config.response_schema['properties']['segments']['items']['properties']
                assert all(timestamps[key]['type']=='STRING' and timestamps[key]['pattern'] for key in ('start_time','end_time'))
                assert config.audio_transcription_config is None
                result=dict(language='en',segments=[dict(speaker=s['speaker_id'],start_time=clock_time(s['start_s']),end_time=clock_time(s['end_s']),text=s['text']) for s in reference['transcript']['segments']])
                return SimpleNamespace(text=json.dumps(result),usage_metadata=meta)
            payload=json.loads(contents)
            if config.tools:
                calls.append('retrieval');assert config.response_schema is None
                passage="Riverton's 2024 transport budget was USD 11000000."
                metadata=types.GroundingMetadata(grounding_chunks=[types.GroundingChunk(web=types.GroundingChunkWeb(uri='https://example.org/test-budget',title='Simulated Gemini source'))],grounding_supports=[types.GroundingSupport(segment=types.Segment(text=passage),grounding_chunk_indices=[0])])
                return SimpleNamespace(text=passage,candidates=[SimpleNamespace(grounding_metadata=metadata)],usage_metadata=meta)
            if 'transcript' in payload:
                calls.append('extraction')
                result,_=templates.generate_json(operation='extraction',system='',payload=payload,response_schema=None,max_output_tokens=8192,budget=SimpleNamespace(consume=lambda _:None))
                return SimpleNamespace(text=json.dumps(result),usage_metadata=meta)
            calls.append('adjudication');assert not config.tools
            evidence=payload['evidence'];pair=payload['pair']
            result=dict(pair_id=pair['pair_id'],summary='Simulated independent assessments.',verdicts=[dict(claim_id=c['claim_id'],status='refuted',rationale='Simulated reference differs.',evidence_refs=[dict(evidence_id=evidence[0]['evidence_id'],stance='refutes')]) for c in payload['claims']])
            return SimpleNamespace(text=json.dumps(result),usage_metadata=meta)
    def client(**kwargs):
        sdk_clients.append(kwargs)
        assert kwargs['vertexai'] is False and kwargs['api_key']==SECRET
        assert 'project' not in kwargs and kwargs['http_options'].retry_options.attempts==1
        return SimpleNamespace(models=Models())
    monkeypatch.setattr(genai,'Client',client)
    b=GeminiBackend({**live_factory.settings,'api_key':SECRET})
    assert sdk_clients==[]
    s=b.run(source,verify=True)
    assert s['status']=='complete',s['issues']
    assert calls==['transcription','extraction','retrieval','adjudication']
    assert all(s[k]['schema_version']=='1.1.0' for k in ('transcript','analysis','verification'))
    assert s['schema_version']=='1.1.0'
    assert {u['provider'] for k in ('transcript','analysis','verification') for u in s[k]['usage']}=={'gemini'}
    assert s['transcript']['issues'][0]['code']=='MODEL_GENERATED_TIMINGS'
    assert b.job_usage(s['job_id'])['attempts_used']==4
    assert Path(b.repository.db_path).name=='live-gemini.sqlite'
    assert SECRET.encode() not in snapshot_json(s)
    assert SECRET not in json.dumps(b.repository.events_for_job(s['job_id']))
    assert SECRET.encode() not in Path(b.repository.db_path).read_bytes()
    cached=b.run(source,verify=True)
    assert b.job_usage(cached['job_id'])['attempts_used']==0 and len(calls)==4


@pytest.mark.parametrize('problem',['no_speech','missing_time','speakerless','wrong_language','out_of_order'])
def test_gemini_audio_never_invents_annotations(tmp_path,reference,problem):
    audio=tmp_path/'test.wav';audio.write_bytes(b'MOCK, NOT SPEECH')
    turn=dict(speaker='speaker A',start_time='00:00.000',end_time='00:01.000',text='No 10 million.')
    payload=dict(language='en',segments=[turn])
    if problem=='no_speech':payload['segments']=[]
    if problem=='missing_time':turn.pop('end_time')
    if problem=='speakerless':turn['speaker']=None
    if problem=='wrong_language':payload['language']='es'
    if problem=='out_of_order':turn.update(start_time='00:02.000',end_time='00:01.000')
    adapter=GeminiAudioTranscriber(dict(provider='gemini',api_key=SECRET))
    adapter._client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **k:SimpleNamespace(text=json.dumps(payload),usage_metadata=None)))
    budget=AttemptBudget(1)
    if problem=='out_of_order':
        from althea_ingestion.transcription import normalize_words
        with pytest.raises(RuntimeError):normalize_words(adapter.transcribe(str(audio),language='en',expected_speakers=2,budget=budget)['words'])
    else:
        with pytest.raises(RuntimeError):adapter.transcribe(str(audio),language='en',expected_speakers=2,budget=budget)
    assert budget.used==1


@pytest.mark.parametrize('timings,detail',[
    ([(0.0,180.5)],'beyond the 180.021s recording'),
    ([(-0.5,1.0)],'start/end times'),
    ([(3.0,4.0),(2.0,3.0)],'previous start 3.000s'),
    ([(1.0,1.0)],'invalid timing'),
])
def test_gemini_invalid_timing_has_actionable_error(tmp_path,timings,detail):
    path=tmp_path/'test.mp3';path.write_bytes(b'MOCK AUDIO')
    payload=dict(language='en',segments=[dict(speaker='A',start_time=clock_time(start),end_time=clock_time(end),text='Speech.') for start,end in timings])
    adapter=GeminiAudioTranscriber(dict(provider='gemini',api_key=SECRET))
    adapter._client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **k:SimpleNamespace(text=json.dumps(payload),usage_metadata=None)))
    budget=AttemptBudget(1)
    with pytest.raises(AppError,match=detail) as caught:
        adapter.transcribe(str(path),language='en',expected_speakers=2,budget=budget,duration_s=180.021)
    assert caught.value.code=='PROVIDER_RESPONSE_INVALID' and budget.used==1


def test_gemini_invalid_duration_stops_before_claim_analysis(live_factory,monkeypatch):
    from google import genai
    _,_,source=live_factory()
    calls=[]
    def generate_content(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=json.dumps(dict(language='en',segments=[dict(speaker='A',start_time='00:00.000',end_time='01:06.000',text='Speech.')])),usage_metadata=None)
    monkeypatch.setattr(genai,'Client',lambda **k:SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    b=GeminiBackend({**live_factory.settings,'api_key':SECRET})
    result=b.run(source,verify=False)
    assert result['status']=='failed' and result['transcript'] is None and result['analysis'] is None
    assert result['issues'][0]['code']=='PROVIDER_RESPONSE_INVALID'
    assert 'beyond the 65.000s recording' in result['issues'][0]['message']
    assert len(calls)==1 and b.job_usage(result['job_id'])['attempts_used']==1


def test_gemini_preserves_valid_overlapping_speech(tmp_path):
    path=tmp_path/'test.wav';path.write_bytes(b'MOCK AUDIO')
    segments=[dict(speaker='A',start_time='00:00.000',end_time='00:03.000',text='First turn.'),dict(speaker='B',start_time='00:01.000',end_time='00:02.000',text='Interruption.')]
    adapter=GeminiAudioTranscriber(dict(provider='gemini',api_key=SECRET))
    adapter._client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **k:SimpleNamespace(text=json.dumps(dict(language='en',segments=segments)),usage_metadata=None)))
    result=adapter.transcribe(str(path),language='en',expected_speakers=2,budget=AttemptBudget(1),duration_s=3.0)
    assert [(w['start_s'],w['end_s'],w['word']) for w in result['words']]==[(0.0,3.0,'First turn.'),(1.0,2.0,'Interruption.')]


def test_gemini_inline_limit_precedes_cloud_attempt(tmp_path):
    path=tmp_path/'large.wav'
    with path.open('wb') as f:f.truncate(13*1024*1024+1)
    budget=AttemptBudget()
    with pytest.raises(AppError,match='13 MiB'):GeminiAudioTranscriber(dict(provider='gemini',api_key=SECRET)).transcribe(str(path),language='en',expected_speakers=2,budget=budget)
    assert budget.used==0


def test_key_settings_preflight_and_cache_identity(tmp_path):
    s=load_settings('live',root=tmp_path,environ={'GEMINI_API_KEY':SECRET})
    assert s['api_key']==SECRET and s['provider']=='gemini' and s['project_id'] is None
    assert {s[k] for k in ('transcribe_model','gemini_audio_model','text_model','grounding_model')}=={'gemini-3.5-flash-lite'}
    assert s['wire_schema_version']=='1.1.0'
    report=preflight(s)
    assert report['provider']=='gemini' and not any(c['name']=='Google Cloud project' for c in report['checks'])
    assert next(c for c in report['checks'] if c['name']=='Gemini API key')['ok']
    assert SECRET not in json.dumps(report)
    other={**s,'api_key':'OTHER-TEST-KEY'}
    assert analysis_key(s,'tr')==analysis_key(other,'tr')
    assert transcription_key(s,'bytes')==transcription_key(other,'bytes')
    assert verification_key(s,'an','p')==verification_key(other,'an','p')
    vertex=validate_settings({**s,'provider':'vertex'})
    assert analysis_key(s,'tr')!=analysis_key(vertex,'tr')


@pytest.mark.parametrize('status,code',[(403,'PROVIDER_AUTH'),(429,'RATE_LIMIT')])
def test_api_key_and_quota_errors_are_safe(monkeypatch,status,code):
    from althea_ingestion import runtime
    monkeypatch.setattr(runtime.time,'sleep',lambda _:None)
    class Failure(Exception):
        def __init__(self):super().__init__('secret='+SECRET);self.code=status
    def fail(**k):raise Failure()
    adapter=VertexAdapter(dict(provider='gemini',api_key=SECRET))
    adapter._client=SimpleNamespace(models=SimpleNamespace(generate_content=fail))
    budget=AttemptBudget()
    with pytest.raises(RuntimeError) as caught:adapter.request('retrieval',budget,model='gemini-2.5-flash')
    assert caught.value.code==code and SECRET not in str(caught.value)
    assert budget.used==(1 if status==403 else 3)


def test_api_key_ui_is_masked_session_only_and_clearable(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from streamlit.proto.TextInput_pb2 import TextInput
    from google import genai
    monkeypatch.setenv('ALTHEA_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    monkeypatch.setattr(genai,'Client',lambda **k:(_ for _ in ()).throw(AssertionError('Saving a key must not call the API')))
    app=AppTest.from_file(str(ROOT/'app/streamlit_app.py'),default_timeout=25).run()
    assert not any(w.label=='Gemini API key' for w in app.text_input)
    assert next(b for b in app.button if b.label=='Analyze').disabled
    next(b for b in app.button if b.label=='Settings').click().run()
    assert not app.exception
    key=next(w for w in app.text_input if w.label=='Gemini API key')
    assert key.proto.type==TextInput.PASSWORD
    key.set_value(SECRET)
    next(b for b in app.button if b.label=='Use API key').click().run()
    assert not app.exception
    backend=app.session_state['althea_backend_Gemini API key']
    assert backend.settings['api_key']==SECRET and backend.list_jobs()==[]
    next(b for b in app.button if b.label=='Home').click().run()
    assert not any(w.label=='Gemini API key' for w in app.text_input)
    assert backend.settings['api_key']==SECRET
    assert next(b for b in app.button if b.label=='Analyze').disabled  # audio still required
    for path in (tmp_path/'data').rglob('*.sqlite'):
        assert SECRET.encode() not in path.read_bytes()
    next(b for b in app.button if b.label=='Settings').click().run()
    next(b for b in app.button if b.label=='Clear API key').click().run()
    assert not app.exception and backend.settings['api_key'] is None
    assert next(w for w in app.text_input if w.label=='Gemini API key').value==''


@pytest.mark.live
def test_explicit_gemini_text_smoke():
    import os
    if os.getenv('ALTHEA_RUN_GEMINI_SMOKE')!='1' or not os.getenv('GEMINI_API_KEY'):
        pytest.skip('Set GEMINI_API_KEY and ALTHEA_RUN_GEMINI_SMOKE=1 to authorize one actual API-key text request.')
    from althea_app.preflight import live_smoke
    result=live_smoke(load_settings('live',overrides={'provider':'gemini'}))
    assert result['status']=='passed'
