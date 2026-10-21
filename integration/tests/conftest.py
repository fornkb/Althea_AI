import copy
import json
import re
import socket
from pathlib import Path
from types import SimpleNamespace
import pytest
from althea_app.backend import LiveBackend,SampleBackend
from althea_app.errors import AppError
from althea_ingestion.common import digest
from althea_evidence_ui.grounding import NATIVE_ATTRIBUTIONS

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def offline(monkeypatch,request):
    if request.node.get_closest_marker('live'):return
    def blocked(*a,**k):raise AssertionError('Offline integration must not contact the network')
    monkeypatch.setattr(socket,'create_connection',blocked)
    monkeypatch.setattr(socket.socket,'connect',blocked)


@pytest.fixture
def reference():
    return json.loads((ROOT/'build_handoffs/reference/reference_snapshot.json').read_text(encoding='utf-8'))


def usage(stage):
    return dict(stage=stage,provider='vertex',model='test-fake-not-a-live-model',request_count=1,input_tokens=None,output_tokens=None)


class Providers:
    """Simulated provider seams, never recordings or real inference results."""
    mode='live'

    def __init__(self,reference,*,empty=False,no_sources=False,many=False):
        self.reference=copy.deepcopy(reference);self.calls=[]
        self.empty,self.no_sources,self.many=empty,no_sources,many
        self.fail_transcription=self.fail_analysis=self.fail_retrieval=False
        self.fail_pair=None;self.native=False;self.invalid=False
        self.segments=copy.deepcopy(reference['transcript']['segments'])
        if many:
            self.segments=[dict(segment_id=f'seg_{i+1:04d}',speaker_id=f'speaker_{i%2+1:02d}',start_s=float(i),end_s=float(i+1),text=f"District{i//2+1}'s 2024 budget was {10 if i%2==0 else 12} US dollars.") for i in range(10)]

    def transcribe(self,path,*,language,expected_speakers,budget,progress=None):
        budget.consume('transcription');self.calls.append('transcription')
        if self.fail_transcription:raise AppError('PROVIDER_AUTH','Mock authorization failure.',stage='transcription')
        return dict(words=[dict(word=s['text'],speaker=s['speaker_id'],start_s=s['start_s'],end_s=s['end_s']) for s in self.segments],usage=[usage('transcription')])

    def generate_json(self,*,operation,system,payload,response_schema,max_output_tokens,budget):
        budget.consume(operation);self.calls.append(operation)
        if self.fail_analysis:raise AppError('PROVIDER_AUTH','Mock authorization failure.',stage='analysis')
        if self.invalid:return {'unknown':'invalid schema'},usage(operation)
        assert operation=='extraction'
        if self.empty:return {'claims':[]},usage(operation)
        segments=payload['transcript']['segments']
        claims=[]
        if self.many:
            for i,segment in enumerate(segments):
                text=segment['text']
                claims.append(dict(speaker_id=segment['speaker_id'],proposition=text,subject=f'District{i//2+1}',metric='annual budget',period='2024',geography=f'District{i//2+1}',population='not_applicable',measurement_basis='annual allocation',qualifiers=[],checkability='checkable',missing_context=[],source_spans=[dict(segment_id=segment['segment_id'],start_char=0,end_char=len(text),quote=text)],quantity_raw=re.search(r'\d+ US dollars',text).group(),currency_context='USD'))
        else:
            by_id={s['segment_id']:s for s in segments}
            for raw in self.reference['analysis']['claims']:
                c=copy.deepcopy(raw);c.pop('claim_id')
                segment=by_id[c['source_spans'][0]['segment_id']]
                c['proposition']=segment['text'];c['source_spans']=[dict(segment_id=segment['segment_id'],start_char=0,end_char=len(segment['text']),quote=segment['text'])]
                q=c.pop('quantity')
                quantity=q['raw_text']
                if quantity not in segment['text']:
                    quantity=re.search(r'(?:\d+(?:\.\d+)? million US dollars|\d+ US dollars|\d+ percent|five percent)',segment['text']).group()
                c.update(quantity_raw=quantity,currency_context=None)
                claims.append(c)
        return dict(claims=claims),usage(operation)

    def retrieve(self,*,transcript,claims,pair,budget):
        budget.consume('retrieval');self.calls.append('retrieval')
        if self.fail_retrieval or pair['pair_id']==self.fail_pair:raise AppError('PROVIDER_UNAVAILABLE','Mock retrieval failure.',stage='verification')
        if self.no_sources:return [],[usage('retrieval')],None
        e=dict(evidence_id=f"ev_{pair['pair_id']}_0001",pair_id=pair['pair_id'],claim_ids=[c['claim_id'] for c in claims],url='https://example.org/testing/'+pair['pair_id'],title='Simulated source for integration tests',publisher=None,published_date=None,retrieved_at='2026-10-21T00:00:00Z',content='A simulated reference gives a third value for the same scope.',content_origin='grounded_summary',queries=['neutral test query'])
        attr=dict(pair_id=pair['pair_id'],search_entry_point_html='<div>Test native metadata</div>') if self.native else None
        if attr:NATIVE_ATTRIBUTIONS.add(digest(attr))
        return [e],[usage('retrieval')],attr

    def judge(self,*,claims,pair,evidence,budget):
        budget.consume('adjudication');self.calls.append('adjudication')
        return dict(pair_id=pair['pair_id'],verdicts=[dict(claim_id=c['claim_id'],status='refuted',rationale='Simulated assessment for interface tests only.',evidence_refs=[dict(evidence_id=evidence[0]['evidence_id'],stance='refutes')]) for c in claims],summary='Simulated independent verdicts; no real fact check.'),[usage('adjudication')]


@pytest.fixture
def live_factory(tmp_path,monkeypatch,reference):
    from althea_ingestion import audio
    monkeypatch.setattr(audio.shutil,'which',lambda binary:binary)
    def run(args,**kwargs):
        if args[0]=='ffprobe':return SimpleNamespace(stdout=json.dumps(dict(format={'duration':'65.0','format_name':'wav'},streams=[dict(codec_type='audio',codec_name='pcm_s16le',channels=2)])).encode())
        return SimpleNamespace(stdout=b'\1\0')
    monkeypatch.setattr(audio,'run_tool',run)
    path=tmp_path/'simulated input with spaces.wav';path.write_bytes(b'MOCK AUDIO BYTES FOR UNIT TESTS; NOT A RECORDING')
    settings=dict(data_dir=str(tmp_path/'data'),project_id='mock-project')
    def factory(providers=None,**changes):
        providers=providers or Providers(reference)
        b=LiveBackend({**settings,**changes},transcriber=providers,text_provider=providers,retriever=providers,judge=providers)
        return b,providers,dict(kind='audio',local_path=str(path),sample_id=None,title='Fake-live integration test')
    factory.settings=settings
    return factory
