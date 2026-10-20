"""Command-line interface for althea_evidence_ui."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from althea_evidence_ui.verification import VerificationService
from althea_evidence_ui.errors import AltheaError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Althea AI Evidence Verification CLI (Team 3)",
    )
    parser.add_argument(
        "--mode",
        choices=["fixture", "live"],
        default="fixture",
        help="Verification mode: fixture (offline) or live (Google Search grounding)",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to analysis.json",
    )
    parser.add_argument(
        "--transcript",
        required=True,
        help="Path to transcript.json",
    )
    parser.add_argument(
        "--pairs",
        default="",
        help="Comma-separated list of pair IDs to verify (e.g. 'pair_0001' or 'pair_0001,pair_0002')",
    )
    parser.add_argument(
        "--output",
        help="Path to output verification JSON file (prints to stdout if omitted)",
    )
    parser.add_argument(
        "--project-id",
        help="Google Cloud project ID (for live mode)",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        sys.stderr.write(f"Error: Input analysis file not found: {args.input}\n")
        return 1

    transcript_path = Path(args.transcript)
    if not transcript_path.is_file():
        sys.stderr.write(f"Error: Transcript file not found: {args.transcript}\n")
        return 1

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            analysis = json.load(f)
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = json.load(f)
    except Exception as e:
        sys.stderr.write(f"Error reading JSON files: {e}\n")
        return 1

    # Parse pair IDs
    if args.pairs.strip():
        pair_ids = [p.strip() for p in args.pairs.split(",") if p.strip()]
    else:
        pair_ids = []

    settings = {
        "mode": args.mode,
        "project_id": args.project_id or "",
        "max_verify_pairs": 4,
    }

    try:
        service = VerificationService(settings)
        verification = service.verify(
            transcript=transcript,
            analysis=analysis,
            pair_ids=pair_ids,
        )
    except AltheaError as e:
        sys.stderr.write(f"Verification error [{e.code}]: {e.message}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"Unexpected error: {e}\n")
        return 1

    output_str = json.dumps(verification, indent=2, ensure_ascii=False) + "\n"

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output_str)
    else:
        sys.stdout.write(output_str)

    return 0


if __name__ == "__main__":
    sys.exit(main())
