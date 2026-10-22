"""Deterministic lexical shortlist, deliberately conservative about unknown scope."""
import re
from itertools import combinations
from .utils import normalized

MATCHING_VERSION = "lexical-context-v1.2.0"
_STOP = set("a an the of to in on for and or was were is are has had it its by at from with this that not".split())
_GENERIC_METRIC = set("business legal provision provisions certain used use count number amount value total annual metric measure status".split())


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
            # A short label can be embedded in a qualified/ambiguous label, e.g.
            # 'business bankruptcies' vs 'bankruptcies or legal provisions used'.
            # This only shortlists a comparison; it never establishes a conflict.
            left_terms, right_terms = _terms(left['metric']), _terms(right['metric'])
            shared = (left_terms & right_terms) - _GENERIC_METRIC
            containment = len(left_terms & right_terms) / max(1,min(len(left_terms),len(right_terms)))
            partial = subject_equal and bool(shared) and containment >= .5
            eligible = (metric_equal or metric_overlap >= .5 or partial) and (subject_equal or subject_overlap >= .5)
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


def contextual_candidates(claims, transcript):
    """Adjacent explicit event-count replies merit reasoning even with no word overlap.

    These are provisional inputs to the comparison model, never conflicts inferred
    from proximity or different numbers. The normal shared pair cap still applies.
    """
    positions={s['segment_id']:i for i,s in enumerate(transcript['segments'])}
    candidates=[]
    for left,right in combinations(claims,2):
        if left['speaker_id']==right['speaker_id']:continue
        quantities=[c.get('quantity') for c in (left,right)]
        if not all(q and q['unit']=='count' and re.search(r'\b(times?|occasions?|occurrences?|events?)$',q['raw_text'].strip(),re.I) for q in quantities):continue
        gap=min(abs(positions[a['segment_id']]-positions[b['segment_id']]) for a in left['source_spans'] for b in right['source_spans'])
        if gap==1:candidates.append(tuple(sorted((left['claim_id'],right['claim_id']))))
    return sorted(candidates)
