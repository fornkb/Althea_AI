import csv
import io
import json
from .common import validate_snapshot


def safe_text(value):
    value = '' if value is None else str(value)
    return "'" + value if value.lstrip().startswith(('=','+','-','@','\t','\r')) or value.startswith(('\t','\r','\n')) else value


def claims_csv(snapshot: dict) -> bytes:
    s = validate_snapshot(snapshot)
    output = io.StringIO(newline='')
    columns = ['claim_id','speaker','proposition','quote','start_s','end_s','subject','metric','period','geography','population','measurement_basis','value','unit','currency','checkability','missing_context']
    writer = csv.DictWriter(output,fieldnames=columns)
    writer.writeheader()
    t = s['transcript']
    segments = {seg['segment_id']:seg for seg in t['segments']} if t else {}
    speakers = {speaker['speaker_id']:speaker['display_name'] for speaker in t['speakers']} if t else {}
    for c in (s['analysis'] or {}).get('claims',[]):
        spans = c['source_spans']; quantity = c['quantity'] or {}
        row = {k:c.get(k) for k in columns}
        row.update(speaker=speakers[c['speaker_id']],quote='\n'.join(span['quote'] for span in spans),
                   start_s=min(segments[span['segment_id']]['start_s'] for span in spans),end_s=max(segments[span['segment_id']]['end_s'] for span in spans),
                   value=quantity.get('value'),unit=quantity.get('unit'),currency=quantity.get('currency'),missing_context='; '.join(c['missing_context']))
        writer.writerow({k: (v if k in ('start_s','end_s','value') and v is not None else safe_text(v)) for k,v in row.items()})
    return output.getvalue().encode('utf-8-sig')


def snapshot_json(snapshot: dict) -> bytes:
    return (json.dumps(validate_snapshot(snapshot),ensure_ascii=False,indent=2)+'\n').encode('utf-8')
