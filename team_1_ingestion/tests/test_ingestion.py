import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
from althea_ingestion import IngestionService, Repository, validate_transcript, recompute_transcript_id, IngestionError
from althea_ingestion.common import digest, validate_snapshot
from althea_ingestion.runtime import AttemptBudget, VertexAdapter
from althea_ingestion.audio import prepare_audio, beneath
from althea_ingestion.transcription import normalize_words, seconds, GoogleCloudTranscriber


def source(path=None):
    return dict(kind='transcript' if path else 'sample',local_path=str(path) if path else None,sample_id=None if path else 'riverton_demo',title='Test')


def test_frozen_contract():
    root = Path(__file__).parents[2]
    assert (root/'build_handoffs/reference/contract_v1_1.py').read_bytes() == (root/'team_1_ingestion/src/althea_ingestion/_contract.py').read_bytes()


def test_sample_import_no_network(snapshot,tmp_path):
    service = IngestionService(dict(mode='fixture',data_dir=str(tmp_path)))
    t = service.ingest(source(),budget=AttemptBudget(0))
    assert t['transcript_id'] == snapshot['transcript']['transcript_id']
    assert len(t['segments']) == 8 and t['origin']=='fixture'
    path = tmp_path/'transcript with spaces.json'
    path.write_text(json.dumps(t,ensure_ascii=False),encoding='utf-8')
    assert service.ingest(source(path),budget=AttemptBudget(0)) == t


@pytest.mark.parametrize('change',['hash','id','language','speaker','order','empty','time','unknown','duration'])
def test_reject_transcript_mutations(snapshot,change):
    t = snapshot['transcript']
    if change=='hash': t['source']['content_sha256']='f'*64
    if change=='id': t['transcript_id']='wrong'
    if change=='language': t['language']='hi'
    if change=='speaker': t['segments'][0]['speaker_id']='ghost'
    if change=='order': t['segments'].reverse()
    if change=='empty': t['segments']=[]
    if change=='time': t['segments'][0]['end_s']=float('nan')
    if change=='unknown': t['extra']=True
    if change=='duration': t['duration_s']=300.001
    with pytest.raises(IngestionError): validate_transcript(t)


def test_unicode_title_and_overlap(snapshot):
    t = snapshot['transcript']
    initial = recompute_transcript_id(t)
    t['source']['title']='नमस्ते ☕'
    assert recompute_transcript_id(t)==initial
    t['segments'][0]['text']='नहीं—10 million; café'
    t['segments'][1]['start_s']=7.0
    t['transcript_id']=recompute_transcript_id(t)
    assert validate_transcript(t)['segments'][0]['text']=='नहीं—10 million; café'


@pytest.mark.parametrize('relative',['../escape.wav','nested/../../escape.wav','C:/escape.wav'])
def test_import_path_escape(snapshot,tmp_path,relative):
    t=snapshot['transcript']; t['source']['audio_relpath']=relative
    path=tmp_path/'t.json'; path.write_text(json.dumps(t),encoding='utf-8')
    with pytest.raises(IngestionError):
        IngestionService(dict(mode='fixture',data_dir=str(tmp_path))).ingest(source(path),budget=AttemptBudget(0))


def test_normalize_words_overlap_gap():
    speakers,turns=normalize_words([
        dict(speaker='opaque-X',word='No',start_s=0.0,end_s=.5),
        dict(speaker='opaque-X',word='10',start_s=.5,end_s=1.0),
        dict(speaker='opaque-Y',word='12',start_s=.75,end_s=1.5),
        dict(speaker='opaque-Y',word='million.',start_s=3.0,end_s=4.0)])
    assert [s['speaker_id'] for s in speakers]==['speaker_01','speaker_02']
    assert turns[0]['text']=='No 10' and len(turns)==3
    assert turns[1]['start_s'] < turns[0]['end_s']


@pytest.mark.parametrize('word',[{},dict(speaker=None,word='No',start_s=0,end_s=1),dict(speaker='x',word='No',start_s=None,end_s=1),dict(speaker='x',word='No',start_s=1,end_s=0)])
def test_bad_words(word):
    with pytest.raises(IngestionError): normalize_words([word])


def mock_media(monkeypatch,duration=300.0,codec='pcm_s16le',silent=False):
    from althea_ingestion import audio
    monkeypatch.setattr(audio.shutil,'which',lambda x:x)
    def run(args,**kwargs):
        assert isinstance(args,list) and 'shell' not in kwargs
        if args[0]=='ffprobe':
            return SimpleNamespace(stdout=json.dumps(dict(format={'duration':str(duration),'format_name':'wav'},streams=[dict(codec_type='audio',codec_name=codec,channels=2)])).encode())
        return SimpleNamespace(stdout=b'\0\0' if silent else b'\1\0')
    monkeypatch.setattr(audio,'run_tool',run)


def test_media_boundary_and_hash(tmp_path,monkeypatch):
    mock_media(monkeypatch)
    path=tmp_path/'two speakers with spaces.WAV'; path.write_bytes(b'fake-test-audio')
    settings=dict(data_dir=str(tmp_path/'data'))
    m=prepare_audio(path,settings)
    assert m['duration_s']==300.0
    assert prepare_audio(path,settings)==m
    assert beneath(settings['data_dir'],m['audio_relpath']).read_bytes()==b'fake-test-audio'
    assert m['original_filename']==path.name
    mock_media(monkeypatch,300.0001)
    with pytest.raises(IngestionError,match='five-minute'): prepare_audio(path,settings)


@pytest.mark.parametrize('problem',['missing','corrupt','silent','oversize','wrongext','format','nostream','video'])
def test_media_invalid(tmp_path,monkeypatch,problem):
    from althea_ingestion import audio
    mock_media(monkeypatch,silent=problem=='silent')
    p=tmp_path/('a.exe' if problem=='wrongext' else 'a.wav'); p.write_bytes(b'bad')
    if problem=='missing': monkeypatch.setattr(audio.shutil,'which',lambda x:None)
    if problem=='corrupt': monkeypatch.setattr(audio,'run_tool',lambda *a,**k:SimpleNamespace(stdout=b'not-json'))
    if problem=='oversize':
        with p.open('wb') as f: f.truncate(20*1024*1024+1)
    if problem in ('format','nostream','video'):
        monkeypatch.setattr(audio,'run_tool',lambda *a,**k:SimpleNamespace(stdout=json.dumps(dict(format={'duration':'1','format_name':'mp4' if problem=='format' else 'wav'},streams=[] if problem=='nostream' else [dict(codec_type='audio'),dict(codec_type='video')])).encode()))
    with pytest.raises(IngestionError): prepare_audio(p,dict(data_dir=str(tmp_path/'data')))


def test_provider_failure_propagates(tmp_path,monkeypatch):
    from althea_ingestion import service
    p=tmp_path/'a.wav';p.write_bytes(b'test')
    monkeypatch.setattr(service,'prepare_audio',lambda *a:dict(path=str(p),duration_s=1.0,content_sha256='0'*64,audio_relpath=None,original_filename=p.name))
    class Fail:
        def transcribe(self,*a,**k): raise IngestionError('PROVIDER_UNAVAILABLE','Failed')
    with pytest.raises(IngestionError): IngestionService(dict(mode='live'),transcriber=Fail()).ingest(dict(kind='audio',local_path=str(p),sample_id=None,title='T'),budget=AttemptBudget())


def test_repository_roundtrip_and_counters(snapshot,tmp_path):
    r=Repository(str(tmp_path/'jobs.sqlite'));r.initialize();r.initialize()
    r.save_snapshot(snapshot)
    assert r.load_snapshot(snapshot['job_id'])==snapshot
    assert r.list_jobs()[0]['title']==snapshot['title']
    r.put_cached('fixture:transcript',snapshot['transcript'])
    cached=r.get_cached('fixture:transcript');cached['segments'][0]['text']='modified'
    assert r.get_cached('fixture:transcript')==snapshot['transcript']
    assert r.get_cached('missing') is None
    with pytest.raises(IngestionError): r.put_cached('bad',{'error':'failure'})
    r.consume_attempt(snapshot['job_id'],'retrieval',20)
    r.save_snapshot(snapshot)
    assert r.attempts_used(snapshot['job_id'])==1
    event=dict(stage='storage',code='TEST',message='token=secret',retryable=False,related_ids=[])
    r.append_event(snapshot['job_id'],event)
    with r._transaction() as db:
        assert 'secret' not in db.execute('SELECT event_json FROM events').fetchone()[0]


def test_atomic_competing_attempts_and_pairs(snapshot,tmp_path):
    r=Repository(str(tmp_path/'jobs.sqlite'));r.initialize();r.save_snapshot(snapshot)
    job=snapshot['job_id']
    def consume(_):
        try: r.consume_attempt(job,'retrieval',20);return True
        except IngestionError as e: assert e.code=='BUDGET_LIMIT';return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(consume,range(50)))==20
    assert r.attempts_used(job)==20
    def reserve(i): return r.reserve_verification_pairs(job,[f'analysis:{i}'],4)
    with ThreadPoolExecutor(max_workers=8) as pool:
        allowed=[x for group in pool.map(reserve,range(20)) for x in group]
    assert len(allowed)==4
    assert r.reserve_verification_pairs(job,allowed,4)==allowed
    assert r.reserve_verification_pairs(job,['another_analysis:0'],4)==[]


def test_review_invalidation_and_versions(snapshot,tmp_path):
    r=Repository(str(tmp_path/'jobs.sqlite'));r.initialize();r.save_snapshot(snapshot)
    job=snapshot['job_id'];r.consume_attempt(job,'retrieval',20)
    r.reserve_verification_pairs(job,['analysis:pair'],4)
    assert r.review_transcript(job,copy.deepcopy(snapshot['transcript']))==snapshot
    reviewed=copy.deepcopy(snapshot['transcript']);reviewed['speakers'][0]['display_name']='Alexandra'
    result=r.review_transcript(job,reviewed)
    assert result['status']=='ready' and result['analysis'] is result['verification'] is None
    assert result['transcript']['origin']=='human_reviewed'
    assert r.attempts_used(job)==1
    with r._transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0]==4
        assert db.execute('SELECT COUNT(*) FROM verified_pairs').fetchone()[0]==1
    malicious=copy.deepcopy(result['transcript']);malicious['source']['content_sha256']='1'*64
    with pytest.raises(IngestionError):r.review_transcript(job,malicious)
    assert r.load_snapshot(job)==result


def test_immutable_collision(snapshot,tmp_path):
    r=Repository(str(tmp_path/'j.sqlite'));r.initialize();r.save_snapshot(snapshot)
    with r._transaction() as db:
        db.execute('UPDATE artifacts SET payload_json=? WHERE artifact_id=?', ('{}','transcript:'+digest(snapshot['transcript'])))
    with pytest.raises(IngestionError,match='collision'):r.save_snapshot(snapshot)


def test_storage_errors(tmp_path):
    with pytest.raises(IngestionError) as e:Repository(str(tmp_path/'missing'/'j.sqlite')).initialize()
    assert e.value.code=='STORAGE_ERROR'


def test_no_failure_cache(snapshot,tmp_path):
    from althea_ingestion.common import verification_identity
    r=Repository(str(tmp_path/'cache.sqlite'));r.initialize()
    v=copy.deepcopy(snapshot['verification']);v.update(results=[],evidence=[],unverified=[dict(pair_id='pair_0001',reason='provider_error')])
    v['verification_id']=verification_identity(v)
    with pytest.raises(IngestionError):r.put_cached('failed',v)
    s=copy.deepcopy(snapshot);s['status']='running'
    with pytest.raises(IngestionError):r.put_cached('running',s)


@pytest.mark.parametrize('status,expected',[(429,3),(503,3),(400,1),(401,1),(404,1)])
def test_retries_and_budget(monkeypatch,status,expected):
    from althea_ingestion import runtime
    monkeypatch.setattr(runtime.time,'sleep',lambda _:None)
    class Failure(Exception):code=status
    class Models:
        def generate_content(self,**kwargs):raise Failure()
    adapter=VertexAdapter({});adapter._client=SimpleNamespace(models=Models())
    budget=AttemptBudget()
    with pytest.raises(IngestionError):adapter.request('transcription',budget,model='m')
    assert budget.used==expected


def test_sdk_configuration():
    from google.genai import types
    assert types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)).retry_options.attempts==1
    # Actual transcription feature availability is separately reported in HANDOFF.


@pytest.mark.parametrize('missing',[False,True])
def test_live_adapter_native_words(tmp_path,missing):
    path=tmp_path/'speech.wav';path.write_bytes(b'mock-audio')
    word=SimpleNamespace(word='No 12 million.',start_offset='0s',end_offset='1s',speaker_label=None)
    response=SimpleNamespace(parts=[SimpleNamespace(audio_transcription=SimpleNamespace(words=[] if missing else [word],speaker_label='opaque'))],usage_metadata=None)
    class Models:
        def generate_content(self,**kwargs):
            config=kwargs['config']
            assert config.audio_transcription_config.word_timestamp
            assert config.audio_transcription_config.diarization
            assert str(config.audio_transcription_config.mode.value)=='VERBATIM'
            assert config.response_schema is None
            return response
    adapter=GoogleCloudTranscriber({});adapter._client=SimpleNamespace(models=Models())
    budget=AttemptBudget()
    if missing:
        with pytest.raises(IngestionError):adapter.transcribe(str(path),language='en',expected_speakers=2,budget=budget)
    else:
        result=adapter.transcribe(str(path),language='en',expected_speakers=2,budget=budget)
        assert normalize_words(result['words'])[1][0]['text']=='No 12 million.'
        assert result['usage'][0]['input_tokens'] is None
    assert budget.used==1


def test_service_with_injected_provider(tmp_path,monkeypatch):
    from althea_ingestion import service
    p=tmp_path/'speech.wav';p.write_bytes(b'mock')
    monkeypatch.setattr(service,'prepare_audio',lambda *a:dict(path=str(p),duration_s=2.0,content_sha256='0'*64,audio_relpath='media/original.wav',original_filename=p.name))
    class Provider:
        def transcribe(self,path,**kwargs):
            kwargs['budget'].consume('transcription')
            return dict(words=[dict(word='नहीं 10.',speaker=0,start_s=0,end_s=1)],usage=[])
    budget=AttemptBudget(1)
    t=IngestionService(dict(mode='live'),transcriber=Provider()).ingest(dict(kind='audio',local_path=str(p),sample_id=None,title='Test'),budget=budget)
    assert t['issues'][0]['code']=='ONE_SPEAKER' and t['origin']=='api'
    assert budget.used==1 and t['segments'][0]['text']=='नहीं 10.'


@pytest.mark.parametrize('failure',[OSError('failed'),subprocess.TimeoutExpired('ffprobe',30),subprocess.CalledProcessError(1,'ffprobe')])
def test_subprocess_failures(monkeypatch,failure):
    from althea_ingestion.audio import run_tool
    def fail(*a,**k):raise failure
    monkeypatch.setattr(subprocess,'run',fail)
    with pytest.raises(IngestionError):run_tool(['ffprobe','path with spaces.wav'])


@pytest.mark.live
def test_live_transcription():
    import os
    path=os.getenv('ALTHEA_LIVE_AUDIO')
    if not os.getenv('GOOGLE_CLOUD_PROJECT') or not path:
        pytest.skip('Set GOOGLE_CLOUD_PROJECT, ADC, FFmpeg and ALTHEA_LIVE_AUDIO to an authorized real clip.')
    result=IngestionService(dict(mode='live',project_id=os.environ['GOOGLE_CLOUD_PROJECT'],data_dir=str(Path('data').resolve()))).ingest(dict(kind='audio',local_path=path,sample_id=None,title='Authorized live smoke'),budget=AttemptBudget())
    assert result['origin']=='api' and result['segments']
