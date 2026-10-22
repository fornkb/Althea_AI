"""Private dictionary boundary checks, independent of the other components."""
import hashlib
import json
import re
from datetime import datetime, timezone, date
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from ._contract import Transcript, Analysis, Verification, Snapshot
from .errors import ComponentError, require


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def timestamp(value):
    require(bool(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z', value)), 'Expected RFC3339 UTC time.')
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ComponentError('CONTRACT_INVALID','Invalid calendar time.') from exc


def transcript_identity(t):
    return 'tr_' + digest({'content_sha256': t['source']['content_sha256'],
                           **{k: t[k] for k in ('language', 'duration_s', 'speakers', 'segments')}})


def analysis_identity(a):
    return 'an_' + digest({k: a[k] for k in ('transcript_id', 'claims', 'pairs')})


def verification_identity(v):
    return 've_' + digest({k: v[k] for k in ('analysis_id', 'evidence', 'results', 'unverified', 'grounding_attributions')})


def wire(model, payload):
    try:
        return model.model_validate(payload, strict=True).model_dump(mode='json')
    except (ValueError, TypeError) as exc:
        raise ComponentError('CONTRACT_INVALID', f'Invalid {model.__name__} structure.') from exc


def validate_transcript(payload):
    t = wire(Transcript, payload)
    require(1 <= len(t['speakers']) <= 4 and bool(t['segments']), 'Require speech and one to four speakers.')
    ids = [s['speaker_id'] for s in t['speakers']]
    require(ids == [f'speaker_{i:02d}' for i in range(1, len(ids)+1)], 'Speaker IDs must be sequential.')
    previous = -1
    for i, s in enumerate(t['segments'], 1):
        require(s['segment_id'] == f'seg_{i:04d}' and s['speaker_id'] in ids, 'Invalid segment references.')
        require(previous <= s['start_s'] < s['end_s'] <= t['duration_s'] + .25, 'Invalid chronological timing.')
        require(all(round(s[k], 3) == s[k] for k in ('start_s', 'end_s')), 'Times need millisecond precision.')
        require(bool(s['text'].strip()), 'Empty speech segment.')
        previous = s['start_s']
    require(t['transcript_id'] == transcript_identity(t), 'Expected transcript_id: ' + transcript_identity(t))
    return t


def validate_analysis(payload, transcript=None):
    a = wire(Analysis, payload)
    require(a['analysis_id'] == analysis_identity(a), 'Analysis identity mismatch.')
    require(len(a['claims']) <= 30 and len(a['pairs']) <= 60, 'Analysis exceeds limits.')
    claims = {c['claim_id']: c for c in a['claims']}
    require(list(claims) == [f'cl_{i:04d}' for i in range(1, len(a['claims'])+1)], 'Invalid claim IDs.')
    segments = None
    if transcript is not None:
        t = validate_transcript(transcript)
        require(a['transcript_id'] == t['transcript_id'], 'Analysis refers to another transcript.')
        segments = {s['segment_id']: s for s in t['segments']}
    previous_span = ('', -1)
    for c in a['claims']:
        require(bool(c['source_spans']), 'Claim lacks original quotation.')
        scope = ('subject', 'metric', 'period', 'geography', 'population', 'measurement_basis')
        require(all(c[k] is None or bool(c[k].strip()) for k in scope), 'Blank scope.')
        require(all(c[k] is not None for k in scope) or bool(c['missing_context']), 'Missing scope must be recorded.')
        require(c['checkability'] != 'needs_context' or bool(c['missing_context']), 'Missing context not recorded.')
        require(c['checkability'] != 'checkable' or all(c[k] for k in ('subject', 'metric', 'period')), 'Checkable claim lacks scope.')
        positions = [(s['segment_id'], s['start_char']) for s in c['source_spans']]
        require(positions == sorted(set(positions)) and positions[0] >= previous_span, 'Claims/spans out of order.')
        previous_span = positions[0]
        for span in c['source_spans']:
            require(span['start_char'] < span['end_char'], 'Empty source span.')
            if segments is not None:
                s = segments.get(span['segment_id'])
                require(s is not None and s['speaker_id'] == c['speaker_id'], 'Invalid source speaker.')
                require(span['end_char'] <= len(s['text']) and s['text'][span['start_char']:span['end_char']] == span['quote'], 'Forged source quotation.')
        q = c['quantity']
        if q:
            if q['operator'] == 'range':
                require(q['value'] is None and q['lower'] is not None and q['upper'] is not None, 'Invalid range.')
                require(Decimal(q['lower']) <= Decimal(q['upper']), 'Reversed range.')
            else:
                require(q['value'] is not None and q['lower'] is None and q['upper'] is None, 'Invalid quantity.')
            require(bool(re.fullmatch('[A-Z]{3}', q['currency'] or '')) if q['unit'] == 'currency' else q['currency'] is None, 'Invalid currency.')
            require(q['basis'] == c['measurement_basis'], 'Quantity basis mismatch.')
            require(any(q['raw_text'] in s['quote'] for s in c['source_spans']), 'Numeric wording absent from quote.')
    tuples = []
    for i, p in enumerate(a['pairs'], 1):
        x, y = p['claim_a_id'], p['claim_b_id']
        require(p['pair_id'] == f'pair_{i:04d}' and x < y and x in claims and y in claims, 'Invalid pair identity.')
        require(claims[x]['speaker_id'] != claims[y]['speaker_id'], 'Pair requires different speakers.')
        tuples.append((x, y))
        require((p['numeric_difference'] is None) == (p['numeric_difference_unit'] is None), 'Incomplete numeric difference.')
        if p['numeric_difference'] is not None:
            l, r = claims[x], claims[y]
            require(all(l[k] is not None and l[k] == r[k] for k in scope), 'Numeric subtraction requires equal known scope.')
            q, z = l['quantity'], r['quantity']
            require(q and z and q['operator'] == z['operator'] == 'eq' and q['unit'] == z['unit'] and q['currency'] == z['currency'] and l['qualifiers'] == r['qualifiers'], 'Unsafe numeric difference.')
            require(Decimal(p['numeric_difference']) == abs(Decimal(q['value'])-Decimal(z['value'])) and p['numeric_difference_unit'] == q['unit'], 'Incorrect numeric difference.')
    require(tuples == sorted(set(tuples)), 'Duplicate/unordered pairs.')
    return a


def normalize_url(url):
    try:
        p = urlsplit(url)
        require(p.scheme.lower() in ('http', 'https') and bool(p.hostname) and not p.username and not p.password and not any(c.isspace() or ord(c) < 32 for c in url), 'Evidence requires a valid HTTP(S) URL.')
        p.port  # validates malformed ports
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith('utm_') and k.lower() not in ('gclid', 'fbclid')]
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', urlencode(sorted(query)), ''))
    except ValueError as exc:
        raise ComponentError('CONTRACT_INVALID', 'Invalid source URL.') from exc


def validate_verification(payload, analysis):
    a = validate_analysis(analysis)
    v = wire(Verification, payload)
    require(v['analysis_id'] == a['analysis_id'] and v['verification_id'] == verification_identity(v), 'Verification identity mismatch.')
    eligible = {p['pair_id']: p for p in a['pairs'] if p['relation'] in ('numeric_discrepancy', 'direct_conflict', 'insufficient_context')}
    required = {p for p,item in eligible.items() if item['relation'] != 'insufficient_context'}
    result_ids = [r['pair_id'] for r in v['results']]
    ids = result_ids + [r['pair_id'] for r in v['unverified']]
    require(len(ids) == len(set(ids)) and required <= set(ids) <= set(eligible), 'Verification must cover established disagreements and only eligible contextual comparisons.')
    evidence, urls, per_pair = {}, set(), {}
    for e in v['evidence']:
        p = eligible.get(e['pair_id'])
        require(p is not None and e['evidence_id'] not in evidence and e['pair_id'] in result_ids, 'Unknown/duplicate evidence.')
        require(bool(e['claim_ids']) and len(set(e['claim_ids'])) == len(e['claim_ids']) and set(e['claim_ids']) <= {p['claim_a_id'], p['claim_b_id']}, 'Invalid evidence claim links.')
        url = normalize_url(e['url'])
        require((e['pair_id'], url) not in urls, 'Duplicate source URL.')
        urls.add((e['pair_id'], url))
        timestamp(e['retrieved_at'])
        if e['published_date'] is not None:
            require(bool(re.fullmatch(r'\d{4}-\d\d-\d\d', e['published_date'])), 'Invalid publication date.')
            try:
                date.fromisoformat(e['published_date'])
            except ValueError as exc:
                raise ComponentError('CONTRACT_INVALID','Invalid calendar date.') from exc
        require((e['content'] is None) if e['content_origin'] == 'metadata_only' else bool(e['content'] and e['content'].strip()), 'Evidence content/origin mismatch.')
        evidence[e['evidence_id']] = e
        per_pair.setdefault(e['pair_id'], []).append((url, e['evidence_id']))
    for pair_id, sources in per_pair.items():
        require([eid for _, eid in sorted(sources)] == [f'ev_{pair_id}_{i:04d}' for i in range(1, len(sources)+1)], 'Evidence IDs must follow normalized URL order.')
    for r in v['results']:
        p = eligible[r['pair_id']]
        require(len(r['verdicts']) == 2 and {c['claim_id'] for c in r['verdicts']} == {p['claim_a_id'], p['claim_b_id']}, 'Require independent verdicts for both claims.')
        for verdict in r['verdicts']:
            seen = set()
            for ref in verdict['evidence_refs']:
                e = evidence.get(ref['evidence_id'])
                require(e is not None and e['pair_id'] == r['pair_id'] and verdict['claim_id'] in e['claim_ids'] and ref['evidence_id'] not in seen, 'Fabricated/duplicate/wrong-pair evidence reference.')
                seen.add(ref['evidence_id'])
            if verdict['status'] in ('supported', 'refuted'):
                stance = 'supports' if verdict['status'] == 'supported' else 'refutes'
                require(any(ref['stance'] == stance and evidence[ref['evidence_id']]['content_origin'] != 'metadata_only' for ref in verdict['evidence_refs']), 'Decisive verdict requires substantive matching evidence.')
    attrs = [g['pair_id'] for g in v['grounding_attributions']]
    require(len(attrs) == len(set(attrs)) and set(attrs) <= set(result_ids), 'Invalid grounding attributions.')
    return v


def validate_snapshot(payload):
    s = wire(Snapshot, payload)
    timestamp(s['created_at']); timestamp(s['updated_at'])
    if s['transcript'] is not None:
        s['transcript'] = validate_transcript(s['transcript'])
    if s['analysis'] is not None:
        require(s['transcript'] is not None, 'Analysis lacks transcript.')
        s['analysis'] = validate_analysis(s['analysis'], s['transcript'])
    if s['verification'] is not None:
        require(s['analysis'] is not None, 'Verification lacks analysis.')
        s['verification'] = validate_verification(s['verification'], s['analysis'])
    if s['status']=='ready':
        require(s['transcript'] is not None and s['analysis'] is None and s['verification'] is None, 'Ready jobs await analysis of a saved transcript.')
    if s['status']=='complete':
        require(s['transcript'] is not None and s['analysis'] is not None, 'Complete jobs require usable transcript and analysis.')
    if s['status']=='partial':
        require(s['transcript'] is not None, 'Partial jobs require usable upstream work.')
    return s


def reviewed_transcript(original, proposed):
    import copy
    require(set(original) == set(proposed), 'Review fields changed.')
    allowed = ('speakers', 'segments', 'transcript_id', 'origin')
    require(all(original[k] == proposed[k] for k in original if k not in allowed), 'Review modified protected media or provenance fields.')
    require([s['speaker_id'] for s in proposed['speakers']] == [s['speaker_id'] for s in original['speakers']], 'Review changed stable speaker IDs.')
    require([s['segment_id'] for s in proposed['segments']] == [s['segment_id'] for s in original['segments']], 'Review changed stable segment IDs.')
    t = copy.deepcopy(proposed)
    t['transcript_id'] = transcript_identity(t)
    t['origin'] = 'human_reviewed'
    return validate_transcript(t)
