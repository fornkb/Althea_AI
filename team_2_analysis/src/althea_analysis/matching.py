"""Deterministic lexical shortlist, deliberately conservative about unknown scope."""
import re
from itertools import combinations
from .utils import normalized

MATCHING_VERSION = "lexical-v1.0.0"
_STOP = set("a an the of to in on for and or was were is are has had it its by at from with this that not".split())


def _terms(text):
    # Numbers cannot create a lexical match. Unicode words are retained.
    return {t for t in re.findall(r"[^\W\d_]+", normalized(text)) if t not in _STOP and len(t) > 2}


def _overlap(left, right):
    a, b = _terms(left), _terms(right)
    return len(a & b) / len(a | b) if a | b else 0


def ranked_candidates(claims):
    ranked = []
    for (i, left), (j, right) in combinations(enumerate(claims), 2):
        if left["speaker_id"] == right["speaker_id"]:
            continue
        subject_equal = bool(left.get("subject") and right.get("subject") and normalized(left["subject"]) == normalized(right["subject"]))
        metric_equal = bool(left.get("metric") and right.get("metric") and normalized(left["metric"]) == normalized(right["metric"]))
        subject_overlap = _overlap(left.get("subject"), right.get("subject"))
        metric_overlap = _overlap(left.get("metric"), right.get("metric"))
        lexical = _overlap(left["proposition"], right["proposition"])
        # Enumerate all cross-speaker pairs, retain plausible topical matches only.
        # Known incompatible metrics should not match merely on city/year/budget.
        if left.get("metric") and right.get("metric"):
            eligible = (metric_equal or metric_overlap >= .5) and (subject_equal or subject_overlap >= .5)
        else:
            shared = _terms(left["proposition"]) & _terms(right["proposition"])
            eligible = lexical >= .45 and len(shared) >= 3
        if not eligible:
            continue
        score = (int(subject_equal and metric_equal), subject_equal + metric_equal,
                 subject_overlap + metric_overlap, lexical, 1 / (1 + abs(j - i)))
        key = tuple(sorted((left["claim_id"], right["claim_id"])))
        ranked.append((score, key))
    return [key for _, key in sorted(ranked, key=lambda x: (tuple(-n for n in x[0]), x[1]))]


def make_candidate_pairs(claims: list[dict], *, max_pairs: int = 60) -> list[tuple[str, str]]:
    if type(max_pairs) is not int or not 0 <= max_pairs <= 60:
        raise ValueError("max_pairs must be an integer from 0 to 60")
    return ranked_candidates(claims)[:max_pairs]
