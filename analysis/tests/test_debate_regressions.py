import copy
import pytest
from althea_analysis import AnalysisService,AttemptBudget,make_candidate_pairs,normalize_quantity
from althea_analysis.providers import ScriptedTextProvider
from .conftest import make_transcript,proposal


@pytest.mark.parametrize('raw,value', [('six times','6'),('four times','4'),('twenty-one times','21'),
    ('one occasion','1'),('6 occurrences','6'),('at least four times','4')])
def test_spoken_event_counts(raw,value):
    q=normalize_quantity(raw,context={'metric':'business bankruptcies','measurement_basis':'count'})
    assert q['value']==value and q['unit']=='count' and q['raw_text']==raw
    assert q['operator']==('ge' if raw.startswith('at least') else 'eq')


@pytest.mark.parametrize('raw,context',[
    ('six times',{'metric':'speed'}),('four times',{'metric':'price','measurement_basis':'count'}),
    ('six times faster',{'measurement_basis':'count'}),('six times per year',{'measurement_basis':'count'}),
    ('2024',{'measurement_basis':'count','period':'2024'}),
    ('2.5 times',{'measurement_basis':'count'}),('-4 times',{'measurement_basis':'count'}),
])
def test_event_counts_do_not_invent_units_or_parse_multipliers(raw,context):
    assert normalize_quantity(raw,context=context) is None


def test_debate_count_rebuttal_survives_matching_without_invented_scope():
    t=make_transcript(["you've taken business bankruptcy six times.",
        'on occasion, four times, we used certain laws that are there.'])
    claims=[proposal(t,0,quantity_raw='six times',subject='speaker_02',metric='business bankruptcies',
        measurement_basis='count',period=None,geography=None,population=None,missing_context=['period','geography','population']),
        proposal(t,1,quantity_raw='four times',subject='speaker_02',metric='bankruptcies or legal provisions used',
        measurement_basis='count',period=None,geography=None,population=None,qualifiers=['on occasion'],missing_context=['period','geography','population'])]
    provider=ScriptedTextProvider([{'claims':claims},{'pairs':[dict(claim_a_id='cl_0001',claim_b_id='cl_0002',relation='insufficient_context',explanation='This looks like a reply about the same business history, but the event definition is ambiguous.')]}])
    result=AnalysisService({},text_provider=provider).analyze(t,budget=AttemptBudget(2))
    assert [c['quantity']['value'] for c in result['claims']]==['6','4']
    assert len(result['pairs'])==1
    pair=result['pairs'][0]
    assert pair['relation']=='insufficient_context' and pair['numeric_difference'] is None
    assert 'six times' in pair['explanation'] and 'four times' in pair['explanation']
    assert len(provider.calls)==2
    assert provider.calls[1]['payload']['context_segments']==t['segments']
    assert all(c['period'] is None and c['geography'] is None for c in result['claims'])
    assert all(not any('could not be normalized' in note for note in c['missing_context']) for c in result['claims'])


def test_generic_business_words_do_not_match_unrelated_claims():
    base=dict(subject='speaker_02',speaker_id='speaker_01',claim_id='cl_0001',metric='business bankruptcies',proposition='My businesses filed six times.')
    unrelated={**base,'speaker_id':'speaker_02','claim_id':'cl_0002','metric':'business revenue','proposition':'My businesses earned ten million.'}
    assert make_candidate_pairs([base,unrelated])==[]
    broader={**unrelated,'metric':'bankruptcies or legal provisions used'}
    assert make_candidate_pairs([base,broader])==[('cl_0001','cl_0002')]
    broader['speaker_id']='speaker_01'
    assert make_candidate_pairs([base,broader])==[]


@pytest.mark.parametrize('relation,expected', [('different_scope','different_scope'),('direct_conflict','insufficient_context'),('numeric_discrepancy','insufficient_context'),('insufficient_context','insufficient_context')])
def test_adjacent_counts_with_no_lexical_overlap_get_bounded_context_review(relation,expected):
    t=make_transcript(['Your businesses filed six times.','My companies used those laws four times.'])
    claims=[proposal(t,0,subject="the interlocutor's business",metric='business bankruptcy',quantity_raw='six times',measurement_basis='count',period=None,geography=None,missing_context=['period','geography']),
        proposal(t,1,subject="the speaker's company",metric='use of certain laws',quantity_raw='four times',measurement_basis='count',period=None,geography=None,missing_context=['period','geography'])]
    provider=ScriptedTextProvider([{'claims':claims},{'pairs':[dict(claim_a_id='cl_0001',claim_b_id='cl_0002',relation=relation,explanation='A contextual comparison of the two stated event counts.')]}])
    result=AnalysisService({},text_provider=provider).analyze(t,budget=AttemptBudget(2))
    assert result['pairs'][0]['relation']==expected
    assert result['pairs'][0]['method']=='llm' and result['pairs'][0]['numeric_difference'] is None
    assert len(provider.calls)==2
