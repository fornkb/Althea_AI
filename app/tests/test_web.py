import io
import json
import threading
import time
import pytest
from althea_app.backend import SampleBackend
from althea_app.web import create_app

SECRET='OFFLINE-TEST-KEY-NOT-A-CREDENTIAL'


@pytest.fixture
def web(tmp_path):
    app=create_app(root=tmp_path,settings={'data_dir':str(tmp_path/'data')})
    app.config['TESTING']=True
    yield app,app.test_client(),tmp_path
    app.extensions['althea_executor'].shutdown(wait=True)


def csrf(client):
    return {'X-CSRF-Token':client.get('/api/bootstrap').json['csrf']}


def wait_for(client,operation_id):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        result=client.get('/api/operations/'+operation_id).json
        if result['status']!='running':return result
        time.sleep(.02)
    raise AssertionError('Background operation did not finish')


def sample(client):
    response=client.post('/api/jobs',data={'kind':'sample','verify':'true','title':'Sample <conversation>'},headers=csrf(client))
    assert response.status_code==202,response.json
    operation=wait_for(client,response.json['operation_id'])
    assert operation['status']=='finished',operation
    return operation['job_id']


def test_real_routes_support_direct_links_and_reload(web):
    app,client,_=web
    for path in ('/','/history','/settings','/jobs/gemini/a-saved-job'):
        response=client.get(path)
        assert response.status_code==200
        assert b'data-nav="home"' in response.data and b'/static/app.js' in response.data
        assert b'streamlit' not in response.data.lower()
    assert client.get('/api/health').json==dict(app='althea',interface='web',status='ready')
    for path in ('/static/app.js','/static/app.css','/static/recorder.js','/static/mark.svg'):
        assert client.get(path).status_code==200


def test_local_app_rejects_cross_origin_mutation_and_bad_hosts(web):
    _,client,_=web
    assert client.post('/api/settings',json={'api_key':SECRET}).status_code==403
    headers={**csrf(client),'Origin':'https://unrelated.example'}
    assert client.post('/api/settings',json={'api_key':SECRET},headers=headers).status_code==403
    assert client.get('/api/bootstrap',headers={'Host':'unrelated.example'}).status_code==400


def test_settings_persist_without_exposing_key_or_calling_google(web,monkeypatch):
    from google import genai
    monkeypatch.setattr(genai,'Client',lambda **k:(_ for _ in ()).throw(AssertionError('Saving settings must not call Google')))
    app,client,root=web
    (root/'.env').write_text('# preserve this comment\nALTHEA_DATA_DIR=data\nGEMINI_API_KEY=old\nGEMINI_API_KEY=duplicate\n',encoding='utf-8')
    response=client.post('/api/settings',json={'api_key':SECRET,'provider':'gemini','persist':True},headers=csrf(client))
    assert response.status_code==200 and response.json['settings']['key_configured']
    assert SECRET.encode() not in response.data
    contents=(root/'.env').read_text()
    assert f'GEMINI_API_KEY={SECRET}' in contents and contents.count('GEMINI_API_KEY=')==1
    assert '# preserve this comment' in contents
    assert 'ALTHEA_DATA_DIR=data' in contents
    assert not list(root.glob('.env.*.tmp'))
    for path in ('/api/bootstrap','/api/settings','/api/jobs'):
        assert SECRET.encode() not in client.get(path).data
    response=client.post('/api/settings',json={'clear_key':True,'persist':True},headers=csrf(client))
    assert response.status_code==200 and not response.json['settings']['key_configured']
    assert SECRET not in (root/'.env').read_text()


def test_sample_history_exports_versions_and_review(web):
    _,client,_=web
    job_id=sample(client)
    base='/api/jobs/sample/'+job_id
    result=client.get(base).json
    assert result['snapshot']['status']=='complete' and len(result['snapshot']['analysis']['claims'])==7
    assert result['usage']['attempts_used']==0
    assert any(job['job_id']==job_id for job in client.get('/api/jobs').json['jobs'])
    assert client.get(base+'/export/json').json['job_id']==job_id
    csv=client.get(base+'/export/csv')
    assert csv.status_code==200 and b'claim_id' in csv.data
    version=result['versions'][0]
    assert 'payload' not in version
    assert client.get(base+'/versions/'+version['artifact_id']).status_code==200
    assert client.get(base+'/audio').status_code==404
    assert client.get(base+'/attributions/non-native').status_code==404
    transcript=result['snapshot']['transcript']
    original=transcript['transcript_id']
    transcript['speakers'][0]['display_name']='Reviewed speaker'
    response=client.post(base+'/review',json={'transcript_id':original,'transcript':transcript},headers=csrf(client))
    assert response.status_code==200
    assert response.json['snapshot']['analysis'] is None
    assert response.json['snapshot']['transcript']['speakers'][0]['display_name']=='Reviewed speaker'
    assert client.post(base+'/review',json={'transcript_id':original,'transcript':transcript},headers=csrf(client)).status_code==409


def test_upload_uses_generated_paths_and_serves_only_stored_audio(live_factory,tmp_path):
    b,_,_=live_factory()
    app=create_app(root=tmp_path,settings=b.settings,backend_factories={'vertex':lambda _:b})
    client=app.test_client()
    try:
        response=client.post('/api/jobs',data={'provider':'vertex','title':'Uploaded debate','file':(io.BytesIO(b'MOCK AUDIO'),'../../speech.wav')},headers=csrf(client))
        assert response.status_code==202,response.json
        operation=wait_for(client,response.json['operation_id'])
        result=client.get('/api/jobs/vertex/'+operation['job_id']).json['snapshot']
        assert result['status']=='complete',result['issues']
        uploads=list((tmp_path/'data'/'uploads').glob('*.wav'))
        assert len(uploads)==1 and uploads[0].name!='speech.wav'
        assert client.get('/api/jobs/vertex/'+operation['job_id']+'/audio').data==b'MOCK AUDIO'
        response=client.post('/api/jobs',data={'provider':'vertex','file':(io.BytesIO(b'alert(1)'),'audio.html')},headers=csrf(client))
        assert response.status_code==400
    finally:app.extensions['althea_executor'].shutdown(wait=True)


def test_background_analysis_keeps_navigation_responsive_and_blocks_duplicates(tmp_path):
    started,release=threading.Event(),threading.Event()
    class SlowSample(SampleBackend):
        def run(self,*args,**kwargs):
            started.set()
            assert release.wait(5)
            return super().run(*args,**kwargs)
    app=create_app(root=tmp_path,settings={'data_dir':str(tmp_path/'data')},backend_factories={'sample':SlowSample})
    client=app.test_client()
    try:
        headers=csrf(client)
        response=client.post('/api/jobs',data={'kind':'sample'},headers=headers)
        assert response.status_code==202 and started.wait(2)
        for page in ('/','/history','/settings','/api/jobs'):
            assert client.get(page).status_code==200
        assert client.get('/api/bootstrap').json['active']['status']=='running'
        assert client.post('/api/jobs',data={'kind':'sample'},headers=headers).status_code==409
        assert client.post('/api/settings',json={'provider':'vertex'},headers=headers).status_code==409
        release.set()
        assert wait_for(client,response.json['operation_id'])['status']=='finished'
    finally:
        release.set()
        app.extensions['althea_executor'].shutdown(wait=True)


def test_evidence_actions_validate_pairs_before_provider_work(web):
    _,client,_=web
    job_id=sample(client)
    base='/api/jobs/sample/'+job_id
    bad=client.post(base+'/actions',json={'action':'verify','pair_ids':['made_up']},headers=csrf(client))
    assert bad.status_code==400
    response=client.post(base+'/actions',json={'action':'refresh','pair_ids':['pair_0001']},headers=csrf(client))
    assert response.status_code==202,response.json
    assert wait_for(client,response.json['operation_id'])['status']=='finished'
    assert client.get(base).json['usage']['attempts_used']==0
