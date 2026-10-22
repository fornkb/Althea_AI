import argparse
import json
import os
import sys
from pathlib import Path
from .service import AnalysisService
from .budget import AttemptBudget
from .errors import AnalysisError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract source-grounded factual claims and potential disagreements.")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--input", required=True, type=Path, help="Frozen v1 Transcript JSON")
    parser.add_argument("--output", required=True, type=Path, help="UTF-8 Analysis JSON destination")
    args = parser.parse_args(argv)
    settings = dict(mode=args.mode)
    if args.mode == "live":
        settings.update(project_id=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
                        text_model=os.environ.get("ALTHEA_TEXT_MODEL", "gemini-2.5-flash"))
    try:
        transcript = json.loads(args.input.read_text(encoding="utf-8-sig"))
        result = AnalysisService(settings).analyze(transcript, budget=AttemptBudget(),
                                                 progress=lambda msg: print(msg, file=sys.stderr))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return 0
    except AnalysisError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("INVALID_INPUT: Could not read input JSON or write the output file.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
