import copy
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from althea_app.backend import LiveBackend,SampleBackend
from althea_app.budget import JobBudget
from althea_app.cache_keys import analysis_key,transcription_key,verification_key
from althea_app.errors import AppError
from althea_app.validation import validate_snapshot,eligible_pairs
from althea_ingestion.common import digest,verification_identity
from althea_evidence_ui import claims_csv,snapshot_json
from althea_evidence_ui.grounding import NATIVE_ATTRIBUTIONS
from .conftest import ROOT,Providers

SOURCE=dict(kind='sample',sample_id='riverton_demo',local_path=None,title='Integrated fictional sample')


def test_context_needed_candidates_can_be_investigated_without_forcing_verdict(live_factory,reference):
    class ContextProvider(Providers):
        def generate_json(self,**kwargs):
            result,usage=super().generate_json(**kwargs)
            result['claims']=result['claims'][:2]
            for c in result['claims']:
                c['period']=None;c['missing_context']=['period'];c['checkability']='needs_context'
            result['claims'][1]['metric']='transport budget or planned allocation'
            return result,usage
    provider=ContextProvider(reference,no_sources=True)
    b,p,source=live_factory(providers=provider)
    result=b.run(source,verify=True)
    assert result['status']=='complete',result['issues']
    assert result['analysis']['pairs'][0]['relation']=='insufficient_context'
    assert result['analysis']['pairs'][0]['numeric_difference'] is None
    assert provider.calls==['transcription','extraction','retrieval']
    assert [v['status'] for v in result['verification']['results'][0]['verdicts']]==['needs_context','needs_context']
    assert b.job_usage(result['job_id'])['attempts_used']==3
    # Existing v1/v1.1 artifacts which didn't include uncertain comparisons
    # remain readable. New checks can add those optional comparisons explicitly.
    legacy=copy.deepcopy(result)
    legacy['verification'].update(results=[],unverified=[],evidence=[],usage=[])
    legacy['verification']['verification_id']=verification_identity(legacy['verification'])
    assert validate_snapshot(legacy)['verification']['results']==[]


def test_contract_hashes_and_real_sample(tmp_path):
    expected=(ROOT/'reference/contract_v1_1.py').read_bytes()
    for path in ROOT.glob('team_*/src/*/_contract.py'):assert path.read_bytes()==expected
    b=SampleBackend({'data_dir':str(tmp_path)})
    s=b.run(SOURCE,verify=True)
    assert s['status']=='complete' and len(s['transcript']['segments'])==8
    assert len(s['analysis']['claims'])==7 and len(s['analysis']['pairs'])==3
    assert [p['relation'] for p in s['analysis']['pairs']]==['numeric_discrepancy','different_scope','compatible']
    assert s['analysis']['pairs'][0]['method']=='deterministic'  # Analysis actually ran
    assert [v['status'] for v in s['verification']['results'][0]['verdicts']]==['refuted','refuted']
    assert b.job_usage(s['job_id'])['attempts_used']==0
    assert json.loads(snapshot_json(s))==s and len(claims_csv(s).decode('utf-8-sig').splitlines())==8
    second=b.run({**SOURCE,'title':'Changed display title'},verify=True)
    assert second['transcript']['transcript_id']==s['transcript']['transcript_id']
    assert second['analysis']['analysis_id']==s['analysis']['analysis_id']
    assert b.job_usage(second['job_id'])['cache_hits']==['analysis','evidence pair_0001']
    resumed=SampleBackend({'data_dir':str(tmp_path)})
    assert len(resumed.list_jobs())==2 and resumed.load(s['job_id'])==s


def test_fake_live_order_cache_and_history(live_factory):
    b,p,source=live_factory()
    s=b.run(source,verify=True)
    assert s['status']=='complete' and not s['issues']
    assert p.calls==['transcription','extraction','retrieval','adjudication']
    assert b.job_usage(s['job_id'])['attempts_used']==4
    second=b.run({**source,'title':'Same content; new job'},verify=True)
    assert p.calls==['transcription','extraction','retrieval','adjudication']
    assert b.job_usage(second['job_id'])['attempts_used']==0
    assert b.job_usage(second['job_id'])['new_attempts_this_action']==0
    assert b.job_usage(second['job_id'])['cache_hits']==['transcription','analysis','evidence pair_0001']
    assert second['transcript']['source']['title']=='Same content; new job'
    assert second['verification']['evidence'][0]['retrieved_at']==s['verification']['evidence'][0]['retrieved_at']
    before=copy.deepcopy(second['verification']['usage'])
    repeat=b.verify_pairs(second['job_id'],['pair_0001'])
    assert repeat['verification']['usage']==before
    events=b.repository.events_for_job(s['job_id'])
    assert sum(e['event']['code']=='ATTEMPT_RESERVED' for e in events)==4
    assert sum(e['event']['code']=='ATTEMPT_COMPLETED' for e in events)==4
    renamed=Path(source['local_path']).with_suffix('.mp3')
    renamed.write_bytes(Path(source['local_path']).read_bytes())
    mismatch=b.run({**source,'local_path':str(renamed)},verify=False)
    assert mismatch['status']=='failed' and mismatch['issues'][0]['code']=='INVALID_INPUT'
    assert len(p.calls)==4  # cache lookup cannot bypass format/extension agreement


def test_model_prompt_and_mode_cache_keys(live_factory,tmp_path):
    b,p,source=live_factory();s=b.run(source,verify=True)
    changed,_,_=live_factory(p,text_model='a-different-model')
    new=changed.run(source,verify=True)
    assert new['status']=='complete' and changed.job_usage(new['job_id'])['attempts_used']==3
    assert p.calls.count('transcription')==1
    changed_prompt,_,_=live_factory(p,extraction_version='new-prompt-version')
    new=changed_prompt.run(source,verify=False)
    assert changed_prompt.job_usage(new['job_id'])['attempts_used']==1
    fixture={**b.settings,'mode':'fixture'}
    assert analysis_key(b.settings,'tr')!=analysis_key(fixture,'tr')
    assert transcription_key(b.settings,'bytes')!=transcription_key({**b.settings,'transcribe_model':'different'},'bytes')
    assert verification_key(b.settings,'an','pair')!=verification_key({**b.settings,'retrieval_version':'v2'},'an','pair')
    titled={**b.settings,'title':'irrelevant','max_provider_attempts':1,'data_dir':'elsewhere'}
    assert analysis_key(b.settings,'tr')==analysis_key(titled,'tr')


@pytest.mark.parametrize('edit',['name','number','time'])
def test_review_invalidates_then_explicit_reanalysis(live_factory,edit):
    b,p,source=live_factory();s=b.run(source,verify=True)
    job=s['job_id'];old_id=s['transcript']['transcript_id'];old_analysis=s['analysis']['analysis_id']
    t=copy.deepcopy(s['transcript'])
    if edit=='name':t['speakers'][0]['display_name']='Reviewed speaker'
    if edit=='number':t['segments'][0]['text']=t['segments'][0]['text'].replace('10 million','9 million')
    if edit=='time':t['segments'][0]['end_s']=7.9
    reviewed=b.save_review(job,t)
    assert reviewed['status']=='ready' and reviewed['analysis'] is reviewed['verification'] is None
    assert reviewed['transcript']['transcript_id']!=old_id and reviewed['transcript']['origin']=='human_reviewed'
    assert b.job_usage(job)['attempts_used']==4 and p.calls.count('transcription')==1
    history=b.artifact_history(job)
    assert any(v['kind']=='analysis' and v['payload']['analysis_id']==old_analysis for v in history)
    new=b.reanalyze(job,verify=True)
    assert new['status']=='complete' and new['analysis']['transcript_id']==new['transcript']['transcript_id']
    assert b.job_usage(job)['attempts_used']==7 and b.job_usage(job)['verification_pairs_used']==2
    assert p.calls.count('transcription')==1


def test_sample_custom_review_never_uses_stale_claims(tmp_path):
    b=SampleBackend({'data_dir':str(tmp_path)});s=b.run(SOURCE,verify=True)
    t=copy.deepcopy(s['transcript']);t['speakers'][0]['display_name']='Edited'
    b.save_review(s['job_id'],t)
    after=b.reanalyze(s['job_id'],verify=True)
    assert after['status']=='ready' and after['analysis'] is None
    assert after['issues'][0]['code']=='CUSTOM_EDIT_REQUIRES_LIVE'
    assert b.job_usage(s['job_id'])['attempts_used']==0


def test_incremental_merge_refresh_and_pair_budget(live_factory,reference):
    p=Providers(reference,many=True);p.native=True
    b,p,source=live_factory(p)
    s=b.run(source,verify=False)
    pairs=list(eligible_pairs(s['analysis']))
    assert len(pairs)==5
    first=b.verify_pairs(s['job_id'],pairs[:2])
    assert len(first['verification']['results'])==2 and len(first['verification']['grounding_attributions'])==2
    second=b.verify_pairs(s['job_id'],[pairs[2]])
    assert len(second['verification']['results'])==3
    p.fail_pair=pairs[1]
    refreshed=b.refresh_verification(s['job_id'],[pairs[1]])
    v=refreshed['verification']
    assert refreshed['status']=='partial'
    assert {r['pair_id'] for r in v['results']}==set(pairs[:3])
    assert {r['pair_id'] for r in v['grounding_attributions']}==set(pairs[:3])
    assert not any(u['pair_id']==pairs[1] for u in v['unverified'])
    assert any(i['code']=='SAVED_EVIDENCE_RETAINED' for i in v['issues'])
    assert v['evidence']==second['verification']['evidence']
    restarted,_,_=live_factory(p)
    assert restarted.load(s['job_id'])['verification']==v
    assert b.repository.get_cached(verification_key(b.settings,s['analysis']['analysis_id'],pairs[1])) is None
    assert any(h['kind']=='verification' and len(h['payload']['results'])==3 for h in b.artifact_history(s['job_id']))
    b.verify_pairs(s['job_id'],[pairs[3]])
    blocked=b.verify_pairs(s['job_id'],[pairs[4]])
    assert next(u['reason'] for u in blocked['verification']['unverified'] if u['pair_id']==pairs[4])=='budget_limit'
    assert b.job_usage(s['job_id'])['verification_pairs_used']==4
    t=copy.deepcopy(blocked['transcript']);t['speakers'][0]['display_name']='New analysis'
    b.save_review(s['job_id'],t);new=b.reanalyze(s['job_id'],verify=False)
    assert new['analysis']['analysis_id']!=s['analysis']['analysis_id']
    denied=b.verify_pairs(s['job_id'],[pairs[0]])
    assert denied['verification']['unverified'][0]['reason']=='budget_limit'


def test_twenty_attempts_persist_across_failures_and_restarts(live_factory,reference):
    p=Providers(reference);p.fail_retrieval=True
    b,p,source=live_factory(p);s=b.run(source,verify=False)
    for i in range(18):
        if i%3==0:b,_,_=live_factory(p)
        result=b.refresh_verification(s['job_id'],['pair_0001'])
        assert result['status']=='partial'
    assert b.job_usage(s['job_id'])['attempts_used']==20
    calls=len(p.calls)
    b,_,_=live_factory(p)
    exhausted=b.verify_pairs(s['job_id'],['pair_0001'])
    assert exhausted['verification']['unverified'][0]['reason']=='budget_limit'
    assert len(p.calls)==calls and b.job_usage(s['job_id'])['attempts_used']==20
    assert b.job_usage(s['job_id'])['verification_pairs_used']==1


@pytest.mark.parametrize('kind',['transcription','analysis','schema','retrieval'])
def test_failure_preserves_right_upstream(live_factory,reference,kind):
    p=Providers(reference)
    p.fail_transcription=kind=='transcription';p.fail_analysis=kind=='analysis'
    p.invalid=kind=='schema';p.fail_retrieval=kind=='retrieval'
    b,p,source=live_factory(p);s=b.run(source,verify=True)
    if kind=='retrieval':
        assert s['status']=='partial' and s['analysis'] is not None and s['verification']['issues']
    else:
        assert s['status']=='failed' and s['analysis'] is None and s['verification'] is None
        assert (s['transcript'] is None)==(kind=='transcription')
        assert 'retrieval' not in p.calls
    assert b.repository.get_cached(analysis_key(b.settings,s['transcript']['transcript_id'])) is None if kind in ('analysis','schema') else True
    assert json.loads(snapshot_json(s))['status']==s['status']


@pytest.mark.parametrize('case',['empty','no_conflicts','no_sources'])
def test_legitimate_empty_and_abstention(live_factory,reference,case):
    p=Providers(reference,empty=case=='empty',no_sources=case=='no_sources')
    if case=='no_conflicts':p.segments[1]['text']=p.segments[1]['text'].replace('12 million','10 million')
    b,p,source=live_factory(p);s=b.run(source,verify=True)
    assert s['status']=='complete'
    if case in ('empty','no_conflicts'):
        assert s['verification']['results']==s['verification']['unverified']==[]
        assert p.calls==['transcription','extraction']
    else:
        assert all(v['status']=='insufficient_evidence' for v in s['verification']['results'][0]['verdicts'])
        assert 'adjudication' not in p.calls


def test_recovery_is_read_only_to_providers_and_skips_active_jobs(tmp_path):
    b=SampleBackend({'data_dir':str(tmp_path)});s=b.run(SOURCE,verify=False)
    s['status']='running';b.repository.save_snapshot(s)
    with b._lock(s['job_id']):
        another=SampleBackend({'data_dir':str(tmp_path)})
        assert another.load(s['job_id'])['status']=='running'
        with pytest.raises(AppError,match='already running'):another.reanalyze(s['job_id'],verify=False)
    resumed=SampleBackend({'data_dir':str(tmp_path)})
    assert resumed.load(s['job_id'])['status']=='partial'
    assert resumed.load(s['job_id'])['issues'][0]['code']=='INTERRUPTED'
    assert resumed.job_usage(s['job_id'])['attempts_used']==0
    blank=copy.deepcopy(s);blank.update(job_id=str(uuid.uuid4()),transcript=None,analysis=None,verification=None,status='running',issues=[])
    b.repository.save_snapshot(blank)
    resumed=SampleBackend({'data_dir':str(tmp_path)})
    assert resumed.load(blank['job_id'])['status']=='failed'


def test_native_attribution_persists_but_arbitrary_html_is_not_trusted(live_factory,reference):
    p=Providers(reference);p.native=True
    b,p,source=live_factory(p);s=b.run(source,verify=True)
    attr=s['verification']['grounding_attributions'][0]
    NATIVE_ATTRIBUTIONS.clear()
    again,_,_=live_factory(p);loaded=again.load(s['job_id'])
    assert digest(attr) in NATIVE_ATTRIBUTIONS
    mutated=copy.deepcopy(loaded);mutated['verification']['grounding_attributions'][0]['search_entry_point_html']='<script>untrusted import</script>'
    mutated['verification']['verification_id']=verification_identity(mutated['verification'])
    again.repository.save_snapshot(mutated);NATIVE_ATTRIBUTIONS.clear()
    loaded=again.load(s['job_id'])
    assert digest(loaded['verification']['grounding_attributions'][0]) not in NATIVE_ATTRIBUTIONS


def test_corrupt_saved_reference_rejected_without_work(tmp_path):
    b=SampleBackend({'data_dir':str(tmp_path)});s=b.run(SOURCE,verify=False)
    s['analysis']['transcript_id']='stale'
    with b.repository._transaction() as db:
        db.execute('UPDATE jobs SET snapshot_json=? WHERE job_id=?',(json.dumps(s),s['job_id']))
    with pytest.raises(Exception):b.load(s['job_id'])


@pytest.mark.parametrize('bad',['unknown','duplicate','ineligible'])
def test_invalid_pair_requests_do_not_consume(tmp_path,bad):
    b=SampleBackend({'data_dir':str(tmp_path)});s=b.run(SOURCE,verify=False)
    pairs={'unknown':['missing'],'duplicate':['pair_0001']*2,'ineligible':['pair_0002']}[bad]
    with pytest.raises(AppError):b.verify_pairs(s['job_id'],pairs)
    assert b.job_usage(s['job_id'])['verification_pairs_used']==0
