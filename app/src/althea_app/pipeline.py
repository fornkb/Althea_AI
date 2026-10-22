"""Pure incremental verification assembly; no I/O and no provider calls."""
import copy
from althea_ingestion.common import canonical,verification_identity
from althea_evidence_ui import validate_verification
from .validation import eligible_pairs


def unique(values):
    seen=set();result=[]
    for value in values:
        encoded=canonical(value)
        if encoded not in seen:
            seen.add(encoded);result.append(copy.deepcopy(value))
    return result


def empty_verification(analysis):
    v=dict(schema_version=analysis['schema_version'],verification_id='pending',analysis_id=analysis['analysis_id'],
        evidence=[],results=[],unverified=[dict(pair_id=p,reason='not_selected') for p in eligible_pairs(analysis)],
        grounding_attributions=[],issues=[],usage=[])
    v['verification_id']=verification_identity(v)
    return v


def merge_verification(analysis, previous, fresh, *, touched, refresh=False, blocked=()):
    """Replace successful pairs atomically; failed refreshes keep dated saved evidence."""
    if previous is None or previous['analysis_id']!=analysis['analysis_id']:
        previous=empty_verification(analysis)
    previous=validate_verification(previous,analysis)
    fresh=validate_verification(fresh,analysis)
    eligible=eligible_pairs(analysis)
    touched=set(touched);blocked=set(blocked)
    results={r['pair_id']:copy.deepcopy(r) for r in previous['results']}
    evidence={p:[copy.deepcopy(e) for e in previous['evidence'] if e['pair_id']==p] for p in eligible}
    attrs={g['pair_id']:copy.deepcopy(g) for g in previous['grounding_attributions']}
    reasons={u['pair_id']:u['reason'] for u in previous['unverified']}
    incoming={r['pair_id']:r for r in fresh['results']}
    for p in touched:
        if p in incoming:
            results[p]=copy.deepcopy(incoming[p])
            evidence[p]=[copy.deepcopy(e) for e in fresh['evidence'] if e['pair_id']==p]
            attrs.pop(p,None)
            for g in fresh['grounding_attributions']:
                if g['pair_id']==p:
                    attrs[p]=copy.deepcopy(g)
            reasons.pop(p,None)
        else:
            current=next((u['reason'] for u in fresh['unverified'] if u['pair_id']==p),'provider_error')
            if current!='not_selected' or p not in reasons:
                reasons[p]=current
    for p in blocked:
        reasons[p]='budget_limit'
    # Old failures for replaced/refreshed pairs are not active errors anymore.
    issues=[i for i in previous['issues'] if not set(i['related_ids']) & touched]
    issues=unique(issues+fresh['issues'])
    retained=(touched-set(incoming) | blocked) & set(results)
    if retained:
        issues.append(dict(stage='verification',code='SAVED_EVIDENCE_RETAINED',
            message='The latest check could not finish. Showing previously saved evidence with its original retrieval dates; it has not been refreshed.',
            retryable=False,related_ids=sorted(retained)))
    issues=unique(issues)
    v=dict(schema_version=analysis['schema_version'],verification_id='pending',analysis_id=analysis['analysis_id'],
        evidence=[e for p in sorted(results) for e in evidence[p]],results=[results[p] for p in sorted(results)],
        unverified=[dict(pair_id=p,reason=reasons.get(p,'not_selected')) for p in eligible if p not in results],
        grounding_attributions=[attrs[p] for p in sorted(attrs) if p in results],issues=issues,
        usage=copy.deepcopy(previous['usage'])+copy.deepcopy(fresh['usage']))
    v['verification_id']=verification_identity(v)
    return validate_verification(v,analysis)
