import copy
from .common import validate_transcript, validate_analysis, validate_verification, verification_identity, normalize_url
from ._contract import Evidence, GroundingAttribution
from .common import wire
from .grounding import FixtureRetriever, GoogleGroundedRetriever
from .adjudication import FixtureJudge, GoogleEvidenceJudge
from .errors import ComponentError, require

RETRIEVAL_VERSION = 'neutral-scope-v1.0.0'
ADJUDICATION_VERSION = 'independent-evidence-v1.0.0'


class VerificationService:
    def __init__(self, settings: dict, *, retriever=None, judge=None):
        self.settings = dict(settings)
        mode = settings.get('mode','fixture')
        require(mode in ('fixture','live'), 'Unknown verification mode.')
        self.retriever = retriever or (FixtureRetriever() if mode == 'fixture' else GoogleGroundedRetriever(settings))
        self.judge = judge or (FixtureJudge() if mode == 'fixture' else GoogleEvidenceJudge(settings))
        require(mode != 'fixture' or all(getattr(p,'mode','fixture') == 'fixture' for p in (self.retriever,self.judge)), 'Fixture mode cannot use live providers.')

    def verify(self, transcript: dict, analysis: dict, pair_ids: list[str], *, budget, progress=None) -> dict:
        t = validate_transcript(transcript)
        a = validate_analysis(analysis,t)
        eligible = {p['pair_id']:p for p in a['pairs'] if p['relation'] in ('direct_conflict','numeric_discrepancy')}
        require(isinstance(pair_ids,list) and all(isinstance(p,str) for p in pair_ids) and len(pair_ids)==len(set(pair_ids)) and set(pair_ids) <= set(eligible), 'Unknown, duplicate or ineligible requested pairs.')
        require(len(pair_ids) <= min(self.settings.get('max_verify_pairs',4),4), 'At most four pairs may be checked in a request.')
        claims = {c['claim_id']:c for c in a['claims']}
        v = dict(schema_version=self.settings.get('wire_schema_version','1.0.0'),verification_id='pending',analysis_id=a['analysis_id'],evidence=[],results=[],unverified=[],grounding_attributions=[],issues=[],usage=[])
        for pair_id,pair in eligible.items():
            if pair_id not in pair_ids:
                v['unverified'].append(dict(pair_id=pair_id,reason='not_selected'))
                continue
            if progress:
                progress('Checking evidence for ' + pair_id)
            pair_claims = [claims[pair[k]] for k in ('claim_a_id','claim_b_id')]
            try:
                evidence, retrieval_usage, attr = self.retriever.retrieve(transcript=copy.deepcopy(t),claims=copy.deepcopy(pair_claims),pair=copy.deepcopy(pair),budget=budget)
                evidence = [wire(Evidence,e) for e in evidence]
                for e in evidence:
                    normalize_url(e['url'])
                    require(e['pair_id']==pair_id and set(e['claim_ids']) <= {c['claim_id'] for c in pair_claims}, 'Retriever returned evidence for another pair.')
                v['usage'].extend(retrieval_usage)
                if not any(e['content_origin'] != 'metadata_only' and e['content'] for e in evidence):
                    result = dict(pair_id=pair_id,summary='The retrieved sources do not supply substantive evidence for this pair.',verdicts=[dict(claim_id=c['claim_id'],status='needs_context' if c['checkability']=='needs_context' else 'insufficient_evidence',rationale='Essential claim context is missing.' if c['checkability']=='needs_context' else 'No substantive source content was available.',evidence_refs=[]) for c in pair_claims])
                    judge_usage = []
                else:
                    result, judge_usage = self.judge.judge(claims=copy.deepcopy(pair_claims),pair=copy.deepcopy(pair),evidence=copy.deepcopy(evidence),budget=budget)
                require(result.get('pair_id')==pair_id, 'Judge changed the requested pair.')
                trial = copy.deepcopy(v)
                trial['results'].append(result); trial['evidence'].extend(evidence); trial['usage'].extend(judge_usage)
                if attr is not None:
                    trial['grounding_attributions'].append(wire(GroundingAttribution,attr))
                trial['unverified'].extend(dict(pair_id=p,reason='not_selected') for p in eligible if p != pair_id and p not in {r['pair_id'] for r in trial['results']} and p not in {r['pair_id'] for r in trial['unverified']})
                trial['verification_id'] = verification_identity(trial)
                validate_verification(trial,a)
                # Commit this pair only after all source and verdict links validate.
                v['results'].append(result); v['evidence'].extend(evidence); v['usage'].extend(judge_usage)
                if attr is not None:
                    v['grounding_attributions'].append(attr)
            except Exception as exc:
                code = getattr(exc,'code','PROVIDER_RESPONSE_INVALID')
                v['unverified'].append(dict(pair_id=pair_id,reason='budget_limit' if code=='BUDGET_LIMIT' else 'provider_error'))
                v['issues'].append(dict(stage='verification',code=code,message='Evidence check failed for this pair; upstream results are preserved.',retryable=bool(getattr(exc,'retryable',False)),related_ids=[pair_id]))
        v['verification_id'] = verification_identity(v)
        return validate_verification(v,a)
