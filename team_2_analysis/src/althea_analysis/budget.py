"""Standalone budget; integration supplies its persisted duck-typed replacement."""
from threading import Lock
from .errors import AnalysisError


class AttemptBudget:
    def __init__(self, limit=20):
        if type(limit) is not int or not 0 <= limit <= 20:
            raise AnalysisError("INVALID_INPUT", "Attempt limit must be an integer from 0 to 20.")
        self.limit = limit
        self.used = 0
        self.stages = []
        self._lock = Lock()

    def consume(self, stage):
        with self._lock:
            if self.used >= self.limit:
                raise AnalysisError("BUDGET_LIMIT", "The job's provider attempt budget is exhausted.", stage=stage)
            self.used += 1
            self.stages.append(stage)
