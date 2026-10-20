"""Fixture backend implementing the DashboardBackend protocol offline."""
from __future__ import annotations
import copy
import datetime
import json
from pathlib import Path
from typing import Any, Callable
import uuid

from althea_evidence_ui._contract import (
    Snapshot,
    JobSummary,
    Transcript,
    Issue,
)
from althea_evidence_ui.errors import (
    AltheaError,
    NotFoundError,
    ContractError,
    InvalidInputError,
)
from althea_evidence_ui.validation import (
    compute_transcript_id,
    canonical_json,
    sha256_digest,
)
from althea_evidence_ui.verification import VerificationService

Progress = Callable[[str], None]

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_fixture_json(filename: str) -> dict:
    path = FIXTURES_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Fixture file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class FixtureBackend:
    """Offline backend implementation of the DashboardBackend protocol."""

    mode: str = "fixture"

    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}
        self.mode = "fixture"
        self.jobs: dict[str, dict] = {}
        self.service = VerificationService(self.settings)

        # Preload reference fixtures
        self._ref_snapshot = load_fixture_json("reference_snapshot.json")
        self._ref_transcript = load_fixture_json("transcript.json")
        self._ref_analysis = load_fixture_json("analysis.json")
        self._ref_verification = load_fixture_json("verification.json")

        # Seed with reference job
        ref_job = copy.deepcopy(self._ref_snapshot)
        self.jobs[ref_job["job_id"]] = ref_job

    def run(
        self,
        source: dict[str, Any],
        *,
        verify: bool,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        """Run analysis on an input request. In fixture mode, riverton_demo is supported."""
        kind = source.get("kind")
        sample_id = source.get("sample_id")
        title = source.get("title", "Riverton sample — fictional")

        if progress:
            progress("Starting fixture analysis...")

        if kind == "sample" and sample_id == "riverton_demo":
            job_id = str(uuid.uuid4())
            now = _now_utc()

            transcript = copy.deepcopy(self._ref_transcript)
            analysis = copy.deepcopy(self._ref_analysis)

            if verify:
                if progress:
                    progress("Running synthetic verification on pair_0001...")
                verification = self.service.verify(
                    transcript=transcript,
                    analysis=analysis,
                    pair_ids=["pair_0001"],
                    progress=progress,
                )
                status = "complete"
            else:
                verification = None
                status = "partial"

            snapshot = {
                "schema_version": "1.0.0",
                "job_id": job_id,
                "title": title,
                "mode": "fixture",
                "status": status,
                "created_at": now,
                "updated_at": now,
                "transcript": transcript,
                "analysis": analysis,
                "verification": verification,
                "issues": [],
            }
            # Validate wire schema
            Snapshot.model_validate(snapshot)
            self.jobs[job_id] = snapshot
            if progress:
                progress("Fixture job complete.")
            return copy.deepcopy(snapshot)

        # Arbitrary audio/transcript input in standalone fixture mode
        job_id = str(uuid.uuid4())
        now = _now_utc()
        issue: dict = {
            "stage": "input",
            "code": "INVALID_INPUT",
            "message": "Arbitrary audio or transcript analysis requires live integration backend; "
                       "standalone fixture mode only processes the Riverton sample.",
            "retryable": False,
            "related_ids": [],
        }
        snapshot = {
            "schema_version": "1.0.0",
            "job_id": job_id,
            "title": title or "Uploaded Job",
            "mode": "fixture",
            "status": "failed",
            "created_at": now,
            "updated_at": now,
            "transcript": None,
            "analysis": None,
            "verification": None,
            "issues": [issue],
        }
        Snapshot.model_validate(snapshot)
        self.jobs[job_id] = snapshot
        if progress:
            progress("File analysis requires live backend.")
        return copy.deepcopy(snapshot)

    def load(self, job_id: str) -> dict[str, Any]:
        """Load job by ID."""
        if job_id not in self.jobs:
            raise NotFoundError(f"Job ID {job_id} not found", related_ids=[job_id])
        return copy.deepcopy(self.jobs[job_id])

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent jobs."""
        sorted_jobs = sorted(
            self.jobs.values(),
            key=lambda j: j.get("updated_at", ""),
            reverse=True,
        )
        summaries = []
        for j in sorted_jobs[:limit]:
            summaries.append({
                "job_id": j["job_id"],
                "title": j["title"],
                "mode": j["mode"],
                "status": j["status"],
                "updated_at": j["updated_at"],
            })
        return summaries

    def save_review(self, job_id: str, transcript: dict[str, Any]) -> dict[str, Any]:
        """Save human-reviewed transcript, invalidate downstream analysis, and set status to ready."""
        snapshot = self.load(job_id)

        # Update origin
        transcript["origin"] = "human_reviewed"

        # Compute new transcript_id
        src = transcript.get("source", {})
        new_tr_id = compute_transcript_id(
            content_sha256=src.get("content_sha256", ""),
            language=transcript.get("language", "en"),
            duration_s=transcript.get("duration_s", 65.0),
            speakers=transcript.get("speakers", []),
            segments=transcript.get("segments", []),
        )
        transcript["transcript_id"] = new_tr_id

        # Invalidate downstream artifacts
        snapshot["transcript"] = transcript
        snapshot["analysis"] = None
        snapshot["verification"] = None
        snapshot["status"] = "ready"
        snapshot["updated_at"] = _now_utc()

        Snapshot.model_validate(snapshot)
        self.jobs[job_id] = snapshot
        return copy.deepcopy(snapshot)

    def reanalyze(
        self,
        job_id: str,
        *,
        verify: bool,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        """Reanalyze an existing job."""
        snapshot = self.load(job_id)
        current_tr = snapshot.get("transcript")
        if not current_tr:
            raise ContractError("Job has no transcript to reanalyze")

        ref_tr_id = self._ref_transcript.get("transcript_id")
        current_tr_id = current_tr.get("transcript_id")

        if progress:
            progress("Reanalyzing transcript...")

        # If unchanged reference sample: deterministic reanalysis
        # Notice: human_reviewed transcript has a different transcript_id or origin,
        # but let's check if the segments/speakers match the reference segments
        ref_segments_canon = canonical_json(self._ref_transcript.get("segments", []))
        curr_segments_canon = canonical_json(current_tr.get("segments", []))

        if curr_segments_canon == ref_segments_canon:
            analysis = copy.deepcopy(self._ref_analysis)
            # Update analysis's transcript_id to match the current transcript_id
            analysis["transcript_id"] = current_tr["transcript_id"]
            # Recompute analysis_id if needed
            body = {
                "transcript_id": analysis["transcript_id"],
                "claims": analysis["claims"],
                "pairs": analysis["pairs"],
            }
            analysis["analysis_id"] = "an_" + sha256_digest(body)

            snapshot["analysis"] = analysis
            snapshot["issues"] = []

            if verify:
                if progress:
                    progress("Re-verifying pair_0001 against reference evidence...")
                verification = self.service.verify(
                    transcript=current_tr,
                    analysis=analysis,
                    pair_ids=["pair_0001"],
                    progress=progress,
                )
                snapshot["verification"] = verification
                snapshot["status"] = "complete"
            else:
                snapshot["verification"] = None
                snapshot["status"] = "partial"

        else:
            # Custom edited transcript cannot be reanalyzed by offline fixtures
            snapshot["analysis"] = None
            snapshot["verification"] = None
            snapshot["status"] = "failed"
            issue: dict = {
                "stage": "analysis",
                "code": "INVALID_INPUT",
                "message": "Custom edited analysis requires live backend.",
                "retryable": False,
                "related_ids": [],
            }
            snapshot["issues"] = [issue]

        snapshot["updated_at"] = _now_utc()
        Snapshot.model_validate(snapshot)
        self.jobs[job_id] = snapshot
        return copy.deepcopy(snapshot)

    def verify_pairs(
        self,
        job_id: str,
        pair_ids: list[str],
        *,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        """Verify selected disagreement pairs."""
        snapshot = self.load(job_id)
        analysis = snapshot.get("analysis")
        transcript = snapshot.get("transcript")
        if not analysis or not transcript:
            raise ContractError("Job has no analysis or transcript to verify")

        verification = self.service.verify(
            transcript=transcript,
            analysis=analysis,
            pair_ids=pair_ids,
            progress=progress,
        )

        snapshot["verification"] = verification
        # Status complete if all eligible verified, else partial
        eligible_count = len([
            p for p in analysis.get("pairs", [])
            if p.get("relation") in ("direct_conflict", "numeric_discrepancy")
        ])
        results_count = len(verification.get("results", []))
        if results_count == eligible_count and results_count > 0:
            snapshot["status"] = "complete"
        else:
            snapshot["status"] = "partial"

        snapshot["updated_at"] = _now_utc()
        Snapshot.model_validate(snapshot)
        self.jobs[job_id] = snapshot
        return copy.deepcopy(snapshot)

    def refresh_verification(
        self,
        job_id: str,
        pair_ids: list[str],
        *,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        """Invalidate selected pair verifications and re-verify."""
        return self.verify_pairs(job_id, pair_ids, progress=progress)
