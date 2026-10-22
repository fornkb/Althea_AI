from pathlib import Path
import pytest

pytest.importorskip('streamlit')
from streamlit.testing.v1 import AppTest


def button(app,label):
    return next(b for b in app.button if b.label==label)


def widget(app,kind,label):
    return next(w for w in getattr(app,kind) if w.label==label)


def test_sample_review_reruns_exports():
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=20).run()
    assert not app.exception
    assert any('Choose Analyze' in x.value for x in app.info)
    button(app,'Analyze').click().run()
    assert not app.exception
    backend=app.session_state['althea_backend_Sample demo']
    assert backend.run_count==1 and backend.verify_count==0
    assert len(app.tabs)==4 and len(app.get('download_button'))==2
    widget(app,'selectbox','Speaker filter').select('speaker_01').run()
    app.run()
    assert backend.run_count==1 and backend.verify_count==0
    widget(app,'checkbox','Select pair_0001').check().run()
    button(app,'Check selected').click().run()
    assert not app.exception
    assert backend.verify_count==1
    assert any('Synthetic evidence' in w.value for w in app.warning)
    widget(app,'text_input','Name · speaker_01').set_value('Reviewed Alex')
    button(app,'Save review').click().run()
    assert not app.exception
    s=app.session_state['althea_snapshot_Sample demo']
    assert s['analysis'] is None and s['verification'] is None and s['status']=='ready'
    assert any('No factual claims' in x.value for x in app.info)
    assert len(app.get('download_button'))==2
    button(app,'Reanalyze').click().run()
    assert not app.exception
    assert any('requires live backend' in w.value for w in app.warning)
    assert backend.run_count==1 and backend.verify_count==1


def test_analyze_with_verification_and_job_load():
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=20).run()
    widget(app,'checkbox','Check up to four disagreements against web evidence').check()
    button(app,'Analyze').click().run()
    assert not app.exception
    backend=app.session_state['althea_backend_Sample demo']
    assert backend.verify_count==1
    job=backend.list_jobs()[0]['job_id']
    app.run()
    widget(app,'selectbox','Saved jobs').select(job).run()
    button(app,'Load saved job').click().run()
    assert not app.exception and backend.verify_count==1 and backend.run_count==1
