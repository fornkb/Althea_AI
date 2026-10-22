import copy
import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from althea_evidence_ui import VerificationService,validate_verification,FixtureBackend,claims_csv,snapshot_json,VerificationError
from althea_evidence_ui.common import verification_identity,analysis_identity,transcript_identity,validate_analysis
from althea_evidence_ui.grounding import parse_grounding,GoogleGroundedRetriever
from althea_evidence_ui.runtime import AttemptBudget,VertexAdapter
from althea_evidence_ui.dashboard import playback_path,save_upload


SOURCE=dict(kind='sample',local_path=None,sample_id='riverton_demo',title='Sample')


def verify(snapshot,pairs=None,**providers):
    return VerificationService(dict(mode='fixture'),**providers).verify(snapshot['transcript'],snapshot['analysis'],['pair_0001'] if pairs is None else pairs,budget=AttemptBudget(0))


def test_contract_and_both_wrong(snapshot):
    root=Path(__file__).parents[2]
    assert (root/'reference/contract_v1_1.py').read_bytes()==(root/'evidence_ui/src/althea_evidence_ui/_contract.py').read_bytes()
    v=verify(snapshot)
    assert [r['status'] for r in v['results'][0]['verdicts']]==['refuted','refuted']
    assert not v['issues'] and all(u['request_count']==0 for u in v['usage'])


@pytest.mark.parametrize('pairs',[['ghost'],['pair_0002'],['pair_0001','pair_0001']])
def test_invalid_selection(snapshot,pairs):
    with pytest.raises(VerificationError):verify(snapshot,pairs)


def test_no_selection_and_empty_analysis(snapshot):
    assert verify(snapshot,[])['unverified']==[dict(pair_id='pair_0001',reason='not_selected')]
    a=snapshot['analysis'];a['claims']=[];a['pairs']=[];a['analysis_id']=analysis_identity(a)
    v=verify(snapshot,[])
    assert not v['results'] and not v['unverified'] and not v['usage']


@pytest.mark.parametrize('problem',['url','fabricated_id','metadata','wrong_claim','wrong_pair','missing_claim','duplicate','identity','duplicate_url','bad_time','bad_date','stance','unknown_field'])
def test_semantic_rejections(snapshot,problem):
    v=snapshot['verification'];e=v['evidence'][0];r=v['results'][0]
    if problem=='url':e['url']='javascript:alert(1)'
    if problem=='fabricated_id':r['verdicts'][0]['evidence_refs'][0]['evidence_id']='invented'
    if problem=='metadata':e.update(content=None,content_origin='metadata_only')
    if problem=='wrong_claim':r['verdicts'][0]['claim_id']='cl_0003'
    if problem=='wrong_pair':e['pair_id']='pair_0002'
    if problem=='missing_claim':r['verdicts'].pop()
    if problem=='duplicate':v['unverified'].append(dict(pair_id='pair_0001',reason='not_selected'))
    if problem=='identity':v['analysis_id']='wrong'
    if problem=='duplicate_url':v['evidence'].append({**copy.deepcopy(e),'evidence_id':'ev_pair_0001_0002','url':e['url']+'#section'})
    if problem=='bad_time':e['retrieved_at']='yesterday'
    if problem=='bad_date':e['published_date']='2024-02-31'
    if problem=='stance':r['verdicts'][0]['evidence_refs'][0]['stance']='context'
    if problem=='unknown_field':r['verdicts'][0]['url']='https://fabricated.example/'
    v['verification_id']=verification_identity(v)
    with pytest.raises((VerificationError,ValueError)):validate_verification(v,snapshot['analysis'])


def test_grounding_mapping_and_url_dedup(snapshot):
    metadata=dict(grounding_chunks=[dict(web=dict(uri='https://EXAMPLE.com/report?year=2024&utm_source=x#top',title='Original')),dict(web=dict(uri='https://example.com/report?year=2024',title='Duplicate')),dict(web=dict(uri='https://example.com/other',title='Metadata')),dict(web=dict(uri='file:///secret',title='Unsafe'))],
                  grounding_supports=[dict(segment=dict(text='Historical scope.'),grounding_chunk_indices=[0,1,999,-1]),dict(segment=dict(text='Not in answer'),grounding_chunk_indices=[2])],web_search_queries=['neutral 2024 budget'])
    evidence,attr=parse_grounding(metadata,'Historical scope.',snapshot['analysis']['pairs'][0],snapshot['analysis']['claims'][:2])
    assert len(evidence)==2 and attr is None
    assert evidence[0]['content_origin']=='metadata_only'
    assert evidence[1]['content']=='Historical scope.' and evidence[1]['content_origin']=='grounded_summary'
    assert '?year=2024&utm_source=x#top' in evidence[1]['url']


class NoSources:
    mode='fixture'
    def retrieve(self,**kwargs):return [],[],None


class FailJudge:
    mode='fixture'
    def judge(self,**kwargs):raise AssertionError('Must abstain without sources')


def test_no_sources_abstains(snapshot):
    v=verify(snapshot,retriever=NoSources(),judge=FailJudge())
    assert [r['status'] for r in v['results'][0]['verdicts']]==['insufficient_evidence']*2


def test_metadata_only_abstains(snapshot):
    class Metadata:
        def retrieve(self,**kwargs):
            e=copy.deepcopy(snapshot['verification']['evidence'][0]);e.update(content=None,content_origin='metadata_only')
            return [e],[],None
    v=verify(snapshot,retriever=Metadata(),judge=FailJudge())
    assert v['results'][0]['verdicts'][0]['status']=='insufficient_evidence'


def test_supported_and_insufficient(snapshot):
    class Judge:
        def judge(self,**kwargs):
            r=copy.deepcopy(snapshot['verification']['results'][0])
            r['verdicts'][0]['status']='supported';r['verdicts'][0]['evidence_refs'][0]['stance']='supports'
            r['verdicts'][1].update(status='insufficient_evidence',evidence_refs=[])
            return r,[]
    v=verify(snapshot,judge=Judge())
    assert [r['status'] for r in v['results'][0]['verdicts']]==['supported','insufficient_evidence']


@pytest.mark.parametrize('budget_failure',[False,True])
def test_partial_pair_failure(snapshot,budget_failure):
    a=snapshot['analysis'];a['pairs'][1]['relation']='direct_conflict';a['analysis_id']=analysis_identity(a)
    class Retriever:
        def retrieve(self,**kwargs):
            if kwargs['pair']['pair_id']=='pair_0002':
                raise VerificationError('BUDGET_LIMIT' if budget_failure else 'PROVIDER_UNAVAILABLE','Failed')
            return copy.deepcopy(snapshot['verification']['evidence']),[],None
    class Judge:
        def judge(self,**kwargs):return snapshot['verification']['results'][0],[]
    v=verify(snapshot,['pair_0001','pair_0002'],retriever=Retriever(),judge=Judge())
    assert len(v['results'])==1 and len(v['evidence'])==1
    assert v['unverified']==[dict(pair_id='pair_0002',reason='budget_limit' if budget_failure else 'provider_error')]


@pytest.mark.parametrize('phase',['retrieval','adjudication'])
def test_quota_failure_identifies_step_without_exposing_provider_payload(snapshot,phase):
    class Retriever:
        mode='live'
        def retrieve(self,**kwargs):
            if phase=='retrieval':
                raise VerificationError('RATE_LIMIT','private-provider-payload',retryable=True)
            return copy.deepcopy(snapshot['verification']['evidence']),[],None
    class Judge:
        mode='live'
        def judge(self,**kwargs):
            raise VerificationError('RATE_LIMIT','private-provider-payload',retryable=True)
    v=VerificationService(dict(mode='live',provider='gemini',grounding_model='gemini-3.5-flash-lite'),
        retriever=Retriever(),judge=Judge()).verify(snapshot['transcript'],snapshot['analysis'],['pair_0001'],budget=AttemptBudget(0))
    message=v['issues'][0]['message']
    assert ('Source search' if phase=='retrieval' else 'Evidence assessment') in message
    assert 'HTTP 429' in message and 'private-provider-payload' not in message
    assert ('paid-tier' in message)==(phase=='retrieval')
    assert not v['results'] and not v['evidence']


def test_judge_injection_rejected(snapshot):
    class Judge:
        def judge(self,**kwargs):
            r=copy.deepcopy(snapshot['verification']['results'][0]);r['verdicts'][0]['evidence_refs'][0]['evidence_id']='INVENTED_IGNORE_SYSTEM'
            return r,[]
    v=verify(snapshot,judge=Judge())
    assert not v['results'] and v['unverified'][0]['reason']=='provider_error'


def test_historical_scope_is_preserved(snapshot):
    class Historical:
        def retrieve(self,**kwargs):
            assert [c['period'] for c in kwargs['claims']]==['2024','2024']
            e=copy.deepcopy(snapshot['verification']['evidence'][0]);e['content']='A different report gives only a 2026 figure.'
            return [e],[],None
    class ScopeJudge:
        def judge(self,**kwargs):
            assert '2026' in kwargs['evidence'][0]['content']
            return dict(pair_id='pair_0001',summary='Historical period is missing.',verdicts=[dict(claim_id=c['claim_id'],status='insufficient_evidence',rationale='2026 does not settle 2024.',evidence_refs=[]) for c in kwargs['claims']]),[]
    v=verify(snapshot,retriever=Historical(),judge=ScopeJudge())
    assert all(r['status']=='insufficient_evidence' for r in v['results'][0]['verdicts'])
    prompt=(Path(__file__).parents[1]/'src/althea_evidence_ui/prompts/adjudicate_v1.txt').read_text()
    assert 'scope mismatch' in prompt and 'untrusted data' in prompt


def test_reject_over_cap(snapshot):
    with pytest.raises(VerificationError):VerificationService(dict(mode='fixture',max_verify_pairs=0)).verify(snapshot['transcript'],snapshot['analysis'],['pair_0001'],budget=AttemptBudget(0))


def test_fixture_session_review_exports(snapshot):
    b=FixtureBackend();s=b.run(SOURCE,verify=True)
    assert len(b.list_jobs())==1 and b.load(s['job_id'])==s
    assert json.loads(snapshot_json(s))==s
    rows=list(csv.DictReader(io.StringIO(claims_csv(s).decode('utf-8-sig'))))
    assert len(rows)==7 and rows[0]['value']=='10000000'
    assert b.save_review(s['job_id'],s['transcript'])==s
    t=copy.deepcopy(s['transcript']);t['segments'][0]['text']='=1+1\nA revised quote'
    reviewed=b.save_review(s['job_id'],t)
    assert reviewed['analysis'] is reviewed['verification'] is None
    assert reviewed['status']=='ready' and reviewed['transcript']['origin']=='human_reviewed'
    result=b.reanalyze(s['job_id'],verify=False)
    assert result['analysis'] is None and result['issues'][0]['code']=='CUSTOM_EDIT_REQUIRES_LIVE'
    with pytest.raises(VerificationError):b.verify_pairs(s['job_id'],['pair_0001'])
    assert b.reanalyze(b.run(SOURCE,verify=False)['job_id'],verify=True)['verification']


@pytest.mark.parametrize('value',['=2+2','+SUM(A1)','-formula','@external','  =1+1','\tformula','\n=1+1'])
def test_formula_safe_csv_preserves_json(snapshot,value):
    t=snapshot['transcript'];t['speakers'][0]['display_name']=value;t['transcript_id']=transcript_identity(t)
    a=snapshot['analysis'];a['transcript_id']=t['transcript_id'];a['analysis_id']=analysis_identity(a)
    snapshot['verification']=None
    row=next(csv.DictReader(io.StringIO(claims_csv(snapshot).decode('utf-8-sig'))))
    assert row['speaker']=="'"+value
    assert json.loads(snapshot_json(snapshot))['transcript']['speakers'][0]['display_name']==value


def test_no_fake_uploads_and_safe_playback(tmp_path):
    with pytest.raises(VerificationError):FixtureBackend().run({**SOURCE,'kind':'audio','sample_id':None,'local_path':'clip.wav'},verify=False)
    upload=SimpleNamespace(name='../../private/voice.wav',getvalue=lambda:b'audio')
    source=save_upload(upload,str(tmp_path))
    assert Path(source['local_path']).parent==tmp_path/'uploads'
    assert Path(source['local_path']).name!='voice.wav'
    assert playback_path(str(tmp_path),'../escape.wav') is None
    assert playback_path(str(tmp_path),'uploads/'+Path(source['local_path']).name)


@pytest.mark.parametrize('status,expected',[(429,3),(503,3),(401,1),(400,1),(404,1)])
def test_retry_accounting(monkeypatch,status,expected):
    from althea_evidence_ui import runtime
    monkeypatch.setattr(runtime.time,'sleep',lambda _:None)
    class Failure(Exception):code=status
    class Models:
        def generate_content(self,**k):raise Failure()
    adapter=VertexAdapter({});adapter._client=SimpleNamespace(models=Models())
    budget=AttemptBudget()
    with pytest.raises(VerificationError):adapter.request('retrieval',budget,model='test')
    assert budget.used==expected


def test_live_defaults_never_fallback(snapshot):
    v=VerificationService(dict(mode='live')).verify(snapshot['transcript'],snapshot['analysis'],['pair_0001'],budget=AttemptBudget(0))
    assert not v['results'] and v['unverified'][0]['reason']=='provider_error'


def test_live_adapters_separate_calls(snapshot):
    from althea_evidence_ui.adjudication import GoogleEvidenceJudge
    from althea_evidence_ui.grounding import NATIVE_ATTRIBUTIONS
    from google.genai import types
    e=snapshot['verification']['evidence'][0]
    metadata=types.GroundingMetadata(grounding_chunks=[types.GroundingChunk(web=types.GroundingChunkWeb(uri=e['url'],title=e['title']))],grounding_supports=[types.GroundingSupport(segment=types.Segment(text=e['content']),grounding_chunk_indices=[0])],search_entry_point=types.SearchEntryPoint(rendered_content='<div>Native Search Suggestions</div>'))
    grounded=SimpleNamespace(candidates=[SimpleNamespace(grounding_metadata=metadata)],text=e['content'],usage_metadata=None)
    adjudicated=SimpleNamespace(text=json.dumps(snapshot['verification']['results'][0]),usage_metadata=None)
    seen=[]
    class Models:
        def generate_content(self,**kwargs):
            seen.append(kwargs)
            return grounded if kwargs['config'].tools else adjudicated
    client=SimpleNamespace(models=Models())
    retriever=GoogleGroundedRetriever({});retriever._client=client
    judge=GoogleEvidenceJudge({});judge._client=client
    budget=AttemptBudget(2)
    result=VerificationService(dict(mode='live'),retriever=retriever,judge=judge).verify(snapshot['transcript'],snapshot['analysis'],['pair_0001'],budget=budget)
    assert not result['issues'] and budget.used==2
    assert seen[0]['config'].tools and seen[0]['config'].response_schema is None
    assert not seen[1]['config'].tools and seen[1]['config'].response_schema
    assert result['evidence'][0]['content_origin']=='grounded_summary'
    assert result['grounding_attributions'][0]['search_entry_point_html']=='<div>Native Search Suggestions</div>'


@pytest.mark.live
def test_live_smoke(snapshot):
    import os
    if not os.getenv('GOOGLE_CLOUD_PROJECT') or not os.getenv('ALTHEA_LIVE_SMOKE'):
        pytest.skip('Set GOOGLE_CLOUD_PROJECT, ADC and ALTHEA_LIVE_SMOKE=1 for an explicitly authorized cloud test.')
    v=VerificationService(dict(mode='live',project_id=os.environ['GOOGLE_CLOUD_PROJECT'])).verify(snapshot['transcript'],snapshot['analysis'],['pair_0001'],budget=AttemptBudget())
    assert not v['issues']
