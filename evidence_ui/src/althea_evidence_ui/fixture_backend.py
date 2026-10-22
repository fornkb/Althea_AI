"""Session-only fictional backend implementing the frozen DashboardBackend."""
import copy
import json
import uuid
from importlib.resources import files
from .common import now, validate_snapshot, reviewed_transcript
from .verification import VerificationService
from .runtime import AttemptBudget
from .errors import ComponentError, require


class FixtureBackend:
    mode = 'fixture'

    def __init__(self, settings=None):
        self.settings = {**(settings or {}),'mode':'fixture'}
        self.jobs = {}
        self.reference = json.loads(files(__package__).joinpath('data/reference_snapshot.json').read_text(encoding='utf-8'))
        self.reservations = {}
        self.run_count = self.verify_count = 0

    def _store(self,s):
        s['updated_at'] = now()
        self.jobs[s['job_id']] = validate_snapshot(s)
        return self.load(s['job_id'])

    def run(self, source: dict, *, verify: bool, progress=None) -> dict:
        from ._contract import InputRequest
        from .common import wire
        source = wire(InputRequest,source)
        require(source['kind']=='sample' and source['sample_id']=='riverton_demo' and source['local_path'] is None, 'File analysis becomes available after live integration; choose the fictional sample.')
        self.run_count += 1
        if progress:
            progress('Loading fictional sample; no external requests.')
        s = copy.deepcopy(self.reference)
        s.update(job_id=str(uuid.uuid4()),title=source['title'],created_at=now(),updated_at=now(),verification=None,status='complete')
        s['transcript']['source']['title'] = source['title']
        self.reservations[s['job_id']] = set()
        self._store(s)
        return self.verify_pairs(s['job_id'],['pair_0001'],progress=progress) if verify else self.load(s['job_id'])

    def load(self, job_id: str) -> dict:
        require(job_id in self.jobs, 'Job is not available in this sample session.', 'JOB_NOT_FOUND')
        return copy.deepcopy(self.jobs[job_id])

    def list_jobs(self, limit: int = 20) -> list[dict]:
        return [{k:s[k] for k in ('job_id','title','mode','status','updated_at')} for s in sorted(self.jobs.values(),key=lambda s:s['updated_at'],reverse=True)[:limit]]

    def save_review(self, job_id: str, transcript: dict) -> dict:
        s = self.load(job_id)
        t = reviewed_transcript(s['transcript'],transcript)
        if t['transcript_id'] == s['transcript']['transcript_id']:
            return s
        s.update(transcript=t,analysis=None,verification=None,status='ready')
        return self._store(s)

    def reanalyze(self, job_id: str, *, verify: bool, progress=None) -> dict:
        s = self.load(job_id)
        if s['transcript']['transcript_id'] != self.reference['transcript']['transcript_id']:
            s.update(analysis=None,verification=None,status='ready')
            s['issues'] = [dict(stage='analysis',code='CUSTOM_EDIT_REQUIRES_LIVE',message='Custom edited analysis requires live backend. The reviewed transcript is preserved.',retryable=False,related_ids=[])]
            return self._store(s)
        s.update(analysis=copy.deepcopy(self.reference['analysis']),verification=None,status='complete',issues=[])
        self._store(s)
        return self.verify_pairs(job_id,['pair_0001'],progress=progress) if verify else self.load(job_id)

    def verify_pairs(self, job_id: str, pair_ids: list[str], *, progress=None) -> dict:
        s = self.load(job_id)
        require(s['analysis'] is not None,'Reanalyze the transcript before evidence checking.')
        require(len(pair_ids)==len(set(pair_ids)) and set(pair_ids)<= {'pair_0001'},'Choose eligible sample pairs only.')
        tokens = {s['analysis']['analysis_id']+':'+p for p in pair_ids}
        require(len(self.reservations[job_id] | tokens)<=4,'Four distinct pairs per job have been reserved.','BUDGET_LIMIT')
        self.reservations[job_id].update(tokens)
        self.verify_count += 1
        result = VerificationService({'mode':'fixture'}).verify(s['transcript'],s['analysis'],pair_ids,budget=AttemptBudget(0),progress=progress)
        # This fixture has one eligible pair; an empty selection preserves prior results.
        if pair_ids or s['verification'] is None:
            s['verification'] = result
        s['status'] = 'partial' if any(u['reason']!='not_selected' for u in s['verification']['unverified']) else 'complete'
        return self._store(s)
