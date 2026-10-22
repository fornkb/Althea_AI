from .errors import issue


class JobBudget:
    def __init__(self, repository, job_id, max_attempts=20):
        self.repository,self.job_id,self.max_attempts=repository,job_id,max_attempts
        self.initial = repository.attempts_used(job_id)
        self.pending = None

    @property
    def used(self):
        return self.repository.attempts_used(self.job_id)

    @property
    def new_attempts(self):
        return self.used-self.initial

    def _event(self,code,message,stage,attempt):
        self.repository.append_event(self.job_id,issue(code,message,related_ids=[stage,str(attempt)]))

    def consume(self, stage):
        if self.pending:
            self.finish(self.pending[0]!=stage)
        self.repository.consume_attempt(self.job_id,stage,self.max_attempts)
        count = self.used
        self.pending=(stage,count)
        self._event('ATTEMPT_RESERVED','One provider attempt reserved.',stage,count)

    def finish(self, success):
        if self.pending:
            stage,attempt=self.pending
            self._event('ATTEMPT_COMPLETED' if success else 'ATTEMPT_FAILED','Provider attempt completed.' if success else 'Provider attempt failed or required repair.',stage,attempt)
            self.pending=None
