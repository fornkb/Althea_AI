import argparse
import json
import sys
from pathlib import Path
from . import LiveBackend,SampleBackend,GeminiBackend,load_settings
from .preflight import preflight,live_smoke


def main():
    p=argparse.ArgumentParser(description='Althea AI local debate analysis; fictional sample is the default mode.')
    p.add_argument('--mode',choices=['fixture','live'],default='fixture')
    p.add_argument('--provider',choices=['vertex','gemini'],default=None,help='Explicit Google Cloud or Gemini API key route')
    inputs=p.add_mutually_exclusive_group()
    inputs.add_argument('--input',help='Existing MP3, WAV or complete Transcript JSON')
    inputs.add_argument('--sample',choices=['riverton_demo'])
    p.add_argument('--verify',action='store_true',help='Check up to four eligible disagreements')
    p.add_argument('--output',help='Complete Snapshot JSON output')
    p.add_argument('--title',default=None)
    p.add_argument('--data-dir')
    p.add_argument('--preflight',action='store_true',help='Check setup without external calls or API credits')
    p.add_argument('--live-smoke',action='store_true',help='Explicitly authorize one accounted hosted text request')
    a=p.parse_args()
    try:
        overrides={}
        if a.data_dir:overrides['data_dir']=a.data_dir
        if a.provider:overrides['provider']=a.provider
        s=load_settings(a.mode,overrides=overrides)
        if a.preflight or a.live_smoke:
            result=preflight(s)
            if a.live_smoke:result['live_smoke']=live_smoke(s)
            encoded=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
            if a.output:
                target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(encoded,encoding='utf-8')
            print(encoded,end='')
            return 1 if result.get('live_smoke',{}).get('status')=='failed' else 0
        if not a.input and not a.sample:p.error('Choose --sample riverton_demo or --input FILE.')
        if not a.output:p.error('--output is required for analysis.')
        title=a.title or ('Riverton sample — fictional' if a.sample else Path(a.input).stem)
        source=dict(kind='sample' if a.sample else 'transcript' if Path(a.input).suffix.lower()=='.json' else 'audio',sample_id=a.sample,local_path=a.input,title=title)
        backend=SampleBackend(s) if a.mode=='fixture' else GeminiBackend(s) if s['provider']=='gemini' else LiveBackend(s)
        snapshot=backend.run(source,verify=a.verify,progress=lambda text:print(text,file=sys.stderr))
        target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(job_id=snapshot['job_id'],status=snapshot['status'],usage=backend.job_usage(snapshot['job_id'])),indent=2))
        return 0 if snapshot['status']=='complete' else 1
    except Exception as exc:
        print(f'{getattr(exc,"code","APP_ERROR")}: {str(exc) if getattr(exc,"code",None) else "Application could not finish; check local setup."}',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
