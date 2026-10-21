import argparse
import json
import os
import sys
from pathlib import Path
from . import IngestionService, IngestionError
from .runtime import AttemptBudget


def main():
    p = argparse.ArgumentParser(description='Althea English audio/transcript ingestion')
    p.add_argument('--mode',choices=['fixture','live'],default='fixture')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--sample'); group.add_argument('--input')
    p.add_argument('--output',required=True); p.add_argument('--title',default='Althea transcript')
    p.add_argument('--data-dir',default='data')
    a = p.parse_args()
    settings = dict(mode=a.mode,data_dir=str(Path(a.data_dir).resolve()),project_id=os.getenv('GOOGLE_CLOUD_PROJECT'),location=os.getenv('GOOGLE_CLOUD_LOCATION','global'),transcribe_model=os.getenv('ALTHEA_TRANSCRIBE_MODEL','gemini-3.5-transcribe'))
    source = dict(kind='sample' if a.sample else 'transcript' if Path(a.input).suffix.lower()=='.json' else 'audio',local_path=a.input,sample_id=a.sample,title=a.title)
    try:
        result = IngestionService(settings).ingest(source,budget=AttemptBudget())
        out = Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return 0
    except (IngestionError,OSError) as exc:
        print(f'{getattr(exc,"code","IO_ERROR")}: {exc}',file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
