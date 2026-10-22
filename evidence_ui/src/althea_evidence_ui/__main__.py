import argparse
import json
import os
import sys
from pathlib import Path
from . import VerificationService, VerificationError
from .runtime import AttemptBudget


def main():
    p = argparse.ArgumentParser(description='Verify selected potential disagreements with supplied evidence')
    p.add_argument('--mode',choices=['fixture','live'],default='fixture')
    p.add_argument('--input',required=True); p.add_argument('--transcript',required=True)
    p.add_argument('--pairs',nargs='*',default=[]); p.add_argument('--output',required=True)
    a = p.parse_args()
    try:
        settings = dict(mode=a.mode,project_id=os.getenv('GOOGLE_CLOUD_PROJECT'),location=os.getenv('GOOGLE_CLOUD_LOCATION','global'),grounding_model=os.getenv('ALTHEA_GROUNDING_MODEL','gemini-2.5-flash'),text_model=os.getenv('ALTHEA_TEXT_MODEL','gemini-2.5-flash'))
        result = VerificationService(settings).verify(json.loads(Path(a.transcript).read_text(encoding='utf-8-sig')),json.loads(Path(a.input).read_text(encoding='utf-8-sig')),a.pairs,budget=AttemptBudget())
        out = Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return 1 if any(u['reason'] in ('provider_error','budget_limit') for u in result['unverified']) else 0
    except (VerificationError,OSError,ValueError) as exc:
        print(f'{getattr(exc,"code","INVALID_INPUT")}: {exc}',file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
