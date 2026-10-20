"""Unit tests for FixtureBackend implementing DashboardBackend protocol."""
import json
from pathlib import Path
import pytest

from althea_evidence_ui.fixture_backend import FixtureBackend
from althea_evidence_ui.errors import NotFoundError, ContractError

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def test_fixture_backend_run_sample():
    backend = FixtureBackend()
    res = backend.run(
        {"kind": "sample", "sample_id": "riverton_demo", "title": "Riverton Test"},
        verify=True,
    )
    assert res["status"] == "complete"
    assert res["verification"] is not None
    assert len(res["verification"]["results"]) == 1
    assert res["mode"] == "fixture"


def test_fixture_backend_run_without_verify():
    backend = FixtureBackend()
    res = backend.run(
        {"kind": "sample", "sample_id": "riverton_demo", "title": "Riverton Test Unverified"},
        verify=False,
    )
    assert res["status"] == "partial"
    assert res["verification"] is None


def test_fixture_backend_save_review_and_invalidation():
    backend = FixtureBackend()
    job = backend.run({"kind": "sample", "sample_id": "riverton_demo"}, verify=True)
    orig_tr_id = job["transcript"]["transcript_id"]

    # Modify transcript
    tr = job["transcript"]
    tr["segments"][0]["text"] = "Modified segment text for review."

    reviewed = backend.save_review(job["job_id"], tr)
    assert reviewed["status"] == "ready"
    assert reviewed["transcript"]["origin"] == "human_reviewed"
    assert reviewed["transcript"]["transcript_id"] != orig_tr_id
    assert reviewed["analysis"] is None
    assert reviewed["verification"] is None


def test_fixture_backend_reanalyze_unchanged_vs_edited():
    backend = FixtureBackend()
    job = backend.run({"kind": "sample", "sample_id": "riverton_demo"}, verify=True)

    # 1. Save review with identical segments (e.g. only speaker name changed)
    tr_unchanged = job["transcript"]
    reviewed_unchanged = backend.save_review(job["job_id"], tr_unchanged)
    reanalyzed = backend.reanalyze(reviewed_unchanged["job_id"], verify=True)
    assert reanalyzed["status"] == "complete"
    assert reanalyzed["analysis"] is not None
    assert reanalyzed["verification"] is not None

    # 2. Save review with altered text
    tr_edited = job["transcript"]
    tr_edited["segments"][0]["text"] = "Completely altered budget figure: 99 million."
    reviewed_edited = backend.save_review(job["job_id"], tr_edited)
    reanalyzed_edited = backend.reanalyze(reviewed_edited["job_id"], verify=True)

    # Must fail with clear issue and preserve reviewed transcript
    assert reanalyzed_edited["status"] == "failed"
    assert reanalyzed_edited["analysis"] is None
    assert reanalyzed_edited["verification"] is None
    assert any("requires live backend" in i["message"] for i in reanalyzed_edited["issues"])


def test_fixture_backend_verify_pairs():
    backend = FixtureBackend()
    job = backend.run({"kind": "sample", "sample_id": "riverton_demo"}, verify=False)
    assert job["verification"] is None

    verified_job = backend.verify_pairs(job["job_id"], ["pair_0001"])
    assert verified_job["status"] == "complete"
    assert verified_job["verification"] is not None
    assert verified_job["verification"]["results"][0]["pair_id"] == "pair_0001"


def test_fixture_backend_load_not_found():
    backend = FixtureBackend()
    with pytest.raises(NotFoundError):
        backend.load("non-existent-uuid")
