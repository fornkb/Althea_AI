from althea_ingestion import validate_transcript
from althea_ingestion.common import validate_snapshot as storage_snapshot
from althea_analysis import validate_analysis
from althea_evidence_ui import validate_verification
from .errors import require


def validate_snapshot(payload):
    s = storage_snapshot(payload)
    if s['analysis'] is not None:
        s['analysis'] = validate_analysis(s['analysis'],s['transcript'])
    if s['verification'] is not None:
        s['verification'] = validate_verification(s['verification'],s['analysis'])
    return s


def eligible_pairs(analysis):
    return {p['pair_id']:p for p in analysis['pairs'] if p['relation'] in ('numeric_discrepancy','direct_conflict','insufficient_context')}


def requested_pairs(analysis, pair_ids, cap):
    eligible = eligible_pairs(analysis)
    require(isinstance(pair_ids,list) and all(isinstance(x,str) for x in pair_ids) and len(pair_ids)==len(set(pair_ids)) and set(pair_ids)<=set(eligible),'Choose unique eligible disagreement IDs only.')
    require(len(pair_ids)<=cap,'Choose at most four disagreements per request.')
    return eligible
