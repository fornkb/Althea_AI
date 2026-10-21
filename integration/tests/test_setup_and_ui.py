import copy
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from althea_app import load_settings,SampleBackend,LiveBackend
from althea_app.settings import validate_settings
from althea_app.preflight import preflight
from althea_app.errors import AppError
from althea_app.cache_keys import analysis_key
from .conftest import ROOT,Providers


@pytest.mark.parametrize('key,value',[('max_claims',0),('max_claims',31),('max_verify_pairs',5),('max_provider_attempts',21),('max_provider_attempts',True),('max_audio_seconds',float('nan')),('max_audio_seconds',301),('request_timeout_s',91),('text_model','bad model'),('location','a\nsecret'),('project_id','bad project')])
def test_settings_reject_unsafe_or_excessive_limits(key,value,tmp_path):
    with pytest.raises(AppError):validate_settings({key:value},root=tmp_path)


def test_dotenv_precedence_and_no_shell_expansion(tmp_path):
    (tmp_path/'.env').write_text('GOOGLE_CLOUD_PROJECT=from-file\nALTHEA_TEXT_MODEL="quoted-model"\nALTHEA_DATA_DIR=runtime-data\n',encoding='utf-8')
    settings=load_settings(root=tmp_path,environ={'GOOGLE_CLOUD_PROJECT':'from-env'})
    assert settings['project_id']=='from-env' and settings['text_model']=='quoted-model'
    assert settings['data_dir']==str(tmp_path/'runtime-data')
    assert settings['mode']=='fixture'
    assert not (tmp_path/'runtime-data').exists()  # settings reading never initializes storage


def test_preflight_no_external_requests_or_client(tmp_path,monkeypatch):
    from google import genai
    monkeypatch.setattr(genai,'Client',lambda **kwargs:(_ for _ in ()).throw(AssertionError('No client during preflight')))
    report=preflight({'data_dir':str(tmp_path),'project_id':None})
    assert report['external_requests']==0
    assert not next(c for c in report['checks'] if c['name']=='Google Cloud project')['ok']
    assert 'Not checked' in report['model_access']
    assert not (tmp_path/'fixture.sqlite').exists()


def test_uploaded_original_filename_survives_generated_path_and_cache(live_factory):
    from types import SimpleNamespace
    from althea_evidence_ui.dashboard import save_upload
    b,p,source=live_factory()
    data=Path(source['local_path']).read_bytes()
    upload=SimpleNamespace(name='Original debate.wav',getvalue=lambda:data)
    request=save_upload(upload,b.settings['data_dir'])
    s=b.run({**request,'title':'Upload'},verify=False)
    assert s['status']=='complete' and s['transcript']['source']['original_filename']=='Original debate.wav'
    assert Path(request['local_path']).name!='Original debate.wav'
    second=save_upload(SimpleNamespace(name='Renamed recording.wav',getvalue=lambda:data),b.settings['data_dir'])
    s=b.run({**second,'title':'Cached upload'},verify=False)
    assert s['transcript']['source']['original_filename']=='Renamed recording.wav'
    assert p.calls==['transcription','extraction']


def test_installed_cli_complete_and_empty_selection(tmp_path):
    output=tmp_path/'snapshot.json'
    env={**os.environ,'PYTHONPATH':os.pathsep.join(str(p) for p in sys.path)}
    command=[sys.executable,'-m','althea_app','--mode','fixture','--sample','riverton_demo','--verify','--data-dir',str(tmp_path/'data'),'--output',str(output)]
    run=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
    assert run.returncode==0,run.stderr
    s=json.loads(output.read_text(encoding='utf-8'))
    assert s['status']=='complete' and len(s['analysis']['claims'])==7
    assert '"attempts_used": 0' in run.stdout
    run=subprocess.run([sys.executable,'-m','althea_app','--help'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
    assert run.returncode==0 and '--preflight' in run.stdout and '--live-smoke' in run.stdout


@pytest.mark.parametrize('case',['missing_tools','overlong','oversized','path_escape','invalid_url'])
def test_failed_input_and_source_integrity(live_factory,reference,tmp_path,monkeypatch,case):
    from althea_ingestion import audio
    p=Providers(reference);b,p,source=live_factory(p)
    if case=='missing_tools':monkeypatch.setattr(audio.shutil,'which',lambda _:None)
    if case=='overlong':
        monkeypatch.setattr(audio,'run_tool',lambda *a,**k:type('R',(),{'stdout':json.dumps(dict(format={'duration':'300.01','format_name':'wav'},streams=[dict(codec_type='audio',codec_name='pcm_s16le',channels=2)])).encode()})())
    if case=='oversized':
        with Path(source['local_path']).open('wb') as f:f.truncate(20*1024*1024+1)
    if case=='path_escape':
        t=copy.deepcopy(reference['transcript']);t['source']['audio_relpath']='../outside.wav'
        path=tmp_path/'import.json';path.write_text(json.dumps(t),encoding='utf-8')
        source.update(kind='transcript',local_path=str(path))
    if case=='invalid_url':
        retrieve=p.retrieve
        def unsafe(**kwargs):
            e,u,a=retrieve(**kwargs);e[0]['url']='javascript:alert(1)';return e,u,a
        monkeypatch.setattr(p,'retrieve',unsafe)
    s=b.run(source,verify=True)
    if case=='invalid_url':
        assert s['status']=='partial' and 'adjudication' not in p.calls
    else:
        assert s['status']=='failed' and s['transcript'] is None and p.calls==[]
        assert b.job_usage(s['job_id'])['attempts_used']==0


def button(app,label):return next(b for b in app.button if b.label==label)
def widget(app,kind,label):return next(w for w in getattr(app,kind) if w.label==label)


def test_integrated_ui_lazy_live_persistent_history_and_review(tmp_path,monkeypatch):
    from google import genai
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('ALTHEA_DATA_DIR',str(tmp_path/'ui-data'))
    monkeypatch.delenv('GOOGLE_CLOUD_PROJECT',raising=False)
    clients=[]
    def no_client(**kwargs):clients.append(kwargs);raise AssertionError('No cloud setup in sample UI')
    monkeypatch.setattr(genai,'Client',no_client)
    app=AppTest.from_file(str(ROOT/'integration/app.py'),default_timeout=25).run()
    assert not app.exception and clients==[]
    widget(app,'radio','Input method').set_value('Try sample').run()
    widget(app,'checkbox','Check up to four disagreements against web evidence').check()
    button(app,'Analyze').click().run()
    assert not app.exception
    b=app.session_state['althea_backend_Sample demo']
    s=app.session_state['althea_snapshot_Sample demo']
    assert s['status']=='complete' and len(b.list_jobs())==1
    assert b.job_usage(s['job_id'])['attempts_used']==0
    assert any('saved jobs stored locally' in value.value for value in app.info)
    assert any(w.label=='Saved jobs' for w in app.selectbox)
    calls=[];analyze=b.analysis.analyze
    def spy(*a,**k):calls.append(True);return analyze(*a,**k)
    monkeypatch.setattr(b.analysis,'analyze',spy)
    widget(app,'selectbox','Speaker filter').select('speaker_01').run()
    app.run()
    assert calls==[] and len(b.list_jobs())==1 and clients==[]
    widget(app,'text_input','Name · speaker_01').set_value('Human-reviewed name')
    button(app,'Save review').click().run()
    assert not app.exception
    assert app.session_state['althea_snapshot_Sample demo']['analysis'] is None
    assert any('No factual claims' in v.value for v in app.info)
    assert len(app.get('download_button'))>=2
    restarted=AppTest.from_file(str(ROOT/'integration/app.py'),default_timeout=25).run()
    widget(restarted,'radio','Input method').set_value('Try sample').run()
    widget(restarted,'selectbox','Saved jobs').select(s['job_id']).run()
    button(restarted,'Load saved job').click().run()
    assert restarted.session_state['althea_snapshot_Sample demo']['transcript']['speakers'][0]['display_name']=='Human-reviewed name'
    widget(restarted,'radio','Navigation').set_value('Settings').run()
    widget(restarted,'selectbox','Analysis provider').select('Live analysis').run()
    assert not restarted.exception and clients==[]
    assert restarted.session_state['althea_backend_Live analysis'].mode=='live'
