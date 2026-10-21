"""Input handoff tests: UI reruns must not start provider work."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from .conftest import ROOT


@pytest.mark.parametrize('method',['Upload audio','Record debate'])
def test_audio_input_explicitly_dispatches_to_real_pipeline(method,live_factory,monkeypatch):
    import streamlit as st
    import althea_app
    from streamlit.testing.v1 import AppTest
    backend,providers,source=live_factory()
    raw=Path(source['local_path']).read_bytes()
    clip=SimpleNamespace(name='recorded-debate.wav' if method=='Record debate' else 'uploaded-debate.wav',getvalue=lambda:raw)
    monkeypatch.setattr(althea_app,'LiveBackend',lambda settings:backend)
    monkeypatch.setattr(st,'audio_input',lambda *a,**k:clip)
    monkeypatch.setattr(st,'file_uploader',lambda label,**k:clip if label=='Upload debate audio' else None)
    app=AppTest.from_file(str(ROOT/'integration/app.py'),default_timeout=25)
    app.session_state['althea_provider']='Live analysis'
    app.run()
    next(w for w in app.radio if w.label=='Input method').set_value(method).run()
    app.run()
    assert not app.exception and providers.calls==[] and backend.list_jobs()==[]
    assert not any(w.label=='Gemini API key' for w in app.text_input)
    next(b for b in app.button if b.label=='Analyze').click().run()
    assert not app.exception
    result=app.session_state['althea_snapshot_Live analysis']
    assert result['status']=='complete' and result['transcript']['source']['original_filename']==clip.name
    assert providers.calls==['transcription','extraction']
    assert backend.job_usage(result['job_id'])['attempts_used']==2
    app.run()
    assert providers.calls==['transcription','extraction']


def test_recorder_and_uploader_are_distinct_visible_options(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('ALTHEA_DATA_DIR',str(tmp_path/'data'))
    app=AppTest.from_file(str(ROOT/'integration/app.py'),default_timeout=25).run()
    choice=next(w for w in app.radio if w.label=='Input method')
    assert choice.options==['Upload audio','Record debate','Try sample']
    assert len(app.get('file_uploader'))==2 and len(app.get('audio_input'))==0
    choice.set_value('Record debate').run()
    assert not app.exception and len(app.get('audio_input'))==1 and len(app.get('file_uploader'))==0
    assert next(b for b in app.button if b.label=='Analyze').disabled
    next(w for w in app.radio if w.label=='Navigation').set_value('Settings').run()
    assert len(app.get('audio_input'))==0 and len(app.get('file_uploader'))==0
